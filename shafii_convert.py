#!/usr/bin/env python3
"""Convert the OpenITI mARkdown of Musnad al-Shafi'i into hadith-db `ar.txt`.

Why bespoke (not openiti_convert.py --autonumber):
  The Shamela0009344 edition of Musnad al-Shafi'i has *no* per-hadith numbers
  in the source. Each hadith is a plain `#` block (an isnad starting with
  أخبرنا / أنبأنا / حدثنا …). openiti_convert.py --autonumber would number every
  plain block sequentially, but this file is bracketed by non-hadith prose:
    - a long biographical preface (نبذة عن الشافعي …) before the first section
    - a scribal colophon (تم كتاب المسند …) after the last hadith
  Numbering those as hadith is wrong, so we number only the real body.

Structure of the source body:
  ### | باب ما خرج من كتاب الوضوء     -> chapter (only one باب; the rest كتاب)
  ### | كتاب العيدين                  -> book
  ### | ومن كتاب الأمالي في الصلاة    -> book (continuation connective ومن/من)
  ### | [ص: 8]                        -> page marker, ignored
  ### |                               -> empty structural marker, ignored
  # <isnad text>  (+ ~~ continuations) -> one hadith, numbered sequentially

Reuses the mARkdown cleaning/grouping helpers from openiti_convert.py.
"""

import argparse
import re
import sys

from openiti_convert import (
    parse_header,
    group_blocks,
    clean,
    clean_marker,
    clean_title,
    PAGEREF_RE,
    PARATEXT_RE,
    SUBHDR_RE,
    SUBHDR_NOPAREN_RE,
    classify_section,
)

# The colophon begins with this phrase ("the Musnad is finished…"); everything
# from here on is scribal matter, not hadith.
COLOPHON_RE = re.compile(r"^\s*تم\s+كتاب\s+المسند")


def convert(text, collection_name):
    lines = text.split("\n")
    author, body_start = parse_header(lines)
    blocks = group_blocks(lines[body_start:])

    out = [f"collection||{collection_name}"]
    stats = {"books": 0, "chapters": 0, "hadith": 0, "skipped_preface": 0,
             "skipped_colophon": 0, "skipped_other": 0}

    have_book = False       # a real section header has opened a book/chapter
    in_body = False         # passed the preface (seen first real section)?
    in_colophon = False
    hadith_n = 0

    def ensure_book():
        nonlocal have_book
        if not have_book:
            out.append(f"book||{collection_name}")
            have_book = True
            stats["books"] += 1

    for block in blocks:
        marker = clean_marker(block)

        # page-only structural line (### | [ص: 52]) -> ignore
        if PAGEREF_RE.match(marker):
            continue
        # typed/empty paratext marker -> ignore
        if PARATEXT_RE.match(marker):
            continue

        # nested section header "### | title" (books & the lone chapter)
        ms = SUBHDR_RE.match(marker)
        title = None
        if ms:
            title = clean(ms.group(2))
        else:
            ms2 = SUBHDR_NOPAREN_RE.match(marker)
            if ms2:
                title = clean(ms2.group(1))
        if title is not None:
            title = clean_title(title)
            if not title:
                # empty "### |" marker
                continue
            in_body = True
            in_colophon = False
            kind = classify_section(title)
            if kind == "chapter":
                ensure_book()
                out.append(f"chapter||{title}")
                stats["chapters"] += 1
            else:
                # كتاب / ومن كتاب … (and any non-باب heading) -> book
                out.append(f"book||{title}")
                have_book = True
                stats["books"] += 1
            continue

        # top-level "# …" block. Before the first section header it is preface;
        # after the colophon phrase it is scribal matter — skip both.
        if marker.startswith("#"):
            body_text = clean(marker.lstrip("#").strip())
            if not body_text:
                continue
            if not in_body:
                stats["skipped_preface"] += 1
                continue
            if in_colophon or COLOPHON_RE.match(body_text):
                in_colophon = True
                stats["skipped_colophon"] += 1
                continue
            ensure_book()
            hadith_n += 1
            out.append(f"hadith|{hadith_n}|{body_text}")
            stats["hadith"] += 1
            continue

        stats["skipped_other"] += 1

    return out, author, stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input", help="OpenITI mARkdown file")
    ap.add_argument("-n", "--name", required=True, help="collection display name (ar)")
    ap.add_argument("-o", "--output", help="output ar.txt path (default stdout)")
    args = ap.parse_args()

    with open(args.input, "rb") as f:
        text = f.read().decode("utf-8", errors="replace")

    out_lines, author, stats = convert(text, args.name)
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
