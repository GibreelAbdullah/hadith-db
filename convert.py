#!/usr/bin/env python3
"""Regenerate metadata.json files from the text files (source of truth).

This script reads the text files in data/{collection}/{lang}.txt,
parses the category|num|text format, and regenerates metadata.json
with byte offsets, book structure, records, and gradings.

Source of truth:
  - data/{collection}/*.txt  (hadith text per language)
  - data/collections.json    (collection list, categories, languages)
  - data/gradeTranslations.json (grade translations)

Generated:
  - data/{collection}/metadata.json (byte offsets, records, books, gradings)
"""

import json
import os
import urllib.request

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, "data")

GRADINGS_URL = "https://raw.githubusercontent.com/GibreelAbdullah/hadith-api/refs/heads/1/info.json"
GRADINGS_CACHE = os.path.join(SCRIPT_DIR, ".gradings_cache.json")

# Map info.json collection names to our collection names
GRADING_NAME_MAP = {
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
        suffix_int = int(suffix)
        if suffix_int >= 2:
            return base + chr(ord("a") + suffix_int - 1)
        elif suffix_int == 1:
            return base
    return s


def load_gradings():
    """Load gradings from hadith-api info.json."""
    if not os.path.exists(GRADINGS_CACHE):
        print(f"  Downloading gradings from {GRADINGS_URL}...")
        urllib.request.urlretrieve(GRADINGS_URL, GRADINGS_CACHE)

    data = json.load(open(GRADINGS_CACHE, encoding="utf-8"))
    gradings = {}
    for info_name, our_name in GRADING_NAME_MAP.items():
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
            coll_gradings[hadith_num] = [[g["name"], g["grade"]] for g in h["grades"]]
        gradings[our_name] = coll_gradings
        print(f"  Loaded {len(coll_gradings)} gradings for {our_name}")
    return gradings


def process_collection(coll_dir, collection_short_name, gradings, collections_data):
    """Regenerate metadata.json from the text files."""
    # Find available languages (txt files in the directory)
    lang_files = {}
    for f in os.listdir(coll_dir):
        if f.endswith(".txt"):
            lang = f[:-4]
            lang_files[lang] = os.path.join(coll_dir, f)

    if not lang_files:
        return

    # Use the first available language to parse structure
    primary_lang = "ar" if "ar" in lang_files else list(lang_files.keys())[0]
    primary_lines = open(lang_files[primary_lang], "rb").read().decode("utf-8").split("\n")
    # Remove trailing empty line
    if primary_lines and primary_lines[-1] == "":
        primary_lines = primary_lines[:-1]

    # Parse structure from the primary language file
    records = []
    books = {}
    collection_info = {}
    collection_intro = {}

    for line_idx, line in enumerate(primary_lines):
        first_pipe = line.find("|")
        if first_pipe == -1:
            continue
        second_pipe = line.find("|", first_pipe + 1)
        if second_pipe == -1:
            continue

        category = line[:first_pipe]
        num = line[first_pipe + 1:second_pipe]

        record = {"line": line_idx, "cat": category}

        if category == "collection":
            pass
        elif category == "collection_intro":
            pass
        elif category == "book":
            record["book"] = num if num else str(len(books) + 1)
        elif category == "book_intro":
            # Find which book this belongs to
            for prev_idx in range(line_idx - 1, -1, -1):
                prev_rec = records[prev_idx] if prev_idx < len(records) else None
                if prev_rec and prev_rec.get("cat") == "book":
                    record["book"] = prev_rec["book"]
                    break
        elif category == "chapter":
            # Find the current book
            for prev_rec in reversed(records):
                if prev_rec.get("cat") == "book":
                    record["book"] = prev_rec["book"]
                    break
            record["chapter"] = num
        elif category == "chapter_intro":
            for prev_rec in reversed(records):
                if prev_rec.get("cat") == "chapter":
                    record["book"] = prev_rec.get("book")
                    record["chapter"] = prev_rec.get("chapter")
                    break
        elif category == "hadith":
            for prev_rec in reversed(records):
                if prev_rec.get("cat") in ("book", "chapter"):
                    record["book"] = prev_rec.get("book")
                    if prev_rec.get("cat") == "chapter":
                        record["chapter"] = prev_rec.get("chapter")
                    break
            record["num"] = num
            # num_book: count hadiths in this book
            book_num = record.get("book")
            if book_num not in books:
                books[book_num] = {"count": 0}
            books[book_num]["count"] += 1
            record["num_book"] = books[book_num]["count"]

        records.append(record)

    # Build collection_info and books metadata from all language files
    # Use language order from collections.json, falling back to sorted
    coll_entry = next((c for c in collections_data["collections"] if c["short_name"] == collection_short_name), None)
    if coll_entry and coll_entry.get("languages"):
        lang_columns = [l for l in coll_entry["languages"] if l in lang_files]
    else:
        lang_columns = sorted(lang_files.keys())

    for lang in lang_columns:
        lines = open(lang_files[lang], "rb").read().decode("utf-8").split("\n")
        if lines and lines[-1] == "":
            lines = lines[:-1]

        for rec in records:
            if rec["line"] >= len(lines):
                continue
            line = lines[rec["line"]]
            second_pipe = line.find("|", line.find("|") + 1)
            text = line[second_pipe + 1:] if second_pipe != -1 else ""

            if rec["cat"] == "collection":
                collection_info[lang] = text
            elif rec["cat"] == "collection_intro":
                collection_intro[lang] = text

    # Build books list with names and hadith ranges
    books_list = []
    book_numbers = []
    for rec in records:
        if rec["cat"] == "book":
            book_numbers.append(rec.get("book", ""))

    for book_num in book_numbers:
        book_entry = {"number": book_num, "hadith_start": 0, "hadith_end": 0}

        # Get hadith range
        book_hadiths = [r for r in records if r.get("cat") == "hadith" and r.get("book") == book_num]
        if book_hadiths:
            nums = []
            for h in book_hadiths:
                try:
                    nums.append(int("".join(c for c in h["num"] if c.isdigit()) or "0"))
                except:
                    pass
            if nums:
                book_entry["hadith_start"] = min(nums)
                book_entry["hadith_end"] = max(nums)

        # Get book names from each language
        book_rec = next((r for r in records if r["cat"] == "book" and r.get("book") == book_num), None)
        if book_rec:
            for lang in lang_columns:
                lines = open(lang_files[lang], "rb").read().decode("utf-8").split("\n")
                if book_rec["line"] < len(lines):
                    line = lines[book_rec["line"]]
                    second_pipe = line.find("|", line.find("|") + 1)
                    text = line[second_pipe + 1:] if second_pipe != -1 else ""
                    book_entry[lang] = text

        books_list.append(book_entry)

    # Compute byte offsets for each language
    offsets = {}
    for lang in lang_columns:
        content = open(lang_files[lang], "rb").read()
        lang_offsets = []
        offset = 0
        for line in content.split(b"\n"):
            lang_offsets.append(offset)
            offset += len(line) + 1  # +1 for \n
        # Remove the last offset if file ends with \n (extra empty entry)
        if content.endswith(b"\n"):
            lang_offsets.append(offset - 1)
        else:
            lang_offsets.append(offset)
        offsets[lang] = lang_offsets

    # Add gradings
    coll_gradings = gradings.get(collection_short_name, {})
    metadata_gradings = {}
    if coll_gradings:
        for rec in records:
            if rec.get("cat") == "hadith" and rec.get("num"):
                for num_part in rec["num"].split(","):
                    if num_part in coll_gradings:
                        metadata_gradings[rec["num"]] = coll_gradings[num_part]
                        break

    # Build final metadata
    metadata = {
        "collection": collection_short_name,
        "languages": lang_columns,
        "books": books_list,
        "records": records,
        "offsets": offsets,
        "collection_info": collection_info,
        "collection_intro": collection_intro,
    }
    if metadata_gradings:
        metadata["gradings"] = metadata_gradings

    with open(os.path.join(coll_dir, "metadata.json"), "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False)

    print(f"  {collection_short_name}: {len(records)} records, {len(lang_columns)} languages")


def main():
    collections_path = os.path.join(DATA_DIR, "collections.json")
    collections_data = json.load(open(collections_path, encoding="utf-8"))

    print("Loading gradings...")
    gradings = load_gradings()

    print("\nRegenerating metadata from text files...")
    for coll in collections_data["collections"]:
        coll_dir = os.path.join(DATA_DIR, coll["short_name"])
        if os.path.isdir(coll_dir):
            process_collection(coll_dir, coll["short_name"], gradings, collections_data)

    print("\nDone!")


if __name__ == "__main__":
    main()
