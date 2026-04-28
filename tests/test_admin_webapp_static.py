from __future__ import annotations

from pathlib import Path


ADMIN_HTML = Path(__file__).resolve().parents[1] / "webapp" / "admin.html"
GIVEAWAY_HTML = Path(__file__).resolve().parents[1] / "webapp" / "giveaway.html"


def test_admin_ui_uses_russian_primary_labels():
    html = ADMIN_HTML.read_text(encoding="utf-8")

    assert "Bulk preview" not in html
    assert "Sync WebApp" not in html
    assert "giveaway mini app" not in html
    assert "Health, sync" not in html
    assert "Alya Admin" not in html
    assert "Панель Alya" in html
    assert "Массовая проверка глав" in html
    assert "Обновить данные читалки" in html


def test_admin_content_has_operator_helpers():
    html = ADMIN_HTML.read_text(encoding="utf-8")

    assert "data-series-select" in html
    assert "contentQuality" in html
    assert "data-open-links" in html
    assert "data-save-bulk" in html
    assert "Сохранить новые главы" in html


def test_admin_audit_and_giveaway_details_are_human_readable():
    html = ADMIN_HTML.read_text(encoding="utf-8")

    assert "Обновление данных читалки" in html
    assert "Массовая загрузка глав" in html
    assert "data-audit-details" in html
    assert "data-giveaway-details" in html
    assert "Запланированные" in html


def test_giveaway_webapp_contains_server_captcha_flow():
    html = GIVEAWAY_HTML.read_text(encoding="utf-8")

    assert 'id="captcha"' in html
    assert "renderCaptcha" in html
    assert "/api/giveaway/join" in html
    assert "captcha_answer" in html
