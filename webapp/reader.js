// ==========================================================================
// Читалка ранобэ — JavaScript v3
// Загрузка/отображение, прогресс чтения, лайки, комментарии
// ==========================================================================

const tg = (window.Telegram && window.Telegram.WebApp) ? window.Telegram.WebApp : { expand: () => {}, ready: () => {}, openTelegramLink: (url) => window.open(url, '_blank'), initDataUnsafe: {} };
tg.expand();
tg.ready();

function openChannel() {
    if (window.Telegram && window.Telegram.WebApp) {
        window.Telegram.WebApp.openTelegramLink('https://t.me/alya_novel');
    } else {
        window.open('https://t.me/alya_novel', '_blank');
    }
}

// === Telegram User ===
const tgUser = tg.initDataUnsafe?.user || {};
const userId = String(tgUser.id || '');
const userName = tgUser.first_name || 'Аноним';

// === Состояние ===
let allData = { series: [] };
let adminIds = []; // Список ID администраторов из БД
let currentSeries = null;
let currentVolume = null;
let currentChapterIdx = 0;
let currentChapters = [];
let isAdminMode = false;
let currentCommentSort = 'top'; 
let allCommentsCache = []; 
let commentsData = []; 
let isImmersive = false;
const LIBRARY_FILTER_KEY = 'reader_library_filter';
const LIBRARY_FILTERS = {
    IN_PROGRESS: 'in_progress',
    NOT_STARTED: 'not_started',
    COMPLETED: 'completed'
};
let libraryFilter = LIBRARY_FILTERS.IN_PROGRESS;

// === Typo Report State ===
let typoSelectedText = '';
let typoContextText = '';
let typoSelectionRange = null;
let _readerTapToScrollSuppressUntil = 0;
let _readerKeyboardUiInitialized = false;
let _networkStatusHideTimer = null;
let _networkStatusBound = false;

function suppressReaderTapToScroll(ms = 700) {
    const until = Date.now() + Number(ms || 0);
    if (until > _readerTapToScrollSuppressUntil) {
        _readerTapToScrollSuppressUntil = until;
    }
}

function isReaderTapToScrollSuppressed() {
    return Date.now() < _readerTapToScrollSuppressUntil;
}

function _isReaderEditableElement(el) {
    if (!el || !(el instanceof HTMLElement)) return false;
    if (!el.closest('#screen-reader')) return false;
    if (el.tagName === 'TEXTAREA') return true;
    if (el.tagName === 'INPUT') {
        const type = (el.getAttribute('type') || 'text').toLowerCase();
        return ['text', 'search', 'url', 'email', 'tel', 'number'].includes(type);
    }
    return !!el.isContentEditable;
}

function bindReaderKeyboardAwareUI() {
    if (_readerKeyboardUiInitialized) return;
    _readerKeyboardUiInitialized = true;

    const root = document.documentElement;
    const body = document.body;
    if (!root || !body) return;

    let keyboardByFocus = false;
    let keyboardByViewport = false;
    let viewportBaseline = 0;

    const applyKeyboardState = () => {
        body.classList.toggle('keyboard-open', keyboardByFocus || keyboardByViewport);
    };

    const visualViewport = window.visualViewport || null;

    const updateViewportKeyboardState = () => {
        if (!visualViewport) return;
        viewportBaseline = Math.max(viewportBaseline, visualViewport.height || 0);
        const occluded = Math.max(0, window.innerHeight - (visualViewport.height + visualViewport.offsetTop));
        keyboardByViewport = occluded > 110 || (viewportBaseline - visualViewport.height) > 130;
        root.style.setProperty('--reader-keyboard-offset', `${Math.max(0, Math.round(occluded))}px`);
        applyKeyboardState();
    };

    document.addEventListener('focusin', (event) => {
        const target = event.target;
        if (!_isReaderEditableElement(target)) return;
        keyboardByFocus = true;
        suppressReaderTapToScroll(900);
        applyKeyboardState();
        setTimeout(() => {
            try {
                if (target && typeof target.scrollIntoView === 'function') {
                    target.scrollIntoView({ block: 'center', behavior: 'smooth' });
                }
            } catch (e) { }
        }, 120);
    });

    document.addEventListener('focusout', () => {
        setTimeout(() => {
            const activeEl = document.activeElement;
            if (!_isReaderEditableElement(activeEl)) {
                keyboardByFocus = false;
                applyKeyboardState();
            }
        }, 60);
    });

    if (visualViewport) {
        visualViewport.addEventListener('resize', updateViewportKeyboardState);
        visualViewport.addEventListener('scroll', updateViewportKeyboardState);
        updateViewportKeyboardState();
    } else {
        root.style.setProperty('--reader-keyboard-offset', '0px');
    }
}

function toggleAdminMode(enabled) {
    isAdminMode = enabled;
    if (document.getElementById('screen-series').classList.contains('active')) renderSeriesList();
    if (isAdminMode) {
        document.getElementById('screen-chapters').classList.add('admin-enabled');
    }
    renderContinueReading();
    if (document.getElementById('screen-chapters').classList.contains('active')) {
        renderVolumeTabs();
        renderChaptersList();
    }
}

async function renameItem(objId) {
    if (!API_URL) return showToast('Переименование доступно только при подключенном API.');
    try {
        const resp = await apiFetch(`${API_URL}/api/rename/request`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ obj_id: objId })
        });
        const data = await resp.json();
        if (data.ok) {
            const bot_username = allData.bot_username || "Alyamangapage_bot";
            tg.openTelegramLink('https://t.me/' + bot_username + '?start=ren_' + data.short_id);
            tg.close();
        } else {
            showToast('Ошибка: ' + (data.error || 'неизвестная'));
        }
    } catch (e) {
        showToast('Ошибка сети: ' + e.message);
    }
}

async function resetCustomName(objId) {
    if (!API_URL) return showToast('Сброс доступен только через прямое подключение (не GitHub Pages).');
    if (!confirm(`Сбросить кастомное имя "${objId}" на дефолт?`)) return;
    try {
        const resp = await apiFetch(`${API_URL}/api/rename`, {
            method: 'DELETE',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ obj_id: objId })
        });
        const result = await resp.json();
        if (result.ok) {
            // Перезагружаем данные чтобы увидеть обновлённые имена
            await loadData();
            showToast('✅ Имя сброшено на дефолт.');
        } else {
            showToast('Ошибка: ' + (result.error || 'неизвестная'));
        }
    } catch (e) {
        showToast('Ошибка сети: ' + e.message);
    }
}

// === Настройки (из localStorage) ===
function getUserRole(userIdStr) {
    if (adminIds.includes(userIdStr)) return { text: 'Админ', css: 'badge-admin' };
    return null;
}

// SQLite возвращает время в UTC "YYYY-MM-DD HH:MM:SS". Превращаем его в валидный ISO 8601 UTC.
function formatDate(dateStr) {
    if (!dateStr) return '';
    try {
        const safeDateStr = dateStr.includes('T') ? dateStr : dateStr.replace(' ', 'T') + 'Z';
        const d = new Date(safeDateStr);
        const now = new Date();
        const diff = now - d;
        const mins = Math.floor(diff / 60000);
        if (mins < 1) return 'только что';
        if (mins < 60) return `${mins} мин. назад`;
        const hours = Math.floor(mins / 60);
        if (hours < 24) return `${hours} ч. назад`;
        const days = Math.floor(hours / 24);
        if (days < 7) return `${days} дн. назад`;
        return d.toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' });
    } catch {
        return dateStr;
    }
}

function toggleImmersiveMode(force = null) {
    isImmersive = force !== null ? force : !isImmersive;
    const header = document.querySelector('.reader-header');
    const bottomBar = document.getElementById('reader-bottom-bar');
    const fab = document.getElementById('fab-container');
    
    if (isImmersive) {
        header?.classList.add('header-hidden');
        bottomBar?.classList.add('bar-hidden');
        fab?.classList.add('fab-hidden');
    } else {
        header?.classList.remove('header-hidden');
        bottomBar?.classList.remove('bar-hidden');
        fab?.classList.remove('fab-hidden');
    }
}

function toggleQuickSwitcher() {
    const switcher = document.getElementById('quick-switcher');
    const overlay = document.getElementById('quick-switcher-overlay');
    if (!switcher) return;
    
    // Прячем меню FAB если открыто
    const fabMenu = document.getElementById('fab-menu');
    if (fabMenu && !fabMenu.classList.contains('hidden')) toggleFab();

    const isActive = switcher.classList.contains('active');
    
    if (!isActive) {
        renderQuickSwitcherList();
        switcher.classList.add('active');
        overlay?.classList.add('active');
        haptic('light');
    } else {
        switcher.classList.remove('active');
        const toc = document.getElementById('toc-panel');
        if (!toc || !toc.classList.contains('active')) {
            overlay?.classList.remove('active');
        }
    }
}

function renderQuickSwitcherList() {
    const list = document.getElementById('quick-switcher-list');
    if (!list || !currentChapters) return;
    
    list.innerHTML = currentChapters.map((ch, idx) => `
        <div class="quick-switcher-item ${idx === currentChapterIdx ? 'active' : ''}" 
             onclick="openChapter(${idx}); toggleQuickSwitcher();">
            ${ch.custom_name || 'Глава ' + ch.chapter}
        </div>
    `).join('');
}

const defaults = { 
    fontSize: 17, 
    theme: 'light', 
    textWidth: 90, 
    font: 'serif', 
    lineHeight: 1.8, 
    textAlign: 'left', 
    indent: true, 
    paraSpacing: 20,
    letterSpacing: 0,
    paraIndent: 25,
    dimmerValue: 0,
    readingMode: 'scroll' // 'scroll' or 'pages'
};
let settings;
try {
    settings = JSON.parse(localStorage.getItem('reader_settings') || 'null') || { ...defaults };
} catch (e) {
    console.warn("Failed to parse settings from localStorage", e);
    settings = { ...defaults };
}
// Миграция старых настроек
if (!settings.lineHeight) settings.lineHeight = 1.8;
if (!settings.textAlign) settings.textAlign = 'left';
if (settings.indent === undefined) settings.indent = true;
if (settings.paraSpacing === undefined) settings.paraSpacing = 20;
if (settings.letterSpacing === undefined) settings.letterSpacing = 0;
if (settings.paraIndent === undefined) settings.paraIndent = 25;
if (settings.dimmerValue === undefined) settings.dimmerValue = 0;
if (settings.readingMode === undefined) settings.readingMode = 'scroll';

let readChapters;
try {
    readChapters = JSON.parse(localStorage.getItem('reader_progress') || '{}');
} catch (e) {
    console.warn("Failed to parse readChapters from localStorage", e);
    readChapters = {};
}

function safeGetLocal(key, defaultVal) {
    try {
        const val = localStorage.getItem(key);
        return val ? JSON.parse(val) : defaultVal;
    } catch (e) {
        return defaultVal;
    }
}
function safeSetLocal(key, val) {
    try {
        localStorage.setItem(key, JSON.stringify(val));
    } catch (e) {}
}

const READER_API_CACHE_KEY = 'reader_api_snapshot_v1';
const OFFLINE_CHAPTER_PREFETCH_COUNT = 3;

function getCachedReaderApiSnapshot() {
    const snapshot = safeGetLocal(READER_API_CACHE_KEY, null);
    if (!snapshot || typeof snapshot !== 'object') return null;
    if (!snapshot.payload || typeof snapshot.payload !== 'object') return null;
    return {
        etag: typeof snapshot.etag === 'string' ? snapshot.etag : '',
        payload: snapshot.payload
    };
}

function saveReaderApiSnapshot(payload, etag = '') {
    if (!payload || typeof payload !== 'object') return;
    safeSetLocal(READER_API_CACHE_KEY, {
        etag: typeof etag === 'string' ? etag : '',
        payload,
        ts: Date.now()
    });
}

function getChapterSourceUrls(chapter) {
    if (!chapter || typeof chapter !== 'object') return [];
    const urls = [];
    if (Array.isArray(chapter.urls)) {
        urls.push(...chapter.urls);
    } else if (typeof chapter.url === 'string' && chapter.url) {
        urls.push(chapter.url);
    }
    return urls
        .map((u) => String(u || '').trim())
        .filter((u) => /^https?:\/\//i.test(u));
}

function toServiceWorkerCacheUrl(rawUrl) {
    if (!rawUrl) return '';
    const src = String(rawUrl).trim();
    const telegraphMatch = src.match(/^https?:\/\/telegra\.ph\/(.+)$/i);
    if (telegraphMatch) {
        return `https://api.telegra.ph/getPage/${telegraphMatch[1]}?return_content=true`;
    }
    return src;
}

async function queueChapterUrlsForOfflineCache(startIdx = currentChapterIdx, count = OFFLINE_CHAPTER_PREFETCH_COUNT) {
    if (typeof navigator === 'undefined' || !('serviceWorker' in navigator)) return;
    if (!Array.isArray(currentChapters) || currentChapters.length === 0) return;

    const maxIdx = Math.min(currentChapters.length - 1, Number(startIdx) + Number(count) - 1);
    const queue = [];
    for (let idx = Number(startIdx); idx <= maxIdx; idx += 1) {
        const chapter = currentChapters[idx];
        const sourceUrls = getChapterSourceUrls(chapter);
        sourceUrls.forEach((url) => {
            const cacheUrl = toServiceWorkerCacheUrl(url);
            if (cacheUrl) queue.push(cacheUrl);
        });
    }
    const uniqueUrls = Array.from(new Set(queue));
    if (uniqueUrls.length === 0) return;

    try {
        let controller = navigator.serviceWorker.controller;
        if (!controller) {
            const registration = await navigator.serviceWorker.ready;
            controller = registration.active || registration.waiting || registration.installing || null;
        }
        if (!controller) return;
        controller.postMessage({
            type: 'CACHE_CHAPTER_URLS',
            urls: uniqueUrls
        });
    } catch (e) {
        console.warn('Service worker chapter cache queue failed:', e);
    }
}

async function registerReaderServiceWorker() {
    if (typeof window === 'undefined') return;
    if (!('serviceWorker' in navigator)) return;
    if (!window.isSecureContext && location.hostname !== 'localhost') return;

    try {
        const reg = await navigator.serviceWorker.register('./sw.js');
        if (reg.waiting) {
            reg.waiting.postMessage({ type: 'SKIP_WAITING' });
        }
        reg.addEventListener('updatefound', () => {
            const installing = reg.installing;
            if (!installing) return;
            installing.addEventListener('statechange', () => {
                if (installing.state === 'installed' && navigator.serviceWorker.controller) {
                    showToast('\u0414\u043e\u0441\u0442\u0443\u043f\u043d\u043e \u043e\u0431\u043d\u043e\u0432\u043b\u0435\u043d\u0438\u0435 \u0447\u0438\u0442\u0430\u043b\u043a\u0438');
                }
            });
        });
        navigator.serviceWorker.addEventListener('controllerchange', () => {
            console.log('Service worker controller updated');
        });
    } catch (e) {
        console.warn('Service worker registration failed:', e);
    }
}

libraryFilter = safeGetLocal(LIBRARY_FILTER_KEY, LIBRARY_FILTERS.IN_PROGRESS);
if (!Object.values(LIBRARY_FILTERS).includes(libraryFilter)) {
    libraryFilter = LIBRARY_FILTERS.IN_PROGRESS;
}

// === Получение API URL из параметров URL ===
// Приоритет: 1) ?api=... из URL 2) window.location.origin (если бот и WebApp на одном хосте)
// На GitHub Pages (без ?api=) остаётся '' — функции, зависящие от API, корректно отключаются
const urlParams = new URLSearchParams(window.location.search);
const API_URL = urlParams.get('api') || (window.location.hostname.includes('github.io') ? '' : window.location.origin);

// === API Wrapper ===
async function apiFetch(url, options = {}) {
    if (typeof navigator !== 'undefined' && !navigator.onLine) {
        throw new Error('Offline');
    }
    options.headers = options.headers || {};
    if (typeof tg !== 'undefined' && tg.initData) {
        options.headers['Authorization'] = 'tma ' + tg.initData;
    }
    return fetch(url, options);
}

const TELEMETRY_DEDUP_WINDOW_MS = 60_000;
const MAX_CLIENT_ERROR_EVENTS_PER_SESSION = 20;
const TELEMETRY_ALLOWED_EVENTS = new Set([
    'client_runtime_error',
    'client_unhandled_rejection',
    'client_state_contract_violation',
    'client_chapter_open_ms'
]);
const _telemetryDedupCache = new Map();
let _sentClientErrorEvents = 0;
let _errorTelemetryBound = false;

function sendClientTelemetry(eventType, payload = {}) {
    if (!API_URL || !TELEMETRY_ALLOWED_EVENTS.has(eventType)) return;
    if (typeof fetch !== 'function') return;

    const body = JSON.stringify({
        event_type: eventType,
        payload,
        page_url: typeof window !== 'undefined' ? window.location.href : ''
    });

    const endpoint = `${API_URL}/api/telemetry`;
    const headers = { 'Content-Type': 'application/json' };

    // sendBeacon keeps telemetry delivery resilient during unload/navigation.
    if (typeof navigator !== 'undefined' && typeof navigator.sendBeacon === 'function') {
        try {
            const beaconPayload = new Blob([body], { type: 'application/json' });
            if (navigator.sendBeacon(endpoint, beaconPayload)) return;
        } catch (e) {}
    }

    apiFetch(endpoint, { method: 'POST', headers, body, keepalive: true }).catch(() => {});
}

function getModuleFromSource(source = '') {
    const src = String(source || '');
    if (!src) return 'unknown';
    if (src.includes('/webapp/')) {
        return src.split('/webapp/').pop().split('?')[0] || 'unknown';
    }
    if (src.includes('\\webapp\\')) {
        return src.split('\\webapp\\').pop().split('?')[0] || 'unknown';
    }
    return src.split('/').pop().split('?')[0] || 'unknown';
}

function toErrorObject(reason) {
    if (reason instanceof Error) return reason;
    if (typeof reason === 'string') return new Error(reason);
    try {
        return new Error(JSON.stringify(reason));
    } catch (e) {
        return new Error(String(reason));
    }
}

function getTelemetryFingerprint(eventType, errorObj, source, module) {
    return [
        eventType,
        String(errorObj?.message || ''),
        String(errorObj?.stack || '').slice(0, 200),
        source || '',
        module || ''
    ].join('|');
}

function getReaderStateSnapshot() {
    return {
        seriesId: currentSeries?.id || null,
        volume: currentVolume?.volume || null,
        chapterIdx: Number.isInteger(currentChapterIdx) ? currentChapterIdx : null,
        chaptersCount: Array.isArray(currentChapters) ? currentChapters.length : null,
        prefetchIdx: Number.isInteger(prefetchedChapter?.idx) ? prefetchedChapter.idx : null,
        hasAbortController: !!_chapterAbortController
    };
}

function reportClientError(eventType, reason, extra = {}) {
    if (_sentClientErrorEvents >= MAX_CLIENT_ERROR_EVENTS_PER_SESSION) return;
    const errorObj = toErrorObject(reason);
    const source = String(extra.source || '');
    const module = String(extra.module || getModuleFromSource(source || errorObj.stack || ''));
    const fingerprint = getTelemetryFingerprint(eventType, errorObj, source, module);
    const now = Date.now();
    const lastSentTs = _telemetryDedupCache.get(fingerprint) || 0;
    if (now - lastSentTs < TELEMETRY_DEDUP_WINDOW_MS) return;

    _telemetryDedupCache.set(fingerprint, now);
    _sentClientErrorEvents += 1;

    sendClientTelemetry(eventType, {
        message: String(errorObj.message || 'Unknown error').slice(0, 1200),
        stack: String(errorObj.stack || '').slice(0, 4000),
        source: source.slice(0, 512),
        module: module.slice(0, 256),
        line: Number.isFinite(extra.line) ? extra.line : null,
        column: Number.isFinite(extra.column) ? extra.column : null,
        state: getReaderStateSnapshot()
    });
}

function buildChapterOpenTelemetryContext(chapterIdx, usePrefetch) {
    const now = (typeof performance !== 'undefined' && performance.now) ? performance.now() : Date.now();
    return {
        startedAtMs: now,
        chapterIdx: Number.isInteger(chapterIdx) ? chapterIdx : null,
        usePrefetch: !!usePrefetch
    };
}

function reportChapterOpenTelemetry(chapter, telemetryContext, source) {
    if (!telemetryContext || !Number.isFinite(telemetryContext.startedAtMs)) return;
    const now = (typeof performance !== 'undefined' && performance.now) ? performance.now() : Date.now();
    const durationMs = now - telemetryContext.startedAtMs;
    if (!Number.isFinite(durationMs) || durationMs < 0 || durationMs > 120000) return;
    const chapterId = chapter && chapter.chapter !== undefined ? String(chapter.chapter) : '';
    sendClientTelemetry('client_chapter_open_ms', {
        module: 'reader.js',
        source: String(source || 'unknown'),
        duration_ms: Math.round(durationMs * 100) / 100,
        series_id: currentSeries?.id || '',
        volume: currentVolume?.volume ?? '',
        chapter: chapterId,
        chapter_idx: Number.isInteger(telemetryContext.chapterIdx) ? telemetryContext.chapterIdx : null,
        used_prefetch: !!telemetryContext.usePrefetch
    });
}

function bindGlobalErrorTelemetry() {
    if (_errorTelemetryBound) return;
    _errorTelemetryBound = true;

    window.addEventListener('error', (event) => {
        reportClientError('client_runtime_error', event.error || event.message, {
            source: event.filename,
            module: getModuleFromSource(event.filename || ''),
            line: event.lineno,
            column: event.colno
        });
    });

    window.addEventListener('unhandledrejection', (event) => {
        const reason = event.reason;
        reportClientError('client_unhandled_rejection', reason, {
            source: 'window.unhandledrejection',
            module: 'bootstrap'
        });
    });
}

function renderStateBlock(target, options = {}) {
    const container = typeof target === 'string' ? document.getElementById(target) : target;
    if (!container) return;

    const variant = String(options.variant || 'empty');
    const icon = typeof options.icon === 'string' && options.icon ? options.icon : (variant === 'error' ? '⚠️' : '📚');
    const title = String(options.title || '');
    const description = String(options.description || '');
    const actionLabel = String(options.actionLabel || '');
    const compact = !!options.compact;
    const onAction = typeof options.onAction === 'function' ? options.onAction : null;
    const hasAction = !!(actionLabel && onAction);

    const classes = ['empty-state', `state-${variant}`];
    if (compact) classes.push('compact');

    container.innerHTML = `
        <div class="${classes.join(' ')}">
            <div class="empty-icon">${icon}</div>
            ${title ? `<h3>${escapeHtml(title)}</h3>` : ''}
            ${description ? `<p>${escapeHtml(description)}</p>` : ''}
            ${hasAction ? `<button type="button" class="retry-btn state-action-btn">${escapeHtml(actionLabel)}</button>` : ''}
        </div>
    `;

    if (hasAction) {
        const actionBtn = container.querySelector('.state-action-btn');
        if (actionBtn) {
            actionBtn.addEventListener('click', () => {
                try {
                    onAction();
                } catch (err) {
                    console.warn('State action error:', err);
                }
            });
        }
    }
}

function updateNetworkStatusBanner({ initial = false } = {}) {
    const banner = document.getElementById('network-status');
    if (!banner) return;
    const isOffline = typeof navigator !== 'undefined' && !navigator.onLine;

    if (isOffline) {
        clearTimeout(_networkStatusHideTimer);
        banner.className = 'network-status-banner offline';
        banner.textContent = `⚠️ \u041d\u0435\u0442 \u0441\u0435\u0442\u0438. \u0427\u0430\u0441\u0442\u044c \u0444\u0443\u043d\u043a\u0446\u0438\u0439 \u0432\u0440\u0435\u043c\u0435\u043d\u043d\u043e \u043d\u0435\u0434\u043e\u0441\u0442\u0443\u043f\u043d\u0430.`;
        return;
    }

    if (initial) {
        banner.className = 'network-status-banner hidden';
        banner.textContent = '';
        return;
    }

    banner.className = 'network-status-banner online';
    banner.textContent = `✅ \u0421\u043e\u0435\u0434\u0438\u043d\u0435\u043d\u0438\u0435 \u0432\u043e\u0441\u0441\u0442\u0430\u043d\u043e\u0432\u043b\u0435\u043d\u043e`;
    clearTimeout(_networkStatusHideTimer);
    _networkStatusHideTimer = setTimeout(() => {
        if (typeof navigator !== 'undefined' && navigator.onLine) {
            banner.className = 'network-status-banner hidden';
            banner.textContent = '';
        }
    }, 2600);
}

function bindNetworkStatusListeners() {
    if (_networkStatusBound) return;
    _networkStatusBound = true;
    window.addEventListener('offline', () => updateNetworkStatusBanner());
    window.addEventListener('online', () => updateNetworkStatusBanner());
    updateNetworkStatusBanner({ initial: true });
}


function getChapterKey() {
    if (!currentSeries || !currentVolume || !currentChapters[currentChapterIdx]) return '';
    return `${currentSeries.id}_v${currentVolume.volume}_ch${currentChapters[currentChapterIdx].chapter}`;
}

function getScrollKey() {
    const key = getChapterKey();
    if (!key) return null;
    return `scroll_${currentSeries.id}_v${currentVolume.volume}_ch${key}`;
}

let _progressSyncTimer = null;

function saveScrollPosition() {
    const key = getScrollKey();
    if (!key) return;
    const el = document.getElementById('reader-content');
    if (!el) return;
    const pct = el.scrollTop / Math.max(1, el.scrollHeight - el.clientHeight);
        safeSetLocal(key, { pct, ts: Date.now() });
    saveLastRead();

    // Синхронизация с сервером (debounced — не чаще 1 раз в 3 секунды)
    if (API_URL && userId && currentSeries && currentVolume && currentChapters[currentChapterIdx]) {
        clearTimeout(_progressSyncTimer);
        _progressSyncTimer = setTimeout(() => {
            apiFetch(API_URL + '/api/progress', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    series_id: currentSeries.id,
                    volume_id: currentVolume.volume,
                    chapter_key: currentChapters[currentChapterIdx].chapter,
                    scroll_pos: pct
                })
            }).catch(e => console.warn('Progress sync error:', e));
        }, 3000);
    }
}

let _scrollResizeObserver = null; // Единственный ResizeObserver для скролла
let _scrollResizeTimeout = null; // Таймаут для очистки observer

function restoreScrollPosition() {
    // Убираем предыдущий observer и таймаут (если были — нет утечки)
    if (_scrollResizeObserver) {
        _scrollResizeObserver.disconnect();
        _scrollResizeObserver = null;
    }
    if (_scrollResizeTimeout) {
        clearTimeout(_scrollResizeTimeout);
        _scrollResizeTimeout = null;
    }

    // 1. Пробуем серверную
    const chIdx = currentChapters[currentChapterIdx];
    if (!chIdx) return;

    let pctToRestore = null;
    const serverBm = serverBookmarks.find(b => b.series_id === currentSeries.id);
    if (serverBm && String(serverBm.volume_id) === String(currentVolume.volume) && String(serverBm.chapter_key) === String(chIdx.chapter)) {
        pctToRestore = serverBm.scroll_pos;
    }

    // 2. Иначе локальную
    if (pctToRestore === null) {
        const key = getScrollKey();
        if (key) {
            const saved = safeGetLocal(key, null);
            if (saved) pctToRestore = saved.pct;
        }
    }

    if (pctToRestore === null) return;
    const el = document.getElementById('reader-content');
    if (!el) return;

    let hasRestored = false;
    _scrollResizeObserver = new ResizeObserver(() => {
        const maxScroll = el.scrollHeight - el.clientHeight;
        if (maxScroll > 0) {
            el.scrollTop = pctToRestore * maxScroll;
            hasRestored = true;
        }
    });
    
    _scrollResizeObserver.observe(el);
    
    _scrollResizeTimeout = setTimeout(() => {
        if (_scrollResizeObserver) {
            _scrollResizeObserver.disconnect();
            _scrollResizeObserver = null;
        }
        _scrollResizeTimeout = null;
        if (!hasRestored) {
            const maxScroll = el.scrollHeight - el.clientHeight;
            el.scrollTop = pctToRestore * maxScroll;
        }
    }, 5000);
}

function saveLastRead() {
    if (!currentSeries || !currentVolume) return;
    const ch = currentChapters[currentChapterIdx];
    if (!ch) return;
    const last = {
        seriesId: currentSeries.id,
        volume: currentVolume.volume,
        chapterIdx: currentChapterIdx,
        chapter: ch.chapter,
        ts: Date.now()
    };
    const all = safeGetLocal('reader_last_read', {});
    all[currentSeries.id] = last;
    safeSetLocal('reader_last_read', all);
}

function getLastRead(seriesId) {
    const all = safeGetLocal('reader_last_read', {});
    const local = all[seriesId];

    const serverBm = serverBookmarks.find(b => String(b.series_id) === String(seriesId));
    
    if (serverBm && local) {
        // Сравниваем время. Сервер возвращает строку TIMESTAMP.
        const serverTs = new Date(serverBm.updated_at + (serverBm.updated_at.includes('Z') ? '' : ' UTC')).getTime();
        const localTs = local.ts || 0;
        
        if (serverTs > localTs) {
            console.log("Using newer Server progress for", seriesId);
            return {
                seriesId: seriesId,
                volume: serverBm.volume_id,
                chapter: serverBm.chapter_key,
                scroll: serverBm.scroll_pos,
                isServer: true
            };
        } else {
            console.log("Using newer Local progress for", seriesId);
            return local;
        }
    }

    if (serverBm) {
        return {
            seriesId: seriesId,
            volume: serverBm.volume_id,
            chapter: serverBm.chapter_key,
            scroll: serverBm.scroll_pos,
            isServer: true
        };
    }
    return local || null;
}

// === Прогресс-бар чтения ===
let progressBarEl = null;

function initProgressBar() {
    if (!progressBarEl) {
        progressBarEl = document.createElement('div');
        progressBarEl.className = 'reading-progress-bar';
        progressBarEl.style.width = '0%';
        document.body.appendChild(progressBarEl);
    }
}

function updateProgressBar(el) {
    if (!progressBarEl) return;
    if (!el) el = document.getElementById('reader-content');
    if (!el) return;
    const max = el.scrollHeight - el.clientHeight;
    const pct = max > 0 ? (el.scrollTop / max) * 100 : 0;
    progressBarEl.style.width = Math.min(100, pct) + '%';
}

// ==========================================================================
// ЗАГРУЗКА ДАННЫХ
// ==========================================================================

let serverBookmarks = []; // Хранит загруженные закладки

async function loadData() {
    console.log("Starting loadData...");
    let hadNetworkFailure = false;

    // Вспомогательная функция для таймаута, если AbortSignal.timeout не поддерживается
    const getTimeoutSignal = (ms) => {
        if (AbortSignal.timeout) return AbortSignal.timeout(ms);
        const controller = new AbortController();
        setTimeout(() => controller.abort(), ms);
        return controller.signal;
    };

    // 1. Пытаемся загрузить прогресс (если есть API)
    if (API_URL && userId) {
        console.log("Fetching progress from API...");
        try {
            const bResp = await apiFetch(API_URL + '/api/progress', { signal: getTimeoutSignal(5000) });
            if (bResp.ok) {
                const bData = await bResp.json();
                serverBookmarks = bData.bookmarks || [];
                console.log("Bookmarks loaded:", serverBookmarks.length);
            } else {
                console.warn("Progress API returned status:", bResp.status);
            }
        } catch (e) {
            console.warn('Bookmarks load warning:', e);
        }
    }

    // 2. Пытаемся загрузить данные из API
    if (API_URL) {
        console.log("Fetching reader data from API:", API_URL + '/api/reader');
        try {
            const cachedSnapshot = getCachedReaderApiSnapshot();
            const headers = {};
            if (cachedSnapshot?.etag) {
                headers['If-None-Match'] = cachedSnapshot.etag;
            }

            const resp = await apiFetch(API_URL + '/api/reader', {
                signal: getTimeoutSignal(10000),
                headers
            });
            let apiData = null;
            if (resp.status === 304) {
                apiData = cachedSnapshot?.payload || null;
                if (apiData) {
                    console.log("Reader API returned 304; using cached snapshot.");
                } else {
                    console.warn("Reader API returned 304, but no cached snapshot found.");
                }
            } else if (resp.ok) {
                apiData = await resp.json();
                const etag = resp.headers.get('ETag') || '';
                saveReaderApiSnapshot(apiData, etag);
                console.log("Data loaded from API, series count:", apiData.series?.length);
            } else {
                console.warn("Reader API returned status:", resp.status);
                hadNetworkFailure = true;
            }

            if (apiData) {
                allData = apiData;
                if (allData.admin_ids) {
                    adminIds = allData.admin_ids.map(id => String(id));
                }
                if (allData.series && allData.series.length > 0) {
                    renderSeriesList();
                    renderContinueReading();
                    handleStartParam();
                    return;
                }
                console.log("API returned empty series list, falling back to JSON...");
            }
        } catch (e) {
            console.warn('API fetch error or timeout:', e);
            hadNetworkFailure = true;
        }
    } else {
        console.log("No API_URL configured, skipping API fetch.");
    }

    // 3. Фолбэк на статический JSON
    console.log("Fetching fallback chapters_data.json...");
    try {
        const resp = await fetch('chapters_data.json?v=' + Date.now(), { signal: getTimeoutSignal(5000) });
        if (resp.ok) {
            allData = await resp.json();
            console.log("Data loaded from fallback JSON, series count:", allData.series?.length);
            if (allData.series && allData.series.length > 0) {
                renderSeriesList();
                renderContinueReading();
                handleStartParam(); // ★ Deep link handling (Phase 5)
                return;
            }
        } else {
            console.warn("Fallback JSON fetch failed with status:", resp.status);
            hadNetworkFailure = true;
        }
    } catch (e) {
        console.error('Fallback JSON fetch error:', e);
        hadNetworkFailure = true;
    }

    console.log("All data sources failed or empty, showing empty state.");
    if (hadNetworkFailure || (typeof navigator !== 'undefined' && !navigator.onLine)) {
        showNetworkState();
        return;
    }
    showEmptyState();
}

function showEmptyState() {
    renderStateBlock('series-list', {
        icon: '\uD83D\uDCDA',
        title: '\u0411\u0438\u0431\u043b\u0438\u043e\u0442\u0435\u043a\u0430 \u043f\u0443\u0441\u0442\u0430',
        description: '\u0414\u0430\u043d\u043d\u044b\u0435 \u043f\u043e\u043a\u0430 \u043d\u0435 \u0437\u0430\u0433\u0440\u0443\u0436\u0435\u043d\u044b. \u0414\u043e\u0431\u0430\u0432\u044c\u0442\u0435 \u0433\u043b\u0430\u0432\u044b \u0447\u0435\u0440\u0435\u0437 \u0431\u043e\u0442\u0430 \u0438\u043b\u0438 \u0437\u0430\u0433\u0440\u0443\u0437\u0438\u0442\u0435 chapters_data.json.'
    });
}

function showNetworkState() {
    renderStateBlock('series-list', {
        variant: 'error',
        icon: '\uD83C\uDF10',
        title: '\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u0437\u0430\u0433\u0440\u0443\u0437\u0438\u0442\u044c \u0434\u0430\u043d\u043d\u044b\u0435',
        description: '\u041f\u0440\u043e\u0432\u0435\u0440\u044c\u0442\u0435 \u0441\u043e\u0435\u0434\u0438\u043d\u0435\u043d\u0438\u0435 \u0441 \u0441\u0435\u0442\u044c\u044e \u0438 \u043f\u043e\u043f\u0440\u043e\u0431\u0443\u0439\u0442\u0435 \u0435\u0449\u0435 \u0440\u0430\u0437.',
        actionLabel: '\u041f\u043e\u0432\u0442\u043e\u0440\u0438\u0442\u044c',
        onAction: () => loadData()
    });
}

function handleStartParam() {
    const start = tg.initDataUnsafe?.start_param || urlParams.get('tgWebAppStartParam');
    if (!start) return;

    // chapter_{series_id}_{volume_num}_{chapter_num/key}
    const match = start.match(/^chapter_([^_]+)_([^_]+)_([^_]+)$/);
    if (match) {
        const [, sId, vNum, cKey] = match;
        const series = allData.series.find(s => String(s.id) === String(sId));
        if (!series) return;
        
        currentSeries = series;
        const vol = series.volumes.find(v => String(v.volume) === String(vNum));
        if (!vol) return;
        
        currentVolume = vol;
        currentChapters = vol.chapters || [];
        const cIdx = currentChapters.findIndex(c => String(c.chapter) === String(cKey));
        
        if (cIdx !== -1) {
            openChapter(cIdx);
        } else {
            // Fallback: if not found by number, maybe first chapter?
            if (currentChapters.length > 0) openChapter(0);
        }
    }
}

// ==========================================================================
// РЕНДЕР ЭКРАНОВ
// ==========================================================================

function renderSeriesList() {
    assertReaderState('renderSeriesList:start');
    const container = document.getElementById('series-list');

    if (!allData.series || allData.series.length === 0) {
        showEmptyState();
        return;
    }

    container.innerHTML = allData.series.map((s, i) => {
        const totalCh = s.volumes.reduce((sum, v) => sum + (v.chapters || []).length, 0);
        const readCount = s.volumes.reduce((sum, v) => {
            return sum + (v.chapters || []).filter(c => isRead(s.id, v.volume, c.chapter)).length;
        }, 0);
        const progress = totalCh > 0 ? Math.round((readCount / totalCh) * 100) : 0;
        const progressText = `${readCount}/${totalCh || 0}`;

        // Бейдж «Продолжить»
        const lastRead = getLastRead(s.id);
        let continueBadge = '';
        if (lastRead) {
            continueBadge = `<span class="continue-badge">▶ Продолжить · Гл. ${lastRead.chapter}</span>`;
        }
        const quickAction = lastRead
            ? `<button class="series-action-btn primary" onclick="jumpToLastRead(event, '${s.id}')">Продолжить</button>`
            : `<button class="series-action-btn" onclick="jumpToLatestChapter(event, '${s.id}')">К последней</button>`;

        const editBtns = isAdminMode ? `
            <button class="admin-edit-btn" title="Переименовать" onclick="renameItem('series_${s.id}'); event.stopPropagation();">&#9998;</button>
            <button class="admin-reset-btn" title="Сброс имени" onclick="resetCustomName('series_${s.id}'); event.stopPropagation();">&#8635;</button>
        ` : '';
        const customBadge = isAdminMode ? `<span class="custom-name-badge">серия</span>` : '';

        // Cover image support (Batch 3)
        const coverEl = s.cover_url
            ? `<img src="${s.cover_url}" class="series-cover-img" alt="${escapeHtml(s.title)}" loading="lazy">`
            : `<div class="series-icon">${['📖', '📕', '📗', '📘', '📙'][i % 5]}</div>`;

        return `
        <div class="series-card" onclick="selectSeries('${s.id}')">
            ${coverEl}
            <div class="series-info">
                <h3>${escapeHtml(s.title)}${customBadge}${editBtns}</h3>
                <p>${s.volumes.length} том(ов) &middot; ${totalCh} глав</p>
                <p class="series-progress-text">Прочитано: ${progressText} (${progress}%)</p>
                ${continueBadge}
                <div class="series-actions">${quickAction}</div>
            </div>
            <span class="series-arrow">&rsaquo;</span>
        </div>`;
    }).join('');
}

function selectSeries(seriesId) {
    assertReaderState('selectSeries:start');
    currentSeries = allData.series.find(s => s.id === seriesId);
    if (!currentSeries) return;

    document.getElementById('chapters-title').textContent = currentSeries.title; // textContent escapes HTML
    renderVolumeTabs();

    // Восстанавливаем последнюю читаемую главу или первый том
    const lastRead = getLastRead(seriesId);
    if (lastRead) {
        const vol = currentSeries.volumes.find(v => String(v.volume) === String(lastRead.volume));
        if (vol) {
            selectVolume(lastRead.volume);
            showScreen('chapters');
            return;
        }
    }

    if (currentSeries.volumes.length > 0) {
        selectVolume(currentSeries.volumes[0].volume);
    }

    showScreen('chapters');
}

function openSeriesChapter(seriesId, volumeId, chapterKey, fallbackToLatest = false) {
    const series = allData.series.find((s) => String(s.id) === String(seriesId));
    if (!series || !Array.isArray(series.volumes) || series.volumes.length === 0) return;

    currentSeries = series;
    const title = document.getElementById('chapters-title');
    if (title) {
        title.textContent = currentSeries.title;
    }

    renderVolumeTabs();

    let targetVolume = series.volumes.find((v) => String(v.volume) === String(volumeId));
    if (!targetVolume && fallbackToLatest) {
        targetVolume = series.volumes[series.volumes.length - 1];
    }
    if (!targetVolume) {
        selectSeries(seriesId);
        return;
    }

    selectVolume(targetVolume.volume);
    showScreen('chapters');

    const chapters = Array.isArray(targetVolume.chapters) ? targetVolume.chapters : [];
    let targetIdx = chapters.findIndex((ch) => String(ch.chapter) === String(chapterKey));
    if (targetIdx === -1 && fallbackToLatest) {
        targetIdx = chapters.length - 1;
    }

    if (targetIdx >= 0) {
        openChapter(targetIdx);
    }
}

function jumpToLatestChapter(event, seriesId) {
    if (event && typeof event.stopPropagation === 'function') {
        event.stopPropagation();
    }
    const series = allData.series.find((s) => String(s.id) === String(seriesId));
    if (!series || !Array.isArray(series.volumes) || series.volumes.length === 0) {
        return;
    }

    const targetVolume = series.volumes[series.volumes.length - 1];
    const chapters = Array.isArray(targetVolume.chapters) ? targetVolume.chapters : [];
    if (chapters.length === 0) {
        selectSeries(seriesId);
        return;
    }

    const lastChapter = chapters[chapters.length - 1];
    openSeriesChapter(seriesId, targetVolume.volume, lastChapter.chapter, true);
}

function jumpToLastRead(event, seriesId) {
    if (event && typeof event.stopPropagation === 'function') {
        event.stopPropagation();
    }
    const lastRead = getLastRead(seriesId);
    if (!lastRead) {
        jumpToLatestChapter(null, seriesId);
        return;
    }

    openSeriesChapter(seriesId, lastRead.volume, lastRead.chapter, true);
}

function renderVolumeTabs() {
    const tabs = document.getElementById('volume-tabs');

    if (currentSeries.volumes.length <= 1) {
        tabs.style.display = 'none';
        return;
    }

    tabs.style.display = 'flex';
    tabs.innerHTML = currentSeries.volumes.map(v => {
        const volName = v.custom_name || `Том ${v.volume}`;
        const hasCustom = !!v.custom_name;
        const editBtns = isAdminMode ? `
            <button class="admin-edit-btn" title="Переименовать" onclick="renameItem('vol_${currentSeries.id}_${v.volume}'); event.stopPropagation();">&#9998;</button>
            ${hasCustom ? `<button class="admin-reset-btn" title="Сброс" onclick="resetCustomName('vol_${currentSeries.id}_${v.volume}'); event.stopPropagation();">&#8635;</button>` : ''}
        ` : '';
        return `
        <button class="vol-tab" data-vol="${v.volume}" onclick="selectVolume(${v.volume})">
            ${hasCustom && isAdminMode ? '<span class="custom-name-badge">кастом</span>' : ''}${volName}${editBtns}
        </button>`;
    }).join('');
}

function selectVolume(volNum) {
    assertReaderState('selectVolume:start');
    currentVolume = currentSeries.volumes.find(v => v.volume === volNum);
    if (!currentVolume) return;

    document.querySelectorAll('.vol-tab').forEach(t => {
        t.classList.toggle('active', parseInt(t.dataset.vol) === volNum);
    });

    renderChaptersList();
}

function renderChaptersList() {
    assertReaderState('renderChaptersList:start');
    cleanupChapterDnD();
    const container = document.getElementById('chapters-list');
    currentChapters = currentVolume.chapters;

    if (currentChapters.length === 0) {
        renderStateBlock(container, {
            icon: '\uD83D\uDCC2',
            title: '\u041d\u0435\u0442 \u0433\u043b\u0430\u0432',
            description: '\u0412 \u044d\u0442\u043e\u043c \u0442\u043e\u043c\u0435 \u043f\u043e\u043a\u0430 \u043d\u0435\u0442 \u0433\u043b\u0430\u0432.'
        });
        return;
    }

    // Определяем последнюю читаемую главу для подсветки
    const lastRead = getLastRead(currentSeries.id);
    const lastChapter = lastRead?.volume === currentVolume.volume ? lastRead.chapter : null;

    container.innerHTML = currentChapters.map((ch, idx) => {
        const readClass = isRead(currentSeries.id, currentVolume.volume, ch.chapter) ? 'read' : '';
        const chapName = ch.custom_name || `Глава ${ch.chapter}`;
        const hasCustom = !!ch.custom_name;
        const linkBtn = isAdminMode ? `<button class="admin-link-btn" title="Редактировать ссылку" onclick="openEditUrlModal(${idx}); event.stopPropagation();">&#128279;</button>` : '';
        const editBtns = isAdminMode ? `
            <button class="admin-edit-btn" title="Переименовать" onclick="renameItem('chap_${currentSeries.id}_${currentVolume.volume}_${ch.chapter}'); event.stopPropagation();">&#9998;</button>
            ${hasCustom ? `<button class="admin-reset-btn" title="Сброс на дефолт" onclick="resetCustomName('chap_${currentSeries.id}_${currentVolume.volume}_${ch.chapter}'); event.stopPropagation();">&#8635;</button>` : ''}
        ` : '';
        const customBadge = (isAdminMode && hasCustom) ? '<span class="custom-name-badge">кастом</span>' : '';
        const isCurrent = lastChapter && String(ch.chapter) === String(lastChapter);

        return `
        <div class="chapter-item ${readClass}${isCurrent ? ' current-chapter' : ''}" data-chapter-idx="${idx}" ${isAdminMode ? 'draggable="true"' : ''} onclick="openChapter(${idx})">
            ${isAdminMode ? '<div class="drag-handle" title="Перетащить">⠿</div>' : ''}
            <div class="chapter-num">${idx + 1}</div>
            <div class="chapter-name">${chapName}${customBadge}${linkBtn}${editBtns}</div>
            ${isCurrent ? '<span style="font-size:12px;color:var(--accent);font-weight:600;">◄</span>' : ''}
            <span class="chapter-read-mark">✓</span>
        </div>`;
    }).join('');

    // Bulk upload button (admin only)
    if (isAdminMode && API_URL) {
        container.innerHTML += `<button class="admin-bulk-btn" onclick="openBulkModal()">📦 Массовое добавление глав</button>`;
    }

    // Init drag-n-drop for admin
    if (isAdminMode) {
        initChapterDnD();
    }
}

// ==========================================================================
// ЧТЕНИЕ
// ==========================================================================

function openChapter(idx, usePrefetch = false) {
    assertReaderState('openChapter:before_set_idx');
    currentChapterIdx = idx;
    assertReaderState('openChapter:after_set_idx');
    const chapter = currentChapters[idx];
    if (!chapter) return;
    
    // Проверка что chapter имеет необходимые свойства
    if (!chapter.chapter) {
        console.warn('Chapter object missing required properties:', chapter);
        return;
    }

    // Smooth transition: fade out
    const content = document.getElementById('reader-content');
    if (content) content.classList.add('loading');

    // Update UI
    const titleHeader = document.getElementById('chapter-title-header');
    if (titleHeader) titleHeader.textContent = chapter.custom_name || `Глава ${chapter.chapter}`;
    
    updateNavButtons();
    if (currentSeries && currentVolume) {
        markAsRead(currentSeries.id, currentVolume.volume, chapter.chapter);
    }
    const telemetryContext = buildChapterOpenTelemetryContext(idx, usePrefetch);
    loadChapterContent(chapter, usePrefetch, telemetryContext);
    queueChapterUrlsForOfflineCache(currentChapterIdx, OFFLINE_CHAPTER_PREFETCH_COUNT);

    initProgressBar();
    if (progressBarEl) progressBarEl.style.width = '0%';
    
    // Auto-close switcher
    const switcher = document.getElementById('quick-switcher');
    if (switcher) switcher.classList.add('hidden');

    showScreen('reader');

    if (API_URL) {
        loadLikes();
        loadReactions();
        loadComments();
        document.getElementById('social-section').style.display = 'block';
    } else {
        document.getElementById('social-section').style.display = 'none';
    }
}

// === Prefetch cache ===
let prefetchedChapter = { idx: -1, html: null };
let _prefetchingIdx = -1;
let _chapterAbortController = null; // AbortController для отмены загрузки при смене главы
const _stateContractWarnings = new Set();

function reportStateContractViolation(context, issue, details = {}) {
    const key = `${context}:${issue}`;
    if (_stateContractWarnings.has(key)) return;
    _stateContractWarnings.add(key);
    console.warn(`[state-contract] ${issue} (${context})`, details);
    sendClientTelemetry('client_state_contract_violation', {
        context,
        issue,
        details,
        state: getReaderStateSnapshot()
    });
}

function assertReaderState(context = 'unknown') {
    if (!Array.isArray(currentChapters)) {
        reportStateContractViolation(context, 'currentChapters_not_array', { type: typeof currentChapters });
        currentChapters = [];
    }

    if (!Number.isInteger(currentChapterIdx) || currentChapterIdx < 0) {
        reportStateContractViolation(context, 'currentChapterIdx_invalid', { value: currentChapterIdx });
        currentChapterIdx = 0;
    }

    if (currentSeries && (typeof currentSeries !== 'object' || currentSeries.id === undefined)) {
        reportStateContractViolation(context, 'currentSeries_invalid', { valueType: typeof currentSeries });
        currentSeries = null;
    }

    if (currentSeries && !Array.isArray(currentSeries.volumes)) {
        reportStateContractViolation(context, 'currentSeries_volumes_invalid', {});
        currentSeries = null;
    }

    if (currentVolume && (typeof currentVolume !== 'object' || currentVolume.volume === undefined)) {
        reportStateContractViolation(context, 'currentVolume_invalid', { valueType: typeof currentVolume });
        currentVolume = null;
    }

    if (currentVolume && !Array.isArray(currentVolume.chapters)) {
        reportStateContractViolation(context, 'currentVolume_chapters_invalid', {});
        currentVolume.chapters = [];
    }

    if (
        currentSeries &&
        currentVolume &&
        Array.isArray(currentSeries.volumes) &&
        !currentSeries.volumes.some((v) => String(v.volume) === String(currentVolume.volume))
    ) {
        reportStateContractViolation(context, 'series_volume_mismatch', {
            seriesId: currentSeries.id,
            volume: currentVolume.volume
        });
        currentVolume = null;
        currentChapters = [];
        currentChapterIdx = 0;
    }

    if (
        !prefetchedChapter ||
        typeof prefetchedChapter !== 'object' ||
        !Number.isInteger(prefetchedChapter.idx)
    ) {
        reportStateContractViolation(context, 'prefetchedChapter_invalid', { valueType: typeof prefetchedChapter });
        prefetchedChapter = { idx: -1, html: null };
    }

    if (prefetchedChapter.html !== null && typeof prefetchedChapter.html !== 'string') {
        reportStateContractViolation(context, 'prefetchedChapter_html_invalid', { valueType: typeof prefetchedChapter.html });
        prefetchedChapter.html = null;
    }

    if (_chapterAbortController && typeof _chapterAbortController.abort !== 'function') {
        reportStateContractViolation(context, 'abortController_invalid', { valueType: typeof _chapterAbortController });
        _chapterAbortController = null;
    }

    if (currentChapters.length === 0) {
        if (currentChapterIdx !== 0) {
            reportStateContractViolation(context, 'currentChapterIdx_without_chapters', { value: currentChapterIdx });
            currentChapterIdx = 0;
        }
        return;
    }

    if (currentChapterIdx >= currentChapters.length) {
        reportStateContractViolation(context, 'currentChapterIdx_out_of_bounds', {
            value: currentChapterIdx,
            chaptersCount: currentChapters.length
        });
        currentChapterIdx = currentChapters.length - 1;
    }
}

function loadChapterContent(chapter, usePrefetch = false, telemetryContext = null) {
    assertReaderState('loadChapterContent:start');
    const container = document.getElementById('reader-text');
    const chapterTelemetryContext = telemetryContext || buildChapterOpenTelemetryContext(currentChapterIdx, usePrefetch);

    // Отменяем предыдущую загрузку, если была
    if (_chapterAbortController) {
        _chapterAbortController.abort();
        _chapterAbortController = null;
    }

    // Check if we have prefetched content for this chapter
    if (usePrefetch && prefetchedChapter.idx === currentChapterIdx && prefetchedChapter.html) {
        renderLoadedContent(container, prefetchedChapter.html, chapter, chapterTelemetryContext, 'prefetch');
        prefetchedChapter = { idx: -1, html: null };
        return;
    }

    let urlsToLoad = [];
    if (chapter.urls && chapter.urls.length > 0) {
        urlsToLoad = [...chapter.urls];
    } else if (chapter.url) {
        urlsToLoad = [chapter.url];
    }

    // Prioritize Telegraph over Teletype
    const telegraphUrls = urlsToLoad.filter(u => u.includes('telegra.ph'));
    if (telegraphUrls.length > 0) {
        urlsToLoad = telegraphUrls; // Загружаем все части телеграфа последовательно
    } else {
        const teletypeUrls = urlsToLoad.filter(u => u.includes('teletype.in'));
        if (teletypeUrls.length > 0) {
            urlsToLoad = [teletypeUrls[0]];
        }
    }

    let signal;
    if (urlsToLoad.length > 0) {
        // ★ Skeleton Loader
        container.innerHTML = `
            <div class="skeleton-loader">
                <div class="skeleton-line" style="width:100%"></div>
                <div class="skeleton-line" style="width:95%"></div>
                <div class="skeleton-line" style="width:85%"></div>
                <div class="skeleton-line" style="width:90%"></div>
                <div class="skeleton-line" style="width:75%"></div>
                <div class="skeleton-line" style="width:98%"></div>
                <div class="skeleton-line" style="width:92%"></div>
            </div>
        `;

        _chapterAbortController = new AbortController();
        signal = _chapterAbortController.signal;
        // Добавляем таймаут 15 секунд
        setTimeout(() => {
            if (_chapterAbortController && !_chapterAbortController.signal.aborted) {
                _chapterAbortController.abort(new Error('Timeout'));
            }
        }, 15000);

        const loadPromises = urlsToLoad.map(async (u) => {
            // Teletype — используем iframe
            if (u.includes('teletype.in')) {
                return `<iframe src="${u}" class="teletype-iframe" frameborder="0" style="width:100%;min-height:85vh;border:none;border-radius:8px;margin-bottom:20px;" loading="lazy"></iframe>`;
            }
            const telegraphMatch = u.match(/telegra\.ph\/(.+)/);
            if (telegraphMatch) {
                try {
                    const resp = await fetch(`https://api.telegra.ph/getPage/${telegraphMatch[1]}?return_content=true`, { signal });
                    const data = await resp.json();
                    if (data.ok && data.result && data.result.content) {
                        return renderTelegraphContent(data.result.content);
                    }
                } catch (e) {
                    if (e.name === 'AbortError') throw e;
                    console.warn("Telegraph API err", e);
                }
            }
            return `<iframe src="${u}" frameborder="0" style="width:100%;min-height:80vh;border:none;border-radius:8px;margin-bottom:20px;"></iframe>`;
        });

        Promise.all(loadPromises).then(results => {
            if (signal.aborted || chapter !== currentChapters[currentChapterIdx]) return;
            renderLoadedContent(container, results.join(''), chapter, chapterTelemetryContext, 'network');
        }).catch(err => {
            if (err.name === 'AbortError') return;
            console.error('Chapter load failed:', err);
            renderStateBlock(container, {
                variant: 'error',
                icon: '\u274C',
                title: '\u041e\u0448\u0438\u0431\u043a\u0430 \u0437\u0430\u0433\u0440\u0443\u0437\u043a\u0438 \u0433\u043b\u0430\u0432\u044b',
                description: '\u041f\u0440\u043e\u0432\u0435\u0440\u044c\u0442\u0435 \u0441\u043e\u0435\u0434\u0438\u043d\u0435\u043d\u0438\u0435 \u0438 \u043f\u043e\u043f\u0440\u043e\u0431\u0443\u0439\u0442\u0435 \u0441\u043d\u043e\u0432\u0430.',
                actionLabel: '\u041f\u043e\u0432\u0442\u043e\u0440\u0438\u0442\u044c',
                onAction: () => loadChapterContent(currentChapters[currentChapterIdx])
            });
        });

    } else if (chapter.text) {
        const paragraphs = chapter.text.split('\n\n').map(p => `<p>${p.trim()}</p>`).join('');
        renderLoadedContent(container, paragraphs, chapter, chapterTelemetryContext, 'inline_text');
    } else {
        container.innerHTML = `
            <div class="empty-state" style="margin-top:20vh;">
                <div class="empty-icon" style="font-size:4rem;opacity:0.3;">⏳</div>
                <h3 style="margin-top:1.5rem;font-weight:700;">Глава еще не загружена</h3>
                <p style="opacity:0.6;max-width:300px;margin:1rem auto;">Эта часть главы еще находится в переводе или ожидает проверки администратором.</p>
                ${isAdminMode ? `<button class="admin-primary-btn" style="margin-top:2rem;" onclick="openEditUrlModal(currentChapterIdx)">🔗 Добавить ссылку</button>` : ''}
            </div>
        `;
        reportChapterOpenTelemetry(chapter, chapterTelemetryContext, 'empty');
    }

    document.getElementById('reader-content').scrollTop = 0;
}

function renderLoadedContent(container, html, chapter, telemetryContext = null, source = 'unknown') {
    container.innerHTML = html;

    // Smooth transition: fade in (remove loading class)
    const contentArea = document.getElementById('reader-content');
    if (contentArea) {
        setTimeout(() => contentArea.classList.remove('loading'), 100);
    }

    // --- Расчет примерного времени чтения ---
    const textContent = container.innerText;
    const wordCount = textContent.split(/\s+/).filter(w => w.length > 0).length;
    if (wordCount > 50) {
        const readingTimeMins = Math.max(1, Math.ceil(wordCount / 200)); 
        const timeBadge = document.createElement('div');
        timeBadge.className = 'reading-time-badge';
        timeBadge.innerHTML = `<svg class="icon-xs" viewBox="0 0 24 24" style="vertical-align:-2px; margin-right:4px;"><circle cx="12" cy="12" r="10" fill="none" stroke="currentColor" stroke-width="2"/><polyline points="12 6 12 12 16 14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>~${readingTimeMins} мин. чтения`;
        container.insertBefore(timeBadge, container.firstChild);
    }

    initLightbox();
    buildToC();
    initImageFadeIn(container);
    applyIframeDarkMode();
    restoreScrollPosition();
    reportChapterOpenTelemetry(chapter, telemetryContext, source);
}

// ★ Skeleton Loader (пункт 5)
function buildSkeletonLoader() {
    let lines = '';
    const widths = [100, 92, 85, 95, 70, 88, 96, 80, 60, 90, 100, 75, 88, 50];
    for (let i = 0; i < widths.length; i++) {
        lines += `<div class="skeleton-line" style="width:${widths[i]}%;animation-delay:${i * 0.05}s"></div>`;
    }
    return `<div class="skeleton-loader">${lines}</div>`;
}

// ★ Image Fade-in (пункт 6)
function initImageFadeIn(container) {
    const imgs = container.querySelectorAll('img');
    imgs.forEach(img => {
        const handleLoad = () => {
            img.classList.remove('img-loading');
            img.classList.add('img-loaded');
        };
        
        if (img.complete) {
            handleLoad();
        } else {
            img.classList.add('img-loading');
            img.addEventListener('load', handleLoad, { once: true });
            img.addEventListener('error', handleLoad, { once: true }); // Снимаем блюр даже если ошибка загрузки
        }
    });
}

// ★ Smart Dark Mode для Teletype iframes (пункт 7) - Отключено (вызывало негатив)
function applyIframeDarkMode() {
    const iframes = document.querySelectorAll('.teletype-iframe');
    const isDark = settings.theme === 'dark' || settings.theme === 'amoled';
    iframes.forEach(f => {
        f.style.filter = isDark ? 'brightness(0.7) contrast(1.1)' : 'none';
    });
}

// ★ Silent Prefetch следующей главы (пункт 4)
function prefetchNextChapter() {
    const nextIdx = currentChapterIdx + 1;
    if (nextIdx >= currentChapters.length) return;
    if (prefetchedChapter.idx === nextIdx || _prefetchingIdx === nextIdx) return; // уже загружено или в процессе

    const chapter = currentChapters[nextIdx];
    if (!chapter) return;

    _prefetchingIdx = nextIdx;

    let urlsToLoad = [];
    if (chapter.urls && chapter.urls.length > 0) {
        urlsToLoad = [...chapter.urls];
    } else if (chapter.url) {
        urlsToLoad = [chapter.url];
    }

    const telegraphUrls = urlsToLoad.filter(u => u.includes('telegra.ph'));
    if (telegraphUrls.length > 0) {
        urlsToLoad = telegraphUrls;
    } else {
        const teletypeUrls = urlsToLoad.filter(u => u.includes('teletype.in'));
        if (teletypeUrls.length > 0) urlsToLoad = [teletypeUrls[0]];
    }

    if (urlsToLoad.length > 0) {
        const prefetchAbortController = new AbortController();
        setTimeout(() => prefetchAbortController.abort(), 20000); // 20s timeout
        
        const loadPromises = urlsToLoad.map(async (u) => {
            if (u.includes('teletype.in')) {
                return `<iframe src="${u}" class="teletype-iframe" frameborder="0" style="width:100%;min-height:85vh;border:none;border-radius:8px;margin-bottom:20px;" loading="lazy"></iframe>`;
            }
            const telegraphMatch = u.match(/telegra\.ph\/(.+)/);
            if (telegraphMatch) {
                try {
                    const resp = await fetch(`https://api.telegra.ph/getPage/${telegraphMatch[1]}?return_content=true`, { signal: prefetchAbortController.signal });
                    const data = await resp.json();
                    if (data.ok && data.result && data.result.content) {
                        const html = renderTelegraphContent(data.result.content);
                        // ★ Smart Image Pre-loading (Phase 4)
                        preloadImagesFromHtml(html);
                        return html;
                    }
                } catch (e) {
                    console.warn('Prefetch Telegraph err', e);
                }
            }
            return '';
        });
        Promise.all(loadPromises).then(results => {
            prefetchedChapter = { idx: nextIdx, html: results.join('') };
            _prefetchingIdx = -1;
            console.log('✅ Prefetched chapter (with images)', nextIdx + 1);
        }).catch(() => { _prefetchingIdx = -1; });
    } else if (chapter.text) {
        const paragraphs = chapter.text.split('\n\n').map(p => `<p>${p.trim()}</p>`).join('');
        prefetchedChapter = { idx: nextIdx, html: paragraphs };
        _prefetchingIdx = -1;
    } else {
        _prefetchingIdx = -1;
    }
}

// Helper for pre-loading images into browser cache
function preloadImagesFromHtml(html) {
    const tmp = document.createElement('div');
    tmp.innerHTML = html;
    const imgs = tmp.querySelectorAll('img');
    imgs.forEach(img => {
        const preloader = new Image();
        preloader.src = img.src;
    });
}

function renderTelegraphContent(nodes) {
    if (!Array.isArray(nodes)) return '';
    return nodes.map(node => {
        if (typeof node === 'string') return node;
        if (!node.tag) return '';

        const children = node.children ? renderTelegraphContent(node.children) : '';
        const attrs = node.attrs ? Object.entries(node.attrs).map(([k, v]) => `${k}="${v}"`).join(' ') : '';

        if (node.tag === 'img' || node.tag === 'figure') {
            if (node.tag === 'img') {
                const src = node.attrs?.src || '';
                const fullSrc = src.startsWith('/') ? `https://telegra.ph${src}` : src;
                return `<img src="${fullSrc}" style="max-width:100%;border-radius:8px;margin:12px 0;" loading="lazy">`;
            }
            return `<figure>${children}</figure>`;
        }

        return `<${node.tag}${attrs ? ' ' + attrs : ''}>${children}</${node.tag}>`;
    }).join('');
}

function navigateChapter(delta) {
    // Сохраняем позицию перед переходом
    saveScrollPosition();
    const newIdx = currentChapterIdx + delta;
    if (newIdx >= 0 && newIdx < currentChapters.length) {
        // ★ Haptic feedback (пункт 8)
        haptic('medium');
        // ★ Slide transition (пункт 3)
        const container = document.getElementById('reader-text');
        const direction = delta > 0 ? 'left' : 'right';
        container.classList.add(`slide-out-${direction}`);
        setTimeout(() => {
            container.classList.remove(`slide-out-${direction}`);
            container.classList.add(`slide-in-${direction === 'left' ? 'right' : 'left'}`);
            openChapter(newIdx, true);
            requestAnimationFrame(() => {
                requestAnimationFrame(() => {
                    container.classList.remove(`slide-in-${direction === 'left' ? 'right' : 'left'}`);
                });
            });
        }, 200);
    }
}

function backFromReader() {
    haptic('light');
    saveScrollPosition();
    showScreen('chapters');
    // Обновляем список глав чтобы показать прогресс
    renderChaptersList();
}

function updateNavButtons() {
    document.getElementById('prev-chapter-btn').disabled = currentChapterIdx === 0;
    document.getElementById('next-chapter-btn').disabled = currentChapterIdx >= currentChapters.length - 1;
    document.getElementById('chapter-indicator').textContent = `${currentChapterIdx + 1} / ${currentChapters.length}`;
}

// ==========================================================================
// ЛАЙКИ
// ==========================================================================

function spawnFloatingEmoji(emoji, targetEl) {
    if (!targetEl) return;
    const rect = targetEl.getBoundingClientRect();
    const count = 6;

    const fragment = document.createDocumentFragment();
    for (let i = 0; i < count; i++) {
        const el = document.createElement('div');
        el.className = 'floating-emoji';
        el.innerHTML = emoji;
        
        // Random layout
        const rx = (Math.random() * 60 - 30);
        const ry = (Math.random() * 20 - 10);
        
        el.style.left = `${rect.left + rect.width / 2 + rx}px`;
        el.style.top = `${rect.top + rect.height / 2 + ry}px`;
        
        // Custom properties for animation
        el.style.setProperty('--tx', `${Math.random() * 100 - 50}px`);
        el.style.setProperty('--ty', `-${Math.random() * 150 + 100}px`);
        el.style.setProperty('--r', `${Math.random() * 90 - 45}deg`);
        el.style.setProperty('--r0', `${Math.random() * 40 - 20}deg`);
        el.style.animationDelay = `${Math.random() * 0.2}s`;

        fragment.appendChild(el);
        setTimeout(() => el.remove(), 1000);
    }
    document.body.appendChild(fragment);
}

function spawnFloatingHearts() {
    const btn = document.getElementById('like-btn');
    spawnFloatingEmoji('❤️', btn);
}

// duplicate removed

async function loadLikes() {
    if (!API_URL) return;
    const key = getChapterKey();
    if (!key) return;
    try {
        const resp = await apiFetch(API_URL + `/api/likes?chapter_key=${encodeURIComponent(key)}`);
        const data = await resp.json();
        updateLikeUI(data.count, data.liked);
    } catch (e) {
        console.warn('Likes load error:', e);
    }
}

async function toggleLike() {
    if (!API_URL || !userId) return;
    const key = getChapterKey();
    if (!key) return;
    try {
        const resp = await apiFetch(API_URL + '/api/likes', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ chapter_key: key })
        });
        const data = await resp.json();

        const btn = document.getElementById('like-btn');
        if (data.liked) {
            btn.classList.add('just-liked');
            spawnFloatingHearts();
        }
        setTimeout(() => btn.classList.remove('just-liked'), 500);

        updateLikeUI(data.count, data.liked);
    } catch (e) {
        console.warn('Like toggle error:', e);
    }
}

function updateLikeUI(count, liked) {
    const btn = document.getElementById('like-btn');
    const icon = document.getElementById('like-icon');
    const countEl = document.getElementById('like-count');

    btn.classList.toggle('liked', liked);
    // Меняем заливку SVG-path вместо textContent (иначе SVG-дерево стирается)
    if (icon) {
        const path = icon.querySelector('path');
        if (path) {
            path.setAttribute('fill', liked ? '#ff6b81' : 'none');
            path.setAttribute('stroke', liked ? '#ff6b81' : 'currentColor');
        }
    }
    countEl.textContent = count > 0 ? count : '';
}

// ==========================================================================
// КОММЕНТАРИИ (Вложенные)
// ==========================================================================

let replyingToId = null;
let lastFailedCommentId = null;
const pendingCommentSends = new Map();
let chapterReactionsState = { reactions: {}, user_reaction: null };

function setCommentSendState(state = 'idle', message = '', failedCommentId = null) {
    const statusEl = document.getElementById('comment-send-status');
    if (!statusEl) return;

    if (state === 'idle') {
        statusEl.className = 'comment-send-status hidden';
        statusEl.innerHTML = '';
        return;
    }

    statusEl.className = `comment-send-status ${state}`;
    if (state === 'sending') {
        statusEl.textContent = message || 'Отправка комментария...';
        return;
    }

    if (state === 'error') {
        if (failedCommentId) {
            lastFailedCommentId = String(failedCommentId);
        }
        statusEl.innerHTML = `
            <span>${escapeHtml(message || 'Не удалось отправить комментарий.')}</span>
            <button type="button" class="retry-inline-btn" onclick="retryLastFailedComment()">Повтор</button>
        `;
    }
}

function retryLastFailedComment() {
    if (!lastFailedCommentId) return;
    retryPendingComment(lastFailedCommentId);
}

function makeTempCommentId() {
    return `tmp_${Date.now()}_${Math.random().toString(36).slice(2, 9)}`;
}

function findCommentInCache(commentId) {
    return allCommentsCache.find((c) => String(c.id) === String(commentId)) || null;
}

function setReply(id, name) {
    replyingToId = id;
    document.getElementById('reply-indicator').style.display = 'flex';
    document.getElementById('reply-to-name').textContent = name;
    document.getElementById('comment-input').focus();
}

function cancelReply() {
    replyingToId = null;
    document.getElementById('reply-indicator').style.display = 'none';
    document.getElementById('reply-to-name').textContent = '';
}

async function loadComments() {
    if (!API_URL) return;
    const key = getChapterKey();
    if (!key) return;
    try {
        const resp = await apiFetch(API_URL + `/api/comments?chapter_key=${encodeURIComponent(key)}`);
        if (!resp.ok) {
            throw new Error(`HTTP ${resp.status}`);
        }
        const data = await resp.json();
        const pending = Array.from(pendingCommentSends.values()).filter((c) => c._optimisticState === 'sending' || c._optimisticState === 'error');
        allCommentsCache = [...pending, ...(data.comments || [])];
        
        const countBadge = document.getElementById('comments-count-badge');
        if (countBadge) countBadge.textContent = allCommentsCache.length > 0 ? `(${allCommentsCache.length})` : '';
        
        if (!activeCommentEditId) {
            renderComments(allCommentsCache);
        }
    } catch (e) {
        console.warn('Comments load error:', e);
        const list = document.getElementById('comments-list');
        if (list) {
            renderStateBlock(list, {
                variant: 'error',
                icon: '\u26A0\uFE0F',
                title: '\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u0437\u0430\u0433\u0440\u0443\u0437\u0438\u0442\u044c \u043a\u043e\u043c\u043c\u0435\u043d\u0442\u0430\u0440\u0438\u0438',
                description: '\u041f\u0440\u043e\u0432\u0435\u0440\u044c\u0442\u0435 \u0441\u0435\u0442\u044c \u0438 \u043f\u043e\u043f\u0440\u043e\u0431\u0443\u0439\u0442\u0435 \u0435\u0449\u0435 \u0440\u0430\u0437.',
                actionLabel: '\u041f\u043e\u0432\u0442\u043e\u0440\u0438\u0442\u044c',
                onAction: () => loadComments()
            });
        }
    }
}

function renderComments(comments) {
    allCommentsCache = comments; // Важно: обновляем кэш для корректной работы сортировки
    const list = document.getElementById('comments-list');
    
    const countBadge = document.getElementById('comments-count-badge');
    if (countBadge) countBadge.textContent = comments.length > 0 ? `(${comments.length})` : '';

    if (comments.length === 0) {
        list.innerHTML = `<div class="no-comments">Пока нет комментариев. Будьте первым! ✨</div>`;
        return;
    }

    // ★ Фаза 5: Применяем сортировку
    commentsData = [...comments];

    const parseDate = (d) => {
        if (!d) return 0;
        const safe = d.includes('T') ? d : d.replace(' ', 'T') + 'Z';
        return new Date(safe).getTime();
    };

    commentsData.forEach(c => {
        if (c._ts === undefined) c._ts = parseDate(c.created_at);
    });

    if (currentCommentSort === 'top') {
        // Сортировка по лайкам (интересные), при равенстве по дате
        commentsData.sort((a, b) => {
            const diff = (b.likes || 0) - (a.likes || 0);
            return diff !== 0 ? diff : b._ts - a._ts;
        });
    } else {
        // По дате (новые сверху)
        commentsData.sort((a, b) => b._ts - a._ts);
    }

    // Строим дерево
    const commentMap = {};
    const topLevel = [];
    commentsData.forEach(c => {
        c.children = [];
        commentMap[c.id] = c;
    });

    commentsData.forEach(c => {
        if (c.parent_id) {
            if (commentMap[c.parent_id]) {
                commentMap[c.parent_id].children.push(c);
            }
            // Сиротские ответы игнорируются
        } else {
            topLevel.push(c);
        }
    });

    function getAvatarColor(userIdStr) {
        const colors = [
            '#FF4D6D', '#EF476F', '#FFD166', '#06D6A0', '#118AB2', '#073B4C', 
            '#7B2CBF', '#5A189A', '#3C096C', '#240046', '#fb5607', '#3a86ff'
        ];
        if (!userIdStr) return colors[0];
        let hash = 0;
        for (let i = 0; i < userIdStr.length; i++) {
            hash = ((hash << 5) - hash) + userIdStr.charCodeAt(i);
            hash |= 0; 
        }
        return colors[Math.abs(hash) % colors.length];
    }

    // Markup helpers are now global

    function renderNode(c, isChild = false) {
        const initial = (c.user_name || 'А')[0].toUpperCase();
        const date = formatDate(c.created_at);
        const isOwn = String(c.user_id) === userId;
        const viewerIsAdmin = isAdminMode; 
        const color = getAvatarColor(String(c.user_id));
        
        // Роль автора (бейджик)
        const role = getUserRole(String(c.user_id));
        const roleBadge = role ? `<span class="comment-role-badge ${role.css}">${role.text}</span>` : '';

        const isPendingComment = c._optimisticState === 'sending' || c._optimisticState === 'error';
        const commentStateClass = c._optimisticState === 'sending'
            ? 'pending-send'
            : (c._optimisticState === 'error' ? 'pending-error' : '');
        const stateBadge = c._optimisticState === 'sending'
            ? `<span class="comment-state-badge sending">Отправка...</span>`
            : (c._optimisticState === 'error' ? `<span class="comment-state-badge error">Не отправлено</span>` : '');

        const deleteBtn = (isOwn || viewerIsAdmin) ? `<button class="c-action-btn c-delete" onclick="deleteComment(${c.id})">Удалить</button>` : '';
        const editBtn = isOwn ? `<button class="c-action-btn" onclick="editComment(${c.id})">Ред.</button>` : '';
        const replyBtn = `<button class="c-action-btn" onclick="setReply(${c.id}, '${escapeHtml(c.user_name)}')">Ответить</button>`;
        const reportBtn = !isOwn ? `<button class="c-action-btn" onclick="reportComment(${c.id})">Пожаловаться</button>` : '';
        const retryBtn = c._optimisticState === 'error'
            ? `<button class="c-action-btn c-retry" onclick="retryPendingComment('${escapeHtml(String(c.id))}')">Повтор</button>`
            : '';
        const discardBtn = c._optimisticState === 'error'
            ? `<button class="c-action-btn c-discard" onclick="discardPendingComment('${escapeHtml(String(c.id))}')">Убрать</button>`
            : '';

        // Реакции
        const likes = c.likes || 0;
        const userReaction = c.user_reaction; 
        const likeActive = userReaction === 'like' ? 'active' : '';
        const reactionPending = !!c._reactionPending;

        // Avatar
        const avatarUrl = API_URL && c.user_id ? `${API_URL}/api/avatar?user_id=${c.user_id}` : null;
        const avatarHtml = avatarUrl 
            ? `<img src="${avatarUrl}" class="comment-avatar" alt="${initial}" style="background:${color}" onerror="this.onerror=null;this.outerHTML='<div class=&quot;comment-avatar&quot; style=&quot;background:${color}&quot;>${initial}</div>';">`
            : `<div class="comment-avatar" style="background:${color}">${initial}</div>`;

        let html = `
        <div class="comment-item ${isChild ? 'comment-reply' : ''} ${commentStateClass}" id="comment-${c.id}">
            ${isChild ? '<div class="comment-branch"></div><div class="comment-branch-curve"></div>' : ''}
            <div class="comment-content">
                <div class="comment-header">
                    ${avatarHtml}
                    <div class="comment-author">${escapeHtml(c.user_name)}${roleBadge}${stateBadge}</div>
                    <div class="comment-date" style="margin-left:auto;">${date}</div>
                </div>
                <div class="comment-text" id="comment-text-${c.id}">${applyMarkup(c.text)}</div>
                <div class="comment-actions">
                    <div class="comment-reactions">
                        ${isPendingComment ? '' : `<button class="c-reaction-btn c-like ${likeActive} ${reactionPending ? 'pending' : ''}" ${reactionPending ? 'disabled' : ''} onclick="reactToComment(${c.id}, 'like')" title="Нравится">
                            <svg class="icon-xs" viewBox="0 0 24 24"><path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3zM7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
                            <span>${likes}</span>
                        </button>`}
                    </div>
                    <div class="comment-main-actions">
                        ${isPendingComment ? '' : replyBtn}
                        ${isPendingComment ? '' : editBtn}
                        ${isPendingComment ? '' : deleteBtn}
                        ${isPendingComment ? '' : reportBtn}
                        ${retryBtn}
                        ${discardBtn}
                    </div>
                </div>
        `;

        if (c.children && c.children.length > 0) {
            html += `<div class="comment-children">` + c.children.map(child => renderNode(child, true)).join('') + `</div>`;
        }

        html += `</div></div>`;
        return html;
    }

    list.innerHTML = topLevel.map(c => renderNode(c, false)).join('');
}

function reportComment(id) {
    if (!API_URL) return;

    // Create a custom modal for reporting instead of prompt()
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay active';
    overlay.style.zIndex = '99999';
    overlay.innerHTML = `
        <div class="modal-container" style="padding: 20px; background: var(--bg); border-radius: 12px; width: 90%; max-width: 400px; margin: auto; position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); box-shadow: var(--shadow);">
            <h3 style="margin-bottom: 12px; font-size: 18px;">Жалоба на комментарий</h3>
            <p style="margin-bottom: 12px; font-size: 14px; opacity: 0.8;">Укажите причину жалобы (спам, оскорбления и т.д.):</p>
            <textarea id="report-reason-input" class="comment-input" rows="3" style="width: 100%; box-sizing: border-box; margin-bottom: 16px; border: 1px solid var(--divider); padding: 8px; border-radius: 8px; background: var(--input-bg); color: var(--text);"></textarea>
            <div style="display: flex; gap: 8px; justify-content: flex-end;">
                <button class="c-action-btn" id="report-cancel-btn">Отмена</button>
                <button class="comment-submit-btn" id="report-submit-btn" style="float: none;">Отправить</button>
            </div>
        </div>
    `;
    document.body.appendChild(overlay);

    document.getElementById('report-cancel-btn').onclick = () => {
        document.body.removeChild(overlay);
    };

    document.getElementById('report-submit-btn').onclick = () => {
        const reason = document.getElementById('report-reason-input').value.trim();
        if (!reason) {
            showToast("Причина не может быть пустой");
            return;
        }
        document.body.removeChild(overlay);

        const commentEl = document.getElementById(`comment-text-${id}`);
        const commentText = commentEl ? commentEl.innerText : "";

        apiFetch(`${API_URL}/api/comments/report`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ comment_id: id, reason: reason, comment_text: commentText })
        }).then(r => r.json()).then(data => {
            if (data.ok) showToast("Жалоба отправлена модераторам.");
            else showToast("Ошибка: " + data.error);
        }).catch(() => showToast("Ошибка сети."));
    };
}

async function reactToComment(commentId, type) {
    if (!API_URL || !userId) {
        showToast('Пожалуйста, авторизуйтесь через бота.');
        return;
    }
    const comment = findCommentInCache(commentId);
    if (!comment) return;

    const prevReaction = comment.user_reaction || null;
    const prevLikes = Number(comment.likes || 0);

    const nextReaction = prevReaction === type ? null : type;
    let nextLikes = prevLikes;
    if (prevReaction === 'like' && type === 'like') {
        nextLikes = Math.max(0, prevLikes - 1);
    } else if (prevReaction !== 'like' && type === 'like') {
        nextLikes = prevLikes + 1;
    }

    comment.user_reaction = nextReaction;
    comment.likes = nextLikes;
    comment._reactionPending = true;
    renderComments(allCommentsCache);

    try {
        const resp = await apiFetch(`${API_URL}/api/comments/react`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ comment_id: commentId, type: type })
        });
        const data = await resp.json();
        if (data.ok) {
            await loadComments();
        } else {
            comment.user_reaction = prevReaction;
            comment.likes = prevLikes;
            delete comment._reactionPending;
            renderComments(allCommentsCache);
            showToast('Ошибка при реакции: ' + (data.error || 'неизвестно'));
        }
    } catch (e) {
        comment.user_reaction = prevReaction;
        comment.likes = prevLikes;
        delete comment._reactionPending;
        renderComments(allCommentsCache);
        showToast('Ошибка сети.');
    } finally {
        delete comment._reactionPending;
    }
}

function sortComments(type) {
    currentCommentSort = type;
    document.getElementById('tab-sort-top').classList.toggle('active', type === 'top');
    document.getElementById('tab-sort-new').classList.toggle('active', type === 'new');
    renderComments(allCommentsCache);
}

let activeCommentEditId = null;

function editComment(id) {
    activeCommentEditId = id;
    const comment = allCommentsCache.find(c => c.id === id);
    if (!comment) return;
    
    const textNode = document.getElementById(`comment-text-${id}`);
    const originalText = comment.text;
    
    textNode.innerHTML = `
        <textarea class="comment-input edit-area" id="edit-input-${id}" rows="3">${escapeHtml(originalText)}</textarea>
        <div class="edit-actions" style="margin-top:8px; display:flex; gap:8px;">
            <button class="comment-submit-btn" style="float:none; padding:6px 14px;" onclick="saveCommentEdit('${id}')">Сохранить</button>
            <button class="c-action-btn" onclick="cancelEdit('${id}')">Отмена</button>
        </div>
    `;
    document.getElementById(`edit-input-${id}`).focus();
}

function cancelEdit(id) {
    activeCommentEditId = null;
    const comment = allCommentsCache.find(c => c.id == id);
    if (comment) {
        const textNode = document.getElementById(`comment-text-${id}`);
        if (textNode) {
            textNode.innerHTML = applyMarkup(comment.text);
        }
    } else {
        renderComments(allCommentsCache);
    }
}

async function saveCommentEdit(id) {
    const newText = document.getElementById(`edit-input-${id}`).value.trim();
    if (!newText) {
        showToast('Комментарий не может быть пустым');
        return;
    }

    try {
        const resp = await apiFetch(`${API_URL}/api/comments/${id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text: newText })
        });
        const data = await resp.json();
        if (data.ok) {
            await loadComments();
            showToast('Комментарий изменён');
        } else {
            showToast('Ошибка: ' + (data.error || 'не удалось'));
        }
    } catch (e) {
        showToast('Ошибка сети.');
    }
}

function updateCommentPreview() {
    const input = document.getElementById('comment-input');
    const preview = document.getElementById('comment-preview-area');
    if (!input || !preview) return;
    
    const val = input.value.trim();
    if (val) {
        preview.classList.remove('hidden');
        preview.innerHTML = `<div style="font-size: 11px; opacity: 0.5; margin-bottom: 4px; font-weight: 700; text-transform: uppercase;">Предпросмотр:</div>` + applyMarkup(val);
    } else {
        preview.classList.add('hidden');
        preview.innerHTML = '';
    }
}

// Inline preview updates automatically on input

function insertFormatting(start, end) {
    const inputId = activeCommentEditId ? `edit-input-${activeCommentEditId}` : 'comment-input';
    const input = document.getElementById(inputId);
    if (!input) return;
    const startPos = input.selectionStart;
    const endPos = input.selectionEnd;
    const text = input.value;
    const selectedText = text.substring(startPos, endPos);
    
    const before = text.substring(0, startPos);
    const after = text.substring(endPos, text.length);
    
    input.value = before + start + selectedText + end + after;
    input.focus();
    
    // Помещаем курсор после вставки
    const newPos = startPos + start.length + selectedText.length + end.length;
    input.setSelectionRange(newPos, newPos);
    
    updateCommentPreview();
}

async function postComment() {
    if (!API_URL || !userId) return;
    const input = document.getElementById('comment-input');
    const text = input.value.trim();
    if (!text) {
        showToast('Комментарий не может быть пустым');
        return;
    }

    const key = getChapterKey();
    if (!key) return;

    const parentId = replyingToId;
    const tempId = makeTempCommentId();
    const pendingComment = {
        id: tempId,
        chapter_key: key,
        user_id: userId,
        user_name: userName,
        text,
        parent_id: parentId || null,
        likes: 0,
        user_reaction: null,
        created_at: new Date().toISOString(),
        _optimisticState: 'sending',
        _retryPayload: {
            chapter_key: key,
            text,
            parent_id: parentId || null
        }
    };

    pendingCommentSends.set(String(tempId), pendingComment);
    allCommentsCache = [pendingComment, ...allCommentsCache];
    input.value = '';
    updateCommentPreview();
    cancelReply();
    renderComments(allCommentsCache);
    setCommentSendState('sending', 'Отправка комментария...');

    const btn = document.querySelector('#comment-form .comment-submit-btn');
    const prevBtnText = btn ? btn.textContent : '';
    if (btn) {
        btn.disabled = true;
        btn.textContent = 'Отправка...';
    }

    try {
        const resp = await apiFetch(API_URL + '/api/comments', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(pendingComment._retryPayload)
        });

        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            throw new Error(err.error || 'Ошибка сервера при отправке');
        }

        pendingCommentSends.delete(String(tempId));
        allCommentsCache = allCommentsCache.filter(c => String(c.id) !== String(tempId));
        setCommentSendState('idle');
        await loadComments();
    } catch (e) {
        console.error('Post comment error:', e);
        pendingComment._optimisticState = 'error';
        allCommentsCache = allCommentsCache.map(c => String(c.id) === String(tempId) ? pendingComment : c);
        lastFailedCommentId = String(tempId);
        renderComments(allCommentsCache);
        setCommentSendState('error', `Не удалось отправить: ${e.message}`, tempId);
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.textContent = prevBtnText || 'Отправить';
        }
    }
}

async function retryPendingComment(commentId) {
    const key = String(commentId);
    const pending = pendingCommentSends.get(key) || findCommentInCache(key);
    if (!pending || !pending._retryPayload) return;
    if (pending._retryInFlight) return;

    pending._retryInFlight = true;
    pending._optimisticState = 'sending';
    renderComments(allCommentsCache);
    setCommentSendState('sending', 'Повторная отправка...');

    try {
        const resp = await apiFetch(API_URL + '/api/comments', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(pending._retryPayload)
        });

        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            throw new Error(err.error || 'Ошибка сервера при отправке');
        }

        pendingCommentSends.delete(key);
        allCommentsCache = allCommentsCache.filter(c => String(c.id) !== key);
        if (lastFailedCommentId === key) {
            lastFailedCommentId = null;
        }
        setCommentSendState('idle');
        await loadComments();
    } catch (e) {
        pending._optimisticState = 'error';
        console.warn('Retry comment error:', e);
        renderComments(allCommentsCache);
        setCommentSendState('error', `Повтор не удался: ${e.message}`, key);
    } finally {
        pending._retryInFlight = false;
    }
}

function discardPendingComment(commentId) {
    const key = String(commentId);
    pendingCommentSends.delete(key);
    allCommentsCache = allCommentsCache.filter(c => String(c.id) !== key);
    if (lastFailedCommentId === key) {
        lastFailedCommentId = null;
        setCommentSendState('idle');
    }
    renderComments(allCommentsCache);
}

async function deleteComment(commentId) {
    if (!API_URL || !userId) return;
    
    const isConfirmed = await new Promise(resolve => {
        if (tg && tg.showConfirm) {
            tg.showConfirm("Удалить комментарий?", resolve);
        } else {
            resolve(confirm("Удалить комментарий?"));
        }
    });
    if (!isConfirmed) return;

    try {
        const resp = await apiFetch(API_URL + '/api/comments', {
            method: 'DELETE',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ comment_id: commentId })
        });
        if (!resp.ok) {
            const errData = await resp.json().catch(()=>({}));
            throw new Error(errData.error || 'Ошибка сервера при удалении');
        }
        await loadComments();
    } catch (e) {
        console.warn('Delete comment error:', e);
        showToast("Ошибка удаления: " + e.message);
    }
}

function escapeHtml(str) {
    if (!str) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

function applyMarkup(text) {
    if (!text) return '';
    let html = escapeHtml(text);
    
    // 2. Bold: [b]...[/b]
    html = html.replace(/\[b\]([\s\S]+?)\[\/b\]/g, '<strong>$1</strong>');
    // 3. Italic: [i]...[/i]
    html = html.replace(/\[i\]([\s\S]+?)\[\/i\]/g, '<em>$1</em>');
    // 4. Strike: [s]...[/s]
    html = html.replace(/\[s\]([\s\S]+?)\[\/s\]/g, '<del>$1</del>');
    // 5. Spoiler: ||...||
    html = html.replace(/\|\|([\s\S]+?)\|\|/g, (match, content) => {
        return `<span class="comment-spoiler" onclick="this.classList.toggle('revealed'); event.stopPropagation();">${content}</span>`;
    });
    // 6. Quote: [quote]...[/quote]
    html = html.replace(/\[quote\]([\s\S]+?)\[\/quote\]/g, '<blockquote class="comment-quote">$1</blockquote>');
    
    return html;
}

// ==========================================================================
// РЕАКЦИИ (Improved v3)
// ==========================================================================

async function loadReactions() {
    if (!API_URL) return;
    const key = getChapterKey();
    if (!key) return;
    try {
        const resp = await apiFetch(API_URL + `/api/reactions?chapter_key=${encodeURIComponent(key)}`);
        if (!resp.ok) {
            throw new Error(`HTTP ${resp.status}`);
        }
        const data = await resp.json();
        chapterReactionsState = {
            reactions: { ...(data.reactions || {}) },
            user_reaction: data.user_reaction || null
        };
        renderReactions(chapterReactionsState);
    } catch (e) {
        console.warn('Reactions load error:', e);
        const bar = document.getElementById('reaction-bar');
        if (bar) {
            renderStateBlock(bar, {
                variant: 'error',
                compact: true,
                icon: '\u26A1',
                title: '\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u0437\u0430\u0433\u0440\u0443\u0437\u0438\u0442\u044c \u0440\u0435\u0430\u043a\u0446\u0438\u0438',
                actionLabel: '\u041f\u043e\u0432\u0442\u043e\u0440\u0438\u0442\u044c',
                onAction: () => loadReactions()
            });
        }
    }
}

function renderReactions(data) {
    const bar = document.getElementById('reaction-bar');
    if (!bar) return;

    const safeData = data || chapterReactionsState || { reactions: {}, user_reaction: null };

    const list = [
        { type: 'like', text: 'Круто', emoji: '👍', svg: '<svg class="r-svg" viewBox="0 0 24 24"><path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3zM7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"/></svg>' },
        { type: 'heart', text: 'Люблю', emoji: '❤️', svg: '<svg class="r-svg" viewBox="0 0 24 24"><path d="M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.3 1.5 4.05 3 5.5l7 7Z"/></svg>' },
        { type: 'fire', text: 'Огонь', emoji: '🔥', svg: '<svg class="r-svg" viewBox="0 0 24 24"><path d="M8.5 14.5A2.5 2.5 0 0 0 11 12c0-1.38-.5-2-1-3-1.072-2.143-.224-4.054 2-6 .5 2.5 2 4.9 4 6.5 2 1.6 3 3.5 3 5.5a7 7 0 1 1-14 0c0-1.153.433-2.294 1-3a2.5 2.5 0 0 0 2.5 2.5z"/></svg>' },
        { type: 'funny', text: 'Угар', emoji: '😂', svg: '<svg class="r-svg" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><path d="M8 14s1.5 2 4 2 4-2 4-2"/><line x1="9" x2="9.01" y1="9" y2="9"/><line x1="15" x2="15.01" y1="9" y2="9"/></svg>' },
        { type: 'wow', text: 'Ого!', emoji: '😮', svg: '<svg class="r-svg" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><path d="M8 15h8"/><line x1="9" x2="9.01" y1="9" y2="9"/><line x1="15" x2="15.01" y1="9" y2="9"/></svg>' },
        { type: 'sad', text: 'Грустно', emoji: '😢', svg: '<svg class="r-svg" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><path d="M16 16s-1.5-2-4-2-4 2-4 2"/><line x1="9" x2="9.01" y1="9" y2="9"/><line x1="15" x2="15.01" y1="9" y2="9"/></svg>' },
        { type: 'battle', text: 'Эпик', emoji: '⚔️', svg: '<svg class="r-svg" viewBox="0 0 24 24"><polyline points="14.5 17.5 3 6 3 3 6 3 17.5 14.5"/><line x1="13" x2="19" y1="19" y2="13"/><line x1="16" x2="20" y1="16" y2="20"/><line x1="19" x2="21" y1="21" y2="19"/></svg>' }
    ];

    const reactions = safeData.reactions || {};
    const user_reaction = safeData.user_reaction;

    bar.innerHTML = list.map(item => {
        const count = reactions[item.type] || 0;
        const active = user_reaction === item.type ? 'active' : '';
        return `
            <div class="reaction-item ${active} type-${item.type}" onclick="toggleReaction('${item.type}')" title="${item.text}">
                <div class="reaction-icon-wrapper">${item.svg}</div>
                <span class="reaction-count">${count > 0 ? count : ''}</span>
            </div>
        `;
    }).join('');
}

let _isReacting = false;


// ==========================================================================
// НАВИГАЦИЯ ЭКРАНОВ
// ==========================================================================

function showScreen(name) {
    assertReaderState(`showScreen:${name}`);
    // Если уходим из читалки — сохраняем позицию
    if (document.getElementById('screen-reader').classList.contains('active') && name !== 'reader') {
        saveScrollPosition();
        if (progressBarEl) progressBarEl.style.width = '0%';
    }
    if (name !== 'reader') {
        document.body.classList.remove('keyboard-open');
        document.documentElement.style.setProperty('--reader-keyboard-offset', '0px');
    }

    const screens = document.querySelectorAll('.screen');
    screens.forEach(s => {
        s.classList.remove('active', 'slide-left');
    });

    document.getElementById(`screen-${name}`).classList.add('active');

    // Admin FAB visibility (Phase 4)
    const adminFab = document.getElementById('admin-fab-container');
    if (adminFab) {
        adminFab.style.display = (name === 'reader' && isAdminMode) ? 'flex' : 'none';
        // Close menu if switching screens
        closeAdminMenu();
    }

    // Update bottom nav
    const navTabs = document.querySelectorAll('.nav-tab');
    if (navTabs.length > 0) {
        navTabs.forEach(t => t.classList.remove('active'));
        // Special case: chapters or reader might not have their own tab, fall back
        const activeTab = document.getElementById(`tab-${name}`);
        if (activeTab) activeTab.classList.add('active');

        // Hide bottom nav in reader
        const bottomNav = document.getElementById('main-bottom-nav');
        if (bottomNav) {
            bottomNav.style.display = name === 'reader' ? 'none' : 'flex';
        }
    }

    if (name === 'library') {
        updateLibraryFilterButtons();
        renderLibraryTab();
        updateLibraryStats();
    }
}

// ==========================================================================
// ПРОГРЕСС ЧТЕНИЯ
// ==========================================================================

function getReadKey(seriesId, vol, chapter) {
    return `${seriesId}_v${vol}_ch${chapter}`;
}

function isRead(seriesId, vol, chapter) {
    return !!readChapters[getReadKey(seriesId, vol, chapter)];
}

function markAsRead(seriesId, vol, chapter) {
    readChapters[getReadKey(seriesId, vol, chapter)] = Date.now();
    safeSetLocal('reader_progress', readChapters);
}

function setFontSize(size) {
    settings.fontSize = parseInt(size);
    
    // Обновляем label если есть
    const label = document.getElementById('label-fontSize');
    if (label) label.innerText = size + 'px';
    
    // Применяем настройки
    applySettings();
    saveSettings();
    
    // Обновляем активные кнопки
    document.querySelectorAll('[data-size]').forEach(b => {
        b.classList.toggle('active', parseInt(b.dataset.size) === parseInt(size));
    });
}

function setTheme(theme) {
    settings.theme = theme;
    applySettings();
    saveSettings();
    updateSettingsUI();
}

function setTextWidth(width) {
    settings.textWidth = parseInt(width);
    const label = document.getElementById('label-textWidth');
    if (label) label.innerText = width + '%';
    applySettings();
    saveSettings();
}

function setFont(font) {
    settings.font = font;
    applySettings();
    saveSettings();
    updateSettingsUI();
}

function setLineHeight(lh) {
    settings.lineHeight = parseFloat(lh);
    const label = document.getElementById('label-lineHeight');
    if (label) label.innerText = lh;
    applySettings();
    saveSettings();
}

function setLetterSpacing(ls) {
    settings.letterSpacing = parseFloat(ls);
    const label = document.getElementById('label-letterSpacing');
    if (label) label.innerText = ls + 'px';
    applySettings();
    saveSettings();
}

function setParaIndent(px) {
    settings.paraIndent = parseInt(px);
    const label = document.getElementById('label-paraIndent');
    if (label) label.innerText = px + 'px';
    applySettings();
    saveSettings();
}

function setTextAlign(align) {
    settings.textAlign = align;
    applySettings();
    saveSettings();
    updateSettingsUI();
}

function setIndent(enabled) {
    settings.indent = enabled;
    const group = document.getElementById('para-indent-group');
    if (group) group.style.display = enabled ? 'block' : 'none';
    applySettings();
    saveSettings();
}

// ==========================================================================
// НАСТРОЙКИ
// ==========================================================================

function toggleSettings() {
    const overlay = document.getElementById('settings-overlay');
    const panel = document.getElementById('settings-panel');
    const isHidden = panel.classList.contains('hidden');
    
    overlay.classList.toggle('hidden');
    panel.classList.toggle('hidden');
    
    if (!isHidden) {
        // Closing: save
        saveSettings();
    } else {
        // Opening: show default tab
        showSettingsTab('font');
        updateSettingsUI();
    }
}

function showSettingsTab(tabName) {
    const contents = document.querySelectorAll('.settings-tab-content');
    const buttons = document.querySelectorAll('.settings-tab-btn');
    
    contents.forEach(content => {
        content.classList.add('hidden');
        content.classList.remove('animate-slide-in');
    });
    buttons.forEach(btn => btn.classList.remove('active'));
    
    const activeContent = document.getElementById(`settings-tab-${tabName}`);
    activeContent.classList.remove('hidden');
    activeContent.classList.add('animate-slide-in');
    
    document.getElementById(`tab-btn-${tabName}`).classList.add('active');
}

function updateSettingsUI() {
    // Labels for sliders
    if (document.getElementById('label-fontSize')) document.getElementById('label-fontSize').innerText = settings.fontSize + 'px';
    if (document.getElementById('label-textWidth')) document.getElementById('label-textWidth').innerText = settings.textWidth + '%';
    if (document.getElementById('label-lineHeight')) document.getElementById('label-lineHeight').innerText = settings.lineHeight;
    if (document.getElementById('label-dimmerValue')) document.getElementById('label-dimmerValue').innerText = settings.dimmerValue + '%';

    // Inputs value
    if (document.getElementById('input-fontSize')) document.getElementById('input-fontSize').value = settings.fontSize;
    if (document.getElementById('input-textWidth')) document.getElementById('input-textWidth').value = settings.textWidth;
    if (document.getElementById('input-lineHeight')) document.getElementById('input-lineHeight').value = settings.lineHeight;
    if (document.getElementById('input-dimmerValue')) document.getElementById('input-dimmerValue').value = settings.dimmerValue;

    // Segmented controls classes
    document.querySelectorAll('[data-font]').forEach(b => b.classList.toggle('active', b.dataset.font === settings.font));
    document.querySelectorAll('[data-align]').forEach(b => b.classList.toggle('active', b.dataset.align === settings.textAlign));
    document.querySelectorAll('[data-theme]').forEach(b => b.classList.toggle('active', b.dataset.theme === settings.theme));
}

function setDimmer(val) {
    settings.dimmerValue = parseInt(val);
    if (document.getElementById('label-dimmerValue')) document.getElementById('label-dimmerValue').innerText = val + '%';
    applySettings();
    saveSettings();
}



function applySettings() {
    // Тема
    document.body.classList.remove('theme-sepia', 'theme-dark', 'theme-gray', 'theme-amoled');
    if (settings.theme !== 'light') {
        document.body.classList.add(`theme-${settings.theme}`);
    }

    // Диммер (Яркость)
    const dimmer = document.getElementById('dimmer-overlay');
    if (dimmer) {
        dimmer.style.backgroundColor = `rgba(0, 0, 0, ${settings.dimmerValue / 100})`;
        dimmer.style.pointerEvents = 'none'; // Всегда прокликивается, если только это не оверлей настроек
    }

    // Шрифт и размер
    const readerText = document.getElementById('reader-text');
    if (readerText) {
        readerText.style.fontSize = settings.fontSize + 'px';
        readerText.style.maxWidth = settings.textWidth + '%';
        readerText.style.lineHeight = settings.lineHeight;
        readerText.style.letterSpacing = settings.letterSpacing + 'px';

        // Шрифт
        readerText.classList.remove('font-sans', 'font-slab', 'font-mono', 'font-montserrat', 'font-display');
        if (settings.font === 'sans') readerText.classList.add('font-sans');
        if (settings.font === 'montserrat') readerText.classList.add('font-montserrat');
        if (settings.font === 'display') readerText.classList.add('font-display');

        // Выравнивание
        readerText.classList.toggle('align-justify', settings.textAlign === 'justify');

        // Отступы
        readerText.classList.toggle('indent-on', settings.indent);

        // Отступ между абзацами
        readerText.style.setProperty('--para-spacing', settings.paraSpacing + 'px');
        readerText.style.setProperty('--para-indent', settings.paraIndent + 'px');
    }

    // Social section width
    const socialSection = document.getElementById('social-section');
    if (socialSection) {
        socialSection.style.maxWidth = settings.textWidth + '%';
    }

    // ★ Smart Dark Mode для Teletype iframes (пункт 7)
    applyIframeDarkMode();

    // ★ Haptic feedback при смене настроек (пункт 8)
    haptic('light');

    // Telegram header
    try {
        const colors = {
            light: '#ffffff', sepia: '#f4ead5', gray: '#333333',
            dark: '#1a1a2e', amoled: '#000000'
        };
        tg.setHeaderColor(colors[settings.theme] || '#ffffff');
    } catch (e) { }
}

function saveSettings() {
    safeSetLocal('reader_settings', settings);
}

function restoreSettings() {
    updateSettingsUI();
    applySettings();
}

// ==========================================================================
// СОБЫТИЯ СКРОЛЛА (автосохранение + прогресс-бар)
// ==========================================================================

let scrollSaveTimer = null;
let lastScrollY = 0;
let uiHidden = false;

document.addEventListener('DOMContentLoaded', () => {
    const readerContent = document.getElementById('reader-content');
    if (readerContent) {
        let pointerDown = false;
        let pointerStartX = 0;
        let pointerStartY = 0;
        let pointerDragged = false;

        readerContent.addEventListener('pointerdown', (e) => {
            if (!e.isPrimary) return;
            pointerDown = true;
            pointerDragged = false;
            pointerStartX = e.clientX;
            pointerStartY = e.clientY;
        }, { passive: true });

        readerContent.addEventListener('pointermove', (e) => {
            if (!pointerDown || !e.isPrimary) return;
            if (Math.abs(e.clientX - pointerStartX) > 8 || Math.abs(e.clientY - pointerStartY) > 8) {
                pointerDragged = true;
            }
        }, { passive: true });

        const finishPointer = () => {
            if (pointerDown && pointerDragged) {
                // После drag/selection подавляем tap-to-scroll, чтобы не было резкого прыжка.
                suppressReaderTapToScroll(900);
            }
            pointerDown = false;
            pointerDragged = false;
        };
        readerContent.addEventListener('pointerup', finishPointer, { passive: true });
        readerContent.addEventListener('pointercancel', finishPointer, { passive: true });

        let ticking = false;
        readerContent.addEventListener('scroll', () => {
            if (!ticking) {
                window.requestAnimationFrame(() => {
                    updateProgressBar(readerContent);

                    // ★ Auto-hide UI на скролле (пункт 1)
                    const currentScroll = readerContent.scrollTop;
                    const topBar = document.getElementById('reader-top-bar');
                    const bottomBar = document.getElementById('reader-bottom-bar');

                    if (topBar && bottomBar) {
                        if (currentScroll > lastScrollY + 8 && currentScroll > 100) {
                            // Скролл вниз — прячем
                            if (!uiHidden) {
                                topBar.classList.add('bars-hidden');
                                bottomBar.classList.add('bars-hidden');
                                uiHidden = true;

                                // Закрываем FAB-меню при скролле вниз
                                const menu = document.getElementById('fab-menu');
                                if (menu && !menu.classList.contains('hidden')) toggleFab();
                            }
                        } else if (currentScroll < lastScrollY - 5) {
                            // Скролл вверх — показываем
                            if (uiHidden) {
                                topBar.classList.remove('bars-hidden');
                                bottomBar.classList.remove('bars-hidden');
                                uiHidden = false;
                            }
                        }
                    }

                    lastScrollY = currentScroll <= 0 ? 0 : currentScroll;

                    // Prefetch and Save Logic
                    clearTimeout(scrollSaveTimer);
                    scrollSaveTimer = setTimeout(() => {
                        const pct = currentScroll / Math.max(1, readerContent.scrollHeight - readerContent.clientHeight);
                        if (pct > 0.8) prefetchNextChapter();
                        saveScrollPosition();
                    }, 500);

                    ticking = false;
                });
                ticking = true;
            }
        }, { passive: true });
    }


        // ★ Tap-to-Scroll zones (пункт 2)
        readerContent.addEventListener('click', (e) => {
            // Игнорируем клики по ссылкам, кнопкам, изображениям, textarea, input
            if (e.target.closest('a, button, img, textarea, input, .social-section, .comment-form, iframe')) return;
            if (isReaderTapToScrollSuppressed()) return;

            const selection = window.getSelection ? window.getSelection() : null;
            if (selection && selection.rangeCount && !selection.isCollapsed && selection.toString().trim().length >= 2) {
                suppressReaderTapToScroll(900);
                return;
            }

            const rect = readerContent.getBoundingClientRect();
            const relativeY = (e.clientY - rect.top) / rect.height;
            const pageHeight = readerContent.clientHeight * 0.85;

            if (relativeY < 0.3) {
                // Верхняя треть — Page Up
                readerContent.scrollBy({ top: -pageHeight, behavior: 'smooth' });
                haptic('light');
            } else if (relativeY > 0.7) {
                // Нижняя треть — Page Down
                readerContent.scrollBy({ top: pageHeight, behavior: 'smooth' });
                haptic('light');
            } else {
                // Центр — Toggle UI
                const topBar = document.getElementById('reader-top-bar');
                const bottomBar = document.getElementById('reader-bottom-bar');
                if (topBar && bottomBar) {
                    topBar.classList.toggle('bars-hidden');
                    bottomBar.classList.toggle('bars-hidden');
                    uiHidden = !uiHidden;
                    haptic('light');
                }
            }
        });
});

// Сохраняем при уходе из приложения
window.addEventListener('beforeunload', () => {
    saveScrollPosition();
});

// ==========================================================================
// ЛАЙКИ И КОММЕНТАРИИ (SOCIAL) & ПРОДОЛЖИТЬ ЧТЕНИЕ
// ==========================================================================

function renderContinueReading() {
    const container = document.getElementById('continue-reading-container');
    if (!container) return;

    let latestBm = null;
    if (serverBookmarks.length > 0) {
        latestBm = serverBookmarks[0];
    } else {
        const allLocal = safeGetLocal('reader_last_read', {});
        let latestLocal = null;
        let maxTs = 0;
        for (let sId in allLocal) {
            if (allLocal[sId].ts > maxTs) {
                maxTs = allLocal[sId].ts;
                latestLocal = allLocal[sId];
            }
        }
        if (latestLocal) Object.assign(latestLocal, { series_id: latestLocal.seriesId, volume_id: latestLocal.volume, chapter_key: latestLocal.chapter });
        latestBm = latestLocal;
    }

    if (!latestBm || !allData.series) {
        container.style.display = 'none';
        return;
    }

    const series = allData.series.find(s => String(s.id) === String(latestBm.series_id));
    if (!series) return;

    const vol = series.volumes.find(v => String(v.volume) === String(latestBm.volume_id));
    let chTitle = "Глава " + latestBm.chapter_key;
    if (vol) {
        const chAttr = vol.chapters.find(c => String(c.chapter) === String(latestBm.chapter_key));
        if (chAttr && chAttr.custom_name) chTitle = chAttr.custom_name;
    }
    const volTitle = vol && vol.custom_name ? vol.custom_name : "Том " + latestBm.volume_id;

    container.style.display = 'block';
    container.innerHTML = `
        <div class="continue-reading-card" onclick="jumpToLastRead(event, '${series.id}')">
            <div class="continue-reading-icon">🔖</div>
            <div class="continue-reading-info">
                <div class="continue-reading-label">Продолжить чтение</div>
                <h3 class="continue-reading-title">${series.title}</h3>
                <p class="continue-reading-chapter">${volTitle}, ${chTitle}</p>
            </div>
            <div class="continue-reading-arrow">→</div>
        </div>
    `;
}


// ==========================================================================
// IMAGE LIGHTBOX
// ==========================================================================

let lightboxImages = [];
let lightboxIdx = 0;
let lightboxZoomed = false;

function initLightbox() {
    const container = document.getElementById('reader-text');
    if (!container) return;
    const imgs = container.querySelectorAll('img');
    lightboxImages = Array.from(imgs);

    imgs.forEach((img, i) => {
        img.style.cursor = 'zoom-in';
        img.onclick = (e) => {
            e.preventDefault();
            e.stopPropagation();
            openLightbox(i);
        };
    });
}

function openLightbox(idx) {
    if (lightboxImages.length === 0) return;
    lightboxIdx = idx;
    lightboxZoomed = false;
    const overlay = document.getElementById('lightbox-overlay');
    const img = document.getElementById('lightbox-img');
    img.src = lightboxImages[idx].src;
    img.classList.remove('zoomed');
    img.style.transform = '';
    overlay.classList.remove('hidden');
    updateLightboxNav();
    document.body.style.overflow = 'hidden';
}

function closeLightbox() {
    document.getElementById('lightbox-overlay').classList.add('hidden');
    document.body.style.overflow = '';
    lightboxZoomed = false;
}

function lightboxNavigate(delta) {
    const newIdx = lightboxIdx + delta;
    if (newIdx >= 0 && newIdx < lightboxImages.length) {
        lightboxIdx = newIdx;
        const img = document.getElementById('lightbox-img');
        img.src = lightboxImages[lightboxIdx].src;
        img.classList.remove('zoomed');
        img.style.transform = '';
        lightboxZoomed = false;
        updateLightboxNav();
    }
}

function updateLightboxNav() {
    document.getElementById('lightbox-prev').disabled = lightboxIdx === 0;
    document.getElementById('lightbox-next').disabled = lightboxIdx >= lightboxImages.length - 1;
    document.getElementById('lightbox-counter').textContent = `${lightboxIdx + 1} / ${lightboxImages.length}`;
    if (lightboxImages.length <= 1) {
        document.getElementById('lightbox-prev').style.display = 'none';
        document.getElementById('lightbox-next').style.display = 'none';
        document.getElementById('lightbox-counter').style.display = 'none';
    } else {
        document.getElementById('lightbox-prev').style.display = '';
        document.getElementById('lightbox-next').style.display = '';
        document.getElementById('lightbox-counter').style.display = '';
    }
}

// Toggle zoom on click + ★ Swipe-to-close (пункт 10)
let lbTouchStartY = 0;
let lbTouchDeltaY = 0;
let lbSwiping = false;

document.addEventListener('DOMContentLoaded', () => {
    const lbImg = document.getElementById('lightbox-img');
    const lbWrapper = document.getElementById('lightbox-image-wrapper');

    if (lbImg) {
        lbImg.addEventListener('click', () => {
            if (lbSwiping) return; // Не зумить после свайпа
            lightboxZoomed = !lightboxZoomed;
            lbImg.classList.toggle('zoomed', lightboxZoomed);
            lbImg.style.transform = lightboxZoomed ? 'scale(2)' : '';
        });
    }

    if (lbWrapper) {
        // ★ Свайп вниз для закрытия Lightbox
        lbWrapper.addEventListener('touchstart', (e) => {
            if (lightboxZoomed) return;
            lbTouchStartY = e.touches[0].clientY;
            lbSwiping = false;
            lbWrapper.style.transition = 'none';
        }, { passive: true });

        lbWrapper.addEventListener('touchmove', (e) => {
            if (lightboxZoomed) return;
            lbTouchDeltaY = e.touches[0].clientY - lbTouchStartY;
            if (Math.abs(lbTouchDeltaY) > 10) {
                lbSwiping = true;
                const opacity = Math.max(0, 1 - Math.abs(lbTouchDeltaY) / 300);
                lbWrapper.style.transform = `translateY(${lbTouchDeltaY}px)`;
                document.getElementById('lightbox-overlay').style.background = `rgba(0,0,0,${0.95 * opacity})`;
            }
        }, { passive: true });

        lbWrapper.addEventListener('touchend', () => {
            if (lightboxZoomed) return;
            lbWrapper.style.transition = '';
            if (Math.abs(lbTouchDeltaY) > 120) {
                // Порог — закрыть
                haptic('light');
                closeLightbox();
            }
            lbWrapper.style.transform = '';
            document.getElementById('lightbox-overlay').style.background = '';
            setTimeout(() => { lbSwiping = false; }, 100);
            lbTouchDeltaY = 0;
        }, { passive: true });
    }
});

// ==========================================================================
// TABLE OF CONTENTS (ToC)
// ==========================================================================

let tocItems = [];
let tocObserver = null;

function buildToC() {
    const tocList = document.getElementById('toc-list');
    if (!tocList) return;

    if (!currentChapters || currentChapters.length === 0) {
        tocList.innerHTML = '<div class="no-chapters">Список глав пуст</div>';
        return;
    }

    // Проверка что currentSeries и currentVolume существуют
    if (!currentSeries || !currentVolume) {
        tocList.innerHTML = '<div class="no-chapters">Данные серии не загружены</div>';
        return;
    }

    tocList.innerHTML = currentChapters.map((ch, idx) => {
        const isActive = idx === currentChapterIdx;
        const isRead = readChapters[ch.id || `${currentSeries.id}_v${currentVolume.volume}_ch${ch.chapter}`];
        return `
            <div class="toc-item ${isActive ? 'active' : ''} ${isRead ? 'read' : ''}" 
                 onclick="openChapter(${idx}); toggleToC();">
                <span class="toc-num">${idx + 1}.</span>
                <span class="toc-name">${ch.custom_name || 'Глава ' + ch.chapter}</span>
                ${isActive ? '<span class="toc-status-icon">📍</span>' : (isRead ? '<span class="toc-status-icon">✓</span>' : '')}
            </div>
        `;
    }).join('');

    // Скролл к активной главе в списке
    setTimeout(() => {
        const activeItem = tocList.querySelector('.toc-item.active');
        if (activeItem) {
            activeItem.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
    }, 100);
}



function highlightToCItem(idx) {
    document.querySelectorAll('.toc-item').forEach((item, i) => {
        item.classList.toggle('active', i === idx);
    });
}

function scrollToHeading(idx) {
    if (!tocItems[idx]) return;
    // Используем ручной offsetTop вместо scrollIntoView (на iOS/Telegram WebView скролит body, а не контейнер)
    const content = document.getElementById('reader-content');
    if (content) {
        content.scrollTo({ top: tocItems[idx].offsetTop - 60, behavior: 'smooth' });
    }
    toggleToC(); // Close sidebar
}

function toggleToC() {
    document.getElementById('toc-overlay').classList.toggle('active');
    document.getElementById('toc-panel').classList.toggle('active');
}

// ==========================================================================
// AUTOSCROLL
// ==========================================================================

let autoscrollActive = false;
let autoscrollEnabled = false; // Setting toggle
let autoscrollSpeed = 3;
let autoscrollRAF = null;

function toggleAutoscrollSetting(enabled) {
    autoscrollEnabled = enabled;
    const fab = document.getElementById('autoscroll-fab');
    const speedGroup = document.getElementById('autoscroll-speed-group');
    if (fab) fab.classList.toggle('hidden', !enabled);
    if (speedGroup) speedGroup.style.display = enabled ? 'block' : 'none';
    if (!enabled) stopAutoscroll();
}

function setAutoscrollSpeed(val) {
    autoscrollSpeed = parseInt(val);
}

function toggleAutoscroll() {
    if (autoscrollActive) {
        stopAutoscroll();
    } else {
        startAutoscroll();
    }
}

function startAutoscroll() {
    autoscrollActive = true;
    const fab = document.getElementById('autoscroll-fab');
    if (fab) {
        fab.classList.add('scrolling');
        fab.textContent = '⏸';
    }
    const el = document.getElementById('reader-content');
    if (!el) return;

    let lastTime = null;
    function step(ts) {
        if (!autoscrollActive) return;
        if (lastTime !== null) {
            const dt = ts - lastTime;
            const px = (autoscrollSpeed * 0.3) * (dt / 16.67); // ~0.3px per speed unit per frame
            el.scrollTop += px;
            // Stop at bottom
            if (el.scrollTop >= el.scrollHeight - el.clientHeight) {
                stopAutoscroll();
                return;
            }
        }
        lastTime = ts;
        autoscrollRAF = requestAnimationFrame(step);
    }
    autoscrollRAF = requestAnimationFrame(step);
}

function stopAutoscroll() {
    autoscrollActive = false;
    if (autoscrollRAF) cancelAnimationFrame(autoscrollRAF);
    autoscrollRAF = null;
    const fab = document.getElementById('autoscroll-fab');
    if (fab) {
        fab.classList.remove('scrolling');
        fab.textContent = '▶';
    }
}

// Pause autoscroll on touch
document.addEventListener('DOMContentLoaded', () => {
    const rc = document.getElementById('reader-content');
    if (rc) {
        rc.addEventListener('touchstart', () => {
            if (autoscrollActive) stopAutoscroll();
        }, { passive: true });
    }
});

// ==========================================================================
// EDIT URL MODAL (Admin)
// ==========================================================================

let editUrlChapterIdx = null;

function openEditUrlModal(chIdx) {
    if (!currentChapters[chIdx]) return;
    editUrlChapterIdx = chIdx;
    const ch = currentChapters[chIdx];
    const chapName = ch.custom_name || `Глава ${ch.chapter}`;
    document.getElementById('edit-url-chapter-name').textContent = chapName;
    const currentUrl = (ch.urls && ch.urls.length > 0) ? ch.urls.join('\n') : (ch.url || '');
    document.getElementById('edit-url-input').value = currentUrl;
    document.getElementById('edit-url-overlay').classList.remove('hidden');
    document.getElementById('edit-url-modal').classList.remove('hidden');
    setTimeout(() => document.getElementById('edit-url-input').focus(), 350);
}

function closeEditUrlModal() {
    document.getElementById('edit-url-overlay').classList.add('hidden');
    document.getElementById('edit-url-modal').classList.add('hidden');
    editUrlChapterIdx = null;
}

async function saveEditUrl() {
    if (editUrlChapterIdx === null || !API_URL) return;
    const ch = currentChapters[editUrlChapterIdx];
    const newUrl = document.getElementById('edit-url-input').value.trim();

    const saveBtn = document.getElementById('edit-url-save');
    saveBtn.disabled = true;
    saveBtn.textContent = 'Сохранение...';

    try {
        const resp = await apiFetch(API_URL + '/api/chapters', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                series_id: currentSeries.id,
                volume: currentVolume.volume,
                chapter: ch.chapter,
                url: newUrl
            })
        });
        const result = await resp.json();
        if (result.ok) {
            // Update local data
            const urlArr = newUrl.split('\n').map(u => u.trim()).filter(u => u.length > 0);
            ch.urls = urlArr;
            ch.url = urlArr[0] || '';
            closeEditUrlModal();
            showToast('✅ Ссылка обновлена!');
        } else {
            showToast('Ошибка: ' + (result.error || 'неизвестная'));
        }
    } catch (e) {
        showToast('Ошибка сети: ' + e.message);
    } finally {
        saveBtn.disabled = false;
        saveBtn.textContent = '💾 Сохранить';
    }
}

// ==========================================================================
// BULK UPLOAD MODAL (Admin)
// ==========================================================================

function openBulkModal() {
    document.getElementById('bulk-upload-input').value = '';
    document.getElementById('bulk-upload-overlay').classList.remove('hidden');
    document.getElementById('bulk-upload-modal').classList.remove('hidden');
    setTimeout(() => document.getElementById('bulk-upload-input').focus(), 350);
}

function closeBulkModal() {
    document.getElementById('bulk-upload-overlay').classList.add('hidden');
    document.getElementById('bulk-upload-modal').classList.add('hidden');
}

async function executeBulkUpload() {
    if (!API_URL || !currentSeries || !currentVolume) return;
    const raw = document.getElementById('bulk-upload-input').value.trim();
    if (!raw) return showToast('Вставьте ссылки');

    const urls = raw.split('\n').map(u => u.trim()).filter(u => u.length > 0);
    if (urls.length === 0) return showToast('Нет валидных ссылок');

    const lastChNum = currentChapters.length > 0
        ? Math.max(...currentChapters.map(c => parseInt(c.chapter) || 0))
        : 0;

    const saveBtn = document.getElementById('bulk-upload-save');
    saveBtn.disabled = true;
    saveBtn.textContent = `Добавление ${urls.length} глав...`;

    try {
        const resp = await apiFetch(API_URL + '/api/chapters/bulk', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                series_id: currentSeries.id,
                volume: currentVolume.volume,
                start_chapter: lastChNum + 1,
                urls: urls
            })
        });
        const result = await resp.json();
        if (result.ok) {
            closeBulkModal();
            showToast(`✅ Добавлено ${result.added} глав!`);
            await loadData(); // Reload
        } else {
            showToast('Ошибка: ' + (result.error || 'неизвестная'));
        }
    } catch (e) {
        showToast('Ошибка сети: ' + e.message);
    } finally {
        saveBtn.disabled = false;
        saveBtn.textContent = '📤 Добавить';
    }
}

// ==========================================================================
// LIBRARY & STATS
// ==========================================================================

let readingStats = safeGetLocal('reader_stats', {timeSpentSeconds:0});

// Track reading time when in 'reader' screen
setInterval(() => {
    if (document.getElementById('screen-reader').classList.contains('active') && !document.hidden) {
        readingStats.timeSpentSeconds += 5;
        if (readingStats.timeSpentSeconds % 60 === 0) { // save every minute
            safeSetLocal('reader_stats', readingStats);
            updateLibraryStats();
        }
    }
}, 5000);

function updateLibraryStats() {
    const timeEl = document.getElementById('stat-time');
    const chEl = document.getElementById('stat-chapters');
    if (!timeEl || !chEl) return;

    // Total Chapters Read
    const totalChaptersRead = Object.keys(readChapters).length;
    chEl.textContent = totalChaptersRead;

    // Time Formatting
    const totalMinutes = Math.floor(readingStats.timeSpentSeconds / 60);
    const hours = Math.floor(totalMinutes / 60);
    const mins = totalMinutes % 60;

    if (hours > 0) {
        timeEl.textContent = `${hours} ч ${mins} м`;
    } else {
        timeEl.textContent = `${mins} м`;
    }
}

function setLibraryFilter(filter) {
    if (!Object.values(LIBRARY_FILTERS).includes(filter)) return;
    libraryFilter = filter;
    safeSetLocal(LIBRARY_FILTER_KEY, libraryFilter);
    updateLibraryFilterButtons();
    renderLibraryTab();
}

function updateLibraryFilterButtons() {
    const buttons = document.querySelectorAll('#library-filters [data-filter]');
    buttons.forEach((btn) => {
        btn.classList.toggle('active', btn.dataset.filter === libraryFilter);
    });
}

function getSeriesProgressMeta(series) {
    const volumes = Array.isArray(series?.volumes) ? series.volumes : [];
    const totalCh = volumes.reduce((sum, v) => sum + (v.chapters || []).length, 0);
    const readCount = volumes.reduce((sum, v) => {
        return sum + (v.chapters || []).filter((c) => isRead(series.id, v.volume, c.chapter)).length;
    }, 0);
    const progress = totalCh > 0 ? Math.round((readCount / totalCh) * 100) : 0;
    const lastRead = getLastRead(series.id);
    const status = readCount === 0
        ? LIBRARY_FILTERS.NOT_STARTED
        : (readCount >= totalCh && totalCh > 0 ? LIBRARY_FILTERS.COMPLETED : LIBRARY_FILTERS.IN_PROGRESS);

    return {
        series,
        totalCh,
        readCount,
        progress,
        lastRead,
        status
    };
}

function renderLibraryTabV2() {
    assertReaderState('renderLibraryTab:start');
    const list = document.getElementById('library-list');
    if (!list) return;
    updateLibraryFilterButtons();

    if (!allData || !allData.series || allData.series.length === 0) {
        renderStateBlock(list, {
            icon: '\uD83D\uDCC2',
            title: '\u041d\u0435\u0442 \u0434\u0430\u043d\u043d\u044b\u0445',
            description: '\u0411\u0438\u0431\u043b\u0438\u043e\u0442\u0435\u043a\u0430 \u043f\u0443\u0441\u0442\u0430. \u0414\u043e\u0431\u0430\u0432\u044c\u0442\u0435 \u043f\u0435\u0440\u0432\u044b\u0435 \u0433\u043b\u0430\u0432\u044b.'
        });
        return;
    }

    const seriesMeta = allData.series.map((series) => getSeriesProgressMeta(series));
    const filtered = seriesMeta
        .filter((meta) => meta.status === libraryFilter)
        .sort((a, b) => {
            const tsA = a.lastRead?.ts || 0;
            const tsB = b.lastRead?.ts || 0;
            if (tsA !== tsB) return tsB - tsA;
            if (a.progress !== b.progress) return b.progress - a.progress;
            return String(a.series.title || '').localeCompare(String(b.series.title || ''), 'ru');
        });

    if (filtered.length === 0) {
        const emptyTextByFilter = {
            [LIBRARY_FILTERS.IN_PROGRESS]: {
                icon: '📝',
                title: 'Нет тайтлов в процессе',
                desc: 'Начните чтение на вкладке «Главная».'
            },
            [LIBRARY_FILTERS.NOT_STARTED]: {
                icon: '📚',
                title: 'Всё начато',
                desc: 'Тайтлов со статусом «Не начато» пока нет.'
            },
            [LIBRARY_FILTERS.COMPLETED]: {
                icon: '✅',
                title: 'Ещё нет завершённых',
                desc: 'Закончите хотя бы один тайтл — он появится здесь.'
            }
        };
        const empty = emptyTextByFilter[libraryFilter] || emptyTextByFilter[LIBRARY_FILTERS.IN_PROGRESS];
        renderStateBlock(list, {
            icon: empty.icon,
            title: empty.title,
            description: empty.desc
        });
        return;
    }

    const itemsHtml = filtered.map((meta) => {
        const s = meta.series;
        const bm = meta.lastRead;
        if (!s) return '';

        let locationText = 'История ещё не начата';
        if (bm) {
            const v = s.volumes.find((x) => String(x.volume) === String(bm.volume));
            let chTitle = `Глава ${bm.chapter}`;
            if (v) {
                const ch = (v.chapters || []).find((c) => String(c.chapter) === String(bm.chapter));
                if (ch && ch.custom_name) chTitle = ch.custom_name;
            }
            const volTitle = v && v.custom_name ? v.custom_name : `Том ${bm.volume}`;
            locationText = `Остановлено: ${volTitle}, ${chTitle}`;
        }

        const progressText = `${meta.readCount}/${meta.totalCh || 0}`;
        const coverImg = s.cover_url ? `<img src="${s.cover_url}" class="library-cover" alt="">` : `<div class="series-icon">📖</div>`;
        const quickAction = bm
            ? `<button class="series-action-btn primary" onclick="jumpToLastRead(event, '${s.id}')">Продолжить</button>`
            : `<button class="series-action-btn" onclick="jumpToLatestChapter(event, '${s.id}')">К последней</button>`;

        return `
        <div class="series-card" style="margin-bottom:12px;" onclick="selectSeries('${s.id}')">
            ${coverImg}
            <div class="series-info">
                <h3>${escapeHtml(s.title)}</h3>
                <p style="font-size: 13px; color: var(--text-sec); margin-top:2px;">${locationText}</p>
                <div class="library-progress-bar">
                    <div class="library-progress-fill" style="width: ${meta.progress}%"></div>
                </div>
                <div style="font-size: 11px; margin-top:4px; text-align:right; color: var(--text-sec);">
                    ${progressText} &middot; ${meta.progress}% прочитано
                </div>
                <div class="series-actions">${quickAction}</div>
            </div>
            <span class="series-arrow">&rsaquo;</span>
        </div>`;
    }).join('');

    list.innerHTML = itemsHtml;
}

function renderLibraryTab() {
    return renderLibraryTabV2();
}



// ==========================================================================
// DRAG-N-DROP CHAPTER SORT (Admin, Batch 3)
// ==========================================================================

let dragSrcIdx = null;

function cleanupChapterDnD() {
    const container = document.getElementById('chapters-list');
    if (!container) return;
    const items = container.querySelectorAll('.chapter-item[draggable="true"]');
    items.forEach(item => {
        item.removeEventListener('dragstart', handleDragStart);
        item.removeEventListener('dragover', handleDragOver);
        item.removeEventListener('drop', handleDrop);
        item.removeEventListener('dragend', handleDragEnd);
        item.removeEventListener('dragenter', handleDragEnter);
        item.removeEventListener('dragleave', handleDragLeave);
        const handle = item.querySelector('.drag-handle');
        if (handle) handle.removeEventListener('touchstart', touchDragStart);
    });
}

function initChapterDnD() {
    const container = document.getElementById('chapters-list');
    if (!container) return;

    const items = container.querySelectorAll('.chapter-item[draggable="true"]');
    items.forEach(item => {
        item.addEventListener('dragstart', handleDragStart);
        item.addEventListener('dragover', handleDragOver);
        item.addEventListener('drop', handleDrop);
        item.addEventListener('dragend', handleDragEnd);
        item.addEventListener('dragenter', handleDragEnter);
        item.addEventListener('dragleave', handleDragLeave);
    });

    // Mobile touch DnD polyfill
    items.forEach(item => {
        const handle = item.querySelector('.drag-handle');
        if (handle) {
            handle.addEventListener('touchstart', touchDragStart, { passive: false });
        }
    });
}

function handleDragStart(e) {
    dragSrcIdx = parseInt(this.dataset.chapterIdx);
    this.classList.add('dragging');
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', dragSrcIdx);
}

function handleDragOver(e) {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
}

function handleDragEnter(e) {
    this.classList.add('drag-over');
}

function handleDragLeave(e) {
    this.classList.remove('drag-over');
}

function handleDrop(e) {
    e.preventDefault();
    this.classList.remove('drag-over');
    const destIdx = parseInt(this.dataset.chapterIdx);
    if (dragSrcIdx !== null && dragSrcIdx !== destIdx) {
        reorderChapters(dragSrcIdx, destIdx);
    }
}

function handleDragEnd(e) {
    document.querySelectorAll('.chapter-item').forEach(item => {
        item.classList.remove('dragging', 'drag-over');
    });
    dragSrcIdx = null;
}

// Touch drag support
let touchDragItem = null;
let touchDragClone = null;
let touchStartY = 0;

function touchDragStart(e) {
    e.preventDefault();
    const item = e.target.closest('.chapter-item');
    if (!item) return;

    touchDragItem = item;
    dragSrcIdx = parseInt(item.dataset.chapterIdx);
    touchStartY = e.touches[0].clientY;

    item.classList.add('dragging');

    document.addEventListener('touchmove', touchDragMove, { passive: false });
    document.addEventListener('touchend', touchDragEnd);
}

function touchDragMove(e) {
    e.preventDefault();
    const touch = e.touches[0];
    const elements = document.elementsFromPoint(touch.clientX, touch.clientY);
    const target = elements.find(el => el.classList.contains('chapter-item') && el !== touchDragItem);

    document.querySelectorAll('.chapter-item').forEach(item => item.classList.remove('drag-over'));
    if (target) target.classList.add('drag-over');
}

function touchDragEnd(e) {
    document.removeEventListener('touchmove', touchDragMove);
    document.removeEventListener('touchend', touchDragEnd);

    const touch = e.changedTouches[0];
    const elements = document.elementsFromPoint(touch.clientX, touch.clientY);
    const target = elements.find(el => el.classList.contains('chapter-item') && el !== touchDragItem);

    if (target && dragSrcIdx !== null) {
        const destIdx = parseInt(target.dataset.chapterIdx);
        if (dragSrcIdx !== destIdx) {
            reorderChapters(dragSrcIdx, destIdx);
        }
    }

    document.querySelectorAll('.chapter-item').forEach(item => {
        item.classList.remove('dragging', 'drag-over');
    });
    touchDragItem = null;
    dragSrcIdx = null;
}

async function reorderChapters(fromIdx, toIdx) {
    // Reorder locally
    const [moved] = currentChapters.splice(fromIdx, 1);
    currentChapters.splice(toIdx, 0, moved);

    // Re-render
    renderChaptersList();

    // Sync with server if available
    if (!API_URL) return;

    const order = currentChapters.map(c => c.chapter);
    try {
        await apiFetch(API_URL + '/api/sort', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                series_id: currentSeries.id,
                volume: currentVolume.volume,
                order: order
            })
        });
    } catch (e) {
        console.warn('Sort sync error:', e);
    }
}

// ==========================================================================
// COVER IMAGES (Batch 3)
// ==========================================================================

function getSeriesCover(series) {
    if (series.cover_url) {
        return `<img src="${series.cover_url}" class="series-cover-img" alt="${series.title}" loading="lazy">`;
    }
    const icons = ['📖', '📕', '📗', '📘', '📙'];
    const idx = allData.series.indexOf(series) % icons.length;
    return `<div class="series-icon">${icons[idx]}</div>`;
}


// ==========================================================================
// РЕПОРТ ОПЕЧАТОК (TYPO REPORTER)
// ==========================================================================

let _typoReporterInitialized = false;
function initTypoReporter() {
    if (_typoReporterInitialized) return;
    _typoReporterInitialized = true;
    
    const readerContent = document.getElementById('reader-content');
    if (!readerContent) return;

    // Используем существующий тултип из HTML (не создаём дубликат)
    const tooltip = document.getElementById('typo-tooltip');
    if (tooltip) {
        // Заменяем onclick на pointerdown чтобы не сбрасывать выделение
        tooltip.onclick = null;
        tooltip.removeAttribute('onclick');
        tooltip.onpointerdown = (e) => {
            e.preventDefault(); // Предотвращаем сброс выделения
            e.stopPropagation();
            showTypoModal();
        };
    }

    // Слушаем выделение
    document.addEventListener('selectionchange', handleSelection);
    document.addEventListener('mouseup', handleSelection);
}

function handleSelection() {
    const readerScreen = document.getElementById('screen-reader');
    if (!readerScreen || !readerScreen.classList.contains('active')) return;

    const selection = window.getSelection();
    const tooltip = document.getElementById('typo-tooltip');

    if (!selection.rangeCount || selection.isCollapsed || selection.toString().trim().length < 2) {
        if (tooltip) tooltip.classList.remove('visible');
        return;
    }

    const range = selection.getRangeAt(0);
    const selectedText = selection.toString().trim();

    // Проверяем, что выделение внутри reader-content
    const readerContent = document.getElementById('reader-content');
    if (!readerContent.contains(range.commonAncestorContainer)) {
        if (tooltip) tooltip.classList.remove('visible');
        return;
    }

    // Ограничиваем длину выделения
    if (selectedText.length > 100) {
        if (tooltip) tooltip.classList.remove('visible');
        return;
    }

    typoSelectedText = selectedText;
    typoSelectionRange = range.cloneRange();
    suppressReaderTapToScroll(1200);

    // Получаем контекст (текст вокруг) точнее, используя позицию в узле
    const startNode = range.startContainer;
    const fullText = startNode.textContent || "";
    const startIdx = Math.max(0, range.startOffset - 60);
    const endIdx = Math.min(fullText.length, range.endOffset + 60);
    typoContextText = fullText.substring(startIdx, endIdx);

    // Позиционируем тултип
    const rect = range.getBoundingClientRect();
    if (tooltip) {
        tooltip.style.left = `${rect.left + rect.width / 2}px`;
        tooltip.style.top = `${rect.top + window.scrollY}px`;
        tooltip.classList.add('visible');
    }
}

function showTypoModal() {
    const modal = document.getElementById('typo-modal');
    const overlay = document.getElementById('typo-modal-overlay');
    const contextEl = document.getElementById('typo-modal-context');
    const tooltip = document.getElementById('typo-tooltip');

    if (tooltip) tooltip.classList.remove('visible');

    // Подсвечиваем опечатку в контексте для модалки
    const escapedSelected = typoSelectedText.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const highlightedContext = typoContextText.replace(
        new RegExp(escapedSelected, 'g'),
        `<span class="typo-modal-selected">${typoSelectedText}</span>`
    );

    contextEl.innerHTML = `"...${highlightedContext}..."`;
    document.getElementById('typo-comment').value = '';

    modal.classList.remove('hidden');
    overlay.classList.remove('hidden');

    // Снимаем выделение в тексте
    window.getSelection().removeAllRanges();
}

function closeTypoModal() {
    document.getElementById('typo-modal').classList.add('hidden');
    document.getElementById('typo-modal-overlay').classList.add('hidden');
}

async function submitTypoReport() {
    if (!API_URL) {
        showToast('Репорты доступны только в онлайн-режиме.');
        return;
    }

    const comment = document.getElementById('typo-comment').value.trim();
    const btn = document.getElementById('typo-submit-btn');
    const originalText = btn.innerText;

    const chapter = currentChapters[currentChapterIdx];
    if (!chapter) return;

    const chapter_key = `${currentSeries.id}_v${currentVolume.volume}_ch${chapter.chapter}`;

    try {
        btn.disabled = true;
        btn.innerText = '⌛ Отправка...';

        const resp = await apiFetch(`${API_URL}/api/typo`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                chapter_key,
                selected_text: typoSelectedText,
                context_text: typoContextText,
                comment: comment
            })
        });

        const result = await resp.json();
        if (result.ok) {
            tg.HapticFeedback.notificationOccurred('success');
            showToast('✅ Спасибо! Репорт об опечатке отправлен.');
            closeTypoModal();
        } else {
            showToast('Ошибка: ' + (result.error || 'неизвестная'));
        }
    } catch (e) {
        showToast('Ошибка сети: ' + e.message);
    } finally {
        btn.disabled = false;
        btn.innerText = originalText;
    }
}

// Глобальный перехватчик — закрывает FAB при клике вне контейнера
// (действия кнопок .fab-menu-item обрабатываются через data-action в HTML onclick)
document.addEventListener('click', (e) => {
    const fabContainer = e.target.closest('.fab-container');
    const menu = document.getElementById('fab-menu');

    if (!fabContainer && menu && menu.classList.contains('fab-menu-visible')) {
        toggleFab(); // Закрываем при клике мимо
    }
});

// ==========================================================================
// ★ HAPTIC FEEDBACK HELPER (пункт 8)
// ==========================================================================

function haptic(style = 'light') {
    try {
        if (tg && tg.HapticFeedback) {
            if (style === 'success') tg.HapticFeedback.notificationOccurred('success');
            else if (style === 'error') tg.HapticFeedback.notificationOccurred('error');
            else tg.HapticFeedback.impactOccurred(style);
        }
    } catch (e) { }
}

// === Custom Toasts ===
function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;

    let icon = '';
    if (type === 'success') icon = '<svg class="icon-sm" viewBox="0 0 24 24"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/><polyline points="22 4 12 14.01 9 11.01" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>';
    else if (type === 'error') icon = '<svg class="icon-sm" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10" fill="none" stroke="currentColor" stroke-width="2"/><line x1="15" y1="9" x2="9" y2="15" fill="none" stroke="currentColor" stroke-width="2"/><line x1="9" y1="9" x2="15" y2="15" fill="none" stroke="currentColor" stroke-width="2"/></svg>';
    else icon = '<svg class="icon-sm" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10" fill="none" stroke="currentColor" stroke-width="2"/><line x1="12" y1="16" x2="12" y2="12" fill="none" stroke="currentColor" stroke-width="2"/><line x1="12" y1="8" x2="12.01" y2="8" fill="none" stroke="currentColor" stroke-width="2"/></svg>';

    toast.innerHTML = `${icon}<span>${message}</span>`;
    container.appendChild(toast);

    setTimeout(() => toast.classList.add('show'), 10);
    setTimeout(() => {
        toast.classList.remove('show');
        setTimeout(() => toast.remove(), 400);
    }, 3000);
}

// === Fab Menu ===
let fabTimeout = null;

function toggleFab() {
    const btn = document.getElementById('fab-btn');
    const menu = document.getElementById('fab-menu');
    const close = document.getElementById('fab-icon-close');

    if (!btn || !menu) return;

    if (fabTimeout) {
        clearTimeout(fabTimeout);
        fabTimeout = null;
    }

    const isOpening = !btn.classList.contains('fab-open');
    haptic('medium');

    if (isOpening) {
        menu.classList.remove('hidden');
        if (close) close.classList.remove('hidden');
        requestAnimationFrame(() => {
            requestAnimationFrame(() => {
                btn.classList.add('fab-open');
                menu.classList.add('fab-menu-visible');
            });
        });
    } else {
        btn.classList.remove('fab-open');
        menu.classList.remove('fab-menu-visible');
        fabTimeout = setTimeout(() => menu.classList.add('hidden'), 400);
    }
}

function fabAction(action) {
    toggleFab(); // Close first
    if (action === 'toc') toggleToC();
    else if (action === 'autoscroll') {
        const toggle = document.getElementById('autoscroll-toggle');
        if (toggle) {
            toggle.checked = !toggle.checked;
            toggleAutoscrollSetting(toggle.checked);
            showToast(toggle.checked ? 'Автоскролл включен' : 'Автоскролл выключен');
        } else {
            // Backup if toggle is missing
            toggleAutoscrollSetting(!autoscrollEnabled);
            showToast(autoscrollEnabled ? 'Автоскролл включен' : 'Автоскролл выключен');
        }
    } else if (action === 'comments') {
        const social = document.getElementById('social-section');
        const content = document.getElementById('reader-content');
        if (social && content) {
            content.scrollTo({
                top: social.offsetTop,
                behavior: 'smooth'
            });
        }
    }
}

// ==========================================================================
// ADMIN FLOATING MENU (Phase 4)
// ==========================================================================

function toggleAdminMenu() {
    const btn = document.getElementById('admin-fab-btn');
    const menu = document.getElementById('admin-menu');
    if (!btn || !menu) return;

    const isOpen = btn.classList.contains('open');
    haptic('medium');

    if (!isOpen) {
        btn.classList.add('open');
        menu.classList.remove('hidden');
    } else {
        closeAdminMenu();
    }
}

function closeAdminMenu() {
    const btn = document.getElementById('admin-fab-btn');
    const menu = document.getElementById('admin-menu');
    if (btn) btn.classList.remove('open');
    if (menu) menu.classList.add('hidden');
}

function renameChapterCurrent() {
    closeAdminMenu();
    const ch = currentChapters[currentChapterIdx];
    if (!ch || !currentSeries || !currentVolume) return;
    
    // Use the existing core rename logic
    renameItem(`chap_${currentSeries.id}_${currentVolume.volume}_${ch.chapter}`);
}

// === Gestures: Swipe Back & Pull to Next ===
let touchStartX = 0;
let gestureTouchStartY = 0;
let isSwipeActive = false;
let isGlobalPullingNext = false; // Переименовано чтобы избежать конфликтов (Баг 2)

const SWIPE_EDGE_MAX_X = 35;
const SWIPE_MIN_DELTA_X = 10;
const SWIPE_MAX_DELTA_Y = 40;
const SWIPE_TRIGGER_THRESHOLD = 85;

function initGestures() {
    const reader = document.getElementById('screen-reader');
    const content = document.getElementById('reader-content');
    const indicator = document.getElementById('swipe-back-indicator');
    const pullNext = document.getElementById('pull-next-indicator');

    if (!reader || !content || !indicator || !pullNext) return;

    reader.addEventListener('pointerdown', (e) => {
        touchStartX = e.clientX;
        gestureTouchStartY = e.clientY;
        isSwipeActive = touchStartX < SWIPE_EDGE_MAX_X; // edge detection
    }, { passive: true });

    reader.addEventListener('pointermove', (e) => {
        if (!isSwipeActive) return;
        let deltaX = e.clientX - touchStartX;
        let deltaY = Math.abs(e.clientY - gestureTouchStartY);

        // Добавлен порог по Y чтобы не срабатывало при скролле (Баг 1)
        if (deltaX > SWIPE_MIN_DELTA_X && deltaY < SWIPE_MAX_DELTA_Y) { 
            indicator.style.opacity = Math.min(deltaX / 100, 0.8);
            // Сохраняем translateY(-50%) для центрирования (Баг 3)
            indicator.style.transform = `translateY(-50%) scaleY(${Math.min(0.5 + deltaX / 200, 1)}) translateX(${deltaX / 2}px)`;
        }
    }, { passive: true });

    reader.addEventListener('pointerup', (e) => {
        let deltaX = e.clientX - touchStartX;
        indicator.style.opacity = 0;
        indicator.style.transform = 'translateY(-50%) translateX(-100%)'; 

        if (isSwipeActive && deltaX > SWIPE_TRIGGER_THRESHOLD) {
            haptic('medium');
            backFromReader();
        }
        isSwipeActive = false;
    }, { passive: true });

    // Pull-to-next logic at bottom (Hybrid Touch/Mouse version for maximum compatibility)
    let pullTouchStartY = 0;
    let pullDistance = 0;
    const pullNextText = document.getElementById('pull-next-text');
    const pullNextArrow = pullNext.querySelector('.pull-next-arrow');

    const onStart = (e) => {
        const scrollTop = content.scrollTop;
        const scrollHeight = content.scrollHeight;
        const clientHeight = content.clientHeight;
        
        // Для мыши (ПК) начинаем жест только если мы УЖЕ внизу страницы, 
        // чтобы не ломать выделение текста и клики в середине контента.
        if (!e.touches && (scrollTop + clientHeight < scrollHeight - 50)) {
            pullTouchStartY = 0;
            return;
        }

        pullTouchStartY = e.touches ? e.touches[0].clientY : e.clientY;
        pullDistance = 0;
        isGlobalPullingNext = false;
    };

    const onMove = (e) => {
        if (currentChapterIdx >= currentChapters.length - 1 || pullTouchStartY === 0) return;
        
        const touchY = e.touches ? e.touches[0].clientY : e.clientY;
        const scrollTop = content.scrollTop;
        const scrollHeight = content.scrollHeight;
        const clientHeight = content.clientHeight;

        // Если мы внизу или уже тянем (используем порог 1px для точности на ПК)
        if (isGlobalPullingNext || (Math.ceil(scrollTop + clientHeight) >= scrollHeight - 1)) {
            let diff = pullTouchStartY - touchY;

            if (diff > 15) { 
                if (!isGlobalPullingNext) {
                    isGlobalPullingNext = true;
                    haptic('light');
                }
                // На мобилках принудительно отменяем скролл чтобы жесту ничто не мешало
                if (e.cancelable && e.touches) e.preventDefault(); 
                
                pullDistance = diff;
                pullNext.style.display = 'flex';
                pullNext.style.opacity = Math.min(diff / 100, 1);

                if (diff > 80) {
                    if (pullNextText) pullNextText.textContent = 'Отпустите для следующей главы';
                    if (pullNextArrow) pullNextArrow.style.transform = 'rotate(180deg)';
                } else {
                    if (pullNextText) pullNextText.textContent = 'Тяните для следующей главы';
                    if (pullNextArrow) pullNextArrow.style.transform = 'rotate(0deg)';
                }
            } else if (isGlobalPullingNext && diff < 5) {
                isGlobalPullingNext = false;
                pullNext.style.display = 'none';
                pullDistance = 0;
            }
        }
    };

    const onEnd = () => {
        if (isGlobalPullingNext && pullDistance > 80) {
            haptic('medium');
            navigateChapter(1);
        }
        pullNext.style.display = 'none';
        pullDistance = 0;
        isGlobalPullingNext = false;
        if (pullNextArrow) pullNextArrow.style.transform = 'rotate(0deg)';
    };

    // Используем раздельные слушатели для Touch и Mouse чтобы избежать pointercancel от pan-y
    content.addEventListener('touchstart', onStart, { passive: true });
    content.addEventListener('touchmove', onMove, { passive: false });
    content.addEventListener('touchend', onEnd);

    content.addEventListener('mousedown', onStart);
    document.addEventListener('mousemove', (e) => { if (pullTouchStartY && !e.touches) onMove(e); });
    document.addEventListener('mouseup', () => { if (pullTouchStartY) { onEnd(); pullTouchStartY = 0; } });
}

function initReaderScrollListeners() {
    const content = document.getElementById('reader-content');
    const screen = document.getElementById('screen-reader');
    const progressBar = document.getElementById('reading-progress-bar');
    if (!content || !screen || !progressBar) return;

    let lastScrollTop = 0;
    const threshold = 15;

    content.addEventListener('scroll', () => {
        const scrollTop = content.scrollTop;
        const scrollHeight = content.scrollHeight - content.clientHeight;
        
        // 1. Прогресс-бар
        const progress = (scrollTop / Math.max(1, scrollHeight)) * 100;
        progressBar.style.width = `${progress}%`;

        // 2. Immersive Scroll (Скрытие UI при скролле вниз)
        if (Math.abs(scrollTop - lastScrollTop) > threshold) {
            if (scrollTop > lastScrollTop && scrollTop > 100) {
                screen.classList.add('immersive');
                // Закрываем FAB при скролле вниз
                const fab = document.getElementById('fab-menu');
                if (fab && !fab.classList.contains('hidden')) toggleFab();
            } else if (scrollTop < lastScrollTop - 5) {
                screen.classList.remove('immersive');
            }
            lastScrollTop = scrollTop;
        }

        // 3. Автосохранение позиции
        clearTimeout(scrollSaveTimer);
        scrollSaveTimer = setTimeout(saveScrollPosition, 1000);

        // 4. Prefetch следующей главы (при 85%)
        if (progress > 85) {
            prefetchNextChapter();
        }
    }, { passive: true });
}

// Optimistic chapter reactions with rollback on network/server errors.
async function toggleReaction(type) {
    if (!API_URL || !userId) {
        showToast('Авторизуйтесь в боте для реакций');
        return;
    }
    if (_isReacting) return;

    const key = getChapterKey();
    if (!key) return;

    _isReacting = true;
    const emojiMap = { like: '👍', heart: '❤️', fire: '🔥', funny: '😂', wow: '😮', sad: '😢', battle: '⚔️' };
    const prevState = {
        reactions: { ...(chapterReactionsState?.reactions || {}) },
        user_reaction: chapterReactionsState?.user_reaction || null
    };
    const nextState = {
        reactions: { ...(prevState.reactions || {}) },
        user_reaction: prevState.user_reaction
    };
    const prevType = prevState.user_reaction;

    haptic('medium');
    if (prevType !== type) {
        nextState.reactions[type] = Number(nextState.reactions[type] || 0) + 1;
        if (prevType) {
            nextState.reactions[prevType] = Math.max(0, Number(nextState.reactions[prevType] || 0) - 1);
        }
        nextState.user_reaction = type;
    } else {
        nextState.reactions[type] = Math.max(0, Number(nextState.reactions[type] || 0) - 1);
        nextState.user_reaction = null;
    }

    chapterReactionsState = nextState;
    renderReactions(chapterReactionsState);

    const itemEl = document.querySelector(`.reaction-item.type-${type}`);
    if (itemEl && !itemEl.classList.contains('active')) {
        spawnFloatingEmoji(emojiMap[type] || '✨', itemEl);
    }
    if (itemEl) {
        itemEl.classList.add('pending');
    }

    try {
        const resp = await apiFetch(API_URL + '/api/reactions', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                chapter_key: key,
                reaction: type
            })
        });
        const data = await resp.json();
        if (!data.ok) {
            throw new Error(data.error || 'Ошибка реакции');
        }
        loadReactions();
    } catch (e) {
        chapterReactionsState = prevState;
        renderReactions(chapterReactionsState);
        showToast('Ошибка сети. Реакция откатена.');
    } finally {
        _isReacting = false;
    }
}

assertReaderState('bootstrap');
bindGlobalErrorTelemetry();
bindNetworkStatusListeners();
registerReaderServiceWorker();
bindReaderKeyboardAwareUI();
updateLibraryFilterButtons();
restoreSettings();
loadData();
initTypoReporter();
initGestures();
initReaderScrollListeners();
