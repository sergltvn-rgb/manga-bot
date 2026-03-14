import asyncio
import aiohttp

async def main():
    async with aiohttp.ClientSession() as session:
        async with session.get("https://nekos.best/api/v2/endpoints") as resp:
            data = await resp.json()
            print(data)

asyncio.run(main())
