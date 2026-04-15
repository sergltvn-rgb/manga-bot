import sqlite3
import datetime

DB_PATH = "manga.db"

def seed():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    
    # Add dummy comment
    chapter_key = "akashic_records_v11_ch0" 
    user_id = "12345" # String as per schema
    user_name = "TestUser"
    text = "Это тестовый комментарий со спойлером ||секрет||!"
    created_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    cur.execute("""
        INSERT INTO chapter_comments (chapter_key, user_id, user_name, text, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (chapter_key, user_id, user_name, text, created_at))
    
    comment_id = cur.lastrowid
    
    # Add dummy reaction
    cur.execute("""
        INSERT INTO chapter_reactions (chapter_key, user_id, reaction)
        VALUES (?, ?, ?)
    """, (chapter_key, user_id, "fire"))
    
    # Add like to comment
    cur.execute("""
        INSERT INTO comment_reactions (comment_id, user_id, type)
        VALUES (?, ?, ?)
    """, (comment_id, "54321", "like"))
    
    conn.commit()
    conn.close()
    print("Dummy data seeded!")

if __name__ == "__main__":
    seed()
