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

    rows = cur.execute(
        'SELECT chronology, "langs$start_end_hadith", book_number, chapter_number, '
        "hadith_num, hadith_num_book, ar, en, category "
        "FROM hadith_data ORDER BY chronology"
    ).fetchall()
    conn.close()

    out_dir = os.path.join(OUTPUT_DIR, collection_short_name)
    os.makedirs(out_dir, exist_ok=True)

    # Build text files and metadata
    ar_lines = []
    en_lines = []
    metadata = {
        "collection": collection_short_name,
        "languages": ["ar", "en"],
        "books": [],
        "records": [],  # one entry per line: {category, book, chapter, hadith_num, hadith_num_book}
        "offsets": {"ar": [], "en": []},
    }

    collection_info = {"ar": "", "en": ""}
    collection_intro = {"ar": "", "en": ""}
    current_books = {}  # book_number -> {ar, en, start_hadith, end_hadith, chapters: [...]}

    for row in rows:
        _chron, langs_field, book_num, chapter_num, hadith_num, hadith_num_book, ar, en, category = row

        # Standardize hadith numbers - remove spaces
        if hadith_num:
            hadith_num = hadith_num.replace(" ", "")

        ar_text = (ar or "").replace("\n", "\\n")
        en_text = (en or "").replace("\n", "\\n")
        ar_lines.append(f"{category}|{hadith_num or ''}|{ar_text}")
        en_lines.append(f"{category}|{hadith_num or ''}|{en_text}")

        line_index = len(ar_lines) - 1

        record = {"line": line_index, "cat": category}

        if category == "collection":
            collection_info = {"ar": ar_text, "en": en_text}
            available_langs = json.loads(langs_field) if langs_field else ["ar", "en"]
            metadata["languages"] = available_langs
        elif category == "collection_intro":
            collection_intro = {"ar": ar_text, "en": en_text}
        elif category == "book":
            hadith_range = json.loads(langs_field) if langs_field else [0, 0]
            record["book"] = book_num
            current_books[book_num] = {
                "number": book_num,
                "ar": ar_text,
                "en": en_text,
                "hadith_start": hadith_range[0],
                "hadith_end": hadith_range[1],
            }
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
    ar_content = "\n".join(ar_lines) + "\n"
    en_content = "\n".join(en_lines) + "\n"

    ar_bytes = ar_content.encode("utf-8")
    en_bytes = en_content.encode("utf-8")

    with open(os.path.join(out_dir, "ar.txt"), "wb") as f:
        f.write(ar_bytes)
    with open(os.path.join(out_dir, "en.txt"), "wb") as f:
        f.write(en_bytes)

    # Compute byte offsets for each line
    ar_offsets = []
    offset = 0
    for line in ar_lines:
        ar_offsets.append(offset)
        offset += len(line.encode("utf-8")) + 1  # +1 for \n
    ar_offsets.append(offset)  # end sentinel

    en_offsets = []
    offset = 0
    for line in en_lines:
        en_offsets.append(offset)
        offset += len(line.encode("utf-8")) + 1
    en_offsets.append(offset)

    metadata["offsets"]["ar"] = ar_offsets
    metadata["offsets"]["en"] = en_offsets
    metadata["collection_info"] = collection_info
    metadata["collection_intro"] = collection_intro
    metadata["books"] = [current_books[k] for k in sorted(current_books.keys(), key=lambda x: (int(''.join(c for c in x if c.isdigit()) or '0'), x))]

    with open(os.path.join(out_dir, "metadata.json"), "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False)

    print(f"  {collection_short_name}: {len(ar_lines)} records, ar={len(ar_bytes)} bytes, en={len(en_bytes)} bytes")


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
