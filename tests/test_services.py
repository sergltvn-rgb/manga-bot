"""Unit-тесты для модулей `services/*.py`, вынесенных в Фазе 3.

Назначение:
- документирует публичное API каждого модуля (что импортируется, что делает);
- ловит регрессии при дальнейших правках `services/`;
- даёт быстрый сигнал (<100ms), что базовая арифметика утилит не сломалась.

Тяжёлые тесты (HTTP-запросы к Telegraph, БД) сюда не идут — они в
`reader-regression.yml`.
"""

from __future__ import annotations

import math

import pytest


# --- services.webapp_cors ---


class TestWebappCors:
    def test_imports(self):
        from services import webapp_cors  # noqa: F401

    def test_extract_origin_http(self):
        from services.webapp_cors import _extract_origin

        assert _extract_origin("https://Example.COM/path") == "https://example.com"
        assert _extract_origin("HTTP://foo.bar") == "http://foo.bar"

    def test_extract_origin_rejects_non_http(self):
        from services.webapp_cors import _extract_origin

        assert _extract_origin("") == ""
        assert _extract_origin("ftp://example.com") == ""
        assert _extract_origin("javascript:alert(1)") == ""
        assert _extract_origin("not-a-url") == ""
        assert _extract_origin(None) == ""  # type: ignore[arg-type]

    def test_origin_allowed_telegram_subdomains(self):
        from services.webapp_cors import _origin_allowed

        # `telegram.org` в суффиксах → все субдомены разрешены.
        assert _origin_allowed("https://web.telegram.org")
        assert _origin_allowed("https://oauth.telegram.org")
        # Не суффикс — отказ.
        assert not _origin_allowed("https://evil.com")
        assert not _origin_allowed("https://telegram.org.evil.com")

    def test_merge_vary_header_dedupes(self):
        from services.webapp_cors import _merge_vary_header

        assert _merge_vary_header("", "Origin") == "Origin"
        assert _merge_vary_header("Accept-Encoding", "Origin") == "Accept-Encoding, Origin"
        # Повторный токен не дублируется.
        assert _merge_vary_header("Origin, Accept", "Origin") == "Origin, Accept"


# --- services.validators ---


class TestValidators:
    def test_imports(self):
        from services import validators  # noqa: F401

    def test_valid_series_id(self):
        from services.validators import _is_valid_series_id

        assert _is_valid_series_id("akashic_records")
        assert _is_valid_series_id("british_belle")
        assert _is_valid_series_id("manga_ru")
        assert _is_valid_series_id("ranobe_en")

    def test_invalid_series_id(self):
        from services.validators import _is_valid_series_id

        assert not _is_valid_series_id("")
        assert not _is_valid_series_id("x" * 100)  # слишком длинный
        assert not _is_valid_series_id("unknown_prefix")
        assert not _is_valid_series_id("manga_")  # пустая часть
        assert not _is_valid_series_id("manga_<script>")  # невалидный lang
        assert not _is_valid_series_id(None)  # type: ignore[arg-type]

    def test_chapter_token(self):
        from services.validators import _is_valid_chapter_token

        assert _is_valid_chapter_token("1")
        assert _is_valid_chapter_token("1.5")
        assert _is_valid_chapter_token("Глава 1")  # кириллица ок
        assert not _is_valid_chapter_token("")
        assert not _is_valid_chapter_token("<script>")  # HTML-опасный
        assert not _is_valid_chapter_token("bad\x00null")  # управляющий
        assert not _is_valid_chapter_token("x" * 64)  # слишком длинный

    def test_normalize_external_url(self):
        from services.validators import _normalize_external_url

        assert _normalize_external_url("https://example.com/foo") == "https://example.com/foo"
        # Credentials отсекаем.
        assert _normalize_external_url("https://user:pass@example.com/") is None
        # Non-http отсекаем.
        assert _normalize_external_url("javascript:alert(1)") is None
        assert _normalize_external_url("") is None
        # Управляющие символы отсекаем.
        assert _normalize_external_url("https://example.com\x00/") is None

    def test_clean_urls_extracts_unique(self):
        from services.validators import _clean_urls

        text = "See https://a.com and https://b.com and https://a.com again"
        assert _clean_urls(text) == ["https://a.com", "https://b.com"]

    def test_safe_json_dumps_truncates(self):
        from services.validators import _safe_json_dumps

        assert _safe_json_dumps({"a": 1}) == '{"a":1}'
        # Длинный payload обрезается.
        long = {"x": "y" * 10000}
        assert len(_safe_json_dumps(long, max_len=100)) <= 100
        # Незасериализуемое → str fallback.
        assert _safe_json_dumps(object()) != ""


# --- services.cache_utils ---


class TestCacheUtils:
    def test_imports(self):
        from services import cache_utils  # noqa: F401

    def test_normalize_etag_strips_weak(self):
        from services.cache_utils import _normalize_etag

        assert _normalize_etag('"abc"') == '"abc"'
        assert _normalize_etag('W/"abc"') == '"abc"'
        assert _normalize_etag("   ") == ""

    def test_if_none_match(self):
        from services.cache_utils import _if_none_match_matches

        assert _if_none_match_matches('"abc"', '"abc"')
        assert _if_none_match_matches('W/"abc"', '"abc"')
        assert _if_none_match_matches("*", '"anything"')
        assert _if_none_match_matches('"a", "b"', '"b"')
        assert not _if_none_match_matches("", '"abc"')
        assert not _if_none_match_matches('"other"', '"abc"')

    def test_build_chapter_cache_key(self):
        from services.cache_utils import _build_chapter_content_cache_key

        assert _build_chapter_content_cache_key("manga_ru", "1", "5") == "manga_ru::1::5"


# --- services.telemetry_utils ---


class TestTelemetryUtils:
    def test_imports(self):
        from services import telemetry_utils  # noqa: F401

    def test_clip_telemetry_text(self):
        from services.telemetry_utils import _clip_telemetry_text

        assert _clip_telemetry_text(None, 100) == ""
        assert _clip_telemetry_text("hello", 100) == "hello"
        assert _clip_telemetry_text("  hello  ", 100) == "hello"
        # Обрезание длины.
        assert _clip_telemetry_text("x" * 200, 50) == "x" * 50
        # Числа конвертятся в строку.
        assert _clip_telemetry_text(42, 100) == "42"

    def test_to_finite_float(self):
        from services.telemetry_utils import _to_finite_float

        assert _to_finite_float("3.14") == pytest.approx(3.14)
        assert _to_finite_float(42) == 42.0
        assert _to_finite_float("not-a-number") is None
        assert _to_finite_float(None) is None
        # NaN/Infinity отсекаются.
        assert _to_finite_float(float("nan")) is None
        assert _to_finite_float(float("inf")) is None
        assert _to_finite_float(math.inf) is None


# --- services.rate_limit ---


class TestRateLimit:
    def test_imports_and_rules_shape(self):
        from services.rate_limit import RATE_LIMIT_RULES, _enforce_rate_limit

        # Все правила имеют корректную форму.
        for scope, rule in RATE_LIMIT_RULES.items():
            assert isinstance(scope, str) and scope, f"bad scope: {scope!r}"
            assert "limit" in rule and "window" in rule
            assert isinstance(rule["limit"], int) and rule["limit"] > 0
            assert isinstance(rule["window"], int) and rule["window"] > 0

        # Enforce экспортирован.
        assert callable(_enforce_rate_limit)


# --- services.webapp_middleware ---


class TestWebappMiddleware:
    def test_imports(self):
        from services.webapp_middleware import (
            API_MAX_BODY_BYTES,
            _response_is_compressible,
            _webapp_cache_control_for_request,  # noqa: F401
            api_security_middleware,
            apply_webapp_response_headers,
        )

        # API_MAX_BODY_BYTES — положительное число, читается из env.
        assert isinstance(API_MAX_BODY_BYTES, int)
        assert API_MAX_BODY_BYTES > 0
        assert callable(api_security_middleware)
        assert callable(apply_webapp_response_headers)
        assert callable(_response_is_compressible)


# --- services.telegraph ---


class TestTelegraph:
    def test_imports(self):
        from services.telegraph import (
            _TelegraphHTMLParser,
            _html_to_nodes,
            get_telegraph_token,
            upload_to_telegraph,
        )

        assert callable(get_telegraph_token)
        assert callable(upload_to_telegraph)
        assert callable(_html_to_nodes)
        assert _TelegraphHTMLParser is not None

    def test_html_to_nodes_wraps_text_in_p(self):
        from services.telegraph import _html_to_nodes

        # Голый текст без тегов → оборачивается в <p>.
        nodes = _html_to_nodes("Hello world")
        assert len(nodes) == 1
        assert nodes[0]["tag"] == "p"
        assert nodes[0]["children"] == ["Hello world"]

    def test_html_to_nodes_drops_script(self):
        from services.telegraph import _html_to_nodes

        nodes = _html_to_nodes("<p>Safe</p><script>alert(1)</script>")
        # <script> и его содержимое выкинуты.
        dumped = str(nodes)
        assert "alert" not in dumped
        assert "Safe" in dumped
