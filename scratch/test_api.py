import aiohttp
import asyncio
import json

API_URL = "http://localhost:8080"

async def test_api():
    async with aiohttp.ClientSession() as session:
        # 1. Test Reader Data
        print("Testing /api/reader...")
        async with session.get(f"{API_URL}/api/reader") as resp:
            print(f"Status: {resp.status}")
            data = await resp.json()
            print(f"Series found: {len(data.get('series', []))}")
            if not data.get('series'):
                print("FAILED: No series found")
                return

        # 2. Test Reactions GET
        chapter_key = data['series'][0]['volumes'][0]['chapters'][0]['chapter']
        print(f"Testing /api/reactions for {chapter_key}...")
        async with session.get(f"{API_URL}/api/reactions", params={"chapter_key": chapter_key}) as resp:
            print(f"Status: {resp.status}")
            reactions = await resp.json()
            print(f"Reactions: {reactions.get('reactions', {})}")

        # 3. Test Comments GET
        print(f"Testing /api/comments for {chapter_key}...")
        async with session.get(f"{API_URL}/api/comments", params={"chapter_key": chapter_key}) as resp:
            print(f"Status: {resp.status}")
            comments = await resp.json()
            print(f"Comments count: {len(comments.get('comments', []))}")

        print("\nAPI Tests completed successfully!")

if __name__ == "__main__":
    try:
        asyncio.run(test_api())
    except Exception as e:
        print(f"ERROR: {e}")
