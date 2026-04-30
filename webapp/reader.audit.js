(function () {
  "use strict";

  const version = "20260430-reader-audit-1";

  const screens = [
    { id: "screen-series", label: "Series library", owns: ["library-navigation", "data-loading"] },
    { id: "screen-chapters", label: "Volume and chapter list", owns: ["library-navigation", "admin-tools"] },
    { id: "screen-reader", label: "Reading surface", owns: ["chapter-rendering", "reader-chrome", "social"] },
    { id: "screen-library", label: "Saved and progress library", owns: ["state-cache", "library-navigation"] },
  ];

  const domains = [
    { id: "auth", range: "reader.js:31-247", owns: ["Telegram WebApp auth", "site auth", "public read mode"] },
    { id: "state-cache", range: "reader.js:249-1817", owns: ["global state", "localStorage", "payload caches", "progress"] },
    { id: "data-loading", range: "reader.js:1821-2078", owns: ["reader API", "fallback snapshot", "startup params"] },
    { id: "library-navigation", range: "reader.js:2090-2486", owns: ["series cards", "volume tabs", "chapter list"] },
    { id: "chapter-rendering", range: "reader.js:2502-3254", owns: ["chapter open", "content API", "fallback rendering", "prefetch"] },
    { id: "reader-chrome", range: "reader.js:3220-3254, 6813-7340", owns: ["prev/next", "gestures", "progress bar"] },
    { id: "admin-tools", range: "reader.js:4990-6450", owns: ["editor", "bulk upload", "cover edit", "sort"] },
    { id: "social", range: "reader.js:3262-4988", owns: ["likes", "comments", "reactions", "typo reports"] },
    { id: "settings", range: "reader.js:674-984, 371-556 html", owns: ["themes", "font controls", "reader density"] },
    { id: "offline-sync", range: "reader.js:1021-1288, sw.js", owns: ["snapshot cache", "chapter cache", "service worker"] },
    { id: "telemetry", range: "reader.js:1375-1565", owns: ["client errors", "reader state contract", "chapter open events"] },
  ];

  const apiEndpoints = [
    "/api/reader",
    "/api/chapter-content",
    "/api/progress",
    "/api/comments",
    "/api/comment-reactions",
    "/api/likes",
    "/api/reactions",
    "/api/chapters",
    "/api/chapters/bulk",
    "/api/chapters/bulk/preview",
    "/api/sort",
    "/api/series",
    "/api/typo",
    "/api/telemetry",
    "/api/auth/me",
    "/api/auth/login",
    "/api/auth/logout",
  ];

  const storageKeys = [
    "reader_admin_mode",
    "reader_library_filter",
    "reader_api_snapshot_v2",
    "reader_api_snapshot_rev",
    "reader_sw_rev",
    "reader_chapter_payload_v2",
    "reader_settings",
    "read_chapters",
    "last_read",
  ];

  const visualViewports = [
    { name: "mobile-small", width: 360, height: 740 },
    { name: "mobile-modern", width: 390, height: 844 },
    { name: "tablet", width: 768, height: 1024 },
    { name: "desktop", width: 1366, height: 900 },
    { name: "wide", width: 1920, height: 1080 },
  ];

  window.READER_AUDIT_MAP = Object.freeze({
    version,
    screens: Object.freeze(screens),
    domains: Object.freeze(domains),
    apiEndpoints: Object.freeze(apiEndpoints),
    storageKeys: Object.freeze(storageKeys),
    visualViewports: Object.freeze(visualViewports),
  });
})();
