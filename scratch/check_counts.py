import sqlite3
conn = sqlite3.connect('manga.db')
c = conn.cursor()
for table in ['chapters_urls', 'ranobe_urls']:
    c.execute(f'SELECT count(*) FROM {table}')
    print(f"{table}: {c.fetchone()[0]}")
conn.close()
