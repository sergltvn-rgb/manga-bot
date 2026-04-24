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

    def test_cors_headers_allow_credentials_for_allowed_origin(self):
        from aiohttp.test_utils import make_mocked_request
        from multidict import CIMultiDict

        from services.webapp_cors import _build_cors_headers

        req = make_mocked_request("OPTIONS", "/api/comments", headers=CIMultiDict({"Origin": "https://web.telegram.org"}))

        headers = _build_cors_headers(req)

        assert headers["Access-Control-Allow-Origin"] == "https://web.telegram.org"
        assert headers["Access-Control-Allow-Credentials"] == "true"


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

    def test_extract_chapter_urls_prefers_urls_list(self):
        from services.validators import _extract_chapter_urls

        data = {
            "urls": ["https://a.com", "https://b.com"],
            "url": "https://legacy.com",
        }
        result = _extract_chapter_urls(data)
        # Оба URL из urls + legacy url добавлен как fallback.
        assert result == ["https://a.com", "https://b.com", "https://legacy.com"]

    def test_extract_chapter_urls_dedupes(self):
        from services.validators import _extract_chapter_urls

        data = {
            "urls": ["https://a.com", "https://a.com", "https://b.com"],
            "url": "https://a.com",  # Дубль из legacy, не должен добавиться.
        }
        assert _extract_chapter_urls(data) == ["https://a.com", "https://b.com"]

    def test_extract_chapter_urls_filters_invalid(self):
        from services.validators import _extract_chapter_urls

        data = {
            "urls": ["https://ok.com", "javascript:alert(1)", "not-a-url", ""],
            "url": None,
        }
        assert _extract_chapter_urls(data) == ["https://ok.com"]

    def test_extract_chapter_urls_legacy_only(self):
        from services.validators import _extract_chapter_urls

        # Старый формат — только одиночное `url`.
        data = {"url": "https://legacy.com"}
        assert _extract_chapter_urls(data) == ["https://legacy.com"]

    def test_extract_chapter_urls_empty(self):
        from services.validators import _extract_chapter_urls

        assert _extract_chapter_urls({}) == []
        assert _extract_chapter_urls({"urls": [], "url": None}) == []


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

    def test_compute_reader_etag_deterministic(self):
        from services.cache_utils import _compute_reader_etag

        p1 = {"series": [{"id": "a", "x": 1}, {"id": "b", "y": 2}]}
        p2 = {"series": [{"id": "a", "x": 1}, {"id": "b", "y": 2}]}
        # Тот же payload → тот же ETag.
        assert _compute_reader_etag(p1) == _compute_reader_etag(p2)
        # Формат: кавычки по краям, 64-символьный sha256.
        etag = _compute_reader_etag(p1)
        assert etag.startswith('"') and etag.endswith('"')
        assert len(etag) == 66  # 64 hex + 2 quotes

    def test_compute_reader_etag_differs_on_content_change(self):
        from services.cache_utils import _compute_reader_etag

        p1 = {"series": [{"id": "a"}]}
        p2 = {"series": [{"id": "b"}]}
        assert _compute_reader_etag(p1) != _compute_reader_etag(p2)

    def test_compute_reader_etag_key_order_agnostic(self):
        from services.cache_utils import _compute_reader_etag

        # sort_keys=True → одинаковый ETag для dict'ов с разным порядком.
        p1 = {"a": 1, "b": 2}
        p2 = {"b": 2, "a": 1}
        assert _compute_reader_etag(p1) == _compute_reader_etag(p2)


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

    def test_sanitize_chapter_open_valid(self):
        from services.telemetry_utils import _sanitize_client_chapter_open_payload

        result = _sanitize_client_chapter_open_payload(
            {
                "duration_ms": 1234.5678,
                "series_id": "manga_ru",
                "volume": "1",
                "chapter": "5",
                "chapter_idx": 4,
                "source": "webapp",
                "used_prefetch": True,
            }
        )
        assert result == {
            "duration_ms": 1234.57,  # округлено до 2 знаков
            "series_id": "manga_ru",
            "volume": "1",
            "chapter": "5",
            "chapter_idx": 4,
            "source": "webapp",
            "used_prefetch": True,
        }

    def test_sanitize_chapter_open_rejects_invalid_duration(self):
        from services.telemetry_utils import (
            MAX_TELEMETRY_METRIC_MS,
            _sanitize_client_chapter_open_payload,
        )

        # Отрицательная длительность — отклонена.
        assert _sanitize_client_chapter_open_payload({"duration_ms": -1}) is None
        # Бесконечность — отклонена.
        assert _sanitize_client_chapter_open_payload({"duration_ms": float("inf")}) is None
        # Нечисловая — отклонена.
        assert _sanitize_client_chapter_open_payload({"duration_ms": "abc"}) is None
        # Слишком большая — отклонена.
        assert _sanitize_client_chapter_open_payload({"duration_ms": MAX_TELEMETRY_METRIC_MS + 1}) is None

    def test_sanitize_chapter_open_chapter_idx_bounds(self):
        from services.telemetry_utils import _sanitize_client_chapter_open_payload

        # 0 ок.
        r = _sanitize_client_chapter_open_payload({"duration_ms": 100, "chapter_idx": 0})
        assert r["chapter_idx"] == 0
        # 10000 ок.
        r = _sanitize_client_chapter_open_payload({"duration_ms": 100, "chapter_idx": 10000})
        assert r["chapter_idx"] == 10000
        # Отрицательный — отбрасывается.
        r = _sanitize_client_chapter_open_payload({"duration_ms": 100, "chapter_idx": -1})
        assert r["chapter_idx"] is None
        # Слишком большой — отбрасывается.
        r = _sanitize_client_chapter_open_payload({"duration_ms": 100, "chapter_idx": 10001})
        assert r["chapter_idx"] is None
        # Нечисловой — отбрасывается.
        r = _sanitize_client_chapter_open_payload({"duration_ms": 100, "chapter_idx": "bad"})
        assert r["chapter_idx"] is None

    def test_sanitize_chapter_open_clips_long_strings(self):
        from services.telemetry_utils import _sanitize_client_chapter_open_payload

        r = _sanitize_client_chapter_open_payload(
            {
                "duration_ms": 100,
                "series_id": "x" * 200,
                "volume": "y" * 200,
                "chapter": "z" * 200,
                "source": "q" * 200,
            }
        )
        assert len(r["series_id"]) == 64
        assert len(r["volume"]) == 32
        assert len(r["chapter"]) == 32
        assert len(r["source"]) == 64


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


# --- services.reader_cache ---


class TestReaderCache:
    def test_imports(self):
        from services.reader_cache import (
            CHAPTER_CONTENT_CACHE_MAX_ENTRIES,
            CHAPTER_CONTENT_CACHE_TTL_SECONDS,
            READER_CACHE_TTL_SECONDS,
            _chapter_content_cache,
            _chapter_content_cache_lock,
            _reader_cache_lock,
            _reader_data_cache,
            invalidate_chapter_content_cache,
            invalidate_reader_cache,
        )

        assert isinstance(READER_CACHE_TTL_SECONDS, int) and READER_CACHE_TTL_SECONDS > 0
        assert isinstance(CHAPTER_CONTENT_CACHE_TTL_SECONDS, int) and CHAPTER_CONTENT_CACHE_TTL_SECONDS > 0
        assert isinstance(CHAPTER_CONTENT_CACHE_MAX_ENTRIES, int) and CHAPTER_CONTENT_CACHE_MAX_ENTRIES > 0
        # State — правильного типа.
        assert isinstance(_reader_data_cache, dict)
        assert set(_reader_data_cache.keys()) == {"payload", "etag", "built_at"}
        assert isinstance(_chapter_content_cache, dict)
        # Locks созданы.
        assert _reader_cache_lock is not None
        assert _chapter_content_cache_lock is not None
        assert callable(invalidate_reader_cache)
        assert callable(invalidate_chapter_content_cache)

    def test_invalidate_chapter_content_clears_dict(self):
        from services.reader_cache import (
            _chapter_content_cache,
            invalidate_chapter_content_cache,
        )

        _chapter_content_cache["test_key"] = {"payload": "x", "status": 200, "built_at": 1.0}
        assert "test_key" in _chapter_content_cache

        invalidate_chapter_content_cache("unit_test")
        assert _chapter_content_cache == {}

    def test_chapter_content_cache_is_bounded_lru(self, monkeypatch):
        import time

        import services.reader_cache as reader_cache
        from services.reader_cache import _chapter_content_cache, _store_chapter_content_cache_entry

        monkeypatch.setattr(reader_cache, "CHAPTER_CONTENT_CACHE_MAX_ENTRIES", 2)
        _chapter_content_cache.clear()

        _store_chapter_content_cache_entry("a", {"html": "a"}, status=200, built_at=time.time())
        _store_chapter_content_cache_entry("b", {"html": "b"}, status=200, built_at=time.time())
        _store_chapter_content_cache_entry("a", {"html": "a2"}, status=200, built_at=time.time())
        _store_chapter_content_cache_entry("c", {"html": "c"}, status=200, built_at=time.time())

        assert list(_chapter_content_cache.keys()) == ["a", "c"]

    def test_invalidate_reader_cache_resets_both(self):
        from services.reader_cache import (
            _chapter_content_cache,
            _reader_data_cache,
            invalidate_reader_cache,
        )

        # Наполняем state.
        _reader_data_cache["payload"] = {"series": []}
        _reader_data_cache["etag"] = '"abc"'
        _reader_data_cache["built_at"] = 1234.5
        _chapter_content_cache["k"] = {"payload": "x", "status": 200, "built_at": 1.0}

        invalidate_reader_cache("unit_test")

        # Reader-payload очищен, chapter-cache тоже.
        assert _reader_data_cache["payload"] is None
        assert _reader_data_cache["etag"] == ""
        assert _reader_data_cache["built_at"] == 0.0
        assert _chapter_content_cache == {}


# --- services.html_utils ---


class TestHtmlUtils:
    def test_imports(self):
        from services import html_utils  # noqa: F401

    def test_visible_content_detects_text(self):
        from services.html_utils import _html_fragment_has_visible_content

        assert _html_fragment_has_visible_content("<p>Hello</p>")
        assert _html_fragment_has_visible_content("<div><img src='x.jpg'/></div>")
        assert _html_fragment_has_visible_content("<p>&nbsp; Привет &nbsp;</p>")
        # Пустые / только-теги фрагменты — не visible.
        assert not _html_fragment_has_visible_content("")
        assert not _html_fragment_has_visible_content("<p></p>")
        assert not _html_fragment_has_visible_content("<div>   </div>")

    def test_analyze_counts(self):
        from services.html_utils import _analyze_html_fragment

        stats = _analyze_html_fragment("<p>Hello <a href='x'>link</a> world</p>" "<img src='y.jpg'/><blockquote>quote</blockquote>")
        assert stats["anchor_count"] == 1
        assert stats["image_count"] == 1
        assert stats["block_count"] == 2  # p + blockquote
        assert stats["text_len"] > 0

    def test_analyze_empty(self):
        from services.html_utils import _analyze_html_fragment

        stats = _analyze_html_fragment("")
        assert stats == {"text_len": 0, "anchor_count": 0, "image_count": 0, "block_count": 0}

    def test_is_low_value(self):
        from services.html_utils import _is_low_value_html_fragment

        # Картинка → не low-value.
        assert not _is_low_value_html_fragment("<img src='big.jpg'/>")
        # Длинный текст → не low-value.
        assert not _is_low_value_html_fragment("<p>" + "x " * 200 + "</p>")
        # Только короткая ссылка → low-value.
        assert _is_low_value_html_fragment('<p><a href="x">См. оригинал</a></p>')
        # Пустой / очень короткий → low-value.
        assert _is_low_value_html_fragment("<p>Ok</p>")

    def test_score_prefers_images_and_text(self):
        from services.html_utils import _score_html_fragment

        # Фрагмент с картинками и текстом > фрагмент со ссылками и коротким текстом.
        rich = "<p>" + "x " * 100 + "</p><img src='y.jpg'/><p>more</p>"
        poor = '<p><a href="x">See</a></p>'
        assert _score_html_fragment(rich) > _score_html_fragment(poor)
        # Картинка перевешивает даже длинный текст без картинок.
        with_image = "<img src='x.jpg'/><p>hi</p>"
        text_only = "<p>" + "x " * 50 + "</p>"
        assert _score_html_fragment(with_image) > _score_html_fragment(text_only)


# --- services.html_rendering ---


class TestHtmlRendering:
    def test_imports(self):
        from services.html_rendering import (
            _SafeHtmlFragmentParser,
            _extract_img_attrs_from_tag,
            _extract_teletype_article_fragment,
            _normalize_teletype_article_fragment,
            _render_telegraph_nodes_server,
            _sanitize_html_fragment,
        )

        assert callable(_render_telegraph_nodes_server)
        assert callable(_sanitize_html_fragment)
        assert callable(_extract_teletype_article_fragment)
        assert callable(_extract_img_attrs_from_tag)
        assert callable(_normalize_teletype_article_fragment)
        assert _SafeHtmlFragmentParser is not None

    def test_render_telegraph_nodes_basic(self):
        from services.html_rendering import _render_telegraph_nodes_server

        # Пустые входы.
        assert _render_telegraph_nodes_server([]) == ""
        assert _render_telegraph_nodes_server(None) == ""  # type: ignore[arg-type]
        # Простой параграф.
        nodes = [{"tag": "p", "children": ["Hello"]}]
        assert _render_telegraph_nodes_server(nodes) == "<p>Hello</p>"

    def test_render_telegraph_nodes_link_href_whitelist(self):
        from services.html_rendering import _render_telegraph_nodes_server

        # Нормальный http href — остаётся.
        nodes = [{"tag": "a", "attrs": {"href": "https://example.com"}, "children": ["Link"]}]
        result = _render_telegraph_nodes_server(nodes)
        assert 'href="https://example.com"' in result
        assert ">Link</a>" in result
        # javascript:// — href отбрасывается.
        nodes_bad = [{"tag": "a", "attrs": {"href": "javascript:alert(1)"}, "children": ["X"]}]
        result_bad = _render_telegraph_nodes_server(nodes_bad)
        assert "javascript" not in result_bad

    def test_render_telegraph_nodes_img_relative_becomes_absolute(self):
        from services.html_rendering import _render_telegraph_nodes_server

        # Относительный /file/xxx.jpg → https://telegra.ph/file/xxx.jpg
        nodes = [{"tag": "img", "attrs": {"src": "/file/abc.jpg"}}]
        result = _render_telegraph_nodes_server(nodes)
        assert 'src="https://telegra.ph/file/abc.jpg"' in result
        assert 'loading="lazy"' in result

    def test_render_telegraph_nodes_img_without_src_dropped(self):
        from services.html_rendering import _render_telegraph_nodes_server

        nodes = [{"tag": "img", "attrs": {}}]
        assert _render_telegraph_nodes_server(nodes) == ""

    def test_render_telegraph_nodes_escapes_text(self):
        from services.html_rendering import _render_telegraph_nodes_server

        # Текст с < и > — должен быть escape'нут.
        nodes = [{"tag": "p", "children": ["<script>alert(1)</script>"]}]
        result = _render_telegraph_nodes_server(nodes)
        assert "&lt;script&gt;" in result
        assert "<script>" not in result.replace("&lt;script&gt;", "")

    def test_sanitize_html_fragment_drops_scripts(self):
        from services.html_rendering import _sanitize_html_fragment

        fragment = "<p>Safe</p><script>alert(1)</script><style>body{}</style>"
        result = _sanitize_html_fragment(fragment)
        assert "Safe" in result
        assert "alert" not in result
        assert "<style>" not in result

    def test_sanitize_html_fragment_whitelist_attrs(self):
        from services.html_rendering import _sanitize_html_fragment

        # onclick выкидывается, href остаётся (если нормализуется).
        fragment = '<a href="https://ok.com" onclick="bad()">click</a>'
        result = _sanitize_html_fragment(fragment)
        assert "onclick" not in result
        assert 'href="https://ok.com"' in result

    def test_sanitize_html_fragment_collapses_br(self):
        from services.html_rendering import _sanitize_html_fragment

        # 3+ <br> подряд → <br><br>
        fragment = "a<br><br><br><br><br>b"
        result = _sanitize_html_fragment(fragment)
        # Должно остаться только два <br>.
        assert result.count("<br>") == 2

    def test_extract_teletype_article_prefers_itemprop(self):
        from services.html_rendering import _extract_teletype_article_fragment

        html_src = """
        <html>
          <article><p>wrong</p></article>
          <article itemprop="articleBody"><p>right</p></article>
        </html>
        """
        fragment = _extract_teletype_article_fragment(html_src)
        assert "right" in fragment
        assert "wrong" not in fragment

    def test_extract_teletype_article_fallback(self):
        from services.html_rendering import _extract_teletype_article_fragment

        html_src = "<html><article><p>body</p></article></html>"
        fragment = _extract_teletype_article_fragment(html_src)
        assert "<p>body</p>" in fragment

    def test_extract_teletype_article_empty(self):
        from services.html_rendering import _extract_teletype_article_fragment

        assert _extract_teletype_article_fragment("") == ""
        assert _extract_teletype_article_fragment("<html>no article</html>") == ""

    def test_extract_img_attrs_from_tag(self):
        from services.html_rendering import _extract_img_attrs_from_tag

        src, alt = _extract_img_attrs_from_tag(
            '<img src="https://cdn.example.com/x.jpg" alt="cover">',
            source_url="https://example.com",
        )
        assert src == "https://cdn.example.com/x.jpg"
        assert alt == "cover"

    def test_extract_img_attrs_relative(self):
        from services.html_rendering import _extract_img_attrs_from_tag

        # Относительный src резолвится относительно source_url.
        src, _ = _extract_img_attrs_from_tag(
            '<img src="/path/x.jpg">',
            source_url="https://example.com/article",
        )
        assert src == "https://example.com/path/x.jpg"

    def test_extract_img_attrs_no_src_returns_empty(self):
        from services.html_rendering import _extract_img_attrs_from_tag

        assert _extract_img_attrs_from_tag("<img alt='x'>") == ("", "")
        assert _extract_img_attrs_from_tag("") == ("", "")

    def test_normalize_teletype_unwraps_noscript_img(self):
        from services.html_rendering import _normalize_teletype_article_fragment

        # <noscript><img></noscript> → <img>
        fragment = '<p>text</p><noscript><img src="https://cdn.x/y.jpg"></noscript>'
        result = _normalize_teletype_article_fragment(fragment, source_url="https://x.com")
        assert 'src="https://cdn.x/y.jpg"' in result
        assert "<noscript>" not in result
        assert 'loading="lazy"' in result


# --- services.reader_api ---


class TestReaderApi:
    def test_imports(self):
        import inspect

        from services.reader_api import handle_chapter_content, handle_reader_data

        assert inspect.iscoroutinefunction(handle_chapter_content)
        assert inspect.iscoroutinefunction(handle_reader_data)

    def test_chapter_content_rejects_invalid_series_id(self):
        import asyncio
        import json

        from aiohttp.test_utils import make_mocked_request

        from services.reader_api import handle_chapter_content

        # Плохой series_id → 400.
        req = make_mocked_request("GET", "/api/chapter-content?series_id=evil&volume=1&chapter=1")
        resp = asyncio.run(handle_chapter_content(req))
        assert resp.status == 400
        body = json.loads(resp.body.decode())
        assert body["error"] == "invalid series_id"

    def test_chapter_content_rejects_invalid_volume(self):
        import asyncio
        import json

        from aiohttp.test_utils import make_mocked_request

        from services.reader_api import handle_chapter_content

        # Валидный series_id, но volume с запрещёнными символами.
        req = make_mocked_request(
            "GET",
            "/api/chapter-content?series_id=manga_ru&volume=bad%20vol&chapter=1",
        )
        resp = asyncio.run(handle_chapter_content(req))
        assert resp.status == 400
        body = json.loads(resp.body.decode())
        assert body["error"] == "invalid volume"

    def test_chapter_content_rejects_invalid_chapter(self):
        import asyncio
        import json

        from aiohttp.test_utils import make_mocked_request

        from services.reader_api import handle_chapter_content

        # Валидные series_id и volume, но chapter с HTML-инъекцией.
        req = make_mocked_request(
            "GET",
            "/api/chapter-content?series_id=manga_ru&volume=1&chapter=%3Cscript%3E",
        )
        resp = asyncio.run(handle_chapter_content(req))
        assert resp.status == 400
        body = json.loads(resp.body.decode())
        assert body["error"] == "invalid chapter"

    def test_chapter_content_supports_etag_and_304(self, monkeypatch):
        import asyncio
        import json

        from aiohttp.test_utils import make_mocked_request
        from multidict import CIMultiDict

        import services.reader_api as reader_api
        from services.reader_api import handle_chapter_content

        payload = {
            "ok": True,
            "source_type": "inline",
            "html": "<p>cached chapter</p>",
            "series_id": "manga_ru",
            "volume": "1",
            "chapter": "1",
        }

        async def fake_get_cached_chapter_content(*_args, **_kwargs):
            return payload, True, 200

        monkeypatch.setattr(reader_api, "get_cached_chapter_content", fake_get_cached_chapter_content)

        req = make_mocked_request("GET", "/api/chapter-content?series_id=manga_ru&volume=1&chapter=1")
        resp = asyncio.run(handle_chapter_content(req))
        assert resp.status == 200
        assert resp.headers.get("ETag")
        assert resp.headers.get("Vary") == "If-None-Match"
        body = json.loads(resp.body.decode())
        assert body["cache_status"] == "hit"

        req_304 = make_mocked_request(
            "GET",
            "/api/chapter-content?series_id=manga_ru&volume=1&chapter=1",
            headers=CIMultiDict({"If-None-Match": resp.headers["ETag"]}),
        )
        resp_304 = asyncio.run(handle_chapter_content(req_304))
        assert resp_304.status == 304
        assert resp_304.body in (None, b"")


# --- services.auth ---


class TestAuth:
    def test_get_auth_user_no_header_returns_none(self):
        from aiohttp.test_utils import make_mocked_request

        from services.auth import get_auth_user

        req = make_mocked_request("GET", "/api/reader-data")
        assert get_auth_user(req) is None

    def test_get_auth_user_empty_tma_returns_none(self):
        from aiohttp.test_utils import make_mocked_request
        from multidict import CIMultiDict

        from services.auth import get_auth_user

        # Authorization: tma (пустой initData) → None.
        req = make_mocked_request("GET", "/api/reader-data", headers=CIMultiDict({"Authorization": "tma "}))
        assert get_auth_user(req) is None

    def test_get_auth_user_bad_signature_returns_none(self):
        from aiohttp.test_utils import make_mocked_request
        from multidict import CIMultiDict

        from services.auth import get_auth_user

        # Подпись заведомо невалидная → validate_telegram_data() вернёт None.
        req = make_mocked_request(
            "GET",
            "/api/reader-data",
            headers=CIMultiDict({"Authorization": "tma user=%7B%22id%22%3A1%7D&hash=deadbeef"}),
        )
        assert get_auth_user(req) is None


# --- services.admin_audit ---


class TestAdminAudit:
    def test_api_error_response_returns_500(self):
        import json

        from services.admin_audit import _api_error_response

        resp = _api_error_response(RuntimeError("boom"), context="/api/test")
        assert resp.status == 500
        body = json.loads(resp.body.decode())
        assert body["error"] == "Internal error"
        assert body["code"] == 500
        # Stack не должен утекать в тело ответа.
        assert "boom" not in resp.body.decode()
        assert "RuntimeError" not in resp.body.decode()

    def test_api_error_response_custom_status(self):
        import json

        from services.admin_audit import _api_error_response

        resp = _api_error_response(ValueError("bad"), context="/api/test", status=400)
        assert resp.status == 400
        body = json.loads(resp.body.decode())
        assert body["code"] == 400

    def test_max_api_error_text_constant(self):
        from services.admin_audit import MAX_API_ERROR_TEXT

        assert MAX_API_ERROR_TEXT == 250


# --- services.telemetry ---


class TestTelemetry:
    def test_serialize_payload_small(self):
        from services.telemetry import _serialize_telemetry_payload

        result = _serialize_telemetry_payload({"a": 1, "b": "hello"})
        assert '"a": 1' in result or '"a":1' in result
        assert "hello" in result

    def test_serialize_payload_truncates_huge(self):
        from services.telemetry import MAX_TELEMETRY_PAYLOAD_JSON_LENGTH, _serialize_telemetry_payload

        # Огромный payload — должен быть обрезан до лимита.
        huge = {"data": "x" * (MAX_TELEMETRY_PAYLOAD_JSON_LENGTH + 10000)}
        result = _serialize_telemetry_payload(huge)
        assert len(result) == MAX_TELEMETRY_PAYLOAD_JSON_LENGTH

    def test_sample_rate_in_range(self):
        from services.telemetry import SERVER_READER_TELEMETRY_SAMPLE_RATE

        assert 0.0 <= SERVER_READER_TELEMETRY_SAMPLE_RATE <= 1.0

    def test_webapp_telemetry_events_whitelist(self):
        from services.telemetry import WEBAPP_TELEMETRY_EVENTS

        assert "client_runtime_error" in WEBAPP_TELEMETRY_EVENTS
        assert "chapter_click" in WEBAPP_TELEMETRY_EVENTS
        # Whitelist; произвольные имена не должны пройти.
        assert "random_bad_event" not in WEBAPP_TELEMETRY_EVENTS


# --- services.likes_api + services.telemetry_api ---


class TestLikesApi:
    def test_imports(self):
        import inspect

        from services.likes_api import handle_likes_get, handle_likes_post

        assert inspect.iscoroutinefunction(handle_likes_get)
        assert inspect.iscoroutinefunction(handle_likes_post)


class TestTelemetryApi:
    def test_imports(self):
        import inspect

        from services.telemetry_api import handle_telemetry_post

        assert inspect.iscoroutinefunction(handle_telemetry_post)


# --- services.admin_chapter_api ---


class TestAdminChapterApi:
    def test_imports(self):
        import inspect

        from services.admin_chapter_api import (
            _get_table_info,
            handle_chapter_add,
            handle_chapter_bulk,
            handle_chapter_bulk_preview,
            handle_chapter_delete,
            handle_chapter_edit,
            handle_rename_delete,
            handle_series_update,
        )

        for h in (
            handle_chapter_add,
            handle_chapter_bulk,
            handle_chapter_bulk_preview,
            handle_chapter_delete,
            handle_chapter_edit,
            handle_rename_delete,
            handle_series_update,
        ):
            assert inspect.iscoroutinefunction(h)
        assert callable(_get_table_info)

    def test_get_table_info_akashic(self):
        from services.admin_chapter_api import _get_table_info

        info = _get_table_info("akashic_records", 1)
        assert info is not None
        table, col, where, _ = info
        assert table == "akashic_ranobe"
        assert col == "chapter"
        assert where == "volume = ? AND chapter = ?"

    def test_get_table_info_british(self):
        from services.admin_chapter_api import _get_table_info

        info = _get_table_info("british_belle", 2)
        assert info is not None
        assert info[0] == "british_ranobe"

    def test_get_table_info_manga(self):
        from services.admin_chapter_api import _get_table_info

        info = _get_table_info("manga_ru", None)
        assert info is not None
        table, col, where, params_fn = info
        assert table == "chapters_urls"
        assert col == "chapter_number"
        # params_fn возвращает (chapter, lang)
        assert params_fn(None, "10") == ("10", "ru")

    def test_get_table_info_ranobe(self):
        from services.admin_chapter_api import _get_table_info

        info = _get_table_info("ranobe_en", None)
        assert info is not None
        assert info[0] == "ranobe_urls"

    def test_get_table_info_unknown_returns_none(self):
        from services.admin_chapter_api import _get_table_info

        assert _get_table_info("unknown_series", 1) is None

    def test_bulk_preview_detects_duplicates_and_does_not_write(self, tmp_path, monkeypatch):
        import asyncio
        import json

        import aiosqlite

        import bot
        import services.admin_chapter_api as admin_chapter_api
        from services.admin_chapter_api import handle_chapter_bulk_preview

        db_path = tmp_path / "bulk-preview.db"

        async def setup_db():
            async with aiosqlite.connect(db_path) as db:
                await db.execute(
                    "CREATE TABLE chapters_urls (chapter_number TEXT, lang TEXT, url TEXT, sort_order INTEGER DEFAULT 0, PRIMARY KEY (chapter_number, lang))"
                )
                await db.execute(
                    "INSERT INTO chapters_urls (chapter_number, lang, url, sort_order) VALUES (?, ?, ?, ?)",
                    ("2", "ru", "https://old.example/2", 2),
                )
                await db.commit()

        asyncio.run(setup_db())
        monkeypatch.setattr(bot, "DB_PATH", str(db_path))
        monkeypatch.setattr(admin_chapter_api, "get_auth_user", lambda _request: {"id": 123})

        async def fake_rate_limit(*_args, **_kwargs):
            return None

        async def fake_check_admin(*_args, **_kwargs):
            return None

        monkeypatch.setattr(admin_chapter_api, "_enforce_rate_limit", fake_rate_limit)
        monkeypatch.setattr(admin_chapter_api, "_check_admin", fake_check_admin)

        class FakeRequest:
            path = "/api/chapters/bulk/preview"

            async def json(self):
                return {
                    "series_id": "manga_ru",
                    "start_chapter": 1,
                    "urls": [
                        "https://example.org/1",
                        "https://example.org/2",
                        "not-a-url",
                    ],
                }

        resp = asyncio.run(handle_chapter_bulk_preview(FakeRequest()))
        assert resp.status == 200
        body = json.loads(resp.body.decode())
        assert body["ok"] is False
        assert body["items"][0]["chapter"] == "1"
        assert body["items"][0]["status"] == "new"
        assert body["items"][1]["chapter"] == "2"
        assert body["items"][1]["status"] == "duplicate"
        assert body["invalid"][0]["index"] == 3
        assert body["warnings"]

        async def count_rows():
            async with aiosqlite.connect(db_path) as db:
                async with db.execute("SELECT COUNT(*) FROM chapters_urls") as cursor:
                    return (await cursor.fetchone())[0]

        assert asyncio.run(count_rows()) == 1


# --- services.comments_api ---


class TestCommentsApi:
    def test_imports(self):
        import inspect

        from services.comments_api import (
            handle_comment_react_post,
            handle_comments_delete,
            handle_comments_get,
            handle_comments_post,
            handle_comments_update,
        )

        for h in (
            handle_comment_react_post,
            handle_comments_delete,
            handle_comments_get,
            handle_comments_post,
            handle_comments_update,
        ):
            assert inspect.iscoroutinefunction(h)


# --- services.validators (новые константы шага 13) ---


class TestValidatorsExtendedLimits:
    def test_new_limits_exported(self):
        from services.validators import (
            MAX_BULK_URLS_PER_REQUEST,
            MAX_CHAPTER_EDIT_RAW_TEXT_LENGTH,
            MAX_CHAPTER_KEY_LENGTH,
            MAX_COMMENT_TEXT_LENGTH,
            MAX_RENAME_OBJECT_ID_LENGTH,
        )

        assert MAX_CHAPTER_KEY_LENGTH == 160
        assert MAX_COMMENT_TEXT_LENGTH == 500
        assert MAX_CHAPTER_EDIT_RAW_TEXT_LENGTH == 18000
        assert MAX_BULK_URLS_PER_REQUEST == 200
        assert MAX_RENAME_OBJECT_ID_LENGTH == 200


# --- services.ai_chat_api + services.typo_api + services.comments_api.handle_comments_report ---


class TestAiChatApi:
    def test_imports(self):
        import inspect

        from services.ai_chat_api import handle_ai_chat

        assert inspect.iscoroutinefunction(handle_ai_chat)


class TestTypoApi:
    def test_imports(self):
        import inspect

        from services.typo_api import handle_typo_post

        assert inspect.iscoroutinefunction(handle_typo_post)


class TestCommentsReport:
    def test_import(self):
        import inspect

        from services.comments_api import handle_comments_report

        assert inspect.iscoroutinefunction(handle_comments_report)


# --- services.admin_art_fsm ---


class TestAdminArtFsm:
    def test_router_and_fsm_exported(self):
        from aiogram import Router
        from aiogram.fsm.state import StatesGroup

        from services.admin_art_fsm import ArtSuggest, ArtUpload, art_router

        assert isinstance(art_router, Router)
        assert issubclass(ArtUpload, StatesGroup)
        assert issubclass(ArtSuggest, StatesGroup)

    def test_handlers_are_coroutines(self):
        import inspect

        from services.admin_art_fsm import (
            callback_suggest_art_menu,
            cmd_add_art,
            cmd_suggest_art,
            finish_art_upload,
            process_art_accept,
            process_art_photo,
            process_art_reject,
            process_suggested_art,
        )

        for h in (
            cmd_add_art,
            cmd_suggest_art,
            finish_art_upload,
            process_art_photo,
            process_suggested_art,
            process_art_accept,
            process_art_reject,
            callback_suggest_art_menu,
        ):
            assert inspect.iscoroutinefunction(h)

    def test_router_has_handlers(self):
        from services.admin_art_fsm import art_router

        # 5 message handlers + 3 callback handlers.
        assert len(art_router.message.handlers) >= 5
        assert len(art_router.callback_query.handlers) >= 3
