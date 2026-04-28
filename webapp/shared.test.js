const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const { JSDOM } = require('jsdom');

const code = fs.readFileSync('shared.js', 'utf8');

function createContext(fetchImpl) {
  const timers = [];
  const context = {
    window: {},
    document: {
      createElement: () => ({
        className: '',
        textContent: '',
        dataset: {},
        classList: { add() {}, remove() {} },
        setAttribute() {},
        appendChild() {},
        addEventListener() {},
      }),
      body: { appendChild() {} },
      querySelector: () => null,
    },
    navigator: { onLine: true, sendBeacon: () => false },
    fetch: fetchImpl,
    AbortController,
    Blob,
    clearTimeout,
    setTimeout: (fn, ms) => {
      timers.push({ fn, ms });
      return timers.length;
    },
    URLSearchParams,
    location: { href: 'https://example.test/reader.html', origin: 'https://example.test' },
    console,
  };
  context.window = context;
  vm.createContext(context);
  vm.runInContext(code, context);
  return context;
}

async function run() {
  const okContext = createContext(async (_url, options) => ({
    ok: true,
    status: 200,
    json: async () => ({ ok: true, from: options.headers.Authorization }),
  }));
  const client = okContext.AlyaWebApp.createApiClient({ baseUrl: 'https://api.test', initData: 'abc', timeoutMs: 1000 });
  const ok = await client.get('/api/check');
  assert.equal(ok.from, 'tma abc');

  const forbiddenContext = createContext(async () => ({
    ok: false,
    status: 403,
    json: async () => ({ ok: false, error: { code: 'forbidden', message: 'Нет доступа.', recovery: 'Откройте из Telegram.' } }),
  }));
  await assert.rejects(
    forbiddenContext.AlyaWebApp.createApiClient({ baseUrl: '' }).get('/api/check'),
    (error) => error.code === 'forbidden' && error.recovery === 'Откройте из Telegram.'
  );

  const legacy = forbiddenContext.AlyaWebApp.normalizeApiError({ error: 'bad_request' }, 400);
  assert.equal(legacy.message, 'Запрос не прошел проверку.');
  assert.equal(legacy.recovery, 'Проверьте введенные данные и повторите действие.');

  const dom = new JSDOM('<!doctype html><body><div id="recovery"></div></body>', { url: 'https://example.test/admin.html' });
  const reportCalls = [];
  const openedLinks = [];
  let clipboardText = '';
  const reportContext = {
    window: {},
    document: dom.window.document,
    navigator: {
      sendBeacon: () => false,
      clipboard: { writeText: async (text) => { clipboardText = text; } },
    },
    Telegram: { WebApp: { openTelegramLink: (url) => openedLinks.push(url) } },
    fetch: async (_url, options) => {
      reportCalls.push(JSON.parse(options.body));
      return { ok: true, status: 200, json: async () => ({ ok: true }) };
    },
    AbortController,
    Blob,
    clearTimeout,
    setTimeout,
    URLSearchParams,
    location: dom.window.location,
    console,
  };
  reportContext.window = reportContext;
  vm.createContext(reportContext);
  vm.runInContext(code, reportContext);
  reportContext.AlyaWebApp.renderRecovery(
    '#recovery',
    { code: 'forbidden', message: 'Нет доступа.', recovery: 'Откройте из Telegram.', requestId: 'abc123' },
    { onRetry: () => {} }
  );
  dom.window.document.querySelector('.shared-button.secondary').click();
  await new Promise((resolve) => setTimeout(resolve, 180));

  assert.equal(reportCalls[0].event_type, 'client_report_to_admin');
  assert.equal(reportCalls[0].payload.module, 'shared-recovery');
  assert.match(clipboardText, /Нет доступа/);
  assert.deepEqual(openedLinks, ['https://t.me/Alyamangapage_bot']);
}

run().catch((error) => {
  console.error(error);
  process.exit(1);
});
