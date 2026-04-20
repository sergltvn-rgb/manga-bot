# Release Checklist (WebApp)

1. Run syntax check: `npm run check:js` in `webapp/`.
2. Open WebApp and verify initial load is successful (no blank screen).
3. Validate series -> volume -> chapter navigation flow.
4. Validate chapter switching (`prev/next`, quick switcher, ToC).
5. Validate scroll persistence and progress bar behavior.
6. Validate likes/reactions/comments basic flow.
7. Validate typo report flow (selection -> modal -> submit).
8. Validate admin flows (rename, edit URL, bulk add, DnD ordering) on admin account.
9. Validate lifecycle behavior: leave app/background tab and return (no state loss, no JS errors).
10. Verify browser console has no critical errors in key flows.
11. Deploy to staging and run smoke test on mobile Telegram WebApp.
12. Roll out to production and monitor metrics/errors for at least 48 hours.
