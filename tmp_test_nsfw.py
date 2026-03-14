import asyncio
import aiohttp

async def main():
    async with aiohttp.ClientSession() as session:
        # Check nekos.life or waifu.pics
        # waifu.pics endpoints:
        # Categories list is usually static in older docs but let's see if we can get it
        try:
            async with session.get("https://api.waifu.pics/nsfw/neko") as resp:
                print("waifu.pics NSFW test:", resp.status)
        except Exception as e:
            print("waifu.pics Error:", e)

asyncio.run(main())
