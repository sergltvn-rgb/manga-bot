#!/usr/bin/env python3
"""Проверяет, что ни в одном .py-файле нет двух top-level `def`/`async def`
с одинаковым именем. Такой shadowing однажды уже положил всю админ-панель
(`_is_bot_admin` был определён дважды → вторая функция затирала первую
при импорте модуля).

Запуск:

    python scripts/check_no_shadowing.py [file1.py file2.py ...]

Без аргументов — сканирует весь репозиторий (кроме .venv / scratch /
__pycache__ / webapp/node_modules).

Выход:
    0 — всё чисто
    1 — найдены дубли (выводит путь и имена)
"""

from __future__ import annotations

import ast
import os
import sys
from collections import Counter
from pathlib import Path

EXCLUDED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "botenv",  # на prod-сервере venv называется именно так
    "env",
    "__pycache__",
    "node_modules",
    "scratch",  # экспериментальные скрипты не чекаем
    "webapp",
    "deploy",
    "dist",
    "build",
    "site-packages",  # на всякий случай, если venv лежит глубже
}


def _is_virtualenv(path: Path) -> bool:
    """Детектит virtualenv по `pyvenv.cfg` — надёжнее чем whitelist имён."""
    return (path / "pyvenv.cfg").is_file()


def iter_py_files(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDED_DIRS and not d.startswith(".") and not _is_virtualenv(Path(dirpath) / d)]
        for f in filenames:
            if f.endswith(".py"):
                yield Path(dirpath) / f


def find_shadowing(py_file: Path) -> list[tuple[str, list[int]]]:
    """Возвращает список (имя_функции, [номера_строк]) для top-level функций,
    которые определены более одного раза в одном модуле.
    """
    try:
        # utf-8-sig автоматически стрипает BOM (U+FEFF), если он есть.
        src = py_file.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as e:
        print(f"WARN: cannot read {py_file}: {e}", file=sys.stderr)
        return []
    try:
        tree = ast.parse(src, filename=str(py_file))
    except SyntaxError as e:
        print(f"WARN: cannot parse {py_file}: {e}", file=sys.stderr)
        return []
    positions: dict[str, list[int]] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            positions.setdefault(node.name, []).append(node.lineno)
    return [(name, lines) for name, lines in positions.items() if len(lines) > 1]


def main(argv: list[str]) -> int:
    if argv:
        files = [Path(a) for a in argv if a.endswith(".py") and Path(a).is_file()]
    else:
        root = Path(__file__).resolve().parent.parent
        files = list(iter_py_files(root))

    total_bad = 0
    for f in files:
        dupes = find_shadowing(f)
        if dupes:
            total_bad += 1
            print(f"[SHADOWING] {f}")
            for name, lines in dupes:
                print(f"  `{name}` defined {len(lines)}x at lines: {', '.join(map(str, lines))}")

    if total_bad:
        print(f"\nFAIL: shadowing found in {total_bad} file(s).", file=sys.stderr)
        return 1
    print(f"OK: no top-level def shadowing in {len(files)} file(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
