---
description: Pre-deploy gate + deploy to mangabot systemd service
---

Последовательность, которую нужно проходить **перед каждым `git push origin main`** и последующим рестартом сервиса.

## 0. Разовая настройка окружения (один раз)

```powershell
pip install -r requirements-dev.txt
pre-commit install
```

После этого линтер и shadowing-чек запускаются автоматически на каждый `git commit`.

## 1. Локальный lint / smoke-gate

```powershell
ruff check .
// turbo
python scripts/check_no_shadowing.py
// turbo
pytest tests/ -q
```

Все три должны вернуть exit code 0. Если что-то падает — **не пушим**, фиксим локально.

> Если `pytest` ещё не установлен, как временный fallback: `python scratch/_manual_smoke.py` — одна и та же логика без pytest.

## 2. Git commit + push

```powershell
git status
git add -A
git commit -m "<conventional commit message>"
git push origin main
```

## 3. Деплой на сервер (SSH)

```bash
cd ~/git_bot
git fetch && git reset --hard origin/main && sudo systemctl restart mangabot
```

## 4. Канареечное наблюдение (5 минут)

В отдельном терминале:

```bash
sudo journalctl -u mangabot -f --no-pager
```

- Проверь, что бот стартовал (`Start polling`, `Бот запущен`).
- В Telegram отправь `/admin` (для админов) или `/start` — проверь, что приходит ответ.
- Если в логах появились `WARNING`/`ERROR` сразу после рестарта — стоп, разбираемся.

## 5. Откат (если что-то пошло не так)

```bash
cd ~/git_bot
git log -n 3 --oneline
git reset --hard <previous_good_sha>
sudo systemctl restart mangabot
```
