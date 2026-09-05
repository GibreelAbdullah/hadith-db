#!/usr/bin/env python3
"""Convert OpenITI mARkdown hadith texts into hadith-db `ar.txt` format.

Input : an OpenITI mARkdown file (raw text as published in openiti/release).
Output: `ar.txt` in the `category|num|text` line format consumed by convert.py,
        plus the extracted author fields (name / aka / died).

mARkdown structure this handles:
  #META# ... #META#Header#End#   -> header block (author info extracted here)
  # | N ( title )                -> section header  -> `book||title`
  # N text                       -> a numbered hadith -> `hadith|N|text`
  # text (no number)             -> unnumbered paragraph (prologue etc.)
  ~~continuation                 -> appended to the current line
Inline tokens cleaned from the text:
  PageVxxPyyy   page markers            -> removed
  msNNN         manuscript sigla        -> removed
  @QB@ / @QE@   Quran quote delimiters  -> removed (text between kept)
  other @XX@    misc mARkdown tags      -> removed

The script is deliberately conservative: it only emits a `hadith` line when a
numbered `# N` marker is present, so we never invent hadith boundaries.
Unnumbered leading paragraphs (author's preface / isnad of the whole book)
become a single `book_intro`-less prologue that is attached to the first book.
"""

import argparse
import re
import sys

# ---- header parsing -------------------------------------------------------

META_RE = re.compile(r"^#META#\s*([\w.]+)\s*::\s*(.*)$")


def parse_header(lines):
    """Return (author dict, body_start_index)."""
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


# ---- text cleanup ---------------------------------------------------------

PAGE_RE = re.compile(r"PageV\d+P\d+")
MS_RE = re.compile(r"\bms\d+\b")
TAG_RE = re.compile(r"@[A-Za-z]+@")           # @QB@ @QE@ @HASH@ ...
HDR_NUM_RE = re.compile(r"^#\s*\|\s*(\d+)?\s*\((.*)\)\s*$", re.S)
# nested sub-section headers, e.g. "### || ( باب ... )" or "### | ( ... )"
SUBHDR_RE = re.compile(r"^#{2,}\s*\|+\s*(\d+)?\s*\((.*)\)\s*$", re.S)
# nested sub-header without parentheses, e.g. "### | باب ذكر ..."
SUBHDR_NOPAREN_RE = re.compile(r"^#{2,}\s*\|+\s*(.+?)\s*$", re.S)
# page-only structural lines, e.g. "### | [ص: 52]" -> ignored, not a chapter
PAGEREF_RE = re.compile(r"^#{2,}\s*\|+\s*\[[^\]]*\]\s*$", re.S)
# paratext / empty structural markers, e.g. "### |PARATEXT|" -> ignored
PARATEXT_RE = re.compile(r"^#{2,}\s*\|[A-Z]+\|", re.S)
HAD_RE = re.compile(r"^#\s+(\d+)\s+(.*)$", re.S)
PLAIN_RE = re.compile(r"^#\s+(.*)$", re.S)


def clean(text):
    text = PAGE_RE.sub(" ", text)
    text = MS_RE.sub(" ", text)
    text = TAG_RE.sub(" ", text)
    text = text.replace("~~", " ")
    # collapse whitespace/newlines produced by continuations
    text = re.sub(r"\s+", " ", text).strip()
    return text


# ---- body parsing ---------------------------------------------------------

def group_blocks(body_lines):
    """Merge `~~` continuation lines into their preceding `#` line.

    Yields raw block strings, each beginning with a single `#`.
    """
    blocks = []
    cur = None
    for line in body_lines:
        if line.startswith("~~"):
            if cur is not None:
                cur += "\n" + line
            # else: stray continuation before any block; ignore
        elif line.startswith("#"):
            if cur is not None:
                blocks.append(cur)
            cur = line
        else:
            # blank or unexpected line: treat as continuation whitespace
            if cur is not None and line.strip():
                cur += "\n" + line
    if cur is not None:
        blocks.append(cur)
    return blocks


def convert(text, collection_name, autonumber=False):
    lines = text.split("\n")
    author, body_start = parse_header(lines)
    body = lines[body_start:]
    blocks = group_blocks(body)

    out = [f"collection||{collection_name}"]
    stats = {"books": 0, "chapters": 0, "hadith": 0, "prologue": 0, "skipped": 0}
    have_book = False
    pending_prologue = []
    auto_n = 0  # running counter for --autonumber mode

    def ensure_book():
        nonlocal have_book
        if not have_book:
            out.append(f"book||{collection_name}")
            have_book = True
            stats["books"] += 1

    def flush_prologue():
        nonlocal pending_prologue
        if pending_prologue:
            out.append(f"book_intro||{' '.join(pending_prologue)}")
            pending_prologue = []

    for block in blocks:
        marker = clean_marker(block)

        # page-only structural line (### | [ص: 52]) -> ignore silently
        if PAGEREF_RE.match(marker):
            continue

        # paratext / typed structural marker (### |PARATEXT|) -> ignore
        if PARATEXT_RE.match(marker):
            continue

        # top-level section header -> book
        m = HDR_NUM_RE.match(marker)
        if m:
            title = clean(m.group(2))
            if not title:
                stats["skipped"] += 1
                continue
            out.append(f"book||{title}")
            have_book = True
            stats["books"] += 1
            flush_prologue()
            continue

        # nested sub-section header -> chapter (needs a parent book).
        # Accept both parenthesised "( ... )" and bare "### | باب ..." forms.
        ms = SUBHDR_RE.match(marker)
        title = None
        if ms:
            title = clean(ms.group(2))
        else:
            ms2 = SUBHDR_NOPAREN_RE.match(marker)
            if ms2:
                title = clean(ms2.group(1))
        if title is not None:
            if not title:
                stats["skipped"] += 1
                continue
            ensure_book()
            out.append(f"chapter||{title}")
            stats["chapters"] += 1
            continue

        # numbered hadith
        mh = HAD_RE.match(marker)
        if mh:
            num = mh.group(1)
            body_text = clean(mh.group(2))
            if not body_text:
                stats["skipped"] += 1
                continue
            ensure_book()
            out.append(f"hadith|{num}|{body_text}")
            stats["hadith"] += 1
            continue

        # plain text block
        mp = PLAIN_RE.match(marker)
        if mp:
            ptext = clean(mp.group(1))
            if not ptext:
                stats["skipped"] += 1
                continue
            if autonumber:
                # treat each plain text block as a sequential hadith
                ensure_book()
                auto_n += 1
                out.append(f"hadith|{auto_n}|{ptext}")
                stats["hadith"] += 1
            else:
                pending_prologue.append(ptext)
                stats["prologue"] += 1
            continue

        stats["skipped"] += 1

    return out, author, stats


def clean_marker(block):
    """Join continuation lines so the regexes can see the full block, but keep
    the leading marker intact for pattern matching."""
    first, _, rest = block.partition("\n")
    rest = rest.replace("~~", " ")
    return first + " " + rest if rest else first


# ---- cli ------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input", help="OpenITI mARkdown file")
    ap.add_argument("-n", "--name", required=True, help="collection display name (ar)")
    ap.add_argument("-o", "--output", help="output ar.txt path (default stdout)")
    ap.add_argument("--autonumber", action="store_true",
                    help="number each plain text block sequentially as a hadith "
                         "(for books lacking per-hadith numbers in the source)")
    args = ap.parse_args()

    with open(args.input, "rb") as f:
        text = f.read().decode("utf-8", errors="replace")

    out_lines, author, stats = convert(text, args.name, autonumber=args.autonumber)
    result = "\n".join(out_lines) + "\n"

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(result)
    else:
        sys.stdout.write(result)

    sys.stderr.write(
        f"author: name={author['name']!r} aka={author['aka']!r} died={author['died']!r}\n"
        f"stats: {stats}\n"
    )


if __name__ == "__main__":
    main()
