import aiosqlite
import asyncio
import re

def _clean(t):
    links = re.findall(r'(https?://[^\s<"\'>]+)', t)
    if not links:
        return t
    telegraph = [l for l in links if 'telegra.ph' in l]
    return '\n'.join(telegraph if telegraph else links)

async def main():
    try:
        async with aiosqlite.connect('manga.db') as db:
            for t in ['chapters_urls','ranobe_urls']:
                async with db.execute(f'SELECT chapter_number, lang, url FROM {t}') as c:
                    rows = await c.fetchall()
                for r in rows:
                    if r[2]:
                        new_url = _clean(r[2])
                        if new_url != r[2]:
                            await db.execute(f'UPDATE {t} SET url=? WHERE chapter_number=? AND lang=?', (new_url, r[0], r[1]))
            
            for t in ['akashic_ranobe','british_ranobe']:
                async with db.execute(f'SELECT volume, chapter, url FROM {t}') as c:
                    rows = await c.fetchall()
                for r in rows:
                    if r[2]:
                        new_url = _clean(r[2])
                        if new_url != r[2]:
                            await db.execute(f'UPDATE {t} SET url=? WHERE volume=? AND chapter=?', (new_url, r[0], r[1]))
            
            await db.commit()
            print("DB Migration successfully completed.")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == '__main__':
    asyncio.run(main())
