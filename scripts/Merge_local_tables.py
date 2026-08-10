#!/usr/bin/env python3
"""
Merge multiple tables in the same SQLite DB into one.
Uses command line arguments for source and target tables.
Prefers rows with a title when duplicates are found.

Usage:
  python merge_local_tables.py -c NF:netflix -o netflix
  python merge_local_tables.py -c YT:youtube -o youtube -d M:\WPGSKD\wpgskd\key_store.db
"""

import sqlite3
import os
import argparse
import re

def is_valid_table_name(name: str) -> bool:
    return bool(re.match(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$", name))

def main():
    parser = argparse.ArgumentParser(description="Merge tables in SQLite DB")
    parser.add_argument("-c", "--clear", required=True, 
                        help="Source tables to merge, separated by colon (e.g., NF:netflix)")
    parser.add_argument("-o", "--output", required=True, 
                        help="Output table name (e.g., netflix)")
    parser.add_argument("-db", "--database", default="key_store.db", 
                        help="Path to SQLite database (default: key_store.db)")
    
    args = parser.parse_args()

    db_path = args.database
    source_tables = args.clear.split(':')
    target_table = args.output

    # Validate table names
    for t in source_tables + [target_table]:
        if not is_valid_table_name(t):
            print(f"Error: Invalid table name '{t}'. Only letters, numbers, and underscores allowed.")
            return

    if not os.path.exists(db_path):
        print(f"Database not found: {db_path}")
        return

    print(f"Database: {db_path}")
    print(f"Merging sources: {source_tables} -> Target: {target_table}")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Read data from source tables
    data = {}
    
    for table in source_tables:
        try:
            cursor.execute(f"SELECT kid, key_, title FROM `{table}`")
            rows = cursor.fetchall()
            print(f"Read {len(rows)} rows from `{table}`")
            
            for kid, key, title in rows:
                dict_key = (kid, key)
                if dict_key in data:
                    # Duplicate found: prefer the one with a title
                    existing_title = data[dict_key][2]
                    if not existing_title and title:
                        data[dict_key] = (kid, key, title)
                else:
                    data[dict_key] = (kid, key, title)
        except sqlite3.OperationalError:
            print(f"Table `{table}` does not exist, skipping.")

    print(f"Total unique keys after merge: {len(data)}")

    # Drop source tables
    for table in source_tables:
        print(f"Dropping source table `{table}`...")
        cursor.execute(f"DROP TABLE IF EXISTS `{table}`")
    
    # Drop target table if it already exists to ensure a clean insert
    cursor.execute(f"DROP TABLE IF EXISTS `{target_table}`")
    
    # Create fresh target table
    print(f"Creating new table `{target_table}`...")
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS `{target_table}` (
            "id"        INTEGER NOT NULL UNIQUE,
            "kid"       TEXT NOT NULL COLLATE NOCASE,
            "key_"      TEXT NOT NULL COLLATE NOCASE,
            "title"     TEXT,
            PRIMARY KEY("id" AUTOINCREMENT),
            UNIQUE("kid", "key_")
        );
    """)

    # Insert merged data
    inserted = 0
    for kid, key, title in data.values():
        cursor.execute(
            f"INSERT INTO `{target_table}` (kid, key_, title) VALUES (?, ?, ?)",
            (kid, key, title)
        )
        inserted += 1

    conn.commit()
    conn.close()

    print(f"Successfully inserted {inserted} rows into the new `{target_table}` table.")
    print("Done.")

if __name__ == "__main__":
    main()