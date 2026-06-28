#!/usr/bin/env python3
"""Convert hadith-db SQLite databases into plain text files + JSON metadata."""

import sqlite3
import json
import os

DB_DIR = os.path.dirname(os.path.abspath(__file__))
MASTER_DB = os.path.join(DB_DIR, "master", "master.db")
BOOKS_DIR = os.path.join(DB_DIR, "books")
OUTPUT_DIR = os.path.join(DB_DIR, "data")


def generate_collections_json():
    """Generate the top-level collections.json from master.db."""
    conn = sqlite3.connect(MASTER_DB)
    cur = conn.cursor()

    languages = [
        {"short_name": r[0], "full_name": r[1], "rtl": bool(r[2])}
        for r in cur.execute("SELECT short_name, full_name, rtl FROM languages")
    ]

    collections = []
    for r in cur.execute("SELECT short_name, ar, en FROM collection ORDER BY id"):
        # Get available languages from the book's database
        book_db = os.path.join(BOOKS_DIR, f"{r[0]}.db")
        available_langs = ["ar", "en"]
        if os.path.exists(book_db):
            bconn = sqlite3.connect(book_db)
            row = bconn.execute(
                "SELECT \"langs$start_end_hadith\" FROM hadith_data WHERE category='collection' LIMIT 1"
            ).fetchone()
            if row and row[0]:
                available_langs = json.loads(row[0])
            bconn.close()
        collections.append({"short_name": r[0], "ar": r[1], "en": r[2], "languages": available_langs})

    conn.close()

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(os.path.join(OUTPUT_DIR, "collections.json"), "w", encoding="utf-8") as f:
        json.dump({"languages": languages, "collections": collections}, f, ensure_ascii=False)


def process_book(db_path, collection_short_name, gradings):
    """Convert a single book database into text files + metadata."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # Detect language columns dynamically
    table_info = cur.execute("PRAGMA table_info(hadith_data)").fetchall()
    all_columns = [col[1] for col in table_info]
    known_non_lang = {"chronology", "langs$start_end_hadith", "book_number", "chapter_number", "hadith_num", "hadith_num_book", "category"}
    lang_columns = [c for c in all_columns if c not in known_non_lang]

    lang_cols_sql = ", ".join(f'"{c}"' for c in lang_columns)
    rows = cur.execute(
        f'SELECT chronology, "langs$start_end_hadith", book_number, chapter_number, '
        f"hadith_num, hadith_num_book, {lang_cols_sql}, category "
        f"FROM hadith_data ORDER BY chronology"
    ).fetchall()
    conn.close()

    out_dir = os.path.join(OUTPUT_DIR, collection_short_name)
    os.makedirs(out_dir, exist_ok=True)

    # Build text files and metadata
    lines_by_lang = {lang: [] for lang in lang_columns}
    metadata = {
        "collection": collection_short_name,
        "languages": lang_columns,
        "books": [],
        "records": [],
        "offsets": {lang: [] for lang in lang_columns},
    }

    collection_info = {lang: "" for lang in lang_columns}
    collection_intro = {lang: "" for lang in lang_columns}
    current_books = {}

    for row in rows:
        # Row structure: chronology, langs_field, book_num, chapter_num, hadith_num, hadith_num_book, *lang_texts, category
        _chron = row[0]
        langs_field = row[1]
        book_num = row[2]
        chapter_num = row[3]
        hadith_num = row[4]
        hadith_num_book = row[5]
        lang_texts = {lang_columns[i]: row[6 + i] for i in range(len(lang_columns))}
        category = row[6 + len(lang_columns)]

        # Standardize hadith numbers - remove spaces
        if hadith_num:
            hadith_num = hadith_num.replace(" ", "")

        for lang in lang_columns:
            text = (lang_texts[lang] or "").replace("\n", "\\n")
            # For structural rows, fall back to another language if empty
            if not text and category in ("collection", "book", "book_intro", "chapter", "chapter_intro"):
                for fallback in ["en", "ar"] + lang_columns:
                    fb_text = (lang_texts.get(fallback) or "").replace("\n", "\\n")
                    if fb_text:
                        text = fb_text
                        break
            lines_by_lang[lang].append(f"{category}|{hadith_num or ''}|{text}")

        line_index = len(lines_by_lang[lang_columns[0]]) - 1

        record = {"line": line_index, "cat": category}

        if category == "collection":
            for lang in lang_columns:
                text = (lang_texts[lang] or "").replace("\n", "\\n")
                if not text:
                    for fallback in ["en", "ar"] + lang_columns:
                        fb = (lang_texts.get(fallback) or "").replace("\n", "\\n")
                        if fb:
                            text = fb
                            break
                collection_info[lang] = text
            available_langs = json.loads(langs_field) if langs_field else lang_columns
            metadata["languages"] = available_langs
        elif category == "collection_intro":
            for lang in lang_columns:
                text = (lang_texts[lang] or "").replace("\n", "\\n")
                if not text:
                    for fallback in ["en", "ar"] + lang_columns:
                        fb = (lang_texts.get(fallback) or "").replace("\n", "\\n")
                        if fb:
                            text = fb
                            break
                collection_intro[lang] = text
        elif category == "book":
            hadith_range = json.loads(langs_field) if langs_field else [0, 0]
            record["book"] = book_num
            book_entry = {
                "number": book_num,
                "hadith_start": hadith_range[0],
                "hadith_end": hadith_range[1],
            }
            for lang in lang_columns:
                text = (lang_texts[lang] or "").replace("\n", "\\n")
                if not text:
                    for fallback in ["en", "ar"] + lang_columns:
                        fb = (lang_texts.get(fallback) or "").replace("\n", "\\n")
                        if fb:
                            text = fb
                            break
                book_entry[lang] = text
            current_books[book_num] = book_entry
        elif category == "book_intro":
            record["book"] = book_num
        elif category == "chapter":
            record["book"] = book_num
            record["chapter"] = chapter_num
        elif category == "chapter_intro":
            record["book"] = book_num
            record["chapter"] = chapter_num
        elif category == "hadith":
            record["book"] = book_num
            record["chapter"] = chapter_num
            record["num"] = hadith_num
            record["num_book"] = hadith_num_book

        metadata["records"].append(record)

    # Add gradings for this collection
    coll_gradings = gradings.get(collection_short_name, {})
    if coll_gradings:
        # Store as {hadith_num: [[name, grade], ...]}
        metadata_gradings = {}
        for rec in metadata["records"]:
            if rec.get("cat") == "hadith" and rec.get("num"):
                # Handle composite numbers like "272,273" - check each
                for num_part in rec["num"].split(","):
                    if num_part in coll_gradings:
                        metadata_gradings[rec["num"]] = [
                            [g["name"], g["grade"]] for g in coll_gradings[num_part]
                        ]
                        break
        metadata["gradings"] = metadata_gradings

    # Write text files and compute byte offsets
    for lang in lang_columns:
        content = "\n".join(lines_by_lang[lang]) + "\n"
        content_bytes = content.encode("utf-8")
        with open(os.path.join(out_dir, f"{lang}.txt"), "wb") as f:
            f.write(content_bytes)

        # Compute byte offsets for each line
        offsets = []
        offset = 0
        for line in lines_by_lang[lang]:
            offsets.append(offset)
            offset += len(line.encode("utf-8")) + 1
        offsets.append(offset)  # end sentinel
        metadata["offsets"][lang] = offsets

    metadata["collection_info"] = collection_info
    metadata["collection_intro"] = collection_intro
    metadata["books"] = [current_books[k] for k in sorted(current_books.keys(), key=lambda x: (int(''.join(c for c in x if c.isdigit()) or '0'), x))]

    # Supplement book names from sections file if available
    sections_path = os.path.join(DB_DIR, "sections", f"{collection_short_name}.min.json")
    if os.path.exists(sections_path):
        sections_data = json.load(open(sections_path, encoding="utf-8"))
        section_books = sections_data.get("books", {})
        for book in metadata["books"]:
            sec = section_books.get(str(book["number"]), {})
            if not book.get("ar") or book["ar"] == "":
                book["ar"] = sec.get("ara-name", "")
            if not book.get("en") or book["en"] == "":
                book["en"] = sec.get("eng-name", "")

    with open(os.path.join(out_dir, "metadata.json"), "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False)

    sizes = ", ".join(f"{lang}={len(('\n'.join(lines_by_lang[lang]) + '\n').encode('utf-8'))} bytes" for lang in lang_columns)
    print(f"  {collection_short_name}: {len(lines_by_lang[lang_columns[0]])} records, {sizes}")


GRADINGS_URL = "https://raw.githubusercontent.com/GibreelAbdullah/hadith-api/refs/heads/1/info.json"
GRADINGS_CACHE = os.path.join(DB_DIR, ".gradings_cache.json")

# Map info.json collection names to our collection names
COLLECTION_NAME_MAP = {
    "abudawud": "abudawud",
    "ibnmajah": "ibn_majah",
    "malik": "malik",
    "nasai": "nasai",
    "tirmidhi": "tirmidhi",
}

def arabicnumber_to_hadith_num(num):
    """Convert info.json arabicnumber (e.g., 384.2) to our format (e.g., 384b)."""
    if isinstance(num, int):
        return str(num)
    s = str(num)
    if "." in s:
        base, suffix = s.split(".", 1)
        # .2 -> b, .3 -> c, etc.
        suffix_int = int(suffix)
        if suffix_int >= 2:
            return base + chr(ord("a") + suffix_int - 1)
    return s


def load_gradings():
    """Load gradings from hadith-api info.json, using a local cache."""
    import urllib.request

    if not os.path.exists(GRADINGS_CACHE):
        print(f"  Downloading gradings from {GRADINGS_URL}...")
        urllib.request.urlretrieve(GRADINGS_URL, GRADINGS_CACHE)

    data = json.load(open(GRADINGS_CACHE, encoding="utf-8"))

    # Build a lookup: {our_collection_name: {hadith_num_str: [grades]}}
    gradings = {}
    for info_name, our_name in COLLECTION_NAME_MAP.items():
        if info_name not in data:
            continue
        coll_gradings = {}
        for h in data[info_name]["hadiths"]:
            if not h.get("grades"):
                continue
            arabic_num = h.get("arabicnumber")
            if arabic_num is None:
                continue
            hadith_num = arabicnumber_to_hadith_num(arabic_num)
            coll_gradings[hadith_num] = h["grades"]
        gradings[our_name] = coll_gradings
        print(f"  Loaded {len(coll_gradings)} gradings for {our_name}")

    return gradings


def main():
    print("Generating collections.json...")
    generate_collections_json()

    print("Loading gradings from hadith-api info.json...")
    gradings = load_gradings()

    print("Processing books...")
    conn = sqlite3.connect(MASTER_DB)
    collections = [r[0] for r in conn.execute("SELECT short_name FROM collection ORDER BY id")]
    conn.close()

    for coll in collections:
        db_path = os.path.join(BOOKS_DIR, f"{coll}.db")
        if os.path.exists(db_path):
            process_book(db_path, coll, gradings)
        else:
            print(f"  WARNING: {db_path} not found, skipping")

    print("Done!")


if __name__ == "__main__":
    main()
