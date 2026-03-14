import asyncio
import aiohttp

async def main():
    async with aiohttp.ClientSession() as session:
        url = "https://api.purrbot.site/v2/img/nsfw/fuck/gif"
        try:
            async with session.get(url) as resp:
                data = await resp.json()
                print("PurrBot response:", data)
        except Exception as e:
            print("PurrBot Error:", e)

asyncio.run(main())
