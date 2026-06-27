#!/usr/bin/env python3
"""Import new books from hadith-api-updater into hadith-db SQLite format."""

import json
import sqlite3
import os

EDITIONS_DIR = "/tmp/hadith-api-updater/hadith-api-updater-master/hadith-api-master/editions"
SECTIONS_DIR = "/tmp/hadith-api-updater/hadith-api-updater-master/hadith-api-master/updates/sections"
BOOKS_DIR = "/home/gibreel/Projects/hadith-db/books"
MASTER_DB = "/home/gibreel/Projects/hadith-db/master/master.db"

# New books to import: {our_name: {edition_prefix: lang_code}}
NEW_BOOKS = {
    "abuhanifa": {"ara-abuhanifa": "ar"},
    "dehlawi": {"ara-dehlawi": "ar", "eng-dehlawi": "en"},
    "maanialathaar": {"ara-maanialathaar": "ar"},
    "nawawi": {"ara-nawawi": "ar", "eng-nawawi": "en"},
    "qudsi": {"ara-qudsi": "ar", "eng-qudsi": "en"},
}

LANG_MAP = {"ara": "ar", "eng": "en", "ben": "bn", "fra": "fr", "tur": "tr"}


def import_book(book_name, editions):
    """Create a SQLite database for a book from its edition JSON files."""
    # Load Arabic edition as the base (has structure/metadata)
    ara_key = next(k for k in editions if k.startswith("ara"))
    ara_data = json.load(open(os.path.join(EDITIONS_DIR, f"{ara_key}.min.json")))

    metadata = ara_data["metadata"]
    sections = metadata.get("sections", {})
    hadiths = ara_data["hadiths"]

    # Load section names from sections file
    sections_file_map = {
        "abuhanifa": "abuhanifa", "dehlawi": "dehlawi",
        "maanialathaar": "maanialathaar", "nawawi": "nawawi", "qudsi": "qudsi"
    }
    sections_filename = sections_file_map.get(book_name, book_name)
    sections_path = os.path.join(SECTIONS_DIR, f"{sections_filename}.min.json")
    if os.path.exists(sections_path):
        sections_data = json.load(open(sections_path))
        section_books = sections_data.get("books", {})
    else:
        section_books = {}

    # Load other language editions
    lang_data = {}
    for edition_name, lang in editions.items():
        data = json.load(open(os.path.join(EDITIONS_DIR, f"{edition_name}.min.json")))
        lang_data[lang] = {h["hadithnumber"]: h["text"] for h in data["hadiths"]}

    # Determine available languages
    available_langs = list(editions.values())

    # Build the database
    db_path = os.path.join(BOOKS_DIR, f"{book_name}.db")
    if os.path.exists(db_path):
        os.remove(db_path)

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA page_size = 1024")

    # Create table with language columns
    lang_cols = ", ".join(f"{lang} TEXT" for lang in available_langs)
    conn.execute(f"""
        CREATE TABLE hadith_data (
            chronology INTEGER PRIMARY KEY,
            "langs$start_end_hadith" TEXT,
            book_number TEXT,
            chapter_number TEXT,
            hadith_num TEXT,
            hadith_num_book INTEGER,
            {lang_cols},
            category TEXT
        )
    """)

    chronology = 1

    # Collection row
    lang_values = {lang: metadata["name"] for lang in available_langs}
    cols = ", ".join(f'"{lang}"' for lang in available_langs)
    vals = ", ".join("?" for _ in available_langs)
    conn.execute(
        f'INSERT INTO hadith_data (chronology, "langs$start_end_hadith", {cols}, category) VALUES (?, ?, {vals}, ?)',
        [chronology, json.dumps(available_langs)] + [lang_values.get(lang, "") for lang in available_langs] + ["collection"]
    )
    chronology += 1

    # Track book info for sections
    current_book = None
    book_hadith_start = None
    book_hadith_end = None

    # Process sections (books) and hadiths
    for section_num in sorted(sections.keys(), key=lambda x: int(x) if x.isdigit() else 0):
        section = sections[section_num]
        if section_num == "0":
            continue  # Skip empty section 0

        # Book row - get names from sections file
        sec_info = section_books.get(str(section_num), {})
        ar_name = sec_info.get("ara-name", section.get("ara-name", section.get("ara_name", "")))
        en_name = sec_info.get("eng-name", section.get("eng-name", section.get("eng_name", "")))
        book_lang_values = []
        for lang in available_langs:
            if lang == "ar":
                book_lang_values.append(ar_name)
            elif lang == "en":
                book_lang_values.append(en_name)
            else:
                book_lang_values.append(en_name)  # fallback to English

        # Find hadith range for this section
        section_hadiths = [h for h in hadiths if str(h.get("reference", {}).get("book")) == str(section_num)]
        if section_hadiths:
            h_start = section_hadiths[0]["arabicnumber"]
            h_end = section_hadiths[-1]["arabicnumber"]
        else:
            h_start = 0
            h_end = 0

        conn.execute(
            f'INSERT INTO hadith_data (chronology, "langs$start_end_hadith", book_number, {cols}, category) VALUES (?, ?, ?, {vals}, ?)',
            [chronology, json.dumps([h_start, h_end]), section_num] + book_lang_values + ["book"]
        )
        chronology += 1

        # Hadiths in this section
        for h in section_hadiths:
            h_num = str(h["arabicnumber"])
            hadith_lang_values = []
            for lang in available_langs:
                text = lang_data.get(lang, {}).get(h["hadithnumber"], "")
                hadith_lang_values.append(text)

            conn.execute(
                f'INSERT INTO hadith_data (chronology, book_number, hadith_num, hadith_num_book, {cols}, category) VALUES (?, ?, ?, ?, {vals}, ?)',
                [chronology, section_num, h_num, h.get("reference", {}).get("hadith"), ] + hadith_lang_values + ["hadith"]
            )
            chronology += 1

    conn.execute("PRAGMA journal_mode = delete")
    conn.commit()
    conn.execute("VACUUM")
    conn.close()

    print(f"  {book_name}: {chronology - 1} records, langs={available_langs}")
    return metadata["name"], available_langs


def update_master_db(new_collections):
    """Add new collections to master.db."""
    conn = sqlite3.connect(MASTER_DB)

    existing = [r[0] for r in conn.execute("SELECT short_name FROM collection")]

    for book_name, (full_name, langs) in new_collections.items():
        if book_name in existing:
            print(f"  Skipping {book_name} (already in master)")
            continue
        # Use the full name for both ar and en (will be overridden by actual names)
        ar_name = full_name  # These are English names from metadata
        en_name = full_name
        conn.execute(
            "INSERT INTO collection (short_name, type, ar, en) VALUES (?, 'collection', ?, ?)",
            [book_name, ar_name, en_name]
        )
        print(f"  Added {book_name} to master.db")

    conn.commit()
    conn.close()


def main():
    print("Importing new books...")
    new_collections = {}

    for book_name, editions in NEW_BOOKS.items():
        full_name, langs = import_book(book_name, editions)
        new_collections[book_name] = (full_name, langs)

    print("\nUpdating master.db...")
    update_master_db(new_collections)

    print("\nDone! Now run convert.py to generate text files and metadata.")


if __name__ == "__main__":
    main()
