from __future__ import annotations

import asyncio

import aiosqlite


def run(coro):
    return asyncio.run(coro)


def test_shop_xp_pack_syncs_level_without_money_reward(tmp_path):
    from bot import apply_shop_xp_pack_purchase

    db_path = tmp_path / "shop-xp.db"

    async def scenario():
        async with aiosqlite.connect(db_path) as db:
            await db.execute(
                "CREATE TABLE users_stats (user_id INTEGER PRIMARY KEY, balance INTEGER DEFAULT 0, xp INTEGER DEFAULT 0, level INTEGER DEFAULT 1)"
            )
            await db.execute("INSERT INTO users_stats (user_id, balance, xp, level) VALUES (?, ?, ?, ?)", (1001, 1000, 90, 1))
            await db.commit()

            await db.execute("BEGIN IMMEDIATE")
            ok, new_xp, new_level = await apply_shop_xp_pack_purchase(db, 1001, price=500, xp_amount=120)
            await db.commit()

            async with db.execute("SELECT balance, xp, level FROM users_stats WHERE user_id = ?", (1001,)) as cursor:
                row = await cursor.fetchone()
            return ok, new_xp, new_level, row

    ok, new_xp, new_level, row = run(scenario())

    assert ok is True
    assert new_xp == 210
    assert new_level == 3
    assert row == (500, 210, 3)
