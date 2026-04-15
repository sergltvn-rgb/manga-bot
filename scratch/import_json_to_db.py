
import sqlite3
import json

def import_data():
    conn = sqlite3.connect('manga.db')
    cursor = conn.cursor()

    with open('webapp/chapters_data.json', 'r', encoding='utf-8') as f:
        data = json.load(f)

    for s in data.get('series', []):
        series_id = s['id']
        title = s['title']
        
        # Сохраняем кастомное имя серии
        cursor.execute('INSERT OR REPLACE INTO custom_names (id, name) VALUES (?, ?)', (f"series_{series_id}", title))
        
        if s.get('cover_url'):
            cursor.execute('INSERT OR REPLACE INTO custom_names (id, name) VALUES (?, ?)', (f"cover_{series_id}", s['cover_url']))

        for v in s.get('volumes', []):
            vol_num = v['volume']
            cursor.execute('INSERT OR REPLACE INTO custom_names (id, name) VALUES (?, ?)', (f"vol_{series_id}_{vol_num}", v.get('custom_name', f"Том {vol_num}")))
            
            for ch in v.get('chapters', []):
                ch_num = ch['chapter']
                ch_name = ch.get('custom_name', f"Глава {ch_num}")
                urls = ch.get('urls', [])
                url_str = '\n'.join(urls) if urls else ch.get('url', '')
                
                cursor.execute('INSERT OR REPLACE INTO custom_names (id, name) VALUES (?, ?)', (f"chap_{series_id}_{vol_num}_{ch_num}", ch_name))
                
                if series_id == 'akashic_records':
                    cursor.execute('INSERT OR REPLACE INTO akashic_ranobe (volume, chapter, url) VALUES (?, ?, ?)', (vol_num, ch_num, url_str))
                elif series_id == 'british_belle':
                    cursor.execute('INSERT OR REPLACE INTO british_ranobe (volume, chapter, url) VALUES (?, ?, ?)', (vol_num, ch_num, url_str))
                elif series_id.startswith('ranobe_'):
                    lang = series_id.replace('ranobe_', '')
                    # В ranobe_urls volume не хранится, всегда Том 1 в текущей схеме БД?
                    # Но в chapters_data.json может быть несколько томов. 
                    # Текущая схема БД для ranobe_urls: (chapter_number, lang, url)
                    cursor.execute('INSERT OR REPLACE INTO ranobe_urls (chapter_number, lang, url) VALUES (?, ?, ?)', (ch_num, lang, url_str))
                elif series_id.startswith('manga_'):
                    lang = series_id.replace('manga_', '')
                    cursor.execute('INSERT OR REPLACE INTO chapters_urls (chapter_number, lang, url) VALUES (?, ?, ?)', (ch_num, lang, url_str))

    conn.commit()
    conn.close()
    print("Import completed successfully!")

if __name__ == '__main__':
    import_data()
