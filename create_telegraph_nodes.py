import json
import asyncio
import aiohttp

async def create_page():
    # 1. Сначала создаем аккаунт
    account_url = "https://api.telegra.ph/createAccount?short_name=AlyaBot&author_name=AlyaBot"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(account_url) as resp:
                acc_resp = await resp.json()
                if not acc_resp.get("ok"):
                    print("Error creating account:", acc_resp)
                    return
                token = acc_resp["result"]["access_token"]
    except Exception as e:
        print("Exception creating account:", e)
        return

    # 2. Формируем Node-контент
    content_nodes = []
    
    # Читаем наш файлик
    with open("commands_list.txt", "r", encoding="utf-8") as f:
        lines = f.readlines()

    for line in lines:
        line = line.strip()
        if not line:
            content_nodes.append({"tag": "br"})
            continue

        # Заголовки разделов
        headers = ["🌸", "📜", "📊", "🎲", "🎭", "🔞"]
        is_header = any(line.startswith(h) for h in headers)

        if is_header:
            content_nodes.append({
                "tag": "p",
                "children": [{
                    "tag": "b",
                    "children": [line]
                }]
            })
        else:
            if line.startswith("•"):
                content_nodes.append({
                    "tag": "p",
                    "children": [f"    {line}"]
                })
            elif "Введите команду" in line or "Подсказка:" in line:
                content_nodes.append({
                    "tag": "p",
                    "children": [{
                        "tag": "i",
                        "children": [line]
                    }]
                })
            else:
                content_nodes.append({
                    "tag": "p",
                    "children": [line]
                })

    # 3. Публикуем страницу
    page_title = "🌸 Команды бота «Аля кокетничает со мной»"
    create_url = "https://api.telegra.ph/createPage"
    
    payload = {
        "access_token": token,
        "title": page_title,
        "author_name": "AlyaBot",
        "content": json.dumps(content_nodes),
        "return_content": "true"
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(create_url, data=payload) as resp:
                resp_json = await resp.json()
                if resp_json.get("ok"):
                    url = resp_json["result"]["url"]
                    print(f"SUCCESS_URL:{url}")
                else:
                    print("Error creating page:", resp_json)
    except Exception as e:
        print("Exception creating page:", e)

asyncio.run(create_page())
