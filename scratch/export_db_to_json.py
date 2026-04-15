import sqlite3
import json
import re

def _clean_urls(url_text):
    if not url_text: return []
    links = re.findall(r'(https?://[^\s<"\'>]+)', url_text)
    return links

def export_data():
    conn = sqlite3.connect('manga.db')
    cursor = conn.cursor()

    result = {"series": [], "bot_username": "Alyamangapage_bot"}
    
    # Загружаем кастомные имена
    cursor.execute('SELECT id, name FROM custom_names')
    custom_names = {row[0]: row[1] for row in cursor.fetchall()}

    # 1. Хроники Акаши (akashic_ranobe)
    cursor.execute('SELECT DISTINCT volume FROM akashic_ranobe ORDER BY volume')
    ak_vols = [row[0] for row in cursor.fetchall()]
    if ak_vols:
        custom_title = custom_names.get("series_akashic_records") or "Хроники Акаши"
        akashic = {"id": "akashic_records", "title": custom_title, "cover_url": custom_names.get("cover_akashic_records", ""), "volumes": []}
        for vol in ak_vols:
            custom_vol = custom_names.get(f"vol_akashic_records_{vol}") or f"Том {vol}"
            cursor.execute('SELECT chapter, url FROM akashic_ranobe WHERE volume = ? ORDER BY CAST(chapter AS REAL)', (vol,))
            chapters = []
            for row in cursor.fetchall():
                extracted = _clean_urls(row[1])
                url_val = extracted[0] if len(extracted) == 1 else ""
                custom_chap = custom_names.get(f"chap_akashic_records_{vol}_{row[0]}") or f"Глава {row[0]}"
                chapters.append({"chapter": row[0], "custom_name": custom_chap, "url": url_val, "urls": extracted})
            akashic["volumes"].append({"volume": vol, "custom_name": custom_vol, "chapters": chapters})
        result["series"].append(akashic)

    # 2. Поцелуй британской красавицы (british_ranobe)
    cursor.execute('SELECT DISTINCT volume FROM british_ranobe ORDER BY volume')
    br_vols = [row[0] for row in cursor.fetchall()]
    if br_vols:
        custom_title = custom_names.get("series_british_belle") or "Поцелуй британской красавицы"
        british = {"id": "british_belle", "title": custom_title, "cover_url": custom_names.get("cover_british_belle", ""), "volumes": []}
        for vol in br_vols:
            custom_vol = custom_names.get(f"vol_british_belle_{vol}") or f"Том {vol}"
            cursor.execute('SELECT chapter, url FROM british_ranobe WHERE volume = ? ORDER BY CAST(chapter AS REAL)', (vol,))
            chapters = []
            for row in cursor.fetchall():
                extracted = _clean_urls(row[1])
                url_val = extracted[0] if len(extracted) == 1 else ""
                custom_chap = custom_names.get(f"chap_british_belle_{vol}_{row[0]}") or f"Глава {row[0]}"
                chapters.append({"chapter": row[0], "custom_name": custom_chap, "url": url_val, "urls": extracted})
            british["volumes"].append({"volume": vol, "custom_name": custom_vol, "chapters": chapters})
        result["series"].append(british)

    # 3. Ранобэ (ranobe_urls)
    cursor.execute('SELECT DISTINCT lang FROM ranobe_urls')
    langs_ro = [row[0] for row in cursor.fetchall()]
    for lang in langs_ro:
        cursor.execute('SELECT chapter_number, url FROM ranobe_urls WHERE lang = ? ORDER BY CAST(chapter_number AS REAL)', (lang,))
        chapters = []
        for row in cursor.fetchall():
            extracted = _clean_urls(row[1])
            url_val = extracted[0] if len(extracted) == 1 else ""
            custom_chap = custom_names.get(f"chap_ranobe_{lang}_1_{row[0]}") or f"Глава {row[0]}"
            chapters.append({"chapter": row[0], "custom_name": custom_chap, "url": url_val, "urls": extracted})
        if chapters:
            lname = "Русский" if lang == "ru" else "English" if lang == "en" else lang
            custom_title = custom_names.get(f"series_ranobe_{lang}") or f"Ранобэ ({lname})"
            custom_vol = custom_names.get(f"vol_ranobe_{lang}_1") or "Том 1"
            result["series"].append({
                "id": f"ranobe_{lang}", "title": custom_title, "cover_url": custom_names.get(f"cover_ranobe_{lang}", ""), "volumes": [{"volume": 1, "custom_name": custom_vol, "chapters": chapters}]
            })

    # 4. Манга (chapters_urls)
    cursor.execute('SELECT DISTINCT lang FROM chapters_urls')
    langs_mg = [row[0] for row in cursor.fetchall()]
    for lang in langs_mg:
        cursor.execute('SELECT chapter_number, url FROM chapters_urls WHERE lang = ? ORDER BY CAST(chapter_number AS REAL)', (lang,))
        chapters = []
        for row in cursor.fetchall():
            extracted = _clean_urls(row[1])
            url_val = extracted[0] if len(extracted) == 1 else ""
            custom_chap = custom_names.get(f"chap_manga_{lang}_1_{row[0]}") or f"Глава {row[0]}"
            chapters.append({"chapter": row[0], "custom_name": custom_chap, "url": url_val, "urls": extracted})
        if chapters:
            lname = "Русский" if lang == "ru" else "English" if lang == "en" else lang
            custom_title = custom_names.get(f"series_manga_{lang}") or f"Манга ({lname})"
            custom_vol = custom_names.get(f"vol_manga_{lang}_1") or "Том 1"
            result["series"].append({
                "id": f"manga_{lang}", "title": custom_title, "cover_url": custom_names.get(f"cover_manga_{lang}", ""), "volumes": [{"volume": 1, "custom_name": custom_vol, "chapters": chapters}]
            })

    with open('webapp/chapters_data.json', 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    
    conn.close()
    print("Export completed successfully!")

if __name__ == '__main__':
    export_data()
