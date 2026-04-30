# Reader WebApp Audit Map

This map is the working checklist for reader polishing. It mirrors
`window.READER_AUDIT_MAP` from `webapp/reader.audit.js` so tests and humans use
the same coverage model.

## Runtime Surfaces

- `screen-series`: series library, search, continue-reading, Telegram login CTA.
- `screen-chapters`: series hero, volume tabs, chapter list, admin add/sort tools.
- `screen-reader`: reader text, top and bottom chrome, gestures, settings, social block.
- `screen-library`: saved/progress library, filters, global search chrome.

## Code Domains

- Auth: Telegram WebApp auth, site auth, public read-only mode.
- State/cache: global reader state, localStorage, reader snapshots, chapter payload cache.
- Data loading: `/api/reader`, fallback JSON, start params, stale cache rotation.
- Navigation: series cards, volume tabs, chapter list, last-read jumps.
- Chapter rendering: chapter API, inline text, Telegraph/Teletype fallback, prefetch.
- Reader chrome: prev/next, progress bar, immersive mode, tap/swipe/pull gestures.
- Admin tools: rich editor, bulk upload, cover edit, chapter delete, sort/move.
- Social: likes, reactions, comments, typo report, auth-required states.
- Settings: themes, font/density controls, dimmer, keyboard-aware UI.
- Offline/sync: service worker, API rev, cached payloads, stale snapshot cleanup.
- Telemetry: client errors, state-contract warnings, chapter-open events.

## Verification Matrix

- Static: `node --check reader.boot.js reader.audit.js reader.js shared.js`,
  `npm run test:jsdom`, and Python WebApp contract tests.
- E2E: public mode, authenticated mode, admin mode, add/edit/delete/sort/bulk,
  comments/reactions/likes/typo, cache/offline fallback, multi-series isolation.
- Visual: 360x740, 390x844, 768x1024, 1366x900, 1920x1080.
- Data fixtures: same chapter numbers across different volumes, empty chapter,
  multiple URL sources, inline text, Telegraph/Teletype/image-only content.

## Current Polishing Notes

- `reader.boot.js` owns script loading order: audit map first, reader app second.
- `reader.audit.js` is intentionally behavior-free and safe to load in production.
- `html/body` must keep `margin: 0`; viewport tests guard against default browser
  margins shifting the reader by 8px.
