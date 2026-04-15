import sqlite3
import os

db_path = "manga.db"

if not os.path.exists(db_path):
    print(f"Error: {db_path} not found.")
    exit(1)

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

tables = ["akashic_ranobe", "british_ranobe", "ranobe_urls", "chapters_urls", "custom_names"]

for table in tables:
    try:
        cursor.execute(f"SELECT count(*) FROM {table}")
        count = cursor.fetchone()[0]
        print(f"Table {table}: {count} records")
    except sqlite3.OperationalError as e:
        print(f"Error checking table {table}: {e}")

conn.close()
