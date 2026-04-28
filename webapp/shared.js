(function initAlyaShared(global) {
  'use strict';

  const DEFAULT_MESSAGES = {
    unauthorized: ['Нужна авторизация.', 'Откройте WebApp из Telegram или войдите через Telegram.'],
    forbidden: ['Нет доступа.', 'Откройте WebApp из Telegram под аккаунтом с нужными правами.'],
    bad_request: ['Запрос не прошел проверку.', 'Проверьте введенные данные и повторите действие.'],
    not_found: ['Данные не найдены.', 'Обновите страницу или вернитесь к списку.'],
    timeout: ['Сервер не успел ответить.', 'Проверьте соединение и повторите действие.'],
    network: ['Нет соединения.', 'Проверьте интернет и повторите действие.'],
    internal: ['Внутренняя ошибка.', 'Повторите действие позже или сообщите админу.'],
    unknown: ['Что-то пошло не так.', 'Повторите действие или сообщите админу.'],
  };

  function normalizeApiError(payload, status) {
    const raw = payload && typeof payload === 'object' ? payload : {};
    const error = raw.error && typeof raw.error === 'object' ? raw.error : {};
    const code = String(
      error.code ||
      raw.error ||
      (status === 401 ? 'unauthorized' : status === 403 ? 'forbidden' : status === 404 ? 'not_found' : 'unknown')
    );
    const defaults = DEFAULT_MESSAGES[code] || DEFAULT_MESSAGES.unknown;
    return {
      code,
      status: Number(status || 0),
      message: String(error.message || defaults[0]),
      recovery: String(error.recovery || defaults[1]),
      requestId: String(raw.request_id || ''),
    };
  }

  function apiErrorToText(error) {
    if (!error) return DEFAULT_MESSAGES.unknown.join(' ');
    const request = error.requestId ? ` Код: ${error.requestId}.` : '';
    return `${error.message || DEFAULT_MESSAGES.unknown[0]} ${error.recovery || DEFAULT_MESSAGES.unknown[1]}${request}`;
  }

  function getTelegramInitData() {
    try {
      return global.Telegram?.WebApp?.initData || '';
    } catch (_) {
      return '';
    }
  }

  function timeoutSignal(ms) {
    if (!global.AbortController || !ms) return null;
    const controller = new global.AbortController();
    const timer = global.setTimeout(() => controller.abort(), ms);
    return { signal: controller.signal, cancel: () => global.clearTimeout(timer) };
  }

  function shouldRetryGet(method, attempt, response) {
    return method === 'GET' && attempt === 0 && [408, 429, 500, 502, 503, 504].includes(Number(response.status));
  }

  function delay(ms) {
    return new Promise((resolve) => global.setTimeout(resolve, ms));
  }

  function createApiClient({ baseUrl = '', initData = getTelegramInitData(), timeoutMs = 10000 } = {}) {
    async function request(path, options = {}) {
      const method = String(options.method || 'GET').toUpperCase();
      let lastError = null;

      for (let attempt = 0; attempt < 2; attempt += 1) {
        const headers = { ...(options.headers || {}) };
        if (initData && !headers.Authorization) headers.Authorization = `tma ${initData}`;
        if (options.body && !headers['Content-Type']) headers['Content-Type'] = 'application/json';
        const timeout = timeoutSignal(timeoutMs);

        try {
          const response = await global.fetch(`${baseUrl}${path}`, {
            ...options,
            method,
            headers,
            signal: options.signal || (timeout && timeout.signal),
          });
          const json = await response.json().catch(() => ({}));
          if (shouldRetryGet(method, attempt, response)) {
            await delay(180);
            continue;
          }
          if (!response.ok || json.ok === false) {
            const details = normalizeApiError(json, response.status);
            const error = new Error(details.message);
            Object.assign(error, details);
            throw error;
          }
          return json;
        } catch (error) {
          if (error && error.code) throw error;
          const code = error && error.name === 'AbortError' ? 'timeout' : 'network';
          const details = normalizeApiError({ error: { code } }, code === 'timeout' ? 408 : 0);
          lastError = Object.assign(new Error(details.message), details);
          if (method === 'GET' && attempt === 0) {
            await delay(180);
            continue;
          }
          throw lastError;
        } finally {
          if (timeout) timeout.cancel();
        }
      }

      throw lastError || Object.assign(new Error(DEFAULT_MESSAGES.unknown[0]), normalizeApiError({ error: 'unknown' }, 0));
    }

    return {
      request,
      get: (path, options = {}) => request(path, { ...options, method: 'GET' }),
      post: (path, body, options = {}) => request(path, { ...options, method: 'POST', body: JSON.stringify(body || {}) }),
      delete: (path, options = {}) => request(path, { ...options, method: 'DELETE' }),
    };
  }

  let toastTimer = null;
  function showToast(text, { tone = 'info', ms = 3200 } = {}) {
    if (!global.document) return;
    let toast = global.document.querySelector('[data-shared-toast]');
    if (!toast) {
      toast = global.document.createElement('div');
      toast.className = 'shared-toast';
      toast.dataset.sharedToast = '1';
      toast.setAttribute('role', 'status');
      toast.setAttribute('aria-live', 'polite');
      global.document.body.appendChild(toast);
    }
    toast.textContent = text;
    toast.dataset.tone = tone;
    toast.classList.add('is-visible');
    global.clearTimeout(toastTimer);
    toastTimer = global.setTimeout(() => toast.classList.remove('is-visible'), ms);
  }

  function renderRecovery(target, error, { retryLabel = 'Повторить', reportLabel = 'Сообщить админу', onRetry = null } = {}) {
    const node = typeof target === 'string' ? global.document.querySelector(target) : target;
    if (!node) return;
    node.innerHTML = '';
    const details = error && error.code ? error : normalizeApiError({ error: error && error.message ? { code: 'unknown', message: error.message } : 'unknown' }, error && error.status);
    const card = global.document.createElement('div');
    card.className = 'shared-recovery';
    card.innerHTML = `<b>${escapeHtml(details.message)}</b><span>${escapeHtml(details.recovery)}</span>`;
    if (details.requestId) {
      const small = global.document.createElement('small');
      small.textContent = `Код обращения: ${details.requestId}`;
      card.appendChild(small);
    }

    const actions = global.document.createElement('div');
    actions.className = 'shared-recovery-actions';
    if (onRetry) {
      const button = global.document.createElement('button');
      button.type = 'button';
      button.className = 'shared-button';
      button.textContent = retryLabel;
      button.addEventListener('click', onRetry);
      actions.appendChild(button);
    }
    const report = global.document.createElement('button');
    report.type = 'button';
    report.className = 'shared-button secondary';
    report.textContent = reportLabel;
    report.addEventListener('click', () => handleReportToAdmin(details));
    actions.appendChild(report);
    card.appendChild(actions);
    node.appendChild(card);
  }

  function reportText(details) {
    const page = global.location && global.location.href ? global.location.href : '';
    const request = details.requestId ? `\nКод: ${details.requestId}` : '';
    return [
      'Alya WebApp report',
      `Ошибка: ${details.message || 'не указана'}`,
      `Что делать: ${details.recovery || 'не указано'}`,
      page ? `Страница: ${page}` : '',
      request.trim(),
    ].filter(Boolean).join('\n');
  }

  async function copyText(text) {
    if (global.navigator && global.navigator.clipboard && typeof global.navigator.clipboard.writeText === 'function') {
      await global.navigator.clipboard.writeText(text);
      return true;
    }
    if (!global.document || typeof global.document.execCommand !== 'function') return false;
    const textarea = global.document.createElement('textarea');
    textarea.value = text;
    textarea.setAttribute('readonly', '');
    textarea.style.position = 'fixed';
    textarea.style.left = '-9999px';
    global.document.body.appendChild(textarea);
    textarea.select();
    const copied = global.document.execCommand('copy');
    textarea.remove();
    return copied;
  }

  async function handleReportToAdmin(details) {
    const text = reportText(details || {});
    sendTelemetry('client_report_to_admin', {
      module: 'shared-recovery',
      message: details && details.message ? details.message : 'manual report',
      error: details,
      report_text: text,
    });
    const copied = await copyText(text).catch(() => false);
    const telegram = global.Telegram && global.Telegram.WebApp;
    if (telegram && typeof telegram.openTelegramLink === 'function') {
      showToast(copied ? 'Отчёт скопирован, открываю чат с админом' : 'Открываю чат с админом', { tone: 'info' });
      global.setTimeout(() => telegram.openTelegramLink('https://t.me/Alyamangapage_bot'), 120);
      return;
    }
    showToast(copied ? 'Отчёт скопирован. Отправьте его админу в Telegram.' : 'Не удалось открыть Telegram. Напишите админу: @Alyamangapage_bot', { tone: copied ? 'info' : 'error' });
  }

  function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, (char) => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;',
    })[char]);
  }

  function sendTelemetry(eventType, payload = {}) {
    try {
      const endpoint = payload.endpoint || '/api/telemetry';
      const body = JSON.stringify({ event_type: eventType, payload, page_url: global.location && global.location.href });
      if (global.navigator && typeof global.navigator.sendBeacon === 'function' && typeof global.Blob === 'function') {
        const ok = global.navigator.sendBeacon(endpoint, new global.Blob([body], { type: 'application/json' }));
        if (ok) return;
      }
      if (typeof global.fetch === 'function') {
        global.fetch(endpoint, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body, keepalive: true }).catch(() => {});
      }
    } catch (_) {}
  }

  global.AlyaWebApp = {
    apiErrorToText,
    createApiClient,
    escapeHtml,
    getTelegramInitData,
    normalizeApiError,
    renderRecovery,
    handleReportToAdmin,
    sendTelemetry,
    showToast,
  };
})(typeof window !== 'undefined' ? window : globalThis);
