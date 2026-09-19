#!/usr/bin/env python3
"""Bespoke converter for al-Jami' al-Saghir (Suyuti) OpenITI mARkdown.

Why this needs special handling
--------------------------------
Unlike the other OpenITI hadith texts, this source does NOT delimit hadith with
line-level `# N` markers. Instead the whole work is a running text in which
each hadith is introduced by an inline `N - ` token (hadith number, dash), and
multiple hadith share a physical line. The generic `openiti_convert.py` only
catches hadith whose number happens to start a line, so it recovered ~2,800 of
the ~10,030 hadith and mis-segmented them.

The work is arranged alphabetically: each Arabic letter is a section headed by
`(باب:)? حرف <letter>` (e.g. "باب: حرف الألف"). Within a letter, entries that
begin with the definite article "ال" are grouped after the bare-word entries;
both share the same running numbering, so we keep the whole letter as one book.

Output: `category|num|text` lines (collection / book / hadith) — same format as
`openiti_convert.py`, consumed by `convert.py`.
"""

import argparse
import re
import sys

META_RE = re.compile(r"^#META#\s*([\w.]+)\s*::\s*(.*)$")
PAGE_RE = re.compile(r"PageV\d+P\d+")
MS_RE = re.compile(r"\bms\d+\b")
TAG_RE = re.compile(r"@[A-Za-z]+@")

# A hadith starts at an inline "N - " (number then dash). The negative
# lookbehind avoids splitting inside a multi-digit run.
HADITH_MARKER_RE = re.compile(r"(?<!\d)(\d{1,5})\s*-\s+")

# A letter-section header: optional "باب:" then "حرف <word>", immediately
# followed by a hadith number marker. We also allow a stray trailing "]".
LETTER_RE = re.compile(r"(?:باب\s*:?\s*)?حرف\s+([^\d\s\]]{1,6})\]?\s+(?=\d{1,5}\s*-\s)")

# Whitelisted Arabic letter-section names (as written in the source, with the
# "ال" article), plus the special "لا" section. Anything else matched by
# LETTER_RE (e.g. the word "انحرف" followed by a footnote number) is rejected.
LETTER_NAMES = {
    "الألف", "الباء", "التاء", "الثاء", "الجيم", "الحاء", "الخاء", "الدال",
    "الذال", "الراء", "الزاي", "السين", "الشين", "الصاد", "الضاد", "الطاء",
    "الظاء", "العين", "الغين", "الفاء", "القاف", "الكاف", "اللام", "الميم",
    "النون", "الهاء", "الواو", "الياء", "لا",
}


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


def reconstruct_body(body_lines):
    """Join all body lines into one string, dropping leading #/~~ markers."""
    parts = []
    for l in body_lines:
        if l.startswith("~~"):
            parts.append(l[2:])
        elif l.startswith("#"):
            parts.append(l[1:])
        else:
            parts.append(l)
    return clean(" ".join(parts))


def convert(text, collection_name):
    lines = text.split("\n")
    author, body_start = parse_header(lines)
    body = reconstruct_body(lines[body_start:])

    # Record letter-header positions so we can emit a `book` at the right place.
    # Map: char offset of the header -> letter word. Only whitelisted Arabic
    # letter-section names are accepted (rejects e.g. "انحرف (4)").
    letters = {
        m.start(): m.group(1)
        for m in LETTER_RE.finditer(body)
        if m.group(1) in LETTER_NAMES
    }

    out = [f"collection||{collection_name}"]
    stats = {"books": 0, "hadith": 0}
    have_book = False
    last_letter = None  # dedupe consecutive same-letter headers into one book
    prev_num = 0        # last accepted hadith number, for OCR sequence repair

    # Walk hadith markers in order; between markers is the hadith text. Before
    # emitting each hadith, emit any letter-header that falls in the gap.
    markers = list(HADITH_MARKER_RE.finditer(body))
    for i, m in enumerate(markers):
        num = m.group(1)
        # OCR repair: the numbering is essentially sequential, but the source
        # occasionally has a mistyped number with an extra digit (e.g. "16555"
        # sitting between 1654 and 1656 — really "1655"). If dropping one digit
        # restores prev+1, use the corrected number.
        if int(num) != prev_num + 1 and len(num) > 1:
            for cand in (num[:-1], num[1:]):
                if cand and int(cand) == prev_num + 1:
                    num = cand
                    break
        prev_num = int(num)
        text_start = m.end()
        text_end = markers[i + 1].start() if i + 1 < len(markers) else len(body)
        htext = body[text_start:text_end].strip()

        # Emit any letter section header located before this hadith's number.
        # A single letter carries two headers in the source (the bare-word group
        # and the "ال…" group); collapse consecutive same-letter headers so each
        # Arabic letter becomes exactly one book.
        gap_start = markers[i - 1].end() if i > 0 else 0
        for off in sorted(k for k in letters if gap_start <= k < m.start()):
            letter = letters[off]
            if letter == last_letter:
                continue
            out.append(f"book||حرف {letter}")
            have_book = True
            last_letter = letter
            stats["books"] += 1

        if not have_book:
            # Safety net: content before the first letter header.
            out.append(f"book||{collection_name}")
            have_book = True
            stats["books"] += 1

        if htext:
            out.append(f"hadith|{num}|{htext}")
            stats["hadith"] += 1

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
