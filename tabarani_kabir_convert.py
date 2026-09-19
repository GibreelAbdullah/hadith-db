#!/usr/bin/env python3
"""Bespoke converter for al-Mu'jam al-Kabir (al-Tabarani), Shamela edition
(0360Tabarani.MucjamKabir.Shamela0001733-ara1).

Why a dedicated parser
----------------------
This edition uses a different mARkdown convention from the generic
`openiti_convert.py`:

  ### | <text>        section header (letter divider / grouping / narrator /
                       per-companion sub-topic)
  ### | N -           a hadith marker (number N); the hadith TEXT follows on
                       the next `#` line(s)
  # PageVxxPyyy        page markers (ignored)

The work is organised by Companion. We produce ONE book per Companion, with the
per-companion sub-topics (صفة / سن / من فضائله / وما أسند …) and per-transmitter
sub-headers as chapters, and the numbered entries as hadith.

Book boundaries
---------------
* Part 1 (famous companions): each Companion opens with "نسبة X" -> new book.
* Part 2 (alphabetical): grouping headers "من اسمه X" and letter dividers
  "باب <letter>" are NOT books; the Companion is the narrator-name title that
  directly precedes the hadith -> new book.
* Known per-companion sub-topics become chapters of the current book.
"""

import argparse
import re
import sys

META_RE = re.compile(r"^#META#\s*([\w.]+)\s*::\s*(.*)$")
PAGE_RE = re.compile(r"PageV\d+P\d+")
MS_RE = re.compile(r"\bms\d+\b")
TAG_RE = re.compile(r"@[A-Za-z]+@")

# A section header: "### | <text>". A hadith marker is the special form
# "### | N -" (number then dash, nothing else).
SEC_RE = re.compile(r"^#{2,}\s*\|\s*(.*?)\s*$")
HADNUM_RE = re.compile(r"^(\d+)\s*-\s*$")
PAGEREF_RE = re.compile(r"^\[[^\]]*\]$")

# Per-companion sub-topic headers -> chapters (never a new book).
CHAPTER_PREFIXES = (
    "صفة", "سن ", "سنه", "من فضائله", "فضائل", "وما أسند", "ومما أسند",
    "ذكر", "بقية", "نسبته", "تمام حديث", "تمام", "وسنه", "ووفاته",
)
# Grouping headers / dividers -> not books (kept as chapters for navigation).
GROUPING_PREFIXES = ("من اسمه", "باب", "العشرة", "مقدمة", "المقدمة")


def parse_header(lines):
    author = {"name": "", "aka": "", "died": ""}
    body_start = 0
    for i, line in enumerate(lines):
        if line.strip() == "#META#Header#End#":
            body_start = i + 1
            break
        m = META_RE.match(line)
        if not m:
            continue
        key, val = m.group(1), m.group(2).strip()
        if val == "NODATA":
            continue
        if key == "010.AuthorNAME":
            author["name"] = val
        elif key == "010.AuthorAKA":
            author["aka"] = val
        elif key == "011.AuthorDIED":
            author["died"] = val
    return author, body_start


def clean(text):
    text = PAGE_RE.sub(" ", text)
    text = MS_RE.sub(" ", text)
    text = TAG_RE.sub(" ", text)
    text = text.replace("~~", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def strip_narrator_name(t):
    """Trim a Companion title to a concise name (drop the descriptive tail
    after the first quote that these headers often carry)."""
    t = re.split(r'["«»]', t)[0]
    return t.strip(" ،:")


def classify_title(t):
    """Return 'chapter' for a sub-topic/grouping header, else 'narrator'
    (a candidate new Companion book)."""
    for p in CHAPTER_PREFIXES:
        if t.startswith(p):
            return "chapter"
    for p in GROUPING_PREFIXES:
        if t.startswith(p):
            return "grouping"
    if t.startswith("نسبة"):
        return "narrator"  # Part 1 Companion
    return "name"  # a bare narrator name (Part 2 Companion, or transmitter)


def convert(text, collection_name):
    lines = text.split("\n")
    author, body_start = parse_header(lines)
    body = lines[body_start:]

    # First pass: build an ordered list of structural tokens.
    #   ("hadith", num) | ("title", text)
    tokens = []
    pending = []  # text lines accumulating for the current hadith
    for raw in body:
        s = raw.strip()
        m = SEC_RE.match(s)
        if m:
            inner = m.group(1).strip()
            # Strip manuscript sigla / page markers / tags that OCR sometimes
            # wedges between the number and the dash ("133 ms0029 -").
            inner_clean = TAG_RE.sub(" ", MS_RE.sub(" ", PAGE_RE.sub(" ", inner)))
            inner_clean = re.sub(r"\s+", " ", inner_clean).strip()
            hm = HADNUM_RE.match(inner_clean)
            if hm:
                tokens.append(["hadith", hm.group(1), []])
                continue
            if PAGEREF_RE.match(inner_clean) or not inner_clean:
                continue
            tokens.append(["title", clean(inner)])
            continue
        # A "#"/"~~" body line: text for the current hadith (if any).
        if s.startswith("#") or s.startswith("~~"):
            frag = s[2:] if s.startswith("~~") else s[1:]
            if PAGE_RE.search(frag) and not frag.strip(" #"):
                continue
            if tokens and tokens[-1][0] == "hadith":
                tokens[-1][2].append(frag)
        # else ignore

    out = [f"collection||{collection_name}"]
    stats = {"books": 0, "chapters": 0, "hadith": 0, "skipped": 0}
    have_book = False
    # In the alphabetical part, a Companion is the FIRST narrator-name title
    # after a grouping header ("من اسمه X") or a letter divider ("باب <letter>").
    # Subsequent name titles (transmitters like "فلان عن فلان") are chapters.
    expect_companion = True

    def emit_book(name):
        nonlocal have_book
        out.append(f"book||{name}")
        have_book = True
        stats["books"] += 1

    def emit_chapter(name):
        if not have_book:
            emit_book(collection_name)
        out.append(f"chapter||{name}")
        stats["chapters"] += 1

    for i, tok in enumerate(tokens):
        if tok[0] == "hadith":
            num, frag = tok[1], tok[2]
            body_text = clean(" ".join(frag))
            if not body_text:
                stats["skipped"] += 1
                continue
            if not have_book:
                emit_book(collection_name)
            out.append(f"hadith|{num}|{body_text}")
            stats["hadith"] += 1
            continue

        title = tok[1]
        if not title:
            continue
        kind = classify_title(title)

        if kind == "narrator":
            # "نسبة X" -> new Companion book (Part 1).
            name = re.sub(r"^نسبة\s+", "", strip_narrator_name(title)).strip()
            emit_book(name or title)
            expect_companion = False
        elif kind == "chapter":
            emit_chapter(title)
            expect_companion = False
        elif kind == "grouping":
            # letter divider / "من اسمه X": a new Companion follows.
            # A leading "مقدمة" before any Companion opens the introduction book.
            if not have_book and title.startswith(("مقدمة", "المقدمة")):
                emit_book("المقدمة")
            else:
                emit_chapter(title)
            expect_companion = True
        else:  # "name"
            if expect_companion:
                emit_book(strip_narrator_name(title))
                expect_companion = False
            else:
                # transmitter sub-header within the current Companion
                emit_chapter(title)

    return out, author, stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("-n", "--name", required=True)
    ap.add_argument("-o", "--output")
    args = ap.parse_args()

    text = open(args.input, "rb").read().decode("utf-8", errors="replace")
    out_lines, author, stats = convert(text, args.name)
    result = "\n".join(out_lines) + "\n"
    if args.output:
        open(args.output, "w", encoding="utf-8").write(result)
    else:
        sys.stdout.write(result)
    sys.stderr.write(
        f"author: name={author['name']!r} aka={author['aka']!r} died={author['died']!r}\n"
        f"stats: {stats}\n"
    )


if __name__ == "__main__":
    main()
