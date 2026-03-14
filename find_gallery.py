with open("bot.py", "r", encoding="utf-8") as f:
    lines = f.readlines()

import re

# Найти хэндлеры, связанные с галереей
# Ищем функции с "def " и смотрим, есть ли в них нужные слова
current_func = []
func_name = ""
print("Searching in bot.py:")

for i, line in enumerate(lines):
    if line.strip().startswith("def ") or line.strip().startswith("async def "):
        if current_func and ("галер" in "".join(current_func).lower() or "сетк" in "".join(current_func).lower() or "фото" in "".join(current_func).lower() or "grid" in "".join(current_func).lower()):
            print(f"\n--- {func_name} ---")
            for fl in current_func:
                if any(x in fl.lower() for x in ["галер", "сетк", "grid", "удалить", "чист", "callback"]):
                    print(fl.strip())
        current_func = [line]
        func_name = line.strip()
    else:
        current_func.append(line)

# Последняя функция
if current_func and ("галер" in "".join(current_func).lower() or "сетк" in "".join(current_func).lower()):
    print(f"\n--- {func_name} ---")
    for fl in current_func:
        print(fl.strip())
