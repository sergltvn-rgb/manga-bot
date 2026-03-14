with open("bot.py", "r", encoding="utf-8") as f:
    for i, line in enumerate(f):
        if "admin_art_grid:" in line or "process_admin_art_grid" in line:
            print(f"Line {i+1}: {line.strip()}")
