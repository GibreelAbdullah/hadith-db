#!/usr/bin/env python3
"""Add new language translations to existing hadith-db SQLite databases."""

import json
import sqlite3
import os

EDITIONS_DIR = "/tmp/hadith-api-updater/hadith-api-updater-master/hadith-api-master/editions"
BOOKS_DIR = "/home/gibreel/Projects/hadith-db/books"
MASTER_DB = "/home/gibreel/Projects/hadith-db/master/master.db"

LANG_MAP = {"ara": "ar", "eng": "en", "ben": "bn", "fra": "fr", "ind": "id", "rus": "ru", "tam": "ta", "tur": "tr", "urd": "ur"}
BOOK_MAP = {
    "abudawud": "abudawud", "bukhari": "bukhari", "ibnmajah": "ibn_majah",
    "malik": "malik", "muslim": "muslim", "musnadahmad": "musnad_ahmad",
    "nasai": "nasai", "tirmidhi": "tirmidhi", "nawawi": "nawawi",
    "qudsi": "qudsi", "dehlawi": "dehlawi", "abuhanifa": "abuhanifa",
    "maanialathaar": "maanialathaar"
}


def arabicnumber_to_hadith_num(num):
    """Convert edition arabicnumber (e.g., 135.02) to our format (e.g., 135b)."""
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


def add_language_to_db(our_book, lang, edition_file):
    """Add a language column to the database and populate it."""
    db_path = os.path.join(BOOKS_DIR, f"{our_book}.db")
    if not os.path.exists(db_path):
        print(f"  SKIP: {db_path} not found")
        return

    # Load the edition JSON
    edition_path = os.path.join(EDITIONS_DIR, edition_file)
    data = json.load(open(edition_path))

    # Build lookup: arabicnumber -> text
    text_by_num = {}
    for h in data["hadiths"]:
        arabic_num = h.get("arabicnumber", h.get("hadithnumber"))
        hadith_num = arabicnumber_to_hadith_num(arabic_num)
        text_by_num[hadith_num] = h.get("text", "")

    conn = sqlite3.connect(db_path)

    # Check if column already exists
    columns = [col[1] for col in conn.execute("PRAGMA table_info(hadith_data)").fetchall()]
    if lang in columns:
        print(f"  SKIP: {our_book}/{lang} column already exists")
        conn.close()
        return

    # Add column
    conn.execute(f'ALTER TABLE hadith_data ADD COLUMN "{lang}" TEXT')

    # Get all hadith rows
    rows = conn.execute("SELECT chronology, hadith_num, category FROM hadith_data").fetchall()

    updated = 0
    for chronology, hadith_num, category in rows:
        if category == "hadith" and hadith_num:
            # Standardize: remove spaces
            lookup_num = hadith_num.replace(" ", "")
            text = text_by_num.get(lookup_num, "")
            if text:
                conn.execute(f'UPDATE hadith_data SET "{lang}" = ? WHERE chronology = ?', [text, chronology])
                updated += 1
        elif category == "collection":
            # Use metadata name if available
            name = data.get("metadata", {}).get("name", "")
            if name:
                conn.execute(f'UPDATE hadith_data SET "{lang}" = ? WHERE chronology = ?', [name, chronology])

    conn.commit()

    # Update the langs$start_end_hadith on the collection row
    row = conn.execute('SELECT "langs$start_end_hadith" FROM hadith_data WHERE category = "collection"').fetchone()
    if row and row[0]:
        langs = json.loads(row[0])
        if lang not in langs:
            langs.append(lang)
            conn.execute('UPDATE hadith_data SET "langs$start_end_hadith" = ? WHERE category = "collection"', [json.dumps(langs)])
            conn.commit()

    conn.close()
    print(f"  {our_book}/{lang}: {updated}/{len(text_by_num)} hadiths matched")


def update_master_languages():
    """Update the languages table in master.db."""
    new_langs = {
        "bn": ("বাংলা", False),
        "fr": ("Français", False),
        "id": ("Bahasa Indonesia", False),
        "ru": ("Русский", False),
        "ta": ("தமிழ்", False),
        "tr": ("Türkçe", False),
        "ur": ("اردو", True),
    }
    conn = sqlite3.connect(MASTER_DB)
    existing = [r[0] for r in conn.execute("SELECT short_name FROM languages")]
    for lang, (full_name, rtl) in new_langs.items():
        if lang not in existing:
            conn.execute("INSERT INTO languages (short_name, full_name, rtl) VALUES (?, ?, ?)", [lang, full_name, rtl])
            print(f"  Added language: {lang} ({full_name})")
    conn.commit()
    conn.close()


def main():
    print("Adding new languages to master.db...")
    update_master_languages()

    print("\nAdding translations to book databases...")
    editions_dir = EDITIONS_DIR
    for f in sorted(os.listdir(editions_dir)):
        if not f.endswith(".min.json") or "1.min" in f:
            continue
        parts = f.replace(".min.json", "").split("-", 1)
        if len(parts) != 2:
            continue
        lang_code, book = parts
        lang = LANG_MAP.get(lang_code)
        our_book = BOOK_MAP.get(book)
        if not lang or not our_book:
            continue
        # Skip ar and en (already exist)
        if lang in ("ar", "en"):
            continue
        add_language_to_db(our_book, lang, f)

    print("\nDone! Run convert.py to regenerate data files.")


if __name__ == "__main__":
    main()
