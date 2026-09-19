#!/usr/bin/env python3
"""Bespoke converter for Shu'ab al-Iman (al-Bayhaqi), Shamela ط الرشد edition
(0458Bayhaqi.ShucabIman.Shamela0010660-ara1), matching https://shamela.ws/book/10660.

Structure in this edition's mARkdown
------------------------------------
  # <N> من شعب الإيمان ...   a "branch" (شعبة) header  -> BOOK
                             (the 77 branches; also "مقدمة" opens the intro book)
  ### | باب ... / فصل ...    sub-section header         -> CHAPTER
  ### | N -                  a hadith marker (number N); TEXT follows on the
                             next `#` lines. May carry an "msNNNN" siglum.
  # <text>                   hadith text / continuation (attached to current hadith)
  ### | [ ... ]              page-reference marker      -> ignored

We emit one BOOK per branch, its باب/فصل as chapters, and the numbered entries
as hadith — mirroring the printed edition's section list.
"""

import argparse
import re
import sys

META_RE = re.compile(r"^#META#\s*([\w.]+)\s*::\s*(.*)$")
PAGE_RE = re.compile(r"PageV\d+P\d+")
MS_RE = re.compile(r"\bms\d+\b")
TAG_RE = re.compile(r"@[A-Za-z]+@")

# A "### |" section marker (single pipe). Its inner text decides the type.
SEC_RE = re.compile(r"^#{2,}\s*\|\s*(.*?)\s*$")
HADNUM_RE = re.compile(r"^(\d+)\s*-\s*$")           # inner "N -" -> hadith
PAGEREF_RE = re.compile(r"^\[[^\]]*\]$")
# A "#"-level branch header: "<ordinal> من شعب الإيمان ...".
BRANCH_RE = re.compile(r"^#\s+(.*?من\s+شعب\s+الإيمان.*)$")
CHAPTER_PREFIXES = ("باب", "فصل", "ذكر", "جماع")

# Shamela's sidebar shows "١ - الإيمان بالله عز وجل" whereas the in-body
# heading reads "الأول من شعب الإيمان، وهو باب في الإيمان بالله عز وجل". The
# in-body headings are noisy (page breaks, ~~ continuations, editorial quotes),
# so we map each branch to its clean topic from the printed table of contents
# (shamela.ws/book/10660), keyed by branch number. Topics have no leading number.
BRANCH_TOPICS = {
    1: "الإيمان بالله عز وجل",
    2: "الإيمان برسل الله صلوات الله عليهم",
    3: "الإيمان بالملائكة",
    4: "الإيمان بالقرآن المنزل على نبينا محمد صلى الله عليه وسلم وسائر الكتب المنزلة على الأنبياء",
    5: "القدر خيره وشره من الله عز وجل",
    6: "الإيمان باليوم الآخر",
    7: "الإيمان بالبعث والنشور بعد الموت",
    8: "حشر الناس بعد ما يبعثون",
    9: "دار المؤمنين ومآبهم الجنة، ودار الكافرين ومآبهم النار",
    10: "محبة الله عز وجل",
    11: "الخوف من الله تعالى",
    12: "الرجاء من الله تعالى",
    13: "التوكل بالله عز وجل والتسليم لأمره تعالى في كل شيء",
    14: "حب النبي صلى الله عليه وسلم",
    15: "تعظيم النبي صلى الله عليه وسلم وإجلاله وتوقيره",
    16: "شح المرء بدينه حتى يكون القذف في النار أحب إليه من الكفر",
    17: "طلب العلم",
    18: "نشر العلم وألا يمنعه أهله أهله",
    19: "تعظيم القرآن",
    20: "الطهارات",
    21: "الصلاة",
    22: "الزكاة",
    23: "الصيام",
    24: "الاعتكاف",
    25: "المناسك",
    26: "الجهاد",
    27: "المرابطة في سبيل الله عز وجل",
    28: "الثبات للعدو وترك الفرار من الزحف",
    29: "أداء خمس المغنم إلى الإمام أو عامله على الغانمين",
    30: "العتق ووجه التقرب إلى الله عز وجل",
    31: "الكفارات الواجبات بالجنايات",
    32: "الإيفاء بالعقود",
    33: "تعديد نعم الله عز وجل وما يجب من شكرها",
    34: "حفظ اللسان عما لا يحتاج إليه",
    35: "الأمانات وما يجب من أدائها إلى أهلها",
    36: "تحريم النفس والجنايات عليها",
    37: "تحريم الفروج وما يجب من التعفف عنها",
    38: "قبض اليد عن الأموال المحرمة",
    39: "الطاعم والمشارب وما يجب التورع عنه منها",
    40: "الملابس والزي والأواني وما يكره منها",
    41: "تحريم الملاعب والملاهي",
    42: "الاقتصاد في النفقة وتحريم أكل المال بالباطل",
    43: "الحث على ترك الغل والحسد",
    44: "تحريم أعراض الناس وما يلزم من ترك الرتع فيها",
    45: "إخلاص العمل لله عز وجل وترك الرياء",
    46: "السرور بالحسنة والاغتمام بالسيئة",
    47: "معالجة كل ذنب بالتوبة",
    48: "القرابين والإبانة عن معناها وغرضها",
    49: "طاعة أولي الأمر بفصولها",
    50: "التمسك بما عليه الجماعة",
    51: "الحكم بين الناس",
    52: "الأمر بالمعروف والنهي عن المنكر",
    53: "التعاون على البر والتقوى",
    54: "الحياء بفصوله",
    55: "بر الوالدين",
    56: "صلة الأرحام",
    57: "حسن الخلق",
    58: "الإحسان إلى المماليك",
    59: "حق السادة على المماليك",
    60: "حقوق الأولاد والأهلين",
    61: "مقاربة أهل الدين وموادتهم وإفشاء السلام بينهم",
    62: "رد السلام",
    63: "عيادة المريض",
    64: "الصلاة على من مات من أهل القبلة",
    65: "تشميت العاطس",
    66: "مباعدة الكفار والمفسدين والغلظ عليهم",
    67: "إكرام الجار",
    68: "إكرام الضيف",
    69: "الستر على أصحاب القروف",
    70: "الصبر على المصائب وعما تنزع النفس إليه من لذة وشهوة",
    71: "الزهد وقصر الأمل",
    72: "المغيرة والمذاء",
    73: "الإعراض عن اللغو",
    74: "الجود والسخاء",
    75: "رحم الصغير وتوقير الكبير",
    76: "الإصلاح بين الناس",
    77: "أن يحب الرجل لأخيه المسلم ما يحب لنفسه، ويكره له ما يكره لنفسه، ويدخل فيه إماطة الأذى عن الطريق",
}
_ORDINAL_MAP = {
    "الأول": 1, "الثاني": 2, "الثالث": 3, "الرابع": 4, "الخامس": 5,
    "السادس": 6, "السابع": 7, "الثامن": 8, "التاسع": 9, "العاشر": 10,
    "الحادي عشر": 11, "الثاني عشر": 12, "الثالث عشر": 13, "الرابع عشر": 14,
    "الخامس عشر": 15, "السادس عشر": 16, "السابع عشر": 17, "الثامن عشر": 18,
    "التاسع عشر": 19, "العشرون": 20, "الثلاثون": 30, "الأربعون": 40,
    "الخمسون": 50, "الستون": 60, "السبعون": 70,
}
_UNITS = {"الحادي": 1, "الثاني": 2, "الثالث": 3, "الرابع": 4, "الخامس": 5,
          "السادس": 6, "السابع": 7, "الثامن": 8, "التاسع": 9}
_TENS = {"العشرون": 20, "الثلاثون": 30, "الأربعون": 40, "الخمسون": 50,
         "الستون": 60, "السبعون": 70}


def branch_number_from_heading(title):
    """Parse the Arabic ordinal at the start of a branch heading -> int, so we
    can look up the clean TOC topic (robust to page breaks/continuations)."""
    t = re.sub(r"\s+", " ", title).strip()
    t = t.split("من شعب")[0].strip()
    if t in _ORDINAL_MAP:
        return _ORDINAL_MAP[t]
    m = re.match(r"^(\S+)\s+و(\S+)$", t)  # "الحادي والعشرون" etc.
    if m and m.group(1) in _UNITS and m.group(2) in _TENS:
        return _TENS[m.group(2)] + _UNITS[m.group(1)]
    return None



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


def convert(text, collection_name):
    lines = text.split("\n")
    author, body_start = parse_header(lines)
    body = lines[body_start:]

    out = [f"collection||{collection_name}"]
    stats = {"books": 0, "chapters": 0, "hadith": 0, "skipped": 0}
    have_book = False
    intro_book_open = False
    branch_no = 0  # running number of the current شعبة (branch)
    cur_hadith = None  # index in `out` of the current hadith line being built
    hadith_frag = []

    def flush_hadith():
        nonlocal cur_hadith, hadith_frag
        if cur_hadith is not None:
            body_text = clean(" ".join(hadith_frag))
            num = out[cur_hadith]
            if body_text:
                out[cur_hadith] = f"hadith|{num}|{body_text}"
                stats["hadith"] += 1
            else:
                out.pop(cur_hadith)  # numbered marker with no text -> drop
            cur_hadith = None
            hadith_frag = []

    def emit_book(name):
        nonlocal have_book
        flush_hadith()
        out.append(f"book||{name}")
        have_book = True
        stats["books"] += 1

    def emit_chapter(name):
        nonlocal have_book
        flush_hadith()
        if not have_book:
            emit_book(collection_name)
        out.append(f"chapter||{name}")
        stats["chapters"] += 1

    for raw in body:
        s = raw.strip()
        if not s:
            continue

        # "### |" section marker
        m = SEC_RE.match(s)
        if m:
            inner = m.group(1).strip()
            inner_clean = re.sub(r"\s+", " ", TAG_RE.sub(" ", MS_RE.sub(" ", PAGE_RE.sub(" ", inner)))).strip()
            hm = HADNUM_RE.match(inner_clean)
            if hm:
                flush_hadith()
                if not have_book:
                    emit_book(collection_name)
                out.append(hm.group(1))  # will become "N|text" on flush
                cur_hadith = len(out) - 1
                hadith_frag = []
                continue
            if PAGEREF_RE.match(inner_clean) or not inner_clean:
                continue
            title = clean(inner)
            if title:
                emit_chapter(title)
            continue

        # "#"-level line: branch header or hadith text.
        if s.startswith("#"):
            frag = s.lstrip("#").strip()
            bm = BRANCH_RE.match(s)
            if bm:
                branch_no += 1
                heading = clean(bm.group(1))
                bnum = branch_number_from_heading(heading)
                topic = BRANCH_TOPICS.get(bnum)
                emit_book(topic or heading)
                continue
            # A page-only marker: skip.
            if PAGE_RE.search(frag) and not PAGE_RE.sub("", frag).strip():
                continue
            if cur_hadith is not None:
                hadith_frag.append(frag)
            # text before the first hadith (مقدمة body) is ignored as prologue
            continue

    flush_hadith()
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
