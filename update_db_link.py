import asyncio
from database import set_commands_link, init_db

async def main():
    await init_db()
    # Укажите созданный Telegraph URL
    link = "https://telegra.ph/Komandy-bota-Alya-koketnichaet-so-mnoj-03-14"
    await set_commands_link(link)
    print("Database updated with new Telegraph link.")

asyncio.run(main())
