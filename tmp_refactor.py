import re

def main():
    with open('bot.py', 'r', encoding='utf-8') as f:
        content = f.read()

    new_func = """
async def build_reader_data() -> dict:
    import aiosqlite
    from database import get_custom_name
    result = {"series": []}
    
    async with aiosqlite.connect('manga.db') as db:
        async with db.execute('SELECT DISTINCT volume FROM akashic_ranobe ORDER BY volume') as cursor:
            ak_vols = [row[0] for row in await cursor.fetchall()]
        if ak_vols:
            custom_title = await get_custom_name("series_akashic_records") or "Хроники Акаши"
            akashic = {"id": "akashic_records", "title": custom_title, "volumes": []}
            for vol in ak_vols:
                custom_vol = await get_custom_name(f"vol_akashic_records_{vol}") or f"Том {vol}"
                async with db.execute('SELECT chapter, url FROM akashic_ranobe WHERE volume = ? ORDER BY CAST(chapter AS REAL)', (vol,)) as c:
                    chapters = []
                    for row in await c.fetchall():
                        extracted = _clean_urls(row[1])
                        url_val = extracted[0] if len(extracted) == 1 else ""
                        custom_chap = await get_custom_name(f"chap_akashic_records_{vol}_{row[0]}") or f"Глава {row[0]}"
                        chapters.append({"chapter": row[0], "custom_name": custom_chap, "url": url_val, "urls": extracted})
                akashic["volumes"].append({"volume": vol, "custom_name": custom_vol, "chapters": chapters})
            result["series"].append(akashic)
            
        async with db.execute('SELECT DISTINCT volume FROM british_ranobe ORDER BY volume') as cursor:
            br_vols = [row[0] for row in await cursor.fetchall()]
        if br_vols:
            custom_title = await get_custom_name("series_british_belle") or "Поцелуй британской красавицы"
            british = {"id": "british_belle", "title": custom_title, "volumes": []}
            for vol in br_vols:
                custom_vol = await get_custom_name(f"vol_british_belle_{vol}") or f"Том {vol}"
                async with db.execute('SELECT chapter, url FROM british_ranobe WHERE volume = ? ORDER BY CAST(chapter AS REAL)', (vol,)) as c:
                    chapters = []
                    for row in await c.fetchall():
                        extracted = _clean_urls(row[1])
                        url_val = extracted[0] if len(extracted) == 1 else ""
                        custom_chap = await get_custom_name(f"chap_british_belle_{vol}_{row[0]}") or f"Глава {row[0]}"
                        chapters.append({"chapter": row[0], "custom_name": custom_chap, "url": url_val, "urls": extracted})
                british["volumes"].append({"volume": vol, "custom_name": custom_vol, "chapters": chapters})
            result["series"].append(british)
            
        async with db.execute('SELECT DISTINCT lang FROM ranobe_urls') as cursor:
            langs_ro = [row[0] for row in await cursor.fetchall()]
        for lang in langs_ro:
            async with db.execute('SELECT chapter_number, url FROM ranobe_urls WHERE lang = ? ORDER BY CAST(chapter_number AS REAL)', (lang,)) as c:
                chapters = []
                for row in await c.fetchall():
                    extracted = _clean_urls(row[1])
                    url_val = extracted[0] if len(extracted) == 1 else ""
                    custom_chap = await get_custom_name(f"chap_ranobe_{lang}_1_{row[0]}") or f"Глава {row[0]}"
                    chapters.append({"chapter": row[0], "custom_name": custom_chap, "url": url_val, "urls": extracted})
            if chapters:
                lname = "Русский" if lang == "ru" else "English" if lang == "en" else lang
                custom_title = await get_custom_name(f"series_ranobe_{lang}") or f"Ранобэ ({lname})"
                custom_vol = await get_custom_name(f"vol_ranobe_{lang}_1") or "Том 1"
                result["series"].append({
                    "id": f"ranobe_{lang}", "title": custom_title, "volumes": [{"volume": 1, "custom_name": custom_vol, "chapters": chapters}]
                })
                
        async with db.execute('SELECT DISTINCT lang FROM chapters_urls') as cursor:
            langs_mg = [row[0] for row in await cursor.fetchall()]
        for lang in langs_mg:
            async with db.execute('SELECT chapter_number, url FROM chapters_urls WHERE lang = ? ORDER BY CAST(chapter_number AS REAL)', (lang,)) as c:
                chapters = []
                for row in await c.fetchall():
                    extracted = _clean_urls(row[1])
                    url_val = extracted[0] if len(extracted) == 1 else ""
                    custom_chap = await get_custom_name(f"chap_manga_{lang}_1_{row[0]}") or f"Глава {row[0]}"
                    chapters.append({"chapter": row[0], "custom_name": custom_chap, "url": url_val, "urls": extracted})
            if chapters:
                lname = "Русский" if lang == "ru" else "English" if lang == "en" else lang
                custom_title = await get_custom_name(f"series_manga_{lang}") or f"Манга ({lname})"
                custom_vol = await get_custom_name(f"vol_manga_{lang}_1") or "Том 1"
                result["series"].append({
                    "id": f"manga_{lang}", "title": custom_title, "volumes": [{"volume": 1, "custom_name": custom_vol, "chapters": chapters}]
                })
                
    return result

"""

    # Ensure build_reader_data is near _clean_urls
    if 'def build_reader_data' not in content:
        content = content.replace("def _clean_urls(url_text: str) -> list:", new_func + "\ndef _clean_urls(url_text: str) -> list:")

    c_sync_old = r'''        import aiosqlite
        result = {"series": \[\]}
        
        async with aiosqlite\.connect\('manga\.db'\) as db:
            async with db\.execute\('SELECT DISTINCT volume FROM akashic_ranobe ORDER BY volume'\) as cursor:.*?        with open\("webapp/chapters_data\.json"'''
            
    c_sync_new = r'''        result = await build_reader_data()
        
        with open("webapp/chapters_data.json"'''

    content = re.sub(c_sync_old, c_sync_new, content, flags=re.DOTALL)

    r_api_old = r'''    try:
        async with aiosqlite\.connect\('manga\.db'\) as db:
            result = {"series": \[\]}
            
            # === Akashic Ranobe ===.*?        return aiohttp\.web\.json_response\(result, headers=CORS_HEADERS\)
            '''
            
    r_api_new = r'''    try:
        result = await build_reader_data()
        return aiohttp.web.json_response(result, headers=CORS_HEADERS)
'''

    content = re.sub(r_api_old, r_api_new, content, flags=re.DOTALL)
    
    with open('bot.py', 'w', encoding='utf-8') as f:
        f.write(content)
        
    print("Code replaced!")

if __name__ == '__main__':
    main()
