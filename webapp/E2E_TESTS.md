# WebApp Playwright E2E

## Install dependencies

```powershell
cd webapp
npm install
```

## Run E2E smoke

```powershell
npm run test:e2e
```

## Run headed mode

```powershell
npm run test:e2e:headed
```

## Covered flows

- Reader user flow: open chapter, prev/next navigation
- Comments: post comment with optimistic update
- Chapter reactions: toggle and state refresh
- Typo report submit
- Admin flow: rename request, chapter URL edit, bulk add, chapter sort sync
