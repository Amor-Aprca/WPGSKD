#!/usr/bin/env python3

import argparse
import sqlite3
import os
import sys

# Add path to import AtomicSQL
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from wpgskd.utils.AtomicSQL import AtomicSQL

"""
Merge multiple Key Store DBs into one.
Correctly handles multi-table structure (one table per service).
"""

parser = argparse.ArgumentParser(
    "Key Store DB merger",
    description="Script to merge one key store db into another"
)
parser.add_argument(
    "-i", "--input",
    help="key store db that will send keys (Source)",
    required=True)
parser.add_argument(
    "-o", "--output",
    help="key store db that will receive keys (Target)",
    required=True)
args = parser.parse_args()

if not os.path.exists(args.input):
    print(f"Input file not found: {args.input}")
    sys.exit(1)

# Ensure output dir exists
os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)

input_db = AtomicSQL()
input_id = input_db.load(sqlite3.connect(args.input))

output_db = AtomicSQL()
output_id = output_db.load(sqlite3.connect(args.output))

# 1. Get all table names from input DB
tables = input_db.safe_execute(
    input_id,
    lambda db, cursor: cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
).fetchall()

tables = [t[0] for t in tables]
print(f"Found tables in input DB: {tables}")

total_added = 0
total_updated = 0
total_skipped = 0

for table in tables:
    print(f"\nProcessing table: {table}...")
    
    # 2. Ensure table exists in output DB
    # We copy the schema from input if it doesn't exist in output
    # But standard vault schema is: id, kid, key_, title
    # To support 'type' column in future, we should check input columns
    
    # Get columns from input table
    input_cols_info = input_db.safe_execute(
        input_id,
        lambda db, cursor: cursor.execute(f"PRAGMA table_info(`{table}`)")
    ).fetchall()
    input_cols = [col[1] for col in input_cols_info]
    
    # Check if table exists in output
    out_table_exists = output_db.safe_execute(
        output_id,
        lambda db, cursor: cursor.execute("SELECT count(name) FROM sqlite_master WHERE type='table' AND name=?", [table])
    ).fetchone()[0] == 1
    
    if not out_table_exists:
        print(f"  - Creating table {table} in output DB...")
        # Standard creation from vaults.py, but let's try to be dynamic if we want 'type' support later
        # For now, stick to standard schema to ensure compatibility with wpgskd
        output_db.safe_execute(
            output_id,
            lambda db, cursor: cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS `{table}` (
                    "id"        INTEGER NOT NULL UNIQUE,
                    "kid"       TEXT NOT NULL COLLATE NOCASE,
                    "key_"      TEXT NOT NULL COLLATE NOCASE,
                    "title"     TEXT,
                    PRIMARY KEY("id" AUTOINCREMENT),
                    UNIQUE("kid", "key_")
                );
                """
            )
        )
        # If input has 'type' column, we might want to add it? 
        # Let's handle Requirement 2 separately.

    # 3. Fetch all rows from input table
    rows = input_db.safe_execute(
        input_id,
        lambda db, cursor: cursor.execute(f"SELECT kid, key_, title FROM `{table}`")
    ).fetchall()
    
    for kid, key, title in rows:
        # Check existence in output
        exists = output_db.safe_execute(
            output_id,
            lambda db, cursor: cursor.execute(
                f"SELECT title FROM `{table}` WHERE kid=? AND key_=?",
                [kid, key]
            )
        ).fetchone()
        
        if exists:
            # Update title if missing
            current_title = exists[0]
            if title and not current_title:
                output_db.safe_execute(
                    output_id,
                    lambda db, cursor: cursor.execute(
                        f"UPDATE `{table}` SET title=? WHERE kid=? AND key_=?",
                        (title, kid, key)
                    )
                )
                total_updated += 1
                # print(f"    Updated {kid}")
            else:
                total_skipped += 1
        else:
            # Insert
            output_db.safe_execute(
                output_id,
                lambda db, cursor: cursor.execute(
                    f"INSERT INTO `{table}` (kid, key_, title) VALUES (?, ?, ?)",
                    (kid, key, title)
                )
            )
            total_added += 1
            print(f"    Added {kid}")

output_db.commit(output_id)

print("\n" + "="*30)
print(f"Merge Complete!")
print(f"Added:   {total_added}")
print(f"Updated: {total_updated}")
print(f"Skipped: {total_skipped}")
print("="*30)