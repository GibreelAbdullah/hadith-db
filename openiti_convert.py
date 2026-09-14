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
# top-level marker without parentheses, e.g. "# | بسم الله" / "# | مقدمة المصنف"
HDR_NOPAREN_RE = re.compile(r"^#\s*\|\s*(.+?)\s*$", re.S)
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

# ---- structural classification of section titles --------------------------
#
# OpenITI hadith texts frequently mark EVERY section (كتاب "book" and باب
# "chapter") with the same top-level `# | ( ... )` marker; the actual hierarchy
# is only encoded in the leading Arabic word of the title. We classify by that
# word so the two-level book/chapter structure is preserved.
#
# A title may be prefixed with a running number, e.g. "1 كتاب الطهارة" or
# "23 باب ...", which we strip before matching.

_LEADING_NUM_RE = re.compile(r"^\s*\d+\s*")
# Some editions introduce a continued book with a connective, e.g.
# "ومن كتاب الأشربة" ("and from the book of…") or "من كتاب الأضاحي". Strip a
# leading و/من connector before testing for the كتاب keyword. (Chapters begin
# with باب, so this never turns a باب into a book.)
_LEADING_CONNECTOR_RE = re.compile(r"^\s*(?:و?من)\s+")

# Words that introduce a top-level book (كتاب). "أول كتاب" = "beginning of the
# book of ...".
BOOK_KEYWORDS = ("كتاب", "أول كتاب")
# Words that introduce a chapter/sub-section within a book.
CHAPTER_KEYWORDS = ("باب", "جماع أبواب", "أبواب", "فصل", "جماع")


def classify_section(title):
    """Classify a section title as 'book', 'chapter', or None (unknown).

    Returns None when the title matches no structural keyword; callers decide
    the default (musnad/mu'jam collections name their sections after narrators,
    which carry no كتاب/باب keyword and are treated as books)."""
    t = _LEADING_NUM_RE.sub("", title).strip()
    # Also allow a "ومن"/"من" connective before the book keyword.
    t_book = _LEADING_CONNECTOR_RE.sub("", t)
    for kw in BOOK_KEYWORDS:
        if t.startswith(kw) or t_book.startswith(kw):
            return "book"
    for kw in CHAPTER_KEYWORDS:
        if t.startswith(kw):
            return "chapter"
    return None


# Artifact from headers written as "( N ) title )" where the greedy paren
# capture leaves a stray "N )" at the front of the extracted title.
_TITLE_NUMPAREN_RE = re.compile(r"^\s*\d+\s*\)\s*")
# A trailing unbalanced ")" left over from the same pattern.
_TITLE_TRAIL_PAREN_RE = re.compile(r"\s*\)\s*$")
# A leading running/sequence number that OpenITI prefixes to section titles,
# e.g. "1 كتاب الطهارة" / "57 باب ...". Only stripped when followed by Arabic
# text (never for a title that is purely a number).
_TITLE_LEADING_NUM_RE = re.compile(r"^\s*\d+\s+(?=[^\d])")


def clean_title(title):
    """Tidy a section title extracted from a header.

    - Removes a leading running/sequence number ("1 كتاب الطهارة" -> "كتاب
      الطهارة"), which OpenITI prefixes to every section heading.
    - Handles the "( N ) title )" shape (seen in Ibn Abi Shayba's `### ||`
      headers) by removing a leading "N )" and any single trailing stray ")".
    """
    t = title
    new = _TITLE_NUMPAREN_RE.sub("", t)
    if new != t:
        # We removed a leading "N )"; drop a matching trailing ")" if present.
        t = _TITLE_TRAIL_PAREN_RE.sub("", new)
    else:
        # Otherwise strip a plain leading sequence number ("1 كتاب ...").
        t = _TITLE_LEADING_NUM_RE.sub("", t)
    # Drop a leading "ومن"/"من" connective when it precedes a book keyword
    # ("ومن كتاب الأشربة" -> "كتاب الأشربة"); leave "باب من ..." untouched.
    t = _LEADING_CONNECTOR_RE.sub("", t) if _LEADING_CONNECTOR_RE.sub("", t).startswith("كتاب") else t
    # Drop a single unbalanced trailing ")" (more ")" than "(").
    if t.count(")") > t.count("("):
        t = _TITLE_TRAIL_PAREN_RE.sub("", t)
    return t.strip()


def _digits(s):
    """Leading run of digits in a (possibly composite) number token."""
    m = re.match(r"\d+", s or "")
    return m.group(0) if m else ""


# In some OpenITI/Shamela editions (e.g. al-Mu'jam al-Kabir) the hadith number
# is mangled by OCR: the true number's low-two digits and a part index leak in,
# producing values like "491491" (true 49, part 1) or "11291291" (true 1129,
# part 1). The genuine "NN P" tokens survive at the START of the hadith text.
# We detect an out-of-sequence number whose text begins with "NN P" and rebuild
# the real number from the previous number's "hundreds" plus NN.
_BODY_NNPART_RE = re.compile(r"^\s*(\d{1,3})\s+(\d{1,2})\s+")


def repair_hadith_number(num, body_text, prev_num, next_num=None):
    d = _digits(num)
    if not d:
        return num, body_text
    n = int(d)
    # Case A: OCR-doubled number jumped implausibly far ahead. The genuine
    # "NN P" tokens survive at the start of the text; rebuild from them.
    if not (prev_num and n <= prev_num + 1000):
        m = _BODY_NNPART_RE.match(body_text)
        if m:
            nn = int(m.group(1))
            mod = 100 if nn < 100 else 1000
            high = (prev_num // mod) * mod
            true = high + nn
            while true <= prev_num:
                true += mod
            if true - prev_num <= 1000:
                body_text = body_text[m.end():].strip()
                return str(true), body_text
    # Case B: isolated backward dip — a number far below the running sequence
    # (OCR dropped/garbled digits), e.g. a stray "638" between 6466 and 6467.
    if prev_num and n < prev_num - 1000:
        return str(prev_num + 1), body_text
    # Case B2: a smaller isolated dip (garbled digit), confirmed by lookahead:
    # the number dips below prev but the NEXT number resumes right after prev
    # (so it is a lone spike-down, not a per-book numbering restart).
    if (
        prev_num
        and next_num is not None
        and n < prev_num - 50
        and prev_num - 5 <= next_num <= prev_num + 5
    ):
        return str(prev_num + 1), body_text
    # Case C: isolated forward jump with no recoverable "NN P" token — an OCR
    # digit-insertion (e.g. 17139 -> "171340"; true 17140). Only when the value
    # balloons absurdly (an inserted digit multiplies it ~10x).
    if prev_num > 100 and n > prev_num * 5 and n > 50000:
        return str(prev_num + 1), body_text
    return num, body_text



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

    # Pre-scan: does this text use كتاب ("book") headers at the top level?
    #   - kitab/bab layout (has كتاب): كتاب -> book, every other top-level
    #     section -> chapter (e.g. Bayhaqi, Ibn Khuzayma, al-Mustadrak).
    #   - musnad/mu'jam layout (no كتاب): each top-level section is named after
    #     a narrator and is itself a "book" (e.g. Tabarani, Abu Ya'la, Tayalisi).
    # This decides the default classification for headers whose keyword is
    # unknown (باب is always a chapter and كتاب is always a book regardless).
    has_kitab = False
    for block in blocks:
        m = HDR_NUM_RE.match(clean_marker(block))
        if m and classify_section(clean(m.group(2))) == "book":
            has_kitab = True
            break
    default_kind = "chapter" if has_kitab else "book"

    out = [f"collection||{collection_name}"]
    stats = {"books": 0, "chapters": 0, "hadith": 0, "prologue": 0, "skipped": 0}
    have_book = False
    have_content = False  # any book/chapter/hadith emitted yet?
    pending_prologue = []
    auto_n = 0  # running counter for --autonumber mode
    prev_hadith_num = 0  # last accepted hadith number, for OCR number repair

    # Normalised collection name, for detecting a leading title-only header that
    # merely repeats the collection name (should be dropped, not made a book).
    def _norm(s):
        s = re.sub(r"[^\wء-ي]", " ", s)
        # Normalise common Arabic orthographic variants so a title like
        # "مصنف بن أبي شيبة" matches the collection "مصنف ابن أبي شيبة".
        s = s.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
        s = s.replace("ى", "ي").replace("ة", "ه")
        s = re.sub(r"\bابن\b", "بن", s)
        return re.sub(r"\s+", " ", s).strip()
    coll_norm = _norm(collection_name)
    coll_words = set(coll_norm.split())

    def is_collection_title(title):
        """True if a header merely names the collection (optionally with an
        added descriptor like the author nisba), so it should be dropped rather
        than treated as a real first section."""
        tn = _norm(title)
        if tn == coll_norm:
            return True
        tw = set(tn.split())
        # All collection words present and few extra tokens (e.g. author nisba).
        if coll_words and coll_words.issubset(tw) and len(tw - coll_words) <= 2:
            return True
        return False

    def ensure_book():
        nonlocal have_book, have_content
        if not have_book:
            # When sections (chapters) appear before any explicit كتاب, they
            # belong to the work's introduction. If the source marked one
            # (e.g. al-Darimi opens with "( المقدمة )"), name the synthetic
            # parent book "المقدمة"; otherwise fall back to the collection name.
            name = collection_name
            if any("المقدمة" in p or "مقدمة" in p for p in pending_prologue):
                name = "المقدمة"
            out.append(f"book||{name}")
            have_book = True
            have_content = True
            stats["books"] += 1

    def flush_prologue():
        nonlocal pending_prologue
        if pending_prologue:
            out.append(f"book_intro||{' '.join(pending_prologue)}")
            pending_prologue = []

    def emit_book(title):
        nonlocal have_book, have_content
        out.append(f"book||{clean_title(title)}")
        have_book = True
        have_content = True
        stats["books"] += 1
        flush_prologue()

    def emit_chapter(title):
        nonlocal have_content
        ensure_book()
        out.append(f"chapter||{clean_title(title)}")
        have_content = True
        stats["chapters"] += 1
        flush_prologue()

    # Pre-scan: for every block that is a numbered hadith, record the NEXT
    # hadith's raw number, so repair_hadith_number can distinguish an isolated
    # OCR dip (sequence resumes right after) from a real per-book restart.
    next_hnum = {}
    _pending_idx = None
    for bi, block in enumerate(blocks):
        mh = HAD_RE.match(clean_marker(block))
        if mh:
            d = _digits(mh.group(1))
            if _pending_idx is not None and d:
                next_hnum[_pending_idx] = int(d)
            _pending_idx = bi

    for bidx, block in enumerate(blocks):
        marker = clean_marker(block)

        # page-only structural line (### | [ص: 52]) -> ignore silently
        if PAGEREF_RE.match(marker):
            continue

        # paratext / typed structural marker (### |PARATEXT|) -> ignore
        if PARATEXT_RE.match(marker):
            continue

        # top-level section header: "# | ( title )".
        # OpenITI encodes both books (كتاب) and chapters (باب) at this same
        # marker level, so classify by the leading Arabic keyword.
        m = HDR_NUM_RE.match(marker)
        if m:
            title = clean(m.group(2))
            if not title:
                stats["skipped"] += 1
                continue
            kind = classify_section(title)
            # Drop a leading header that just repeats the collection title
            # (a spurious "first book" duplicating the collection name).
            if kind is None and not have_content and is_collection_title(title):
                stats["skipped"] += 1
                continue
            if kind is None:
                kind = default_kind
            if kind == "chapter":
                emit_chapter(title)
            else:
                emit_book(title)
            continue

        # top-level marker without parentheses: "# | بسم الله" / "# | مقدمة".
        # These are not real sections; treat their text as prologue.
        mnp = HDR_NOPAREN_RE.match(marker)
        if mnp:
            ptext = clean(mnp.group(1))
            if not ptext:
                stats["skipped"] += 1
                continue
            pending_prologue.append(ptext)
            stats["prologue"] += 1
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
            # Even at the nested `###` level a كتاب heading introduces a real
            # book (e.g. Ibn Abi Shayba marks its ~40 kutub as `### || كتاب ...`
            # while everything else is a chapter). Classify accordingly.
            if classify_section(clean_title(title)) == "book":
                emit_book(title)
            else:
                emit_chapter(title)
            continue

        # numbered hadith
        mh = HAD_RE.match(marker)
        if mh:
            num = mh.group(1)
            body_text = clean(mh.group(2))
            if not body_text:
                stats["skipped"] += 1
                continue
            num, body_text = repair_hadith_number(num, body_text, prev_hadith_num, next_hnum.get(bidx))
            d = _digits(num)
            if d:
                prev_hadith_num = int(d)
            ensure_book()
            out.append(f"hadith|{num}|{body_text}")
            have_content = True
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
                have_content = True
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
