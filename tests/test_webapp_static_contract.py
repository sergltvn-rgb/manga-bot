from __future__ import annotations

from pathlib import Path


WEBAPP = Path(__file__).resolve().parents[1] / "webapp"


def read(name: str) -> str:
    return (WEBAPP / name).read_text(encoding="utf-8")


def test_shared_webapp_assets_exist_and_are_linked_from_operator_pages():
    assert (WEBAPP / "shared.css").exists()
    assert (WEBAPP / "shared.js").exists()

    for page in ["reader.html", "arts.html", "giveaway.html", "admin.html"]:
        html = read(page)
        assert 'href="shared.css' in html
        assert 'src="shared.js' in html


def test_webapp_pages_have_recovery_actions_instead_of_raw_errors():
    for page in ["arts.html", "giveaway.html", "admin.html"]:
        html = read(page)
        assert "Повторить" in html or "Обновить" in html
        assert "Сообщить админу" in html

    combined = "\n".join(read(page) for page in ["arts.html", "giveaway.html", "admin.html"])
    assert "bad_request" not in combined
    assert "Script error." not in combined


def test_service_worker_revision_is_not_hardcoded_default():
    sw = read("sw.js")
    reader = read("reader.js")

    assert "const SW_REV" in sw
    assert "webapp-build.json" in reader
    assert "window.__WEBAPP_BUILD" in reader
    assert "|| '16'" not in reader


def test_recovery_mounts_stay_hidden_until_rendered():
    for page in ["arts.html", "giveaway.html", "admin.html"]:
        assert 'class="shared-recovery" hidden' not in read(page)

    assert ".shared-recovery[hidden]" in read("shared.css")


def test_report_to_admin_has_real_client_action():
    shared_js = read("shared.js")

    assert "handleReportToAdmin" in shared_js
    assert "client_report_to_admin" in shared_js
    assert "openTelegramLink" in shared_js
    assert "navigator.clipboard" in shared_js


def test_reader_inline_admin_handlers_are_exported_for_onclick_buttons():
    reader_js = read("reader.js")

    assert "window.openChapterEditModal = openChapterEditModal" in reader_js
