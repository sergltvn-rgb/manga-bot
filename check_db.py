import sqlite3
conn = sqlite3.connect('manga.db')
cursor = conn.cursor()
cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
print("Tables:", cursor.fetchall())
try:
    cursor.execute("SELECT * FROM akashic_ranobe LIMIT 5")
    print("Akashic:", cursor.fetchall())
    cursor.execute("SELECT * FROM british_ranobe LIMIT 5")
    print("British:", cursor.fetchall())
except Exception as e:
    print(e)
