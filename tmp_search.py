with open("bot.py", "r", encoding="utf-8") as f:
    lines = f.readlines()

print(f"Total lines: {len(lines)}")
for i, line in enumerate(lines):
    if "галер" in line.lower() or "сетк" in line.lower() or "арт" in line.lower() or "grid" in line.lower() or "media" in line.lower():
        print(f"[{i+1}] {line.strip()}")
