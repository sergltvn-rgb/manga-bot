// ==========================================================================
// Читалка ранобэ — JavaScript v3
// Загрузка/отображение, прогресс чтения, лайки, комментарии
// ==========================================================================

const tg = (window.Telegram && window.Telegram.WebApp) ? window.Telegram.WebApp : { expand: () => {}, ready: () => {}, openTelegramLink: (url) => window.open(url, '_blank'), initDataUnsafe: {} };
tg.expand();
tg.ready();

const initialSearchParams = new URLSearchParams(window.location.search);
const initialStartParam = tg.initDataUnsafe?.start_param || initialSearchParams.get('tgWebAppStartParam') || '';
const giveawayStartMatch = String(initialStartParam).match(/^giveaway_(\d+)$/);
if (giveawayStartMatch) {
    const target = new URL('giveaway.html', window.location.href);
    target.searchParams.set('giveaway_id', giveawayStartMatch[1]);
    for (const key of ['api', 'rev']) {
        const value = initialSearchParams.get(key);
        if (value) target.searchParams.set(key, value);
    }
    window.location.replace(target.toString());
}

function openChannel() {
    if (window.Telegram && window.Telegram.WebApp) {
        window.Telegram.WebApp.openTelegramLink('https://t.me/alya_novel');
    } else {
        window.open('https://t.me/alya_novel', '_blank');
    }
}

// === Telegram User ===
const tgUser = tg.initDataUnsafe?.user || {};
let userId = String(tgUser.id || '');
let userName = tgUser.first_name || 'Аноним';
let webAuthUser = null;
let webAuthLoaded = false;

function hasTelegramAuth() {
    return Boolean(userId && tg && tg.initData);
}

function hasSiteAuth() {
    return Boolean(!hasTelegramAuth() && webAuthUser && webAuthUser.id);
}

function hasWriteAuth() {
    return hasTelegramAuth() || hasSiteAuth();
}

function isPublicReadMode() {
    return !hasWriteAuth();
}

function applyAuthUser(user) {
    webAuthUser = user && user.id ? user : null;
    if (hasTelegramAuth()) {
        userId = String(tgUser.id || '');
        userName = tgUser.first_name || 'Аноним';
        return;
    }
    if (webAuthUser) {
        userId = String(webAuthUser.id || '');
        userName = webAuthUser.first_name || webAuthUser.username || 'Читатель';
    } else {
        userId = '';
        userName = 'Аноним';
    }
}

function getBotUsername() {
    return String((allData && allData.bot_username) || 'Alyamangapage_bot').replace(/^@/, '');
}

function getTelegramReaderUrl() {
    return `https://t.me/${encodeURIComponent(getBotUsername())}`;
}

function openTelegramReaderAuth() {
    const url = getTelegramReaderUrl();
    if (window.Telegram && window.Telegram.WebApp && typeof window.Telegram.WebApp.openTelegramLink === 'function') {
        window.Telegram.WebApp.openTelegramLink(url);
        return;
    }
    window.open(url, '_blank', 'noopener');
}

function requireTelegramAuth(actionText = 'выполнить действие') {
    syncPublicReadModeUI();
    showToast(`Войдите через Telegram, чтобы ${actionText}.`);
    return false;
}

function syncPublicReadModeUI() {
    const publicMode = isPublicReadMode();
    if (document.body) {
        document.body.classList.toggle('public-read-mode', publicMode);
    }

    const form = document.getElementById('comment-form');
    const cta = document.getElementById('comment-auth-cta');
    const input = document.getElementById('comment-input');
    const sendBtn = document.querySelector('#comment-form .comment-send-btn');
    const formatBtn = document.getElementById('comment-format-toggle');
    const likeBtn = document.getElementById('like-btn');
    const reactionBar = document.getElementById('reaction-bar');
    const loginWidget = document.getElementById('telegram-login-widget');
    const globalLoginWidget = document.getElementById('global-telegram-login-widget');
    const authUser = document.getElementById('comment-auth-user');

    if (form) {
        form.classList.toggle('auth-required', publicMode);
        form.setAttribute('aria-hidden', publicMode ? 'true' : 'false');
    }
    if (cta) {
        cta.classList.toggle('hidden', !publicMode);
    }
    if (authUser) {
        authUser.textContent = webAuthUser ? `Вы вошли как ${webAuthUser.first_name || webAuthUser.username || userName}` : '';
        authUser.classList.toggle('hidden', !webAuthUser);
    }
    if (loginWidget && publicMode) {
        renderTelegramLoginWidget(loginWidget);
    }
    if (globalLoginWidget) {
        globalLoginWidget.classList.toggle('hidden', !publicMode);
        if (publicMode) {
            renderTelegramLoginWidget(globalLoginWidget);
        }
    }
    [input, sendBtn, formatBtn].forEach((el) => {
        if (!el) return;
        el.disabled = publicMode;
        el.setAttribute('aria-disabled', publicMode ? 'true' : 'false');
    });
    if (likeBtn) {
        likeBtn.classList.toggle('auth-required', publicMode);
        likeBtn.setAttribute('aria-disabled', publicMode ? 'true' : 'false');
        likeBtn.title = publicMode ? 'Войдите через Telegram, чтобы поставить лайк' : '';
    }
    if (reactionBar) {
        reactionBar.classList.toggle('auth-required', publicMode);
    }
}

function renderTelegramLoginWidget(mount = document.getElementById('telegram-login-widget')) {
    if (!mount || mount.dataset.botUsername === getBotUsername()) return;
    mount.dataset.botUsername = getBotUsername();
    mount.innerHTML = '';
    const script = document.createElement('script');
    script.async = true;
    script.src = 'https://telegram.org/js/telegram-widget.js?22';
    script.setAttribute('data-telegram-login', getBotUsername());
    script.setAttribute('data-size', 'medium');
    script.setAttribute('data-userpic', 'false');
    script.setAttribute('data-request-access', 'write');
    script.setAttribute('data-onauth', 'onTelegramLogin(user)');
    mount.appendChild(script);
}

async function refreshAfterAuthChange() {
    syncAdminModeControls();
    syncPublicReadModeUI();
    if (document.getElementById('screen-chapters')?.classList.contains('active')) {
        renderChaptersList();
    }
    if (document.getElementById('screen-reader')?.classList.contains('active')) {
        renderComments(allCommentsCache);
        renderReactions(chapterReactionsState);
        await Promise.allSettled([loadLikes(), loadComments(), loadReactions()]);
    }
}

async function verifySiteAuthSession(expectedUser = null) {
    if (!API_URL || hasTelegramAuth()) return false;
    const resp = await apiFetch(`${API_URL}/api/auth/me`, { cache: 'no-store' });
    if (!resp.ok) return false;
    const data = await resp.json().catch(() => ({}));
    const user = data.authenticated ? data.user : null;
    applyAuthUser(user);
    if (!user || !user.id) return false;
    if (expectedUser && expectedUser.id && String(user.id) !== String(expectedUser.id)) {
        applyAuthUser(null);
        return false;
    }
    return true;
}

function handleAuthRejected(message = 'Сессия Telegram не активна. Войдите ещё раз.') {
    if (!hasTelegramAuth()) {
        applyAuthUser(null);
        syncAdminModeControls();
        syncPublicReadModeUI();
        renderComments(allCommentsCache);
        renderReactions(chapterReactionsState);
    }
    showToast(message);
}

async function loadSiteAuthState() {
    if (!API_URL || hasTelegramAuth()) {
        webAuthLoaded = true;
        return;
    }
    try {
        const resp = await apiFetch(`${API_URL}/api/auth/me`);
        if (resp.ok) {
            const data = await resp.json();
            applyAuthUser(data.authenticated ? data.user : null);
        }
    } catch (e) {
        console.warn('Site auth state load failed:', e);
    } finally {
        webAuthLoaded = true;
        syncPublicReadModeUI();
    }
}

window.onTelegramLogin = async function onTelegramLogin(user) {
    if (!API_URL) {
        showToast('Вход доступен только на сайте с API.');
        return false;
    }
    try {
        const resp = await apiFetch(`${API_URL}/api/auth/telegram-login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(user || {})
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok || !data.authenticated) {
            throw new Error(data.error || 'Не удалось войти');
        }
        const verified = await verifySiteAuthSession(data.user);
        if (!verified) {
            throw new Error('браузер не сохранил сессию Telegram');
        }
        await refreshAfterAuthChange();
        showToast('Вы вошли через Telegram.');
        return true;
    } catch (e) {
        applyAuthUser(null);
        syncPublicReadModeUI();
        console.warn('Telegram site login failed:', e);
        showToast(`Вход не удался: ${e.message}`);
        return false;
    }
};

// === Состояние ===
let allData = { series: [] };
let adminIds = []; // Список ID администраторов из БД
let currentSeries = null;
let currentVolume = null;
let currentChapterIdx = 0;
let currentChapters = [];
const ADMIN_MODE_STORAGE_KEY = 'reader_admin_mode';
let isAdminMode = (() => {
    try { return localStorage.getItem(ADMIN_MODE_STORAGE_KEY) === '1'; } catch (e) { return false; }
})();
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
let _chapterLoadingHintTimer = null;
let _nextChapterPrefetchTimer = null;
let _nextChapterPrefetchChildTimers = [];
let _nextChapterPrefetchToken = 0;
let _chapterWarmupTimer = null;

function clearNextChapterPrefetchTimers() {
    if (_nextChapterPrefetchTimer) {
        clearTimeout(_nextChapterPrefetchTimer);
        _nextChapterPrefetchTimer = null;
    }
    _nextChapterPrefetchChildTimers.forEach((timerId) => clearTimeout(timerId));
    _nextChapterPrefetchChildTimers = [];
    _nextChapterPrefetchToken += 1;
}

function queueNextChapterPrefetchChild(callback, delay) {
    const timerId = setTimeout(() => {
        _nextChapterPrefetchChildTimers = _nextChapterPrefetchChildTimers.filter((id) => id !== timerId);
        callback();
    }, delay);
    _nextChapterPrefetchChildTimers.push(timerId);
}

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

function isCurrentUserAdmin() {
    return !!userId && adminIds.includes(String(userId));
}

function hasAdminApi() {
    return !!API_URL;
}

function persistAdminMode(enabled) {
    try {
        if (enabled) localStorage.setItem(ADMIN_MODE_STORAGE_KEY, '1');
        else localStorage.removeItem(ADMIN_MODE_STORAGE_KEY);
    } catch (e) { /* ignore storage errors */ }
}

function syncAdminFabVisibility() {
    const adminFab = document.getElementById('admin-fab-container');
    if (!adminFab) return;
    const readerActive = !!document.getElementById('screen-reader')?.classList.contains('active');
    adminFab.style.display = (readerActive && isAdminMode && hasAdminApi()) ? 'flex' : 'none';
    if (!(readerActive && isAdminMode)) {
        closeAdminMenu();
    }
}

function syncAdminBadge() {
    const header = document.querySelector('#screen-reader .reader-header');
    if (!header) return;
    let badge = header.querySelector('.admin-mode-badge');
    if (isAdminMode && isCurrentUserAdmin()) {
        if (!badge) {
            badge = document.createElement('span');
            badge.className = 'admin-mode-badge';
            badge.textContent = 'РЕДАКТОР';
            header.appendChild(badge);
        }
    } else if (badge) {
        badge.remove();
    }
}

// Refresh v4: глобальный admin FAB — контекстное меню с быстрыми действиями.
function syncGlobalAdminFab(screenName) {
    const fab = document.getElementById('global-admin-fab');
    if (!fab) return;
    const active = screenName || (document.querySelector('.screen.active') || {}).id?.replace('screen-', '') || '';
    const allowed = ['series', 'chapters', 'library'].includes(active);
    const canShow = isAdminMode && allowed && hasAdminApi();
    if (canShow) {
        fab.hidden = false;
        fab.setAttribute('data-screen', active);
    } else {
        fab.hidden = true;
        fab.classList.remove('is-open');
        const menu = document.getElementById('global-admin-menu');
        if (menu) menu.hidden = true;
    }
}

function buildGlobalAdminMenuItems(screenName) {
    const items = [];
    if (screenName === 'chapters' && currentSeries && currentVolume) {
        items.push({ icon: '📦', label: 'Массовая загрузка глав', onClick: 'openBulkModal()' });
        items.push({ icon: '📄', label: 'Добавить главу', onClick: 'openAddChapterForCurrent()' });
        items.push({ icon: '🖼️', label: 'Обложка серии', onClick: 'openCoverEditForCurrent()' });
    } else if (screenName === 'series' || screenName === 'library') {
        items.push({ icon: '🔄', label: 'Обновить данные', onClick: 'refreshReaderDataInBackground()' });
    }
    items.push({ icon: '🚪', label: 'Выйти из режима редактора', onClick: 'toggleAdminMode(false)' });
    return items;
}

function toggleGlobalAdminMenu() {
    const fab = document.getElementById('global-admin-fab');
    const menu = document.getElementById('global-admin-menu');
    if (!fab || !menu) return;
    const isOpen = fab.classList.contains('is-open');
    if (isOpen) {
        fab.classList.remove('is-open');
        setTimeout(() => { menu.hidden = true; }, 200);
        return;
    }
    // Заполнить меню согласно текущему экрану
    const screenName = fab.getAttribute('data-screen') || 'series';
    const items = buildGlobalAdminMenuItems(screenName);
    menu.innerHTML = items.map(it => `
        <button type="button" class="global-admin-menu-item" onclick="toggleGlobalAdminMenu(); ${it.onClick}">
            <span class="icon">${it.icon}</span><span>${escapeHtml(it.label)}</span>
        </button>
    `).join('');
    menu.hidden = false;
    requestAnimationFrame(() => fab.classList.add('is-open'));
}

// Закрывать меню при клике вне
document.addEventListener('click', (e) => {
    const fab = document.getElementById('global-admin-fab');
    if (!fab || fab.hidden) return;
    if (!fab.classList.contains('is-open')) return;
    if (fab.contains(e.target)) return;
    fab.classList.remove('is-open');
    const menu = document.getElementById('global-admin-menu');
    if (menu) setTimeout(() => { menu.hidden = true; }, 200);
});

function syncAdminModeControls() {
    const canUseAdminMode = isCurrentUserAdmin();
    const apiAvailable = hasAdminApi();
    const adminIdsLoaded = Array.isArray(adminIds) && adminIds.length > 0;
    const toggle = document.getElementById('admin-mode-toggle');
    const hint = document.getElementById('admin-mode-hint');
    const settingRow = document.getElementById('admin-mode-setting');
    const chaptersScreen = document.getElementById('screen-chapters');

    // Wipe the persisted toggle only once admin_ids are known and either
    // the API is missing or the current user is not an admin. This avoids
    // accidentally clearing the stored preference during bootstrap, when
    // admin_ids have not yet arrived from the server.
    if (isAdminMode && ((adminIdsLoaded && !canUseAdminMode) || !apiAvailable)) {
        isAdminMode = false;
        persistAdminMode(false);
    }

    const effectivelyEnabled = canUseAdminMode && apiAvailable;

    if (toggle) {
        toggle.disabled = !effectivelyEnabled;
        toggle.checked = effectivelyEnabled ? !!isAdminMode : false;
    }
    if (hint) {
        if (!canUseAdminMode) {
            hint.textContent = 'Недоступно для этого аккаунта';
        } else if (!apiAvailable) {
            hint.textContent = 'Недоступно в offline-режиме (без API)';
        } else {
            hint.textContent = 'Только для администраторов';
        }
    }
    if (settingRow) {
        settingRow.classList.toggle('setting-disabled', !effectivelyEnabled);
    }
    if (chaptersScreen) {
        chaptersScreen.classList.toggle('admin-enabled', canUseAdminMode && isAdminMode);
    }
    syncAdminFabVisibility();
    syncAdminBadge();
    syncGlobalAdminFab();
}

function toggleAdminMode(enabled) {
    if (!isCurrentUserAdmin()) {
        isAdminMode = false;
        persistAdminMode(false);
        syncAdminModeControls();
        if (enabled) {
            showToast('Режим редактора доступен только администраторам.');
        }
        return;
    }

    if (enabled && !hasAdminApi()) {
        isAdminMode = false;
        persistAdminMode(false);
        syncAdminModeControls();
        showToast('Режим редактора недоступен без подключения к API.');
        return;
    }

    isAdminMode = !!enabled;
    persistAdminMode(isAdminMode);

    if (document.getElementById('screen-series').classList.contains('active')) renderSeriesList();
    const chaptersScreen = document.getElementById('screen-chapters');
    if (chaptersScreen) {
        chaptersScreen.classList.toggle('admin-enabled', isAdminMode);
    }
    if (!isAdminMode) {
        closeEditUrlModal();
        closeBulkModal();
        closeAddChapterModal();
        closeCoverEditModal();
        closeAdminMenu();
        const fabMenu = document.getElementById('fab-menu');
        const fabBtn = document.getElementById('fab-btn');
        if (fabMenu) fabMenu.classList.add('hidden');
        if (fabBtn) fabBtn.classList.remove('active');
    }
    renderContinueReading();
    if (document.getElementById('screen-chapters').classList.contains('active')) {
        renderVolumeTabs();
        renderChaptersList();
    }
    syncAdminModeControls();
}

// Unified confirmation helper — uses Telegram showConfirm when available,
// falls back to native confirm outside the Mini App environment.
function adminConfirm(message) {
    return new Promise((resolve) => {
        try {
            if (tg && typeof tg.showConfirm === 'function') {
                tg.showConfirm(String(message || ''), (ok) => resolve(!!ok));
                return;
            }
        } catch (e) { /* fall through */ }
        try {
            resolve(!!confirm(String(message || '')));
        } catch (e) {
            resolve(false);
        }
    });
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
            const deepLink = 'https://t.me/' + bot_username + '?start=ren_' + data.short_id;
            try {
                if (tg && typeof tg.openTelegramLink === 'function') {
                    tg.openTelegramLink(deepLink);
                } else {
                    window.open(deepLink, '_blank', 'noopener');
                }
            } catch (e) {
                window.open(deepLink, '_blank', 'noopener');
            }
            showToast('Завершите переименование в чате с ботом.');
            haptic('light');
        } else {
            showToast('Ошибка: ' + (data.error || 'неизвестная'));
        }
    } catch (e) {
        showToast('Ошибка сети: ' + e.message);
    }
}

async function resetCustomName(objId) {
    if (!API_URL) return showToast('Сброс доступен только через прямое подключение (не GitHub Pages).');
    const ok = await adminConfirm(`Сбросить кастомное имя "${objId}" на дефолт?`);
    if (!ok) return;
    try {
        const resp = await apiFetch(`${API_URL}/api/rename`, {
            method: 'DELETE',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ obj_id: objId })
        });
        const result = await resp.json();
        if (result.ok) {
            // Обновляем данные в фоне — без сброса скролла
            refreshReaderDataInBackground();
            showToast('✅ Имя сброшено на дефолт.');
            haptic('success');
        } else {
            showToast('Ошибка: ' + (result.error || `HTTP ${resp.status}`));
        }
    } catch (e) {
        showToast('Ошибка сети: ' + e.message);
    }
}

// Background refresh that preserves scroll / current chapter state.
let _bgRefreshPending = false;
async function refreshReaderDataInBackground() {
    if (_bgRefreshPending) return;
    _bgRefreshPending = true;
    const scrollEl = document.getElementById('reader-content');
    const savedScroll = scrollEl ? scrollEl.scrollTop : 0;
    try {
        await loadData();
    } catch (e) {
        /* noop */
    } finally {
        _bgRefreshPending = false;
        if (scrollEl && savedScroll > 0) {
            try { scrollEl.scrollTop = savedScroll; } catch (e) { /* noop */ }
        }
    }
}

// === Настройки (из localStorage) ===
function getUserRole(userIdStr) {
    if (adminIds.includes(userIdStr)) return { text: 'Админ', css: 'badge-admin' };
    return null;
}

function clearChapterLoadingHint() {
    if (_chapterLoadingHintTimer) {
        clearTimeout(_chapterLoadingHintTimer);
        _chapterLoadingHintTimer = null;
    }
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
    document.getElementById('screen-reader')?.classList.toggle('immersive', isImmersive);
}

function setQuickSwitcherOpen(isOpen) {
    const switcher = document.getElementById('quick-switcher');
    const overlay = document.getElementById('quick-switcher-overlay');
    if (!switcher) return;

    // Прячем меню FAB если открыто
    const fabMenu = document.getElementById('fab-menu');
    if (fabMenu && !fabMenu.classList.contains('hidden')) toggleFab();

    if (isOpen) {
        renderQuickSwitcherList();
        switcher.classList.add('active');
        overlay?.classList.remove('hidden');
        overlay?.classList.add('active');
    } else {
        switcher.classList.remove('active');
        overlay?.classList.remove('active');
        overlay?.classList.add('hidden');
    }
}

function toggleQuickSwitcher() {
    const switcher = document.getElementById('quick-switcher');
    if (!switcher) return;
    const willOpen = !switcher.classList.contains('active');
    setQuickSwitcherOpen(willOpen);
    if (willOpen) haptic('light');
}

function renderQuickSwitcherList() {
    const list = document.getElementById('quick-switcher-list');
    if (!list || !currentChapters) return;

    list.innerHTML = currentChapters.map((ch, idx) => `
        <div class="quick-switcher-item ${idx === currentChapterIdx ? 'active' : ''}" data-chapter-idx="${idx}">
            ${ch.custom_name || 'Глава ' + ch.chapter}
        </div>
    `).join('');
}

function setToCOpen(isOpen) {
    document.getElementById('toc-overlay')?.classList.toggle('active', !!isOpen);
    document.getElementById('toc-panel')?.classList.toggle('active', !!isOpen);
}

function closeSettingsPanel({ save = false } = {}) {
    const overlay = document.getElementById('settings-overlay');
    const panel = document.getElementById('settings-panel');
    if (!overlay || !panel) return;
    if (save && !panel.classList.contains('hidden')) {
        saveSettings();
    }
    overlay.classList.add('hidden');
    panel.classList.add('hidden');
}

function resetTransientUiState({ saveSettingsOnClose = false } = {}) {
    setQuickSwitcherOpen(false);
    setToCOpen(false);
    closeSettingsPanel({ save: saveSettingsOnClose });
    closeEditUrlModal();
    closeBulkModal();
    closeAddChapterModal();
    closeTypoModal();
    closeAdminMenu();
    document.body.classList.remove('keyboard-open');
    document.documentElement.style.setProperty('--reader-keyboard-offset', '0px');
}

function openExternalChapterSource(url) {
    const safeUrl = String(url || '').trim();
    if (!safeUrl) return;
    if (window.Telegram && window.Telegram.WebApp && typeof window.Telegram.WebApp.openTelegramLink === 'function' && /^https?:\/\//i.test(safeUrl)) {
        window.Telegram.WebApp.openTelegramLink(safeUrl);
        return;
    }
    window.open(safeUrl, '_blank', 'noopener');
}

function chapterHasAnyContent(chapter) {
    return !!(chapter && ((typeof chapter.text === 'string' && chapter.text.trim()) || getChapterSourceUrls(chapter).length > 0));
}

function sameReaderKey(a, b) {
    return String(a ?? '') === String(b ?? '');
}

function findSeriesById(seriesId) {
    if (!Array.isArray(allData?.series)) return null;
    return allData.series.find((series) => sameReaderKey(series?.id, seriesId)) || null;
}

function findVolumeByKey(series, volumeKey) {
    if (!series || !Array.isArray(series.volumes)) return null;
    return series.volumes.find((volume) => sameReaderKey(volume?.volume, volumeKey)) || null;
}

function resetCurrentSeriesSelection() {
    currentVolume = null;
    currentChapters = [];
    currentChapterIdx = 0;
    prefetchedChapter = { idx: -1, html: null };
    clearNextChapterPrefetchTimers();
    if (_chapterWarmupTimer) {
        clearTimeout(_chapterWarmupTimer);
        _chapterWarmupTimer = null;
    }

    const chaptersList = document.getElementById('chapters-list');
    if (chaptersList) {
        chaptersList.innerHTML = '';
    }

    const volumeTabs = document.getElementById('volume-tabs');
    if (volumeTabs) {
        volumeTabs.innerHTML = '';
        volumeTabs.style.display = 'none';
    }
}

function handleSeriesSelectionAction(action, seriesId, event = null) {
    if (event && typeof event.stopPropagation === 'function') {
        event.stopPropagation();
    }
    if (action === 'continue') {
        jumpToLastRead(null, seriesId);
        return;
    }
    if (action === 'latest') {
        jumpToLatestChapter(null, seriesId);
    }
}

function chapterContentLooksVisible(target) {
    if (!target) return false;
    if (target.querySelector('img, iframe, video, picture, object, embed')) {
        return true;
    }
    const text = String(target.textContent || '').replace(/\s+/g, ' ').trim();
    return text.length > 0;
}

let _delegatedSelectionEventsBound = false;

function bindDelegatedSelectionEvents() {
    if (_delegatedSelectionEventsBound) return;
    _delegatedSelectionEventsBound = true;

    document.getElementById('series-list')?.addEventListener('click', (event) => {
        const actionBtn = event.target.closest('[data-series-action]');
        if (actionBtn) {
            handleSeriesSelectionAction(actionBtn.dataset.seriesAction || '', actionBtn.dataset.seriesId || '', event);
            return;
        }

        const card = event.target.closest('.series-card[data-series-id]');
        if (!card) return;
        if (event.target.closest('.admin-edit-btn, .admin-reset-btn')) return;
        selectSeries(card.dataset.seriesId || '');
    });

    document.getElementById('library-list')?.addEventListener('click', (event) => {
        const actionBtn = event.target.closest('[data-series-action]');
        if (actionBtn) {
            handleSeriesSelectionAction(actionBtn.dataset.seriesAction || '', actionBtn.dataset.seriesId || '', event);
            return;
        }

        const card = event.target.closest('.series-card[data-series-id]');
        if (!card) return;
        selectSeries(card.dataset.seriesId || '');
    });

    document.getElementById('continue-reading-container')?.addEventListener('click', (event) => {
        const actionCard = event.target.closest('[data-series-action][data-series-id]');
        if (!actionCard) return;
        handleSeriesSelectionAction(actionCard.dataset.seriesAction || '', actionCard.dataset.seriesId || '', event);
    });

    document.getElementById('chapters-list')?.addEventListener('click', (event) => {
        const fallbackBtn = event.target.closest('[data-chapter-fallback-url]');
        if (fallbackBtn) {
            event.stopPropagation();
            openExternalChapterSource(fallbackBtn.dataset.chapterFallbackUrl || '');
            return;
        }
        // Inline onclick on .admin-move-btn handles primary action; this is a
        // defensive fallback in case delegation is the only path that fires.
        const moveBtn = event.target.closest('[data-move-chapter]');
        if (moveBtn) {
            event.stopPropagation();
            event.preventDefault();
            if (moveBtn.disabled) return;
            const idx = Number(moveBtn.dataset.chapterIdx);
            const direction = moveBtn.dataset.moveChapter === 'up' ? -1 : 1;
            if (Number.isInteger(idx)) moveChapter(idx, direction);
            return;
        }
        if (event.target.closest('.admin-edit-btn, .admin-reset-btn, .admin-link-btn, .drag-handle, .admin-bulk-btn, .admin-move-btn')) return;

        const item = event.target.closest('.chapter-item[data-chapter-idx]');
        if (!item) return;
        if (item.classList.contains('chapter-item-disabled')) return;
        const idx = Number(item.dataset.chapterIdx);
        if (Number.isInteger(idx)) openChapter(idx);
    });

    document.getElementById('quick-switcher-list')?.addEventListener('click', (event) => {
        const item = event.target.closest('.quick-switcher-item[data-chapter-idx]');
        if (!item) return;
        const idx = Number(item.dataset.chapterIdx);
        if (!Number.isInteger(idx)) return;
        openChapter(idx);
        setQuickSwitcherOpen(false);
    });
}

// Refresh v4: тема по умолчанию — тёмная (Tachiyomi-style). Если у пользователя
// нет сохранённого выбора и ОС предпочитает светлую — уважаем это.
function _r4DefaultTheme() {
    try {
        if (window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches) {
            return 'light';
        }
    } catch (_) {}
    return 'dark';
}
const defaults = {
    fontSize: 17,
    theme: _r4DefaultTheme(),
    textWidth: 90,
    font: 'serif',
    lineHeight: 1.8,
    textAlign: 'left',
    indent: true,
    paraSpacing: 20,
    letterSpacing: 0,
    paraIndent: 25,
    dimmerValue: 0,
    readingMode: 'scroll', // 'scroll' or 'pages'
    dropCap: true,
    hideProgress: false,
    hideChapterHeader: false
};

const READER_DIMMER_MAX = 45;

function clampDimmerValue(value) {
    const parsed = Number.parseInt(value, 10);
    if (!Number.isFinite(parsed)) return 0;
    return Math.min(READER_DIMMER_MAX, Math.max(0, parsed));
}

function normalizeReaderSettings(candidate) {
    const source = candidate && typeof candidate === 'object' ? candidate : {};
    const next = { ...defaults, ...source };
    next.dimmerValue = clampDimmerValue(next.dimmerValue);
    if (!next.lineHeight) next.lineHeight = defaults.lineHeight;
    if (!next.textAlign) next.textAlign = defaults.textAlign;
    if (next.indent === undefined) next.indent = defaults.indent;
    if (next.paraSpacing === undefined) next.paraSpacing = defaults.paraSpacing;
    if (next.letterSpacing === undefined) next.letterSpacing = defaults.letterSpacing;
    if (next.paraIndent === undefined) next.paraIndent = defaults.paraIndent;
    if (next.readingMode === undefined) next.readingMode = defaults.readingMode;
    if (next.hideProgress === undefined) next.hideProgress = defaults.hideProgress;
    if (next.hideChapterHeader === undefined) next.hideChapterHeader = defaults.hideChapterHeader;
    next.hideProgress = !!next.hideProgress;
    next.hideChapterHeader = !!next.hideChapterHeader;
    return next;
}

let settings;
try {
    const saved = JSON.parse(localStorage.getItem('reader_settings') || 'null');
    if (saved && typeof saved === 'object') {
        settings = normalizeReaderSettings(saved);
    } else {
        settings = normalizeReaderSettings(defaults);
    }
} catch (e) {
    console.warn("Failed to parse settings from localStorage", e);
    settings = normalizeReaderSettings(defaults);
}
// Миграция старых настроек
settings = normalizeReaderSettings(settings);

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

const READER_API_CACHE_PREFIX = 'reader_api_snapshot_v2';
const READER_CACHE_REV_KEY = 'reader_api_snapshot_rev';
const READER_SW_SYNC_KEY = 'reader_sw_rev';
const OFFLINE_CHAPTER_PREFETCH_COUNT = 3;

function getCachedReaderApiSnapshot() {
    const snapshot = safeGetLocal(getReaderApiCacheKey(), null);
    if (!snapshot || typeof snapshot !== 'object') return null;
    if (!snapshot.payload || typeof snapshot.payload !== 'object') return null;
    return {
        etag: typeof snapshot.etag === 'string' ? snapshot.etag : '',
        payload: snapshot.payload
    };
}

function saveReaderApiSnapshot(payload, etag = '') {
    if (!payload || typeof payload !== 'object') return;
    safeSetLocal(getReaderApiCacheKey(), {
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

const CHAPTER_PAYLOAD_CACHE_LIMIT = 16;
const CHAPTER_PAYLOAD_PERSIST_LIMIT = 32;
const CHAPTER_PAYLOAD_PERSIST_PREFIX = 'reader_chapter_payload_v2';
const chapterPayloadCache = new Map();
const chapterPayloadInflight = new Map();
let readerSearchQuery = '';
let bulkUploadPreviewState = null;

function buildChapterPayloadCacheKey(seriesId, volume, chapterId) {
    if (seriesId === undefined || volume === undefined || chapterId === undefined) return '';
    return `${String(seriesId)}::${String(volume)}::${String(chapterId)}`;
}

function getPersistentChapterPayloadKey(cacheKey) {
    return `${CHAPTER_PAYLOAD_PERSIST_PREFIX}_${READER_REV}_${cacheKey}`;
}

function getPersistentChapterPayload(cacheKey) {
    if (!cacheKey) return null;
    const cached = safeGetLocal(getPersistentChapterPayloadKey(cacheKey), null);
    if (!cached || typeof cached !== 'object' || !cached.payload || typeof cached.payload !== 'object') return null;
    return {
        payload: cached.payload,
        etag: typeof cached.etag === 'string' ? cached.etag : '',
        ts: Number(cached.ts || 0)
    };
}

function prunePersistentChapterPayloads() {
    try {
        const prefix = `${CHAPTER_PAYLOAD_PERSIST_PREFIX}_${READER_REV}_`;
        const entries = [];
        for (let i = 0; i < localStorage.length; i += 1) {
            const key = localStorage.key(i);
            if (!key || !key.startsWith(prefix)) continue;
            const item = safeGetLocal(key, null);
            entries.push({ key, ts: Number(item?.ts || 0) });
        }
        entries.sort((a, b) => b.ts - a.ts);
        entries.slice(CHAPTER_PAYLOAD_PERSIST_LIMIT).forEach((entry) => localStorage.removeItem(entry.key));
    } catch (err) {
        console.warn('Chapter persistent cache prune failed:', err);
    }
}

function rememberPersistentChapterPayload(cacheKey, payload, etag = '') {
    if (!cacheKey || !payload || typeof payload !== 'object') return;
    safeSetLocal(getPersistentChapterPayloadKey(cacheKey), {
        payload,
        etag: typeof etag === 'string' ? etag : '',
        ts: Date.now()
    });
    prunePersistentChapterPayloads();
}

function getCachedChapterPayload(cacheKey) {
    if (!cacheKey) return null;
    if (chapterPayloadCache.has(cacheKey)) {
        const payload = chapterPayloadCache.get(cacheKey);
        chapterPayloadCache.delete(cacheKey);
        chapterPayloadCache.set(cacheKey, payload);
        return payload;
    }
    const persistent = getPersistentChapterPayload(cacheKey);
    if (!persistent?.payload) return null;
    rememberCachedChapterPayload(cacheKey, persistent.payload, { persist: false, etag: persistent.etag });
    return persistent.payload;
}

function rememberCachedChapterPayload(cacheKey, payload, options = {}) {
    if (!cacheKey || !payload || typeof payload !== 'object') return;
    const etag = typeof options.etag === 'string' ? options.etag : '';
    if (etag) {
        payload._etag = etag;
    }
    if (chapterPayloadCache.has(cacheKey)) {
        chapterPayloadCache.delete(cacheKey);
    }
    chapterPayloadCache.set(cacheKey, payload);
    while (chapterPayloadCache.size > CHAPTER_PAYLOAD_CACHE_LIMIT) {
        const firstKey = chapterPayloadCache.keys().next().value;
        if (!firstKey) break;
        chapterPayloadCache.delete(firstKey);
    }
    if (options.persist !== false) {
        rememberPersistentChapterPayload(cacheKey, payload, etag || payload._etag || '');
    }
}

function buildChapterContentApiUrlFor(seriesId, volume, chapterId) {
    if (!API_URL || seriesId === undefined || volume === undefined || chapterId === undefined || chapterId === null || chapterId === '') return '';
    const query = new URLSearchParams({
        series_id: String(seriesId),
        volume: String(volume),
        chapter: String(chapterId)
    });
    return `${API_URL}/api/chapter-content?${query.toString()}`;
}

async function warmChapterPayloadByIndex(idx, options = {}) {
    const preferPrefetchSlot = !!options.preferPrefetchSlot;
    if (!API_URL || !currentSeries || !currentVolume || !Array.isArray(currentChapters)) return null;

    const chapter = currentChapters[idx];
    if (!chapter || chapter.chapter === undefined || chapter.chapter === null || chapter.chapter === '') return null;

    const cacheKey = buildChapterPayloadCacheKey(currentSeries.id, currentVolume.volume, chapter.chapter);
    if (!cacheKey) return null;

    const cached = getCachedChapterPayload(cacheKey);
    if (cached) {
        if (preferPrefetchSlot && cached.ok && cached.html) {
            prefetchedChapter = { idx, html: cached.html };
        }
        return cached;
    }

    const inflight = chapterPayloadInflight.get(cacheKey);
    if (inflight) {
        return inflight;
    }

    const endpoint = buildChapterContentApiUrlFor(currentSeries.id, currentVolume.volume, chapter.chapter);
    if (!endpoint) return null;

    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 12000);
    const request = apiFetch(endpoint, { signal: controller.signal })
        .then(async (resp) => {
            if (!resp.ok) {
                throw new Error(`HTTP ${resp.status}`);
            }
            const payload = await resp.json();
            if (payload && typeof payload === 'object') {
                rememberCachedChapterPayload(cacheKey, payload, { etag: resp.headers.get('etag') || '' });
                if (preferPrefetchSlot && payload.ok && payload.html) {
                    prefetchedChapter = { idx, html: payload.html };
                }
            }
            return payload;
        })
        .catch((err) => {
            if (err?.name !== 'AbortError') {
                console.warn('Background chapter warmup failed:', err);
            }
            return null;
        })
        .finally(() => {
            clearTimeout(timeoutId);
            chapterPayloadInflight.delete(cacheKey);
        });

    chapterPayloadInflight.set(cacheKey, request);
    return request;
}

function toServiceWorkerCacheUrl(rawUrl) {
    if (!rawUrl) return '';
    const src = String(rawUrl).trim();
    const telegraphMatch = src.match(/^https?:\/\/telegra\.ph\/(.+)$/i);
    if (telegraphMatch) {
        return `https://api.telegra.ph/getPage/${telegraphMatch[1]}?return_content=true`;
    }
    // Не ставим в prefetch cross-origin URL'ы без CORS (teletype.in и т.п.) — они и так
    // грузятся через <iframe>, а SW fetch только засоряет консоль CORS-ошибками.
    if (/^https?:\/\/teletype\.in\//i.test(src)) return '';
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
        const swUrl = `./sw.js?rev=${encodeURIComponent(READER_REV)}`;
        const reg = await navigator.serviceWorker.register(swUrl);
        safeSetLocal(READER_SW_SYNC_KEY, READER_REV);
        if (reg.waiting) {
            reg.waiting.postMessage({ type: 'SKIP_WAITING' });
        }
        if (typeof reg.update === 'function') {
            reg.update().catch(() => {});
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
const WEBAPP_BUILD_META = window.__WEBAPP_BUILD || {};
const READER_REV = String(urlParams.get('rev') || window.__READER_REV || WEBAPP_BUILD_META.rev || '20260428-stability-1').trim() || '20260428-stability-1';
const API_URL = urlParams.get('api') || (window.location.hostname.includes('github.io') ? '' : window.location.origin);

function getReaderApiCacheKey(rev = READER_REV) {
    return `${READER_API_CACHE_PREFIX}_${String(rev || 'default')}`;
}

function clearLegacyReaderApiSnapshots(exceptRev = READER_REV) {
    const keepKey = getReaderApiCacheKey(exceptRev);
    try {
        const toDelete = [];
        for (let i = 0; i < localStorage.length; i += 1) {
            const key = localStorage.key(i);
            if (!key) continue;
            if ((key.startsWith(READER_API_CACHE_PREFIX) || key === 'reader_api_snapshot_v1') && key !== keepKey) {
                toDelete.push(key);
            }
        }
        toDelete.forEach((key) => localStorage.removeItem(key));
    } catch (e) {}
}

function handleReaderCacheVersionChange() {
    const previousRev = safeGetLocal(READER_CACHE_REV_KEY, '');
    if (String(previousRev || '') === READER_REV) return;
    clearLegacyReaderApiSnapshots(READER_REV);
    safeSetLocal(READER_CACHE_REV_KEY, READER_REV);
    sendClientTelemetry('cache_version_mismatch', {
        module: 'reader.js',
        previous_rev: String(previousRev || ''),
        current_rev: READER_REV,
        screen: getActiveScreenName(),
        tg_platform: getTelegramPlatform(),
        has_overlay: hasBlockingOverlay()
    });
}

async function checkWebAppBuildVersion() {
    try {
        const response = await fetch(`webapp-build.json?t=${Date.now()}`, { cache: 'no-store', signal: getTimeoutSignal(3500) });
        if (!response.ok) return;
        const meta = await response.json();
        const latestRev = String(meta.rev || '').trim();
        if (!latestRev || latestRev === READER_REV) return;
        sendClientTelemetry('webapp_update_available', {
            module: 'reader.js',
            current_rev: READER_REV,
            latest_rev: latestRev,
            screen: getActiveScreenName(),
        });
        showToast('Доступна новая версия читалки. Обновите страницу.');
    } catch (error) {
        sendClientTelemetry('webapp_build_check_failed', {
            module: 'reader.js',
            message: error && error.message ? String(error.message) : 'unknown',
            screen: getActiveScreenName(),
        });
    }
}

// === API Wrapper ===
async function apiFetch(url, options = {}) {
    if (typeof navigator !== 'undefined' && !navigator.onLine) {
        throw new Error('Offline');
    }
    options.headers = options.headers || {};
    options.credentials = options.credentials || 'include';
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
    'client_chapter_open_ms',
    'series_selected',
    'chapters_screen_opened',
    'chapter_click',
    'chapter_content_load_failed',
    'cache_version_mismatch'
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

function getActiveScreenName() {
    const active = document.querySelector('.screen.active');
    if (!active || !active.id) return 'unknown';
    return active.id.replace(/^screen-/, '') || 'unknown';
}

function getTelegramPlatform() {
    return String(tg?.platform || tg?.initDataUnsafe?.platform || 'web');
}

function hasBlockingOverlay() {
    const selectors = [
        '#quick-switcher.active',
        '#toc-panel.active',
        '#settings-panel:not(.hidden)',
        '#edit-url-modal:not(.hidden)',
        '#bulk-upload-modal:not(.hidden)',
        '#typo-modal:not(.hidden)',
        '#lightbox-overlay:not(.hidden)'
    ];
    return selectors.some((selector) => document.querySelector(selector));
}

function buildTelemetryContext(extra = {}) {
    return {
        module: 'reader.js',
        rev: READER_REV,
        screen: getActiveScreenName(),
        tg_platform: getTelegramPlatform(),
        has_overlay: hasBlockingOverlay(),
        ...extra
    };
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
    if (API_URL && hasWriteAuth() && currentSeries && currentVolume && currentChapters[currentChapterIdx]) {
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
        progressBarEl = document.getElementById('reading-progress-bar');
    }
    if (progressBarEl) progressBarEl.style.width = '0%';
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
    if (API_URL && hasWriteAuth()) {
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
                adminIds = Array.isArray(allData.admin_ids) ? allData.admin_ids.map(id => String(id)) : [];
                syncAdminModeControls();
                syncPublicReadModeUI();
                if (allData.series && allData.series.length > 0) {
                    validateCriticalSeriesMappings();
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
        const resp = await fetch('chapters_data.json?v=' + encodeURIComponent(READER_REV), { signal: getTimeoutSignal(5000) });
        if (resp.ok) {
            allData = await resp.json();
            adminIds = Array.isArray(allData.admin_ids) ? allData.admin_ids.map(id => String(id)) : [];
            syncAdminModeControls();
            syncPublicReadModeUI();
            console.log("Data loaded from fallback JSON, series count:", allData.series?.length);
            if (allData.series && allData.series.length > 0) {
                validateCriticalSeriesMappings();
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

function normalizeReaderSearchText(value) {
    return String(value || '').toLowerCase().replace(/\s+/g, ' ').trim();
}

function chapterSearchText(chapter, volume) {
    const parts = [
        chapter?.chapter,
        chapter?.custom_name,
        chapter?.title,
        chapter?.name,
        volume !== undefined && volume !== null ? `том ${volume}` : '',
        volume !== undefined && volume !== null ? `vol ${volume}` : '',
        chapter?.chapter !== undefined ? `глава ${chapter.chapter}` : '',
        chapter?.chapter !== undefined ? `chapter ${chapter.chapter}` : ''
    ];
    return normalizeReaderSearchText(parts.filter(Boolean).join(' '));
}

function seriesSearchText(series) {
    const parts = [series?.title, series?.id, series?.author, ...(Array.isArray(series?.tags) ? series.tags : [])];
    (series?.volumes || []).forEach((volume) => {
        parts.push(volume?.custom_name, volume?.volume !== undefined ? `том ${volume.volume}` : '');
        (volume?.chapters || []).forEach((chapter) => parts.push(chapterSearchText(chapter, volume?.volume)));
    });
    return normalizeReaderSearchText(parts.filter(Boolean).join(' '));
}

function matchesSeriesSearch(series, query) {
    if (!query) return true;
    return seriesSearchText(series).includes(query);
}

function matchesChapterSearch(chapter, query, volume) {
    if (!query) return true;
    return chapterSearchText(chapter, volume).includes(query);
}

function updateReaderSearchEmpty(message = '') {
    const empty = document.getElementById('reader-search-empty');
    if (!empty) return;
    if (!message) {
        empty.classList.add('hidden');
        empty.textContent = '';
        return;
    }
    empty.textContent = message;
    empty.classList.remove('hidden');
}

function syncReaderSearchVisibility() {
    const panel = document.getElementById('reader-search-panel');
    if (!panel) return;
    const screenName = getActiveScreenName();
    const visible = screenName === 'series' || screenName === 'chapters';
    panel.classList.toggle('hidden', !visible);
    if (!visible) {
        updateReaderSearchEmpty('');
        return;
    }
    const input = document.getElementById('reader-search-input');
    const clear = document.getElementById('reader-search-clear');
    if (input && input.value !== readerSearchQuery) input.value = readerSearchQuery;
    if (clear) clear.classList.toggle('hidden', !readerSearchQuery);
}

function handleReaderSearchInput(value) {
    readerSearchQuery = normalizeReaderSearchText(value);
    syncReaderSearchVisibility();
    const active = getActiveScreenName();
    if (active === 'series') renderSeriesList();
    if (active === 'chapters') renderChaptersList();
}

function clearReaderSearch() {
    readerSearchQuery = '';
    const input = document.getElementById('reader-search-input');
    if (input) input.value = '';
    syncReaderSearchVisibility();
    const active = getActiveScreenName();
    if (active === 'series') renderSeriesList();
    if (active === 'chapters') renderChaptersList();
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

function validateCriticalSeriesMappings() {
    if (!Array.isArray(allData.series)) return;
    const ids = allData.series.map((series) => String(series?.id || ''));
    const expected = ['akashic_records', 'ranobe_alya', 'manga_ru'];
    const presentExpected = expected.filter((id) => ids.includes(id));
    if (presentExpected.length === 0) return;

    const uniqueIds = new Set(ids);
    if (uniqueIds.size !== ids.length || presentExpected.some((id) => !uniqueIds.has(id))) {
        reportStateContractViolation('loadData:series_ids', 'critical_series_mapping_invalid', {
            ids,
            expected_present: presentExpected
        });
    }
}

function handleStartParam() {
    const start = tg.initDataUnsafe?.start_param || urlParams.get('tgWebAppStartParam');
    if (!start) return;

    // chapter_{series_id}_{volume_num}_{chapter_num/key}
    const match = start.match(/^chapter_([^_]+)_([^_]+)_([^_]+)$/);
    if (match) {
        const [, sId, vNum, cKey] = match;
        const series = findSeriesById(sId);
        if (!series) return;

        currentSeries = series;
        const vol = findVolumeByKey(series, vNum);
        if (!vol) return;

        currentVolume = vol;
        currentChapters = vol.chapters || [];
        const cIdx = currentChapters.findIndex(c => sameReaderKey(c.chapter, cKey));

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

    const query = readerSearchQuery;
    const visibleSeries = allData.series.filter((series) => matchesSeriesSearch(series, query));
    if (visibleSeries.length === 0) {
        container.innerHTML = '';
        updateReaderSearchEmpty(query ? 'Ничего не найдено. Попробуйте название серии, том или номер главы.' : '');
        return;
    }
    updateReaderSearchEmpty('');
    container.innerHTML = visibleSeries.map((s, i) => renderSeriesPosterCard(s, i)).join('');
}

// Refresh v4: карточка-постер (2:3 обложка + компактная инфа снизу).
function renderSeriesPosterCard(s, idx = 0) {
    const totalCh = s.volumes.reduce((sum, v) => sum + (v.chapters || []).length, 0);
    const readCount = s.volumes.reduce((sum, v) => {
        return sum + (v.chapters || []).filter(c => isRead(s.id, v.volume, c.chapter)).length;
    }, 0);
    const progress = totalCh > 0 ? Math.round((readCount / totalCh) * 100) : 0;
    const lastRead = getLastRead(s.id);

    // Плейсхолдер без обложки — градиент с первой буквой названия.
    const firstLetter = (s.title || '?').trim().charAt(0).toUpperCase();
    const coverInner = s.cover_url
        ? `<img src="${escapeHtml(s.cover_url)}" alt="${escapeHtml(s.title)}" loading="lazy" class="series-poster-img">`
        : `<div class="r4-poster-placeholder series-poster-img">${escapeHtml(firstLetter)}</div>`;

    // Chip-ряд поверх обложки: continue (если есть), completed, new.
    const chips = [];
    if (progress === 100 && totalCh > 0) {
        chips.push('<span class="r4-chip r4-chip--accent">✓ Прочитано</span>');
    } else if (lastRead) {
        chips.push('<span class="r4-chip r4-chip--accent">▶ Продолжить</span>');
    }
    if (isAdminMode) {
        chips.push('<span class="r4-chip r4-chip--outline">серия</span>');
    }

    // Refresh v4: NEW/HOT badges — data-driven через поля серии (если есть).
    // NEW: s.is_new === true или серия не читалась и имеет пометку s.recently_added === true.
    // HOT: s.hot === true или s.popular === true.
    const badges = [];
    if (s.is_new === true || s.recently_added === true) {
        badges.push('<span class="series-poster-badge is-new">NEW</span>');
    } else if (s.hot === true || s.popular === true) {
        badges.push('<span class="series-poster-badge is-hot">HOT</span>');
    }

    // Админ-действия — плавающая полоска в углу обложки.
    const adminOverlay = isAdminMode ? `
        <div class="series-poster-admin" onclick="event.stopPropagation();">
            <button class="admin-edit-btn" title="Переименовать" onclick="renameItem('series_${s.id}'); event.stopPropagation();">&#9998;</button>
            <button class="admin-reset-btn" title="Сброс имени" onclick="resetCustomName('series_${s.id}'); event.stopPropagation();">&#8635;</button>
            <button class="admin-edit-btn" title="Обложка" onclick="openCoverEditModal('${escapeHtml(String(s.id))}'); event.stopPropagation();">&#128247;</button>
        </div>` : '';

    // Progress-полоска снизу обложки.
    const progressBar = totalCh > 0
        ? `<div class="series-poster-progress" role="progressbar" aria-valuenow="${progress}" aria-valuemin="0" aria-valuemax="100">
                <span style="width: ${progress}%"></span>
           </div>`
        : '';

    const meta = lastRead
        ? `Гл. ${escapeHtml(String(lastRead.chapter))} · ${readCount}/${totalCh}`
        : `${s.volumes.length} т. · ${totalCh} гл.`;

    return `
    <div class="series-card series-poster" data-series-id="${escapeHtml(String(s.id))}">
        <div class="series-poster-cover">
            ${coverInner}
            ${badges.join('')}
            ${chips.length ? `<div class="series-poster-chips">${chips.join('')}</div>` : ''}
            ${progressBar}
            ${adminOverlay}
        </div>
        <div class="series-poster-info">
            <h3 class="series-poster-title">${escapeHtml(s.title)}</h3>
            <p class="series-poster-meta">${meta}</p>
        </div>
    </div>`;
}

// Refresh v4: series detail hero над списком глав. Рендерится data-driven —
// если в данных нет description/tags/cover_url, соответствующие блоки скрываются.
function renderSeriesDetailHero(series) {
    const hero = document.getElementById('series-detail-hero');
    if (!hero) return;
    if (!series) { hero.hidden = true; hero.innerHTML = ''; return; }

    const totalCh = (series.volumes || []).reduce((sum, v) => sum + ((v.chapters || []).length), 0);
    const readCount = (series.volumes || []).reduce((sum, v) => {
        return sum + (v.chapters || []).filter(c => isRead(series.id, v.volume, c.chapter)).length;
    }, 0);
    const progress = totalCh > 0 ? Math.round((readCount / totalCh) * 100) : 0;
    const lastRead = getLastRead(series.id);

    // Обложка — используем img с blur-up если поле есть.
    const firstLetter = (series.title || '?').trim().charAt(0).toUpperCase();
    const coverHtml = series.cover_url
        ? `<img src="${escapeHtml(series.cover_url)}" alt="${escapeHtml(series.title)}" loading="lazy" decoding="async" class="series-detail-cover-img">`
        : `<div class="r4-poster-placeholder series-detail-cover-img">${escapeHtml(firstLetter)}</div>`;

    const description = (typeof series.description === 'string' ? series.description.trim() : '');
    const tags = Array.isArray(series.tags) ? series.tags.filter(Boolean) : [];
    const author = typeof series.author === 'string' ? series.author.trim() : '';

    // CTA — continue/start. Используем существующий handleSeriesSelectionAction.
    const ctaLabel = lastRead ? '▶ Продолжить чтение' : '▶ Начать читать';
    const ctaAction = lastRead
        ? `onclick="handleSeriesSelectionAction('continue', '${escapeHtml(String(series.id))}', event)"`
        : `onclick="handleSeriesSelectionAction('latest', '${escapeHtml(String(series.id))}', event)"`;
    const ctaDisabled = totalCh === 0 ? 'disabled' : '';

    const chipRow = [];
    chipRow.push(`<span class="r4-chip r4-chip--outline">${series.volumes.length} томов</span>`);
    chipRow.push(`<span class="r4-chip r4-chip--outline">${totalCh} глав</span>`);
    if (author) chipRow.push(`<span class="r4-chip r4-chip--outline">${escapeHtml(author)}</span>`);
    if (progress > 0 && progress < 100) chipRow.push(`<span class="r4-chip r4-chip--accent">${progress}%</span>`);
    else if (progress === 100) chipRow.push('<span class="r4-chip r4-chip--accent">✓ Прочитано</span>');

    const tagsHtml = tags.length
        ? `<div class="series-detail-tags">${tags.slice(0, 8).map(t => `<span class="r4-chip r4-chip--outline">${escapeHtml(String(t))}</span>`).join('')}</div>`
        : '';

    const descHtml = description
        ? `<p class="series-detail-description" data-collapsed="true">${escapeHtml(description)}</p>`
        : '';

    hero.innerHTML = `
        <div class="series-detail-top">
            <div class="series-detail-cover">${coverHtml}</div>
            <div class="series-detail-meta">
                <div class="series-detail-chips">${chipRow.join('')}</div>
                <button type="button" class="series-detail-cta" ${ctaAction} ${ctaDisabled}>${ctaLabel}</button>
            </div>
        </div>
        ${descHtml}
        ${tagsHtml}
    `;
    hero.hidden = false;
}

function selectSeries(seriesId) {
    assertReaderState('selectSeries:start');
    const nextSeries = findSeriesById(seriesId);
    if (!nextSeries) return;

    currentSeries = nextSeries;
    resetCurrentSeriesSelection();

    sendClientTelemetry('series_selected', buildTelemetryContext({
        series_id: currentSeries.id,
        volumes_count: Array.isArray(currentSeries.volumes) ? currentSeries.volumes.length : 0
    }));

    document.getElementById('chapters-title').textContent = currentSeries.title; // textContent escapes HTML
    renderSeriesDetailHero(currentSeries);
    renderVolumeTabs();

    // Восстанавливаем последнюю читаемую главу или первый том
    const lastRead = getLastRead(seriesId);
    const targetVolume = (lastRead && findVolumeByKey(currentSeries, lastRead.volume))
        || (currentSeries.volumes.length > 0 ? currentSeries.volumes[0] : null);
    if (targetVolume) {
        selectVolume(targetVolume.volume);
    } else {
        // Safety: ensure chapters-list is rendered (empty-state) even without volume.
        renderChaptersList();
    }

    showScreen('chapters');
    sendClientTelemetry('chapters_screen_opened', buildTelemetryContext({
        series_id: currentSeries.id,
        volume: currentVolume?.volume ?? ''
    }));
}

function openSeriesChapter(seriesId, volumeId, chapterKey, fallbackToLatest = false) {
    const series = findSeriesById(seriesId);
    if (!series || !Array.isArray(series.volumes) || series.volumes.length === 0) return;

    currentSeries = series;
    resetCurrentSeriesSelection();
    const title = document.getElementById('chapters-title');
    if (title) {
        title.textContent = currentSeries.title;
    }

    renderVolumeTabs();

    let targetVolume = findVolumeByKey(series, volumeId);
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
    let targetIdx = chapters.findIndex((ch) => sameReaderKey(ch.chapter, chapterKey));
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
    const series = findSeriesById(seriesId);
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

    if (!currentSeries || !Array.isArray(currentSeries.volumes) || currentSeries.volumes.length <= 1) {
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
    if (!currentSeries) return;
    currentVolume = findVolumeByKey(currentSeries, volNum);
    if (!currentVolume) return;

    document.querySelectorAll('.vol-tab').forEach(t => {
        t.classList.toggle('active', sameReaderKey(t.dataset.vol, currentVolume.volume));
    });

    renderChaptersList();
}

function renderChaptersList() {
    assertReaderState('renderChaptersList:start');
    cleanupChapterDnD();
    // Defensive: re-resolve currentSeries/currentVolume from the latest allData
    // to guard against stale object refs after background data refresh (and to
    // guarantee that chapters-list always reflects the currently selected series).
    if (currentSeries) {
        const freshSeries = findSeriesById(currentSeries.id);
        if (freshSeries && freshSeries !== currentSeries) {
            currentSeries = freshSeries;
        }
    }
    if (currentSeries && currentVolume) {
        const freshVolume = findVolumeByKey(currentSeries, currentVolume.volume);
        if (freshVolume && freshVolume !== currentVolume) {
            currentVolume = freshVolume;
        }
    }
    const container = document.getElementById('chapters-list');
    if (!currentVolume || !Array.isArray(currentVolume.chapters)) {
        currentChapters = [];
        if (container) container.innerHTML = '';
        renderStateBlock(container, {
            icon: '\uD83D\uDCC2',
            title: '\u041D\u0435\u0442 \u0433\u043B\u0430\u0432',
            description: '\u041D\u0435 \u0443\u0434\u0430\u043B\u043E\u0441\u044C \u043E\u0442\u043A\u0440\u044B\u0442\u044C \u0442\u043E\u043C. \u041F\u043E\u043F\u0440\u043E\u0431\u0443\u0439\u0442\u0435 \u043E\u0442\u043A\u0440\u044B\u0442\u044C \u0441\u0435\u0440\u0438\u044E \u0435\u0449\u0451 \u0440\u0430\u0437.'
        });
        return;
    }
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
    const query = readerSearchQuery;
    const visibleChapters = currentChapters
        .map((ch, idx) => ({ ch, idx }))
        .filter(({ ch }) => matchesChapterSearch(ch, query, currentVolume.volume));

    if (visibleChapters.length === 0) {
        renderStateBlock(container, {
            icon: '\uD83D\uDD0E',
            title: '\u041d\u0438\u0447\u0435\u0433\u043e \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d\u043e',
            description: '\u041f\u043e\u043f\u0440\u043e\u0431\u0443\u0439\u0442\u0435 \u043d\u043e\u043c\u0435\u0440 \u0433\u043b\u0430\u0432\u044b, \u043d\u0430\u0437\u0432\u0430\u043d\u0438\u0435 \u0438\u043b\u0438 \u0442\u043e\u043c.'
        });
        updateReaderSearchEmpty(query ? 'В этом томе нет глав по текущему запросу.' : '');
        return;
    }
    updateReaderSearchEmpty('');

    const lastRead = getLastRead(currentSeries.id);
    const lastChapter = sameReaderKey(lastRead?.volume, currentVolume.volume) ? lastRead.chapter : null;

    container.innerHTML = visibleChapters.map(({ ch, idx }, visibleIdx) => {
        const readClass = isRead(currentSeries.id, currentVolume.volume, ch.chapter) ? 'read' : '';
        const chapName = ch.custom_name || `Глава ${ch.chapter}`;
        const hasCustom = !!ch.custom_name;
        const linkBtn = isAdminMode ? `<button class="admin-link-btn" title="Редактировать ссылку" onclick="openEditUrlModal(${idx}); event.stopPropagation();">&#128279;</button>` : '';
        const editBtns = isAdminMode ? `
            <button class="admin-edit-btn" title="Переименовать" onclick="renameItem('chap_${currentSeries.id}_${currentVolume.volume}_${ch.chapter}'); event.stopPropagation();">&#9998;</button>
            ${hasCustom ? `<button class="admin-reset-btn" title="Сброс на дефолт" onclick="resetCustomName('chap_${currentSeries.id}_${currentVolume.volume}_${ch.chapter}'); event.stopPropagation();">&#8635;</button>` : ''}
        ` : '';
        const moveBtns = isAdminMode ? `
            <button type="button" class="admin-move-btn" title="Переместить вверх" data-move-chapter="up" data-chapter-idx="${idx}" ${idx === 0 ? 'disabled' : ''} onclick="event.stopPropagation(); event.preventDefault(); moveChapter(${idx}, -1);">&#9650;</button>
            <button type="button" class="admin-move-btn" title="Переместить вниз" data-move-chapter="down" data-chapter-idx="${idx}" ${idx === currentChapters.length - 1 ? 'disabled' : ''} onclick="event.stopPropagation(); event.preventDefault(); moveChapter(${idx}, 1);">&#9660;</button>
        ` : '';
        const customBadge = (isAdminMode && hasCustom) ? '<span class="custom-name-badge">кастом</span>' : '';
        const isCurrent = lastChapter && sameReaderKey(ch.chapter, lastChapter);
        const hasContent = chapterHasAnyContent(ch);
        const sourceUrls = getChapterSourceUrls(ch);
        const fallbackBtn = !hasContent && sourceUrls[0]
            ? `<button type="button" class="series-action-btn" data-chapter-fallback-url="${escapeHtml(sourceUrls[0])}">Открыть источник</button>`
            : '';

        const readState = readClass === 'read';
        const srcCount = Array.isArray(ch.urls) ? ch.urls.length : (ch.url ? 1 : 0);
        const metaParts = [];
        if (!hasContent) metaParts.push('<span class="chapter-meta-warn">нет источника</span>');
        if (srcCount > 1) metaParts.push(`<span>${srcCount} источника</span>`);
        if (readState) metaParts.push('<span class="chapter-meta-read">✓ прочитано</span>');
        else if (isCurrent) metaParts.push('<span class="chapter-meta-current">читается</span>');
        else metaParts.push('<span>не прочитано</span>');
        const meta = metaParts.join('<span class="chapter-meta-dot">·</span>');

        return `
        <div class="chapter-item chapter-tile ${readClass}${isCurrent ? ' current-chapter' : ''}${!hasContent ? ' chapter-item-disabled' : ''}" data-chapter-idx="${idx}" ${isAdminMode ? 'draggable="true"' : ''}>
            ${isAdminMode ? '<div class="drag-handle" title="Перетащить">⠿</div>' : ''}
            ${isAdminMode ? `<div class="admin-move-group">${moveBtns}</div>` : ''}
            <div class="chapter-num${readState ? ' is-read' : ''}${isCurrent ? ' is-current' : ''}">${query ? visibleIdx + 1 : idx + 1}</div>
            <div class="chapter-body">
                <div class="chapter-name">${chapName}${customBadge}${linkBtn}${editBtns}${fallbackBtn}</div>
                <div class="chapter-meta">${meta}</div>
            </div>
            <span class="chapter-read-mark" aria-hidden="true">✓</span>
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

    scheduleCurrentVolumeWarmup();
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

    sendClientTelemetry('chapter_click', buildTelemetryContext({
        series_id: currentSeries?.id || '',
        volume: currentVolume?.volume ?? '',
        chapter: chapter.chapter,
        chapter_idx: idx,
        has_source: getChapterSourceUrls(chapter).length > 0,
        has_inline_text: !!(chapter.text && String(chapter.text).trim())
    }));

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
    setQuickSwitcherOpen(false);

    showScreen('reader');

    if (API_URL) {
        loadLikes();
        loadReactions();
        loadComments();
        document.getElementById('social-section').style.display = 'block';
        syncPublicReadModeUI();
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
        !currentSeries.volumes.some((v) => sameReaderKey(v.volume, currentVolume.volume))
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

function buildChapterContentApiUrl(chapter) {
    if (!currentSeries || !currentVolume || !chapter?.chapter) return '';
    return buildChapterContentApiUrlFor(currentSeries.id, currentVolume.volume, chapter.chapter);
}

function buildChapterFallbackPayload(chapter, overrides = {}) {
    const sourceUrls = getChapterSourceUrls(chapter);
    return {
        ok: false,
        source_type: 'fallback',
        html: '',
        fallback_url: sourceUrls[0] || null,
        ...overrides
    };
}

function renderUnavailableChapterState(container, chapter, telemetryContext = null, payload = {}) {
    const resolved = buildChapterFallbackPayload(chapter, payload);
    const contentArea = document.getElementById('reader-content');
    clearChapterLoadingHint();
    if (contentArea) contentArea.classList.remove('loading');

    const hasFallbackUrl = !!resolved.fallback_url;
    renderStateBlock(container, {
        variant: hasFallbackUrl ? 'error' : 'empty',
        icon: hasFallbackUrl ? '📡' : '📂',
        title: hasFallbackUrl ? 'Не удалось загрузить главу' : 'Глава пока не загружена',
        description: hasFallbackUrl
            ? 'Можно открыть оригинальный источник напрямую, пока встроенное чтение недоступно.'
            : 'Для этой главы пока нет текста или рабочей ссылки.',
        actionLabel: hasFallbackUrl ? 'Открыть источник' : 'Вернуться к главам',
        onAction: () => {
            if (hasFallbackUrl) {
                openExternalChapterSource(resolved.fallback_url);
            } else {
                backFromReader();
            }
        }
    });

    sendClientTelemetry('chapter_content_load_failed', buildTelemetryContext({
        series_id: currentSeries?.id || '',
        volume: currentVolume?.volume ?? '',
        chapter: chapter?.chapter || '',
        source_type: resolved.source_type || 'fallback',
        fallback_url: resolved.fallback_url || '',
        reason: resolved.reason || 'missing_content'
    }));
    reportChapterOpenTelemetry(chapter, telemetryContext, 'fallback');
}

function loadChapterContentFromServer(chapter, telemetryContext = null) {
    const container = document.getElementById('reader-text');
    const chapterTelemetryContext = telemetryContext || buildChapterOpenTelemetryContext(currentChapterIdx, false);
    if (!container) return;

    const endpoint = buildChapterContentApiUrl(chapter);
    const cacheKey = buildChapterPayloadCacheKey(currentSeries?.id, currentVolume?.volume, chapter?.chapter);
    if (!API_URL || !endpoint) {
        return loadChapterContentDirectFallback(chapter, chapterTelemetryContext);
    }

    const cachedPayload = getCachedChapterPayload(cacheKey);
    let renderedCachedPayload = false;
    if (cachedPayload && cachedPayload.ok && cachedPayload.html) {
        renderLoadedContent(container, cachedPayload.html, chapter, chapterTelemetryContext, cachedPayload.source_type || 'api_cache');
        renderedCachedPayload = true;
        if (!chapterContentLooksVisible(container)) {
            renderUnavailableChapterState(container, chapter, chapterTelemetryContext, {
                source_type: cachedPayload?.source_type || 'fallback',
                fallback_url: cachedPayload?.fallback_url || null,
                reason: 'empty_cached_content'
            });
            renderedCachedPayload = false;
        }
    } else if (cachedPayload && !cachedPayload.ok) {
        renderUnavailableChapterState(container, chapter, chapterTelemetryContext, {
            source_type: cachedPayload?.source_type || 'fallback',
            fallback_url: cachedPayload?.fallback_url || null,
            reason: 'cached_fallback'
        });
        renderedCachedPayload = true;
    }

    const inflightPayload = cacheKey ? chapterPayloadInflight.get(cacheKey) : null;
    if (inflightPayload) {
        if (!renderedCachedPayload) showChapterLoadingState(container, chapter);
        inflightPayload.then((payload) => {
            if (chapter !== currentChapters[currentChapterIdx]) return;
            if (payload && payload.ok && payload.html) {
                renderLoadedContent(container, payload.html, chapter, chapterTelemetryContext, payload.source_type || 'api_warm_cache');
                if (!chapterContentLooksVisible(container)) {
                    renderUnavailableChapterState(container, chapter, chapterTelemetryContext, {
                        source_type: payload?.source_type || 'fallback',
                        fallback_url: payload?.fallback_url || null,
                        reason: 'empty_warm_content'
                    });
                }
                return;
            }
            renderUnavailableChapterState(container, chapter, chapterTelemetryContext, {
                source_type: payload?.source_type || 'fallback',
                fallback_url: payload?.fallback_url || null,
                reason: payload?.ok === false ? 'warm_server_fallback' : 'warm_empty_html'
            });
        });
        return;
    }

    _chapterAbortController = new AbortController();
    const signal = _chapterAbortController.signal;
    setTimeout(() => {
        if (_chapterAbortController && !_chapterAbortController.signal.aborted) {
            _chapterAbortController.abort(new Error('Timeout'));
        }
    }, 15000);

    if (!renderedCachedPayload) {
        showChapterLoadingState(container, chapter);
    } else {
        const hint = container.querySelector('[data-chapter-loading-hint]');
        if (hint) hint.textContent = 'Показываю сохранённую главу, тихо проверяю обновление...';
    }

    const headers = {};
    const cachedEtag = cachedPayload?._etag || getPersistentChapterPayload(cacheKey)?.etag || '';
    if (cachedEtag) headers['If-None-Match'] = cachedEtag;

    apiFetch(endpoint, { signal, headers }).then(async (resp) => {
        if (signal.aborted || chapter !== currentChapters[currentChapterIdx]) return;
        if (resp.status === 304) {
            if (!renderedCachedPayload && cachedPayload && cachedPayload.ok && cachedPayload.html) {
                renderLoadedContent(container, cachedPayload.html, chapter, chapterTelemetryContext, cachedPayload.source_type || 'api_cache');
            }
            return;
        }
        if (!resp.ok) {
            throw new Error(`HTTP ${resp.status}`);
        }
        const payload = await resp.json();
        if (payload && typeof payload === 'object') {
            rememberCachedChapterPayload(cacheKey, payload, { etag: resp.headers.get('etag') || '' });
        }
        if (payload && payload.ok && payload.html) {
            renderLoadedContent(container, payload.html, chapter, chapterTelemetryContext, payload.source_type || 'api');
            if (!chapterContentLooksVisible(container)) {
                renderUnavailableChapterState(container, chapter, chapterTelemetryContext, {
                    source_type: payload?.source_type || 'fallback',
                    fallback_url: payload?.fallback_url || null,
                    reason: 'empty_rendered_content'
                });
            }
            return;
        }
        renderUnavailableChapterState(container, chapter, chapterTelemetryContext, {
            source_type: payload?.source_type || 'fallback',
            fallback_url: payload?.fallback_url || null,
            reason: payload?.ok === false ? 'server_fallback' : 'empty_html'
        });
    }).catch((err) => {
        if (err.name === 'AbortError') return;
        if (renderedCachedPayload) {
            const hint = container.querySelector('[data-chapter-loading-hint]');
            if (hint) hint.textContent = 'Нет сети, показываю сохранённую версию.';
            return;
        }
        console.warn('Chapter API load failed, using direct fallback:', err);
        loadChapterContentDirectFallback(chapter, chapterTelemetryContext);
    });
}

function loadChapterContentDirectFallback(chapter, telemetryContext = null) {
    const container = document.getElementById('reader-text');
    const chapterTelemetryContext = telemetryContext || buildChapterOpenTelemetryContext(currentChapterIdx, false);
    if (!container) return;

    let urlsToLoad = getChapterSourceUrls(chapter);
    const telegraphUrls = urlsToLoad.filter((u) => u.includes('telegra.ph'));
    if (telegraphUrls.length > 0) {
        urlsToLoad = telegraphUrls;
    } else {
        const teletypeUrls = urlsToLoad.filter((u) => u.includes('teletype.in'));
        if (teletypeUrls.length > 0) {
            urlsToLoad = [teletypeUrls[0]];
        }
    }

    if (urlsToLoad.length === 0) {
        if (chapter.text) {
            const paragraphs = chapter.text.split('\n\n').map((p) => `<p>${p.trim()}</p>`).join('');
            renderLoadedContent(container, paragraphs, chapter, chapterTelemetryContext, 'inline_text');
        } else {
            renderUnavailableChapterState(container, chapter, chapterTelemetryContext, { reason: 'missing_content' });
        }
        return;
    }

    showChapterLoadingState(container, chapter);
    _chapterAbortController = new AbortController();
    const signal = _chapterAbortController.signal;
    setTimeout(() => {
        if (_chapterAbortController && !_chapterAbortController.signal.aborted) {
            _chapterAbortController.abort(new Error('Timeout'));
        }
    }, 15000);

    const loadPromises = urlsToLoad.map(async (u) => {
        if (u.includes('teletype.in')) {
            return `<iframe src="${u}" class="teletype-iframe" frameborder="0" style="width:100%;min-height:85vh;border:none;border-radius:8px;margin-bottom:20px;" loading="lazy"></iframe>`;
        }
        const telegraphMatch = u.match(/telegra\.ph\/(.+)/);
        if (telegraphMatch) {
            const resp = await fetch(`https://api.telegra.ph/getPage/${telegraphMatch[1]}?return_content=true`, { signal });
            const data = await resp.json();
            if (data.ok && data.result && data.result.content) {
                return renderTelegraphContent(data.result.content);
            }
        }
        return `<iframe src="${u}" frameborder="0" style="width:100%;min-height:80vh;border:none;border-radius:8px;margin-bottom:20px;" loading="lazy"></iframe>`;
    });

    Promise.all(loadPromises).then((results) => {
        if (signal.aborted || chapter !== currentChapters[currentChapterIdx]) return;
        const joined = results.join('').trim();
        if (!joined) {
            renderUnavailableChapterState(container, chapter, chapterTelemetryContext, {
                source_type: 'fallback',
                reason: 'empty_direct_fallback'
            });
            return;
        }
        renderLoadedContent(container, joined, chapter, chapterTelemetryContext, 'network_fallback');
    }).catch((err) => {
        if (err.name === 'AbortError') return;
        console.error('Chapter direct fallback failed:', err);
        renderUnavailableChapterState(container, chapter, chapterTelemetryContext, {
            source_type: 'fallback',
            reason: 'direct_fallback_error'
        });
    });
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

    loadChapterContentFromServer(chapter, chapterTelemetryContext);
    return;

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
    clearChapterLoadingHint();
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
    scheduleNextChapterPrefetch(chapter);
}

// ★ Skeleton Loader (пункт 5)
function buildSkeletonLoader(title = 'Загружаем главу', description = 'Подготавливаем текст и изображения...') {
    let lines = '';
    const widths = [100, 92, 85, 95, 70, 88, 96, 80, 60, 90, 100, 75, 88, 50];
    for (let i = 0; i < widths.length; i++) {
        lines += `<div class="skeleton-line" style="width:${widths[i]}%;animation-delay:${i * 0.05}s"></div>`;
    }
    return `
        <div class="skeleton-loader-card">
            <div class="skeleton-loader-copy">
                <strong>${escapeHtml(title)}</strong>
                <span class="skeleton-loader-caption" data-chapter-loading-hint>${escapeHtml(description)}</span>
            </div>
            <div class="skeleton-loader">${lines}</div>
        </div>
    `;
}

function showChapterLoadingState(container, chapter = null) {
    if (!container) return;
    clearChapterLoadingHint();
    const hasRemoteSource = getChapterSourceUrls(chapter).length > 0;
    const description = hasRemoteSource
        ? 'Подготавливаем текст и изображения из источника...'
        : 'Открываем текст главы...';
    container.innerHTML = buildSkeletonLoader('Загружаем главу', description);
    const contentArea = document.getElementById('reader-content');
    if (contentArea) contentArea.scrollTop = 0;

    _chapterLoadingHintTimer = setTimeout(() => {
        if (container !== document.getElementById('reader-text')) return;
        const hint = container.querySelector('[data-chapter-loading-hint]');
        if (!hint) return;
        hint.textContent = 'Источник отвечает дольше обычного. Для больших глав из TeleType это нормально.';
    }, 1200);
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

    if (API_URL && currentSeries && currentVolume && chapter.chapter) {
        warmChapterPayloadByIndex(nextIdx, { preferPrefetchSlot: true }).catch(() => {}).finally(() => {
            _prefetchingIdx = -1;
        });
        return;
    }

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
    if (!API_URL) return;
    if (!hasWriteAuth()) {
        requireTelegramAuth('ставить лайки');
        return;
    }
    const key = getChapterKey();
    if (!key) return;
    try {
        const resp = await apiFetch(API_URL + '/api/likes', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ chapter_key: key })
        });
        const data = await resp.json();
        if (!resp.ok) {
            if (resp.status === 401) {
                handleAuthRejected('Сессия Telegram не активна. Войдите ещё раз, чтобы ставить лайки.');
                return;
            }
            throw new Error(data.error || `HTTP ${resp.status}`);
        }

        const btn = document.getElementById('like-btn');
        if (data.liked) {
            btn.classList.add('just-liked');
            spawnFloatingHearts();
        }
        setTimeout(() => btn.classList.remove('just-liked'), 500);

        updateLikeUI(data.count, data.liked);
    } catch (e) {
        console.warn('Like toggle error:', e);
        showToast(`Не удалось поставить лайк: ${e.message || 'ошибка сети'}`);
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
    if (!hasWriteAuth()) {
        requireTelegramAuth('отвечать на комментарии');
        return;
    }
    replyingToId = id;
    const indicator = document.getElementById('reply-indicator');
    if (indicator) indicator.style.display = 'flex';
    const nameEl = document.getElementById('reply-to-name');
    if (nameEl) nameEl.textContent = name;
    const input = document.getElementById('comment-input');
    if (input) input.focus();
}

function cancelReply() {
    replyingToId = null;
    const indicator = document.getElementById('reply-indicator');
    if (indicator) indicator.style.display = 'none';
    const nameEl = document.getElementById('reply-to-name');
    if (nameEl) nameEl.textContent = '';
}

// Refresh v5: toggle toolbar forматирования (B/I/S/quote/spoiler)
function toggleCommentToolbar() {
    const toolbar = document.getElementById('comment-toolbar');
    const btn = document.getElementById('comment-format-toggle');
    if (!toolbar) return;
    const isHidden = toolbar.classList.toggle('hidden');
    toolbar.setAttribute('aria-hidden', isHidden ? 'true' : 'false');
    if (btn) btn.classList.toggle('is-active', !isHidden);
}

// Refresh v5: auto-grow textarea для Telegram-стиля (1 → 5 строк макс)
function autoGrowCommentInput(el) {
    if (!el) return;
    el.style.height = 'auto';
    const maxHeight = 120; // ~5 строк
    const newHeight = Math.min(el.scrollHeight, maxHeight);
    el.style.height = newHeight + 'px';
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
        const editedTs = c.updated_at ? parseDate(c.updated_at) : 0;
        const createdTs = c._ts || parseDate(c.created_at);
        const isEdited = editedTs && (editedTs - createdTs > 1000);
        const editedBadge = isEdited
            ? `<span class="comment-edited-badge" title="Отредактировано ${formatDate(c.updated_at)}">ред.</span>`
            : '';
        const canWriteComments = hasWriteAuth();
        const isOwn = canWriteComments && String(c.user_id) === userId;
        const viewerIsAdmin = canWriteComments && isAdminMode;
        const color = getAvatarColor(String(c.user_id));
        const role = getUserRole(String(c.user_id));
        const roleBadge = role ? `<span class="comment-role-badge ${role.css}">${role.text}</span>` : '';

        const isPendingComment = c._optimisticState === 'sending' || c._optimisticState === 'error';
        const ownClass = isOwn ? 'is-own' : '';
        const commentStateClass = c._optimisticState === 'sending'
            ? 'pending-send'
            : (c._optimisticState === 'error' ? 'pending-error' : '');
        const stateBadge = c._optimisticState === 'sending'
            ? `<span class="comment-state-badge sending">Отправка…</span>`
            : (c._optimisticState === 'error' ? `<span class="comment-state-badge error">Не отправлено</span>` : '');

        // Refresh v5: inline reply-preview (если это ответ) — цитата автора + отрывок
        let replyPreviewHtml = '';
        if (c.parent_id) {
            const parent = commentMap[c.parent_id];
            if (parent) {
                const snippet = String(parent.text || '').replace(/\s+/g, ' ').slice(0, 80);
                const ellipsis = (parent.text || '').length > 80 ? '…' : '';
                replyPreviewHtml = `
                    <div class="comment-reply-preview" onclick="(function(){const el=document.getElementById('comment-${parent.id}');if(el){el.scrollIntoView({behavior:'smooth',block:'center'});el.classList.add('comment-flash');setTimeout(()=>el.classList.remove('comment-flash'),1200);}})()">
                        <div class="reply-preview-name">${escapeHtml(parent.user_name || '')}</div>
                        <div class="reply-preview-text">${escapeHtml(snippet)}${ellipsis}</div>
                    </div>`;
            }
        }

        const deleteBtn = (isOwn || viewerIsAdmin) ? `<button class="c-action-btn c-delete" onclick="deleteComment(${c.id})" title="Удалить"><svg viewBox="0 0 24 24" width="13" height="13" aria-hidden="true"><path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2m3 0v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg></button>` : '';
        const editBtn = isOwn ? `<button class="c-action-btn" onclick="editComment(${c.id})" title="Редактировать"><svg viewBox="0 0 24 24" width="13" height="13" aria-hidden="true"><path d="M12 20h9M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5z" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg></button>` : '';
        const replyBtn = canWriteComments ? `<button class="c-action-btn c-reply" onclick="setReply(${c.id}, '${escapeHtml(c.user_name)}')"><svg viewBox="0 0 24 24" width="13" height="13" aria-hidden="true"><path d="M10 9V5l-7 7 7 7v-4.1c5 0 8.5 1.6 11 5.1-1-5-4-10-11-11z" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg><span>Ответить</span></button>` : '';
        const reportBtn = canWriteComments && !isOwn ? `<button class="c-action-btn" onclick="reportComment(${c.id})" title="Пожаловаться"><svg viewBox="0 0 24 24" width="13" height="13" aria-hidden="true"><path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1zM4 22V3" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg></button>` : '';
        const retryBtn = c._optimisticState === 'error'
            ? `<button class="c-action-btn c-retry" onclick="retryPendingComment('${escapeHtml(String(c.id))}')">Повтор</button>`
            : '';
        const discardBtn = c._optimisticState === 'error'
            ? `<button class="c-action-btn c-discard" onclick="discardPendingComment('${escapeHtml(String(c.id))}')">Убрать</button>`
            : '';

        const likes = c.likes || 0;
        const userReaction = c.user_reaction;
        const likeActive = userReaction === 'like' ? 'active' : '';
        const reactionPending = !!c._reactionPending;
        const likeBtn = isPendingComment || !canWriteComments ? '' : `<button class="c-action-btn c-like ${likeActive} ${reactionPending ? 'pending' : ''}" ${reactionPending ? 'disabled' : ''} onclick="reactToComment(${c.id}, 'like')" title="Нравится">
            <svg viewBox="0 0 24 24" width="13" height="13" aria-hidden="true"><path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z" fill="${likeActive ? 'currentColor' : 'none'}" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
            <span>${likes || ''}</span>
        </button>`;

        const avatarUrl = API_URL && c.user_id ? `${API_URL}/api/avatar?user_id=${c.user_id}` : null;
        const avatarHtml = avatarUrl
            ? `<img src="${avatarUrl}" class="comment-avatar" alt="${initial}" style="background:${color}" onerror="this.onerror=null;this.outerHTML='<div class=&quot;comment-avatar&quot; style=&quot;background:${color}&quot;>${initial}</div>';">`
            : `<div class="comment-avatar" style="background:${color}">${initial}</div>`;

        let html = `
        <div class="comment-item ${isChild ? 'comment-reply' : ''} ${ownClass} ${commentStateClass}" id="comment-${c.id}">
            ${avatarHtml}
            <div class="comment-bubble-wrap">
                <div class="comment-bubble">
                    <div class="comment-meta">
                        <span class="comment-author">${escapeHtml(c.user_name)}</span>${roleBadge}${stateBadge}
                        <span class="comment-date">${date}${editedBadge ? ' · ' + editedBadge : ''}</span>
                    </div>
                    ${replyPreviewHtml}
                    <div class="comment-text" id="comment-text-${c.id}">${applyMarkup(c.text)}</div>
                </div>
                <div class="comment-actions">
                    ${likeBtn}
                    ${isPendingComment ? '' : replyBtn}
                    ${isPendingComment ? '' : editBtn}
                    ${isPendingComment ? '' : deleteBtn}
                    ${isPendingComment ? '' : reportBtn}
                    ${retryBtn}
                    ${discardBtn}
                </div>
            </div>
        </div>`;

        if (c.children && c.children.length > 0) {
            html += `<div class="comment-children">` + c.children.map(child => renderNode(child, true)).join('') + `</div>`;
        }
        return html;
    }

    list.innerHTML = topLevel.map(c => renderNode(c, false)).join('');
}

function reportComment(id) {
    if (!API_URL) return;
    if (!hasWriteAuth()) {
        requireTelegramAuth('отправлять жалобы');
        return;
    }

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
    if (!API_URL) return;
    if (!hasWriteAuth()) {
        requireTelegramAuth('ставить реакции комментариям');
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
        if (!resp.ok) {
            if (resp.status === 401) {
                comment.user_reaction = prevReaction;
                comment.likes = prevLikes;
                delete comment._reactionPending;
                renderComments(allCommentsCache);
                handleAuthRejected('Сессия Telegram не активна. Войдите ещё раз, чтобы реагировать.');
                return;
            }
            throw new Error(data.error || `HTTP ${resp.status}`);
        }
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
    const input = document.getElementById(`edit-input-${id}`);
    if (!input) return;
    const newText = input.value.trim();
    if (!newText) {
        showToast('Комментарий не может быть пустым');
        return;
    }
    const btns = document.querySelectorAll(`#comment-text-${id} .edit-actions button`);
    btns.forEach(b => { b.disabled = true; });

    try {
        const resp = await apiFetch(`${API_URL}/api/comments/${id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text: newText })
        });
        let data = {};
        try { data = await resp.json(); } catch (_) { data = {}; }
        if (!resp.ok || !data.ok) {
            const msg = data.error || `HTTP ${resp.status}`;
            if (resp.status === 403) {
                showToast('Редактировать можно только свои комментарии');
            } else if (resp.status === 404) {
                showToast('Комментарий не найден');
            } else {
                showToast('Не удалось сохранить: ' + msg);
            }
            return;
        }

        // Optimistic local update — без полного reload. Пользователь видит изменение сразу.
        const serverComment = data.comment || {};
        const cached = allCommentsCache.find(c => String(c.id) === String(id));
        if (cached) {
            cached.text = serverComment.text || newText;
            cached.updated_at = serverComment.updated_at || new Date().toISOString();
        }
        activeCommentEditId = null;
        renderComments(allCommentsCache);
        showToast('Комментарий изменён', 'success');
        haptic('success');
    } catch (e) {
        showToast('Ошибка сети.');
    } finally {
        btns.forEach(b => { b.disabled = false; });
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
    if (!API_URL) return;
    if (!hasWriteAuth()) {
        requireTelegramAuth('писать комментарии');
        return;
    }
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
            if (resp.status === 401) {
                pendingCommentSends.delete(String(tempId));
                allCommentsCache = allCommentsCache.filter(c => String(c.id) !== String(tempId));
                input.value = text;
                updateCommentPreview();
                renderComments(allCommentsCache);
                setCommentSendState('idle');
                handleAuthRejected('Сессия Telegram не активна. Войдите ещё раз, чтобы отправлять комментарии.');
                return;
            }
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
    const publicMode = isPublicReadMode();

    bar.innerHTML = list.map(item => {
        const count = reactions[item.type] || 0;
        const active = !publicMode && user_reaction === item.type ? 'active' : '';
        const authClass = publicMode ? 'auth-required' : '';
        const authAttrs = publicMode
            ? `aria-disabled="true" onclick="requireTelegramAuth('ставить реакции')"`
            : `onclick="toggleReaction('${item.type}')"`;
        return `
            <div class="reaction-item ${active} ${authClass} type-${item.type}" ${authAttrs} title="${item.text}">
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
    resetTransientUiState({ saveSettingsOnClose: true });

    const screens = document.querySelectorAll('.screen');
    screens.forEach(s => {
        s.classList.remove('active', 'slide-left');
    });

    document.getElementById(`screen-${name}`).classList.add('active');

    // Admin FAB + badge visibility (Phase 4) — delegated to helper
    syncAdminFabVisibility();
    syncAdminBadge();
    // Refresh v4: global admin FAB на не-reader экранах
    syncGlobalAdminFab(name);
    syncReaderSearchVisibility();
    syncReadingStatsTimer(name);

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

// Refresh v4: drop-cap (первая буква первого параграфа)
function setDropCap(enabled) {
    settings.dropCap = !!enabled;
    applySettings();
    saveSettings();
}

function setHideProgress(enabled) {
    settings.hideProgress = !!enabled;
    applySettings();
    saveSettings();
    updateSettingsUI();
}

function setHideChapterHeader(enabled) {
    settings.hideChapterHeader = !!enabled;
    applySettings();
    saveSettings();
    updateSettingsUI();
}

// ==========================================================================
// НАСТРОЙКИ
// ==========================================================================

function toggleSettings() {
    const overlay = document.getElementById('settings-overlay');
    const panel = document.getElementById('settings-panel');
    const isHidden = panel.classList.contains('hidden');

    if (!isHidden) {
        closeSettingsPanel({ save: true });
    } else {
        overlay.classList.remove('hidden');
        panel.classList.remove('hidden');
        showSettingsTab('font');
        updateSettingsUI();
    }
}

function scheduleNextChapterPrefetch(chapter) {
    clearNextChapterPrefetchTimers();
    const chapterKey = chapter && chapter.chapter !== undefined ? String(chapter.chapter) : '';
    const seriesId = currentSeries?.id;
    const volumeId = currentVolume?.volume;
    const baseChapterIdx = currentChapterIdx;
    const token = _nextChapterPrefetchToken;
    _nextChapterPrefetchTimer = setTimeout(() => {
        _nextChapterPrefetchTimer = null;
        if (token !== _nextChapterPrefetchToken) return;
        if (!sameReaderKey(currentSeries?.id, seriesId) || !sameReaderKey(currentVolume?.volume, volumeId)) return;
        if (currentChapterIdx !== baseChapterIdx) return;
        const activeChapter = currentChapters[baseChapterIdx];
        if (!activeChapter || String(activeChapter.chapter) !== chapterKey) return;
        if (API_URL) {
            const indexes = [baseChapterIdx - 1, baseChapterIdx + 1, baseChapterIdx + 2];
            indexes.forEach((idx, order) => {
                queueNextChapterPrefetchChild(() => {
                    if (token !== _nextChapterPrefetchToken) return;
                    if (!sameReaderKey(currentSeries?.id, seriesId) || !sameReaderKey(currentVolume?.volume, volumeId)) return;
                    if (currentChapterIdx !== baseChapterIdx) return;
                    warmChapterPayloadByIndex(idx, { preferPrefetchSlot: idx === baseChapterIdx + 1 }).catch(() => {});
                }, order * 180);
            });
        }
        prefetchNextChapter();
    }, 180);
}

function scheduleCurrentVolumeWarmup() {
    if (_chapterWarmupTimer) {
        clearTimeout(_chapterWarmupTimer);
    }
    if (!API_URL || !currentSeries || !currentVolume || !Array.isArray(currentChapters) || currentChapters.length === 0) {
        return;
    }

    const lastRead = getLastRead(currentSeries.id);
    const preferredIdx = (
        sameReaderKey(lastRead?.volume, currentVolume.volume)
            ? currentChapters.findIndex((chapter) => sameReaderKey(chapter?.chapter, lastRead?.chapter))
            : -1
    );
    const candidateIndexes = [];
    if (preferredIdx >= 0) candidateIndexes.push(preferredIdx);
    if (!candidateIndexes.includes(0)) candidateIndexes.push(0);
    if (preferredIdx >= 0 && preferredIdx + 1 < currentChapters.length && !candidateIndexes.includes(preferredIdx + 1)) {
        candidateIndexes.push(preferredIdx + 1);
    } else if (currentChapters.length > 1 && !candidateIndexes.includes(1)) {
        candidateIndexes.push(1);
    }

    _chapterWarmupTimer = setTimeout(() => {
        const seriesId = currentSeries?.id;
        const volumeId = currentVolume?.volume;
        candidateIndexes.forEach((idx, order) => {
            setTimeout(() => {
                if (!sameReaderKey(currentSeries?.id, seriesId) || !sameReaderKey(currentVolume?.volume, volumeId)) return;
                warmChapterPayloadByIndex(idx, { preferPrefetchSlot: idx === preferredIdx + 1 }).catch(() => {});
            }, order * 220);
        });
    }, 90);
}

// Refresh v5: табы удалены — функция осталась no-op для обратной совместимости
function showSettingsTab(tabName) {
    const activeContent = document.getElementById(`settings-tab-${tabName}`);
    if (activeContent) {
        activeContent.classList.remove('hidden');
    }
}

// Refresh v5: live-превью в настройках. Зеркалит `.reader-text` стили + индикаторы max-width, dimmer, indent, dropCap.
function syncSettingsPreview() {
    const preview = document.getElementById('settings-preview');
    const previewInner = document.getElementById('settings-preview-inner');
    const previewDimmer = document.getElementById('settings-preview-dimmer');
    const previewText = preview ? preview.querySelector('.settings-preview-text') : null;
    if (!preview || !previewText) return;

    // Маппинг font-key → font-family (зеркалит applySettings)
    const fontMap = {
        serif: "'Noto Serif', Georgia, serif",
        sans: "Inter, -apple-system, system-ui, sans-serif",
        mono: "'JetBrains Mono', 'Fira Code', Consolas, monospace",
        display: "'Playfair Display', serif"
    };
    const fontKey = settings && settings.font ? settings.font : 'serif';
    previewText.style.fontFamily = fontMap[fontKey] || fontMap.serif;

    if (!settings) return;

    if (settings.fontSize) previewText.style.fontSize = (settings.fontSize * 0.85) + 'px';
    if (settings.lineHeight) previewText.style.lineHeight = String(settings.lineHeight);
    if (typeof settings.letterSpacing === 'number') previewText.style.letterSpacing = settings.letterSpacing + 'px';
    if (settings.textAlign) previewText.style.textAlign = settings.textAlign;

    // Макс. ширина — отражает settings.textWidth (50..100 %)
    if (previewInner && settings.textWidth) {
        previewInner.style.maxWidth = settings.textWidth + '%';
    }

    // Красная строка — toggle класс + размер отступа
    previewText.classList.toggle('indent-on', !!settings.indent);
    if (typeof settings.paraIndent === 'number') {
        // В превью шрифт меньше, поэтому переводим px → em ~относительно размера превью.
        const previewFontPx = (settings.fontSize || 17) * 0.85;
        const indentEm = settings.paraIndent / previewFontPx;
        previewText.style.setProperty('--preview-para-indent', indentEm.toFixed(2) + 'em');
    }

    // Буквица
    previewText.classList.toggle('drop-cap-on', !!settings.dropCap);

    // Яркость (dimmer)
    if (previewDimmer && typeof settings.dimmerValue === 'number') {
        previewDimmer.style.background = `rgba(0, 0, 0, ${settings.dimmerValue / 100})`;
    }
    // Фон и цвет берутся из CSS-переменных темы автоматически.
}

function updateSettingsUI() {
    settings = normalizeReaderSettings(settings);
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

    // Refresh v4 toggles
    const dropCapInput = document.getElementById('input-dropCap');
    if (dropCapInput) dropCapInput.checked = !!settings.dropCap;
    const hideProgressInput = document.getElementById('hide-progress-toggle');
    if (hideProgressInput) hideProgressInput.checked = !!settings.hideProgress;
    const hideChapterHeaderInput = document.getElementById('hide-chapter-header-toggle');
    if (hideChapterHeaderInput) hideChapterHeaderInput.checked = !!settings.hideChapterHeader;

    syncAdminModeControls();
}

function setDimmer(val) {
    const nextValue = clampDimmerValue(val);
    settings.dimmerValue = nextValue;
    if (document.getElementById('label-dimmerValue')) document.getElementById('label-dimmerValue').innerText = nextValue + '%';
    if (document.getElementById('input-dimmerValue')) document.getElementById('input-dimmerValue').value = nextValue;
    applySettings();
    saveSettings();
}



function applySettings() {
    settings = normalizeReaderSettings(settings);
    // Тема (Refresh v4: добавлены warm, high-contrast)
    document.body.classList.remove('theme-sepia', 'theme-dark', 'theme-gray', 'theme-amoled', 'theme-warm', 'theme-high-contrast');
    if (settings.theme && settings.theme !== 'light') {
        document.body.classList.add(`theme-${settings.theme}`);
    }
    document.body.classList.toggle('reader-hide-progress', !!settings.hideProgress);
    document.body.classList.toggle('reader-hide-chapter-header', !!settings.hideChapterHeader);

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

        // Шрифт (Refresh v4: поддержка mono)
        readerText.classList.remove('font-sans', 'font-slab', 'font-mono', 'font-montserrat', 'font-display');
        if (settings.font === 'sans') readerText.classList.add('font-sans');
        if (settings.font === 'mono') readerText.classList.add('font-mono');
        if (settings.font === 'montserrat') readerText.classList.add('font-montserrat');
        if (settings.font === 'display') readerText.classList.add('font-display');

        // Выравнивание
        readerText.classList.toggle('align-justify', settings.textAlign === 'justify');

        // Отступы
        readerText.classList.toggle('indent-on', settings.indent);

        // Refresh v4: drop-cap (первая буква первого параграфа)
        readerText.classList.toggle('drop-cap-on', !!settings.dropCap);

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

    // Refresh v5: синхронизация live-превью в настройках (если панель открыта)
    syncSettingsPreview();
}

function saveSettings() {
    settings = normalizeReaderSettings(settings);
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
                    const screen = document.getElementById('screen-reader');
                    const isNowImmersive = screen?.classList.toggle('immersive') || false;
                    isImmersive = isNowImmersive;
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

    const series = findSeriesById(latestBm.series_id);
    if (!series) return;

    const vol = findVolumeByKey(series, latestBm.volume_id);
    let chTitle = "Глава " + latestBm.chapter_key;
    if (vol) {
        const chAttr = vol.chapters.find(c => sameReaderKey(c.chapter, latestBm.chapter_key));
        if (chAttr && chAttr.custom_name) chTitle = chAttr.custom_name;
    }
    const volTitle = vol && vol.custom_name ? vol.custom_name : "Том " + latestBm.volume_id;

    // Общий прогресс серии.
    const totalCh = series.volumes.reduce((sum, v) => sum + (v.chapters || []).length, 0);
    const readCount = series.volumes.reduce((sum, v) => {
        return sum + (v.chapters || []).filter(c => isRead(series.id, v.volume, c.chapter)).length;
    }, 0);
    const progress = totalCh > 0 ? Math.round((readCount / totalCh) * 100) : 0;

    const firstLetter = (series.title || '?').trim().charAt(0).toUpperCase();
    const coverHtml = series.cover_url
        ? `<img src="${escapeHtml(series.cover_url)}" alt="${escapeHtml(series.title)}" loading="lazy">`
        : `<div class="r4-poster-placeholder continue-cover-placeholder">${escapeHtml(firstLetter)}</div>`;

    container.style.display = 'block';
    container.innerHTML = `
        <div class="continue-reading-card continue-reading-hero" data-series-action="continue" data-series-id="${escapeHtml(String(series.id))}">
            <div class="continue-reading-cover">${coverHtml}</div>
            <div class="continue-reading-info">
                <div class="continue-reading-label">Продолжить чтение</div>
                <h3 class="continue-reading-title">${escapeHtml(series.title)}</h3>
                <p class="continue-reading-chapter">${escapeHtml(volTitle)} · ${escapeHtml(chTitle)}</p>
                <div class="continue-reading-progress">
                    <div class="continue-reading-progress-bar" style="width: ${progress}%"></div>
                </div>
                <div class="continue-reading-progress-text">${readCount}/${totalCh || 0} глав · ${progress}%</div>
            </div>
            <div class="continue-reading-arrow" aria-hidden="true">›</div>
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
    const panel = document.getElementById('toc-panel');
    setToCOpen(!(panel && panel.classList.contains('active')));
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

// Refresh v4: SVG icons для autoscroll fab
const AUTOSCROLL_PLAY_SVG = '<svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor" aria-hidden="true"><path d="M6 4.5v15L20 12z"/></svg>';
const AUTOSCROLL_PAUSE_SVG = '<svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor" aria-hidden="true"><rect x="6" y="5" width="4" height="14" rx="1"/><rect x="14" y="5" width="4" height="14" rx="1"/></svg>';

function startAutoscroll() {
    autoscrollActive = true;
    const fab = document.getElementById('autoscroll-fab');
    if (fab) {
        fab.classList.add('scrolling');
        fab.innerHTML = AUTOSCROLL_PAUSE_SVG;
        fab.setAttribute('aria-label', 'Пауза автоскролла');
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
        fab.innerHTML = AUTOSCROLL_PLAY_SVG;
        fab.setAttribute('aria-label', 'Запустить автоскролл');
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

// Remember pristine button labels to restore after async operations.
function captureOriginalLabel(btn) {
    if (!btn) return;
    if (!btn.dataset.originalLabel) {
        btn.dataset.originalLabel = btn.textContent.trim();
    }
}
function restoreOriginalLabel(btn) {
    if (!btn) return;
    btn.disabled = false;
    if (btn.dataset.originalLabel) {
        btn.textContent = btn.dataset.originalLabel;
    }
}

function openEditUrlModal(chIdx) {
    if (!currentChapters[chIdx]) {
        showToast('Нет главы для редактирования');
        return;
    }
    if (!hasAdminApi()) {
        showToast('Редактирование доступно только при подключенном API.');
        return;
    }
    editUrlChapterIdx = chIdx;
    const ch = currentChapters[chIdx];
    const chapName = ch.custom_name || `Глава ${ch.chapter}`;
    document.getElementById('edit-url-chapter-name').textContent = chapName;
    const currentUrl = (ch.urls && ch.urls.length > 0) ? ch.urls.join('\n') : (ch.url || '');
    document.getElementById('edit-url-input').value = currentUrl;
    // Reset button to pristine state in case a previous attempt errored out.
    restoreOriginalLabel(document.getElementById('edit-url-save'));
    document.getElementById('edit-url-overlay').classList.remove('hidden');
    document.getElementById('edit-url-modal').classList.remove('hidden');
    setTimeout(() => document.getElementById('edit-url-input').focus(), 350);
}

function closeEditUrlModal() {
    const overlay = document.getElementById('edit-url-overlay');
    const modal = document.getElementById('edit-url-modal');
    if (overlay) overlay.classList.add('hidden');
    if (modal) modal.classList.add('hidden');
    restoreOriginalLabel(document.getElementById('edit-url-save'));
    editUrlChapterIdx = null;
}

async function saveEditUrl() {
    if (editUrlChapterIdx === null || !API_URL) return;
    const ch = currentChapters[editUrlChapterIdx];
    const newUrl = document.getElementById('edit-url-input').value.trim();

    const saveBtn = document.getElementById('edit-url-save');
    captureOriginalLabel(saveBtn);
    if (saveBtn) {
        saveBtn.disabled = true;
        saveBtn.textContent = 'Сохранение...';
    }

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
            const urlArr = newUrl.split('\n').map(u => u.trim()).filter(u => u.length > 0);
            ch.urls = urlArr;
            ch.url = urlArr[0] || '';
            closeEditUrlModal();
            showToast('✅ Ссылка обновлена!');
            haptic('success');
            // Re-render list silently to reflect updated link state.
            if (document.getElementById('screen-chapters')?.classList.contains('active')) {
                renderChaptersList();
            }
        } else {
            showToast('Ошибка: ' + (result.error || `HTTP ${resp.status}`));
        }
    } catch (e) {
        showToast('Ошибка сети: ' + e.message);
    } finally {
        restoreOriginalLabel(saveBtn);
    }
}

// ==========================================================================
// BULK UPLOAD MODAL (Admin)
// ==========================================================================

function openBulkModal() {
    if (!hasAdminApi()) {
        showToast('Массовая загрузка доступна только при подключенном API.');
        return;
    }
    if (!currentSeries || !currentVolume) {
        showToast('Сначала выберите том.');
        return;
    }
    const input = document.getElementById('bulk-upload-input');
    if (input) input.value = '';
    bulkUploadPreviewState = null;
    renderBulkPreviewPanel(null);
    restoreOriginalLabel(document.getElementById('bulk-upload-save'));
    document.getElementById('bulk-upload-overlay').classList.remove('hidden');
    document.getElementById('bulk-upload-modal').classList.remove('hidden');
    setTimeout(() => { if (input) input.focus(); }, 350);
}

function closeBulkModal() {
    const overlay = document.getElementById('bulk-upload-overlay');
    const modal = document.getElementById('bulk-upload-modal');
    if (overlay) overlay.classList.add('hidden');
    if (modal) modal.classList.add('hidden');
    bulkUploadPreviewState = null;
    renderBulkPreviewPanel(null);
    restoreOriginalLabel(document.getElementById('bulk-upload-save'));
}

// Pick next chapter number, supporting decimals like "1.5".
function computeNextChapterNumber(chapters) {
    const nums = (chapters || [])
        .map((c) => Number.parseFloat(c?.chapter))
        .filter((n) => Number.isFinite(n));
    if (nums.length === 0) return 1;
    const max = Math.max(...nums);
    return Math.max(1, Math.floor(max) + 1);
}

function collectBulkUploadPayload() {
    const raw = document.getElementById('bulk-upload-input')?.value.trim() || '';
    const urls = raw.split('\n').map((u) => u.trim()).filter((u) => u.length > 0);
    return {
        raw,
        urls,
        payload: {
            series_id: currentSeries?.id,
            volume: currentVolume?.volume,
            start_chapter: computeNextChapterNumber(currentChapters),
            urls
        }
    };
}

function renderBulkPreviewPanel(result) {
    const panel = document.getElementById('bulk-upload-preview-panel');
    if (!panel) return;
    if (!result) {
        panel.classList.add('hidden');
        panel.innerHTML = '';
        return;
    }

    const items = Array.isArray(result.items) ? result.items : [];
    const invalid = Array.isArray(result.invalid) ? result.invalid : [];
    const duplicates = Array.isArray(result.duplicates) ? result.duplicates : [];
    const warnings = Array.isArray(result.warnings) ? result.warnings : [];
    const newCount = items.filter((item) => item.status !== 'duplicate').length;
    const itemRows = items.map((item) => {
        const status = item.status === 'duplicate' ? 'Дубликат' : 'Новая';
        const rowClass = item.status === 'duplicate' ? 'is-duplicate' : 'is-new';
        return `
            <div class="bulk-preview-row ${rowClass}">
                <div class="bulk-preview-status">${status}</div>
                <div class="bulk-preview-url">Глава ${escapeHtml(String(item.chapter ?? ''))}: ${escapeHtml(item.url || '')}</div>
            </div>`;
    }).join('');
    const invalidRows = invalid.map((item) => `
        <div class="bulk-preview-row is-invalid">
            <div class="bulk-preview-status">Ошибка</div>
            <div class="bulk-preview-url">${escapeHtml(item.url || item.value || '')}</div>
            <div class="bulk-preview-warning">${escapeHtml(item.error || item.message || 'невалидная ссылка')}</div>
        </div>`).join('');
    const warningRows = warnings.map((item) => `
        <div class="bulk-preview-warning-row">${escapeHtml(item.message || String(item))}</div>`).join('');

    panel.innerHTML = `
        <div class="bulk-preview-summary">
            <span class="bulk-preview-chip">Новых: ${newCount}</span>
            <span class="bulk-preview-chip">Дубликатов: ${duplicates.length}</span>
            <span class="bulk-preview-chip">Ошибок: ${invalid.length}</span>
        </div>
        <div class="bulk-preview-list">${itemRows}${invalidRows}${warningRows}</div>
    `;
    panel.classList.remove('hidden');
}

async function previewBulkUpload() {
    if (!API_URL || !currentSeries || !currentVolume) return null;
    const collected = collectBulkUploadPayload();
    if (!collected.raw) return showToast('Вставьте ссылки');
    if (collected.urls.length === 0) return showToast('Нет валидных ссылок');

    const previewBtn = document.getElementById('bulk-upload-preview');
    captureOriginalLabel(previewBtn);
    if (previewBtn) {
        previewBtn.disabled = true;
        previewBtn.textContent = 'Проверяю...';
    }

    try {
        const resp = await apiFetch(API_URL + '/api/chapters/bulk/preview', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(collected.payload)
        });
        const result = await resp.json();
        bulkUploadPreviewState = { raw: collected.raw, result };
        renderBulkPreviewPanel(result);
        if (!resp.ok || result.ok === false) {
            showToast(result.error || 'Есть ошибки, публикация остановлена');
        }
        return result;
    } catch (e) {
        showToast('Ошибка проверки: ' + e.message);
        return null;
    } finally {
        restoreOriginalLabel(previewBtn);
    }
}

async function executeBulkUpload() {
    if (!API_URL || !currentSeries || !currentVolume) return;
    const raw = document.getElementById('bulk-upload-input').value.trim();
    if (!raw) return showToast('Вставьте ссылки');

    const urls = raw.split('\n').map(u => u.trim()).filter(u => u.length > 0);
    if (urls.length === 0) return showToast('Нет валидных ссылок');

    const nextChNum = computeNextChapterNumber(currentChapters);

    const saveBtn = document.getElementById('bulk-upload-save');
    captureOriginalLabel(saveBtn);
    if (saveBtn) {
        saveBtn.disabled = true;
        saveBtn.textContent = `Добавление ${urls.length} глав...`;
    }

    try {
        const resp = await apiFetch(API_URL + '/api/chapters/bulk', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                series_id: currentSeries.id,
                volume: currentVolume.volume,
                start_chapter: nextChNum,
                urls: urls
            })
        });
        const result = await resp.json();
        if (result.ok) {
            closeBulkModal();
            showToast(`✅ Добавлено ${result.added} глав!`);
            haptic('success');
            refreshReaderDataInBackground();
        } else {
            showToast('Ошибка: ' + (result.error || `HTTP ${resp.status}`));
        }
    } catch (e) {
        showToast('Ошибка сети: ' + e.message);
    } finally {
        restoreOriginalLabel(saveBtn);
    }
}

// ==========================================================================
// ADD / DELETE / COVER MODALS (Admin, Iteration D)
// ==========================================================================

async function executeBulkUploadLegacy() {
    if (!API_URL || !currentSeries || !currentVolume) return;
    const collected = collectBulkUploadPayload();
    if (!collected.raw) return showToast('Вставьте ссылки');
    if (collected.urls.length === 0) return showToast('Нет валидных ссылок');

    let preview = bulkUploadPreviewState && bulkUploadPreviewState.raw === collected.raw
        ? bulkUploadPreviewState.result
        : null;
    if (!preview) {
        preview = await previewBulkUpload();
    }
    const invalid = Array.isArray(preview?.invalid) ? preview.invalid : [];
    if (!preview || invalid.length > 0 || preview.ok === false) {
        return showToast('Публикация остановлена: исправьте ошибки предпросмотра');
    }

    const saveBtn = document.getElementById('bulk-upload-save');
    captureOriginalLabel(saveBtn);
    if (saveBtn) {
        saveBtn.disabled = true;
        saveBtn.textContent = `Добавление ${collected.urls.length} глав...`;
    }

    try {
        const resp = await apiFetch(API_URL + '/api/chapters/bulk', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(collected.payload)
        });
        const result = await resp.json();
        if (result.ok) {
            closeBulkModal();
            showToast(`Добавлено ${result.added} глав`);
            haptic('success');
            refreshReaderDataInBackground();
        } else {
            showToast('Ошибка: ' + (result.error || `HTTP ${resp.status}`));
        }
    } catch (e) {
        showToast('Ошибка сети: ' + e.message);
    } finally {
        restoreOriginalLabel(saveBtn);
    }
}

function openAddChapterModal(forIdx) {
    if (!hasAdminApi()) {
        showToast('Добавление доступно только при подключенном API.');
        return;
    }
    if (!currentSeries || !currentVolume) {
        showToast('Сначала выберите том.');
        return;
    }
    closeAdminMenu();
    const overlay = document.getElementById('add-chapter-overlay');
    const modal = document.getElementById('add-chapter-modal');
    const volumeInput = document.getElementById('add-chapter-volume');
    const chapInput = document.getElementById('add-chapter-number');
    const nameInput = document.getElementById('add-chapter-name');
    const urlInput = document.getElementById('add-chapter-url');
    const toneSelect = document.getElementById('add-chapter-tone');
    const editor = document.getElementById('add-chapter-editor');
    const seriesName = document.getElementById('chapter-editor-series-name');
    const sourceRow = document.getElementById('chapter-editor-source-row');
    const scheduleInput = document.getElementById('add-chapter-scheduled-at');
    if (!overlay || !modal) return;
    if (seriesName) seriesName.textContent = currentSeries?.title || currentSeries?.id || 'Серия';
    if (volumeInput) volumeInput.value = String(currentVolume.volume ?? 1);
    if (chapInput) chapInput.value = String(computeNextChapterNumber(currentChapters));
    if (nameInput) nameInput.value = '';
    if (urlInput) urlInput.value = '';
    if (toneSelect) toneSelect.value = 'without_negativity';
    if (editor) editor.innerHTML = '';
    if (sourceRow) sourceRow.classList.add('hidden');
    if (scheduleInput) {
        scheduleInput.value = '';
        scheduleInput.classList.add('hidden');
    }
    updateAddChapterCounter();
    restoreOriginalLabel(document.getElementById('add-chapter-save'));
    overlay.classList.remove('hidden');
    modal.classList.remove('hidden');
    document.body.classList.add('chapter-editor-open');
    setTimeout(() => { if (editor) editor.focus(); }, 150);
}

function closeAddChapterModal() {
    const overlay = document.getElementById('add-chapter-overlay');
    const modal = document.getElementById('add-chapter-modal');
    if (overlay) overlay.classList.add('hidden');
    if (modal) modal.classList.add('hidden');
    document.body.classList.remove('chapter-editor-open');
    restoreOriginalLabel(document.getElementById('add-chapter-save'));
}

function normalizeChapterEditorText(text) {
    return String(text || '').replace(/\u00a0/g, ' ').replace(/\s+/g, ' ').trim();
}

function getChapterEditorPlainText() {
    const editor = document.getElementById('add-chapter-editor');
    return normalizeChapterEditorText(editor?.innerText || editor?.textContent || '');
}

function getChapterEditorParagraphCount() {
    const editor = document.getElementById('add-chapter-editor');
    const raw = String(editor?.innerText || editor?.textContent || '').replace(/\u00a0/g, ' ').trim();
    if (!raw) return 0;
    return raw.split(/\n+/).map((line) => line.trim()).filter(Boolean).length;
}

function getChapterEditorHtml() {
    const editor = document.getElementById('add-chapter-editor');
    const text = getChapterEditorPlainText();
    if (!editor || !text) return '';
    return (editor.innerHTML || '').trim() || escapeHtml(text);
}

function updateAddChapterCounter() {
    const counter = document.getElementById('add-chapter-counter');
    if (!counter) return;
    counter.textContent = `${getChapterEditorParagraphCount()} / ${getChapterEditorPlainText().length}`;
}

function focusChapterEditor() {
    const editor = document.getElementById('add-chapter-editor');
    if (editor) editor.focus();
}

function execChapterEditorCommand(command) {
    focusChapterEditor();
    if (!command) return;
    if (command.startsWith('formatBlock:')) {
        const block = command.split(':')[1] || 'P';
        document.execCommand('formatBlock', false, block);
    } else {
        document.execCommand(command, false, null);
    }
    updateAddChapterCounter();
}

function toggleChapterEditorSource() {
    const sourceRow = document.getElementById('chapter-editor-source-row');
    if (!sourceRow) return;
    sourceRow.classList.toggle('hidden');
    if (!sourceRow.classList.contains('hidden')) {
        document.getElementById('add-chapter-url')?.focus();
    }
}

function insertChapterEditorImage() {
    const url = window.prompt('URL изображения');
    if (!url || !/^https?:\/\//i.test(url.trim())) {
        if (url) showToast('Укажите http(s)-ссылку на изображение');
        return;
    }
    focusChapterEditor();
    document.execCommand('insertImage', false, url.trim());
    updateAddChapterCounter();
}

function handleChapterEditorToolbar(event) {
    const target = event?.currentTarget || event?.target;
    const command = target?.dataset?.editorCommand || '';
    const action = target?.dataset?.editorAction || '';
    if (action === 'source') {
        toggleChapterEditorSource();
        return;
    }
    if (action === 'image') {
        insertChapterEditorImage();
        return;
    }
    execChapterEditorCommand(command);
}

function toggleChapterSchedulePicker() {
    const scheduleInput = document.getElementById('add-chapter-scheduled-at');
    if (!scheduleInput) return;
    scheduleInput.classList.toggle('hidden');
    if (!scheduleInput.classList.contains('hidden')) scheduleInput.focus();
}

function collectAddChapterContentPayload() {
    const urlInput = document.getElementById('add-chapter-url');
    const source = (urlInput?.value || '').trim();
    const editorHtml = getChapterEditorHtml();
    return {
        url: source || editorHtml,
        contentHtml: source ? '' : editorHtml,
    };
}

async function saveAddChapter() {
    if (!API_URL || !currentSeries || !currentVolume) return;
    const volumeInput = document.getElementById('add-chapter-volume');
    const chapInput = document.getElementById('add-chapter-number');
    const nameInput = document.getElementById('add-chapter-name');
    const toneSelect = document.getElementById('add-chapter-tone');
    const scheduleInput = document.getElementById('add-chapter-scheduled-at');
    const volume = (volumeInput?.value || currentVolume.volume || '').toString().trim();
    const chapter = (chapInput?.value || '').trim();
    const name = (nameInput?.value || '').trim();
    const contentPayload = collectAddChapterContentPayload();
    const url = contentPayload.url;
    const tone = (toneSelect?.value || 'without_negativity').trim();
    const scheduledAt = (scheduleInput?.value || '').trim();
    if (!volume) return showToast('Укажите том');
    if (!chapter) return showToast('Укажите номер главы');
    if (!url) return showToast('Заполните содержание главы или ссылку');

    const saveBtn = document.getElementById('add-chapter-save');
    captureOriginalLabel(saveBtn);
    if (saveBtn) { saveBtn.disabled = true; saveBtn.textContent = 'Создание...'; }

    try {
        const resp = await apiFetch(API_URL + '/api/chapters', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                series_id: currentSeries.id,
                volume: volume,
                chapter: chapter,
                name: name,
                url: url,
                content_html: contentPayload.contentHtml,
                tone: tone,
                scheduled_at: scheduledAt
            })
        });
        const result = await resp.json();
        if (result.ok) {
            const targetVolume = findVolumeByKey(currentSeries, volume) || currentVolume;
            if (targetVolume && Array.isArray(targetVolume.chapters)) {
                const exists = targetVolume.chapters.some((item) => sameReaderKey(item.chapter, chapter));
                if (!exists) {
                    targetVolume.chapters.push({
                        chapter,
                        custom_name: name || `Глава ${chapter}`,
                        text: '',
                        url,
                    });
                    if (sameReaderKey(targetVolume.volume, currentVolume.volume)) {
                        currentChapters = targetVolume.chapters;
                    }
                }
            }
            closeAddChapterModal();
            showToast('✅ Глава добавлена!');
            haptic('success');
            refreshReaderDataInBackground();
        } else {
            showToast('Ошибка: ' + (result.error || `HTTP ${resp.status}`));
        }
    } catch (e) {
        showToast('Ошибка сети: ' + e.message);
    } finally {
        restoreOriginalLabel(saveBtn);
    }
}

async function deleteChapterCurrent() {
    if (!API_URL || !currentSeries || !currentVolume) return;
    const ch = currentChapters[currentChapterIdx];
    if (!ch) return showToast('Нет текущей главы');
    closeAdminMenu();
    const chapName = ch.custom_name || `Глава ${ch.chapter}`;
    const confirmed = await adminConfirm(`Удалить "${chapName}"? Это необратимо.`);
    if (!confirmed) return;

    try {
        const resp = await apiFetch(API_URL + '/api/chapters', {
            method: 'DELETE',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                series_id: currentSeries.id,
                volume: currentVolume.volume,
                chapter: ch.chapter
            })
        });
        const result = await resp.json();
        if (result.ok) {
            showToast('✅ Глава удалена.');
            haptic('success');
            // Locally drop it from the list and navigate back one chapter if possible.
            currentChapters.splice(currentChapterIdx, 1);
            if (currentChapterIdx >= currentChapters.length) {
                currentChapterIdx = Math.max(0, currentChapters.length - 1);
            }
            refreshReaderDataInBackground();
            // Return to chapters screen so the user sees the new list.
            showScreen('chapters');
            renderChaptersList();
        } else {
            showToast('Ошибка: ' + (result.error || `HTTP ${resp.status}`));
        }
    } catch (e) {
        showToast('Ошибка сети: ' + e.message);
    }
}

function openCoverEditModal(seriesId) {
    if (!hasAdminApi()) {
        showToast('Редактирование обложки доступно только при подключенном API.');
        return;
    }
    const series = findSeriesById(seriesId);
    if (!series) return;
    const overlay = document.getElementById('cover-edit-overlay');
    const modal = document.getElementById('cover-edit-modal');
    const input = document.getElementById('cover-edit-input');
    const preview = document.getElementById('cover-edit-preview');
    const title = document.getElementById('cover-edit-series-name');
    if (!overlay || !modal || !input) return;
    input.dataset.seriesId = String(series.id);
    input.value = series.cover_url || '';
    if (title) title.textContent = series.title || '';
    if (preview) {
        preview.src = series.cover_url || '';
        preview.style.display = series.cover_url ? 'block' : 'none';
    }
    restoreOriginalLabel(document.getElementById('cover-edit-save'));
    overlay.classList.remove('hidden');
    modal.classList.remove('hidden');
    setTimeout(() => input.focus(), 350);
}

function closeCoverEditModal() {
    const overlay = document.getElementById('cover-edit-overlay');
    const modal = document.getElementById('cover-edit-modal');
    if (overlay) overlay.classList.add('hidden');
    if (modal) modal.classList.add('hidden');
    restoreOriginalLabel(document.getElementById('cover-edit-save'));
}

function updateCoverPreview() {
    const input = document.getElementById('cover-edit-input');
    const preview = document.getElementById('cover-edit-preview');
    if (!input || !preview) return;
    const url = (input.value || '').trim();
    if (url) {
        preview.src = url;
        preview.style.display = 'block';
    } else {
        preview.removeAttribute('src');
        preview.style.display = 'none';
    }
}

async function saveCoverEdit() {
    if (!API_URL) return;
    const input = document.getElementById('cover-edit-input');
    if (!input) return;
    const seriesId = input.dataset.seriesId;
    const coverUrl = (input.value || '').trim();
    if (!seriesId) return;

    const saveBtn = document.getElementById('cover-edit-save');
    captureOriginalLabel(saveBtn);
    if (saveBtn) { saveBtn.disabled = true; saveBtn.textContent = 'Сохранение...'; }

    try {
        const resp = await apiFetch(API_URL + '/api/series', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ series_id: seriesId, cover_url: coverUrl })
        });
        const result = await resp.json();
        if (result.ok) {
            // Patch local data so the card updates without a full reload.
            const series = findSeriesById(seriesId);
            if (series) series.cover_url = coverUrl;
            closeCoverEditModal();
            showToast('✅ Обложка обновлена!');
            haptic('success');
            if (document.getElementById('screen-series')?.classList.contains('active')) {
                renderSeriesList();
            }
            refreshReaderDataInBackground();
        } else {
            showToast('Ошибка: ' + (result.error || `HTTP ${resp.status}`));
        }
    } catch (e) {
        showToast('Ошибка сети: ' + e.message);
    } finally {
        restoreOriginalLabel(saveBtn);
    }
}

// ==========================================================================
// LIBRARY & STATS
// ==========================================================================

let readingStats = safeGetLocal('reader_stats', {timeSpentSeconds:0});
let readingStatsTimer = null;

function tickReadingStats() {
    if (getActiveScreenName() !== 'reader' || document.hidden) {
        syncReadingStatsTimer();
        return;
    }
    readingStats.timeSpentSeconds += 5;
    if (readingStats.timeSpentSeconds % 60 === 0) {
        safeSetLocal('reader_stats', readingStats);
        updateLibraryStats();
    }
}

function startReadingStatsTimer() {
    if (readingStatsTimer || getActiveScreenName() !== 'reader' || document.hidden) return;
    readingStatsTimer = setInterval(tickReadingStats, 5000);
}

function stopReadingStatsTimer({ persist = true } = {}) {
    if (!readingStatsTimer) return;
    clearInterval(readingStatsTimer);
    readingStatsTimer = null;
    if (persist) {
        safeSetLocal('reader_stats', readingStats);
        updateLibraryStats();
    }
}

function syncReadingStatsTimer(screenName = getActiveScreenName()) {
    if (screenName === 'reader' && !document.hidden) {
        startReadingStatsTimer();
    } else {
        stopReadingStatsTimer();
    }
}

document.addEventListener('visibilitychange', () => {
    syncReadingStatsTimer();
});

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

    // Refresh v4: используем единый компонент poster-карточки, чтобы библиотека
    // выглядела идентично главному экрану.
    const itemsHtml = filtered
        .map((meta, idx) => (meta.series ? renderSeriesPosterCard(meta.series, idx) : ''))
        .join('');

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
    if (!Array.isArray(currentChapters) || fromIdx < 0 || toIdx < 0) return;
    if (fromIdx >= currentChapters.length || toIdx >= currentChapters.length) return;
    if (fromIdx === toIdx) return;

    const previousChapters = currentChapters.slice();

    // Reorder locally
    const [moved] = currentChapters.splice(fromIdx, 1);
    currentChapters.splice(toIdx, 0, moved);

    // Re-render
    renderChaptersList();

    // Sync with server if available
    if (!API_URL) return;

    const order = currentChapters.map(c => c.chapter);
    try {
        const resp = await apiFetch(API_URL + '/api/sort', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                series_id: currentSeries.id,
                volume: currentVolume.volume,
                order: order
            })
        });
        if (!resp || !resp.ok) {
            const status = resp?.status || 0;
            let detail = '';
            let payload = null;
            try {
                detail = await resp.text();
                payload = detail ? JSON.parse(detail) : null;
            } catch (_) {}
            console.warn('sort PUT failed', status, detail);
            let msg;
            if (status === 401 || status === 403) {
                msg = 'Недостаточно прав для изменения порядка.';
            } else if (status === 409) {
                const missing = Array.isArray(payload?.unmatched) && payload.unmatched.length
                    ? ` (${payload.unmatched.slice(0, 3).join(', ')})`
                    : '';
                msg = `Порядок не сохранён: глава отсутствует в БД${missing}.`;
            } else {
                msg = `Не удалось сохранить порядок (HTTP ${status}).`;
            }
            currentChapters = previousChapters;
            if (currentVolume) currentVolume.chapters = previousChapters;
            renderChaptersList();
            try { safeSetLocal(getReaderApiCacheKey(), null); } catch (_) {}
            refreshReaderDataInBackground();
            showToast(msg);
        } else {
            haptic('success');
            showToast('✅ Порядок сохранён');
            // Invalidate local snapshot so next loadData() hits the server.
            try { safeSetLocal(getReaderApiCacheKey(), null); } catch (_) {}
        }
    } catch (e) {
        console.warn('Sort sync error:', e);
        currentChapters = previousChapters;
        if (currentVolume) currentVolume.chapters = previousChapters;
        renderChaptersList();
        showToast('Ошибка сети при сохранении порядка.');
    }
}

function moveChapter(fromIdx, direction) {
    if (!Array.isArray(currentChapters) || !Number.isInteger(fromIdx)) return;
    const toIdx = fromIdx + (direction > 0 ? 1 : -1);
    if (toIdx < 0 || toIdx >= currentChapters.length) return;
    reorderChapters(fromIdx, toIdx);
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

// Refresh v4: Pull-to-Refresh для экранов series / chapters / library.
// Работает на scroll-контейнерах `.content-area` и `#chapters-list`/`#series-list`.
// Активируется при scrollTop === 0 и pull вниз >= 80px + 150ms delay.
(function bindPullToRefresh() {
    try {
        const PTR_SELECTORS = ['#series-list', '#chapters-list', '#library-list'];
        const THRESHOLD = 80;
        const HOLD_MS = 150;
        const indicator = document.getElementById('pull-refresh-indicator');
        if (!indicator) return;

        let startY = 0;
        let lastY = 0;
        let active = false;
        let readyAt = 0;
        let target = null;
        let refreshing = false;

        const setIndicator = (state, progress = 0) => {
            if (!indicator) return;
            if (!state) {
                indicator.removeAttribute('data-state');
                indicator.style.transform = 'translate(-50%, -110%)';
                return;
            }
            indicator.setAttribute('data-state', state);
            if (state === 'pulling' || state === 'ready') {
                // Тянем — выдвигаем пропорционально
                const y = Math.min(10, -110 + progress * 120);
                indicator.style.transform = `translate(-50%, ${y}%)`;
            } else if (state === 'refreshing') {
                indicator.style.transform = 'translate(-50%, 10%)';
                const label = indicator.querySelector('.ptr-label');
                if (label) label.textContent = 'Обновляем...';
            }
        };

        const getTargetFromEvent = (e) => {
            // Определяем активный scroll-контейнер по ближайшему `.content-area` или известным selectors
            const path = (e.composedPath ? e.composedPath() : (e.path || []));
            for (const el of path) {
                if (!el || !el.matches) continue;
                if (el.matches(PTR_SELECTORS.join(','))) return el;
                if (el.matches('.content-area')) {
                    // убедиться что активный экран — не reader
                    const parent = el.closest('.screen');
                    if (parent && parent.id !== 'screen-reader' && parent.classList.contains('active')) {
                        return el;
                    }
                }
            }
            return null;
        };

        const onStart = (e) => {
            if (refreshing) return;
            const t = e.touches && e.touches[0];
            if (!t) return;
            const el = getTargetFromEvent(e);
            if (!el) return;
            if (el.scrollTop > 0) return;
            target = el;
            startY = t.clientY;
            lastY = startY;
            active = true;
            readyAt = 0;
        };
        const onMove = (e) => {
            if (!active || refreshing || !target) return;
            const t = e.touches && e.touches[0];
            if (!t) return;
            lastY = t.clientY;
            const diff = lastY - startY;
            if (diff <= 0) {
                active = false;
                setIndicator(null);
                return;
            }
            if (target.scrollTop > 0) {
                active = false;
                setIndicator(null);
                return;
            }
            const progress = Math.min(1, diff / THRESHOLD);
            if (diff >= THRESHOLD) {
                if (!readyAt) readyAt = Date.now();
                setIndicator('ready', 1);
            } else {
                readyAt = 0;
                setIndicator('pulling', progress);
            }
        };
        const onEnd = async () => {
            if (!active || refreshing) { active = false; setIndicator(null); return; }
            active = false;
            const diff = lastY - startY;
            if (diff >= THRESHOLD && Date.now() - readyAt >= HOLD_MS) {
                refreshing = true;
                setIndicator('refreshing');
                haptic('light');
                try {
                    if (typeof loadData === 'function') await loadData();
                    if (typeof showToast === 'function') showToast('Обновлено', 'success');
                } catch (err) {
                    if (typeof showToast === 'function') showToast('Не удалось обновить', 'error');
                } finally {
                    setTimeout(() => {
                        refreshing = false;
                        setIndicator(null);
                        const label = indicator.querySelector('.ptr-label');
                        if (label) label.textContent = 'Потяните для обновления';
                    }, 400);
                }
            } else {
                setIndicator(null);
            }
        };

        document.addEventListener('touchstart', onStart, { passive: true });
        document.addEventListener('touchmove', onMove, { passive: true });
        document.addEventListener('touchend', onEnd, { passive: true });
        document.addEventListener('touchcancel', onEnd, { passive: true });
    } catch (_) { /* ignore */ }
})();

// Refresh v4: blur-up effect для postеr обложек. Помечаем загруженные <img>
// с классом `.series-poster-img` / `.series-detail-cover-img` и снимаем blur.
(function bindImageBlurUp() {
    try {
        const markLoaded = (img) => {
            if (!img || !img.classList) return;
            if (img.classList.contains('is-loaded')) return;
            img.classList.add('is-loaded');
        };
        document.addEventListener('load', (e) => {
            const t = e.target;
            if (!t || !t.matches) return;
            if (t.matches('img.series-poster-img, img.series-detail-cover-img')) {
                markLoaded(t);
            }
        }, true);
        // На случай если изображение уже в кэше и load не сработает.
        const checkCached = () => {
            document.querySelectorAll('img.series-poster-img, img.series-detail-cover-img').forEach((img) => {
                if (img.complete && img.naturalWidth > 0) markLoaded(img);
            });
        };
        let imageObserverStarted = false;
        const observeNewImages = () => {
            if (imageObserverStarted) return;
            if (!document.body || typeof MutationObserver === 'undefined') return;
            imageObserverStarted = true;
            const observer = new MutationObserver((mutations) => {
                mutations.forEach((mutation) => {
                    mutation.addedNodes.forEach((node) => {
                        if (!node || node.nodeType !== Node.ELEMENT_NODE) return;
                        const candidates = [];
                        if (node.matches?.('img.series-poster-img, img.series-detail-cover-img')) {
                            candidates.push(node);
                        }
                        node.querySelectorAll?.('img.series-poster-img, img.series-detail-cover-img').forEach((img) => candidates.push(img));
                        candidates.forEach((img) => {
                            if (img.complete && img.naturalWidth > 0) markLoaded(img);
                        });
                    });
                });
            });
            observer.observe(document.body, { childList: true, subtree: true });
        };
        const startImageBlurUp = () => {
            checkCached();
            observeNewImages();
        };
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', startImageBlurUp, { once: true });
        } else {
            startImageBlurUp();
        }
        setTimeout(checkCached, 250);
    } catch (_) { /* ignore */ }
})();

// Refresh v4: клик по description разворачивает/сворачивает её
document.addEventListener('click', (e) => {
    const desc = e.target && e.target.closest && e.target.closest('.series-detail-description');
    if (!desc) return;
    const collapsed = desc.getAttribute('data-collapsed') === 'true';
    desc.setAttribute('data-collapsed', collapsed ? 'false' : 'true');
});

// Refresh v4: глобальный лёгкий haptic на значимые UI-тапы. Подключаем
// capturing-режимом чтобы ловить события до их обработки конкретными handlers.
// Работает только в Telegram-окружении (см. guard в `haptic`).
(function bindGlobalHaptics() {
    try {
        const HAPTIC_SELECTOR = [
            '.series-card',
            '.chapter-item',
            '.nav-tab',
            '.vol-tab',
            '.r4-pill',
            '.comment-tab',
            '.library-filter-btn',
            '.manga-action-btn',
            '.nav-btn',
            '.fab-btn',
            '.admin-fab-btn',
            '.theme-chip'
        ].join(',');
        document.addEventListener('pointerdown', (e) => {
            const t = e.target && e.target.closest && e.target.closest(HAPTIC_SELECTOR);
            if (t && !t.disabled) haptic('light');
        }, { capture: true, passive: true });
    } catch (_) { /* ignore */ }
})();

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
    if (!ch || !currentSeries || !currentVolume) {
        showToast('Нет текущей главы для переименования');
        return;
    }

    // Use the existing core rename logic
    renameItem(`chap_${currentSeries.id}_${currentVolume.volume}_${ch.chapter}`);
}

function resetCurrentChapterName() {
    closeAdminMenu();
    const ch = currentChapters[currentChapterIdx];
    if (!ch || !currentSeries || !currentVolume) {
        showToast('Нет текущей главы');
        return;
    }
    if (!ch.custom_name) {
        showToast('У главы нет кастомного имени');
        return;
    }
    resetCustomName(`chap_${currentSeries.id}_${currentVolume.volume}_${ch.chapter}`);
}

function openCoverEditForCurrent() {
    closeAdminMenu();
    if (!currentSeries) {
        showToast('Сначала выберите серию');
        return;
    }
    openCoverEditModal(currentSeries.id);
}

function openAddChapterForCurrent() {
    openAddChapterModal();
}

// Close admin menu when virtual keyboard opens to avoid overlap issues.
document.addEventListener('focusin', (e) => {
    if (_isReaderEditableElement(e.target)) closeAdminMenu();
});

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

    // Refresh v5: круговой pull-to-next + crossfade overlay
    // Индикатор лежит в #screen-reader (не в scroll-контенте), поэтому работает как overlay.
    const pullNextText = document.getElementById('pull-next-text');
    const pullNextRingFg = pullNext.querySelector('.ring-fg');
    const pullStartThreshold = 12;  // px пока скролл «идёт натурально»
    const pullTriggerDistance = 90; // px — порог срабатывания
    let pullTouchStartY = 0;
    let pullDistance = 0;
    let pullTriggered = false;

    const setPullProgress = (progress) => {
        // progress 0..1 → stroke-dashoffset 100..0 (pathLength=100)
        if (pullNextRingFg) {
            const clamped = Math.max(0, Math.min(1, progress));
            pullNextRingFg.setAttribute('stroke-dashoffset', String((1 - clamped) * 100));
        }
    };

    const showPullIndicator = () => {
        pullNext.classList.add('is-visible');
        pullNext.setAttribute('aria-hidden', 'false');
    };
    const hidePullIndicator = () => {
        pullNext.classList.remove('is-visible', 'triggered', 'loading');
        pullNext.setAttribute('aria-hidden', 'true');
        setPullProgress(0);
        if (pullNextText) pullNextText.textContent = 'Следующая глава';
    };

    const atBottom = () => {
        const scrollTop = content.scrollTop;
        const scrollHeight = content.scrollHeight;
        const clientHeight = content.clientHeight;
        return Math.ceil(scrollTop + clientHeight) >= scrollHeight - 1;
    };

    const onStart = (e) => {
        // Начинаем жест только если уже внизу. Это устраняет рывок в середине,
        // когда скролл встречал prevent-default на 15-м пикселе.
        if (!atBottom()) {
            pullTouchStartY = 0;
            return;
        }
        pullTouchStartY = e.touches ? e.touches[0].clientY : e.clientY;
        pullDistance = 0;
        pullTriggered = false;
        isGlobalPullingNext = false;
    };

    const onMove = (e) => {
        if (currentChapterIdx >= currentChapters.length - 1 || pullTouchStartY === 0) return;

        const touchY = e.touches ? e.touches[0].clientY : e.clientY;
        let diff = pullTouchStartY - touchY;

        if (!atBottom() && !isGlobalPullingNext) return;

        if (diff > pullStartThreshold) {
            if (!isGlobalPullingNext) {
                isGlobalPullingNext = true;
                showPullIndicator();
            }
            // Блокируем нативный скролл только после того как стартовал жест.
            if (e.cancelable && e.touches) e.preventDefault();

            pullDistance = diff;
            const progress = Math.min(1, (diff - pullStartThreshold) / pullTriggerDistance);
            setPullProgress(progress);

            const shouldTrigger = diff >= (pullTriggerDistance + pullStartThreshold);
            if (shouldTrigger && !pullTriggered) {
                pullTriggered = true;
                pullNext.classList.add('triggered');
                if (pullNextText) pullNextText.textContent = 'Отпустите →';
                haptic('medium');
            } else if (!shouldTrigger && pullTriggered) {
                pullTriggered = false;
                pullNext.classList.remove('triggered');
                if (pullNextText) pullNextText.textContent = 'Следующая глава';
                haptic('light');
            }
        } else if (isGlobalPullingNext && diff < 4) {
            // Пользователь вернул палец вверх — прячем индикатор.
            isGlobalPullingNext = false;
            pullTriggered = false;
            pullDistance = 0;
            hidePullIndicator();
        }
    };

    const onEnd = () => {
        if (isGlobalPullingNext && pullTriggered) {
            // Lock индикатор в loading-состоянии + crossfade-переход.
            pullNext.classList.add('loading');
            if (pullNextText) pullNextText.textContent = 'Загрузка...';
            haptic('medium');
            navigateChapterCrossfade(1);
        } else {
            hidePullIndicator();
        }
        isGlobalPullingNext = false;
        pullTriggered = false;
        pullDistance = 0;
        pullTouchStartY = 0;
    };

    // Раздельные слушатели Touch/Mouse чтобы избежать pointercancel от pan-y
    content.addEventListener('touchstart', onStart, { passive: true });
    content.addEventListener('touchmove', onMove, { passive: false });
    content.addEventListener('touchend', onEnd);
    content.addEventListener('touchcancel', hidePullIndicator);

    content.addEventListener('mousedown', onStart);
    document.addEventListener('mousemove', (e) => { if (pullTouchStartY && !e.touches) onMove(e); });
    document.addEventListener('mouseup', () => { if (pullTouchStartY) onEnd(); });
}

// Refresh v5: crossfade-переход к следующей главе (вызывается только из pull-gesture,
// чтобы кнопки Пред/След сохраняли привычный slide-эффект).
function navigateChapterCrossfade(delta) {
    saveScrollPosition();
    const newIdx = currentChapterIdx + delta;
    if (newIdx < 0 || newIdx >= currentChapters.length) return;

    const content = document.getElementById('reader-content');
    const pullNext = document.getElementById('pull-next-indicator');

    haptic('medium');

    const applyNext = () => {
        openChapter(newIdx, true);
        if (content) content.scrollTop = 0;
        requestAnimationFrame(() => {
            requestAnimationFrame(() => {
                if (content) content.classList.remove('crossfading');
                if (pullNext) {
                    pullNext.classList.remove('is-visible', 'triggered', 'loading');
                    pullNext.setAttribute('aria-hidden', 'true');
                    const ringFg = pullNext.querySelector('.ring-fg');
                    if (ringFg) ringFg.setAttribute('stroke-dashoffset', '100');
                    const text = document.getElementById('pull-next-text');
                    if (text) text.textContent = 'Следующая глава';
                }
            });
        });
    };

    if (!content) { applyNext(); return; }

    content.classList.add('crossfading');
    setTimeout(applyNext, 220);
}

function initReaderScrollListeners() {
    const content = document.getElementById('reader-content');
    const screen = document.getElementById('screen-reader');
    const progressBar = document.getElementById('reading-progress-bar');
    if (!content || !screen || !progressBar) return;

    const scrubber = document.getElementById('reader-scrubber');
    let scrubberSeeking = false;

    let lastScrollTop = 0;
    const threshold = 15;

    content.addEventListener('scroll', () => {
        const scrollTop = content.scrollTop;
        const scrollHeight = content.scrollHeight - content.clientHeight;

        // 1. Прогресс-бар
        const progress = (scrollTop / Math.max(1, scrollHeight)) * 100;
        progressBar.style.width = `${progress}%`;

        // Refresh v4: синхронизируем scrubber (если пользователь сейчас не тянет)
        if (scrubber && !scrubberSeeking) {
            const pct = Math.max(0, Math.min(100, progress));
            scrubber.value = String(Math.round(pct * 10));
            scrubber.style.setProperty('--scrubber-progress', pct.toFixed(2) + '%');
        }

        // 2. Immersive Scroll (Скрытие UI при скролле вниз)
        if (Math.abs(scrollTop - lastScrollTop) > threshold) {
            if (scrollTop > lastScrollTop && scrollTop > 100) {
                screen.classList.add('immersive');
                isImmersive = true;
                // Закрываем FAB при скролле вниз
                const fab = document.getElementById('fab-menu');
                if (fab && !fab.classList.contains('hidden')) toggleFab();
            } else if (scrollTop < lastScrollTop - 5) {
                screen.classList.remove('immersive');
                isImmersive = false;
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

    // Refresh v4: scrubber → seek content
    if (scrubber) {
        const seekToScrubber = () => {
            const ratio = Math.max(0, Math.min(1, Number(scrubber.value) / 1000));
            const scrollHeight = content.scrollHeight - content.clientHeight;
            content.scrollTop = ratio * scrollHeight;
            scrubber.style.setProperty('--scrubber-progress', (ratio * 100).toFixed(2) + '%');
        };
        scrubber.addEventListener('input', () => {
            scrubberSeeking = true;
            seekToScrubber();
        }, { passive: true });
        const endSeek = () => {
            scrubberSeeking = false;
        };
        scrubber.addEventListener('change', endSeek, { passive: true });
        scrubber.addEventListener('pointerup', endSeek, { passive: true });
        scrubber.addEventListener('blur', endSeek);
    }
}

// Optimistic chapter reactions with rollback on network/server errors.
async function toggleReaction(type) {
    if (!API_URL) return;
    if (!hasWriteAuth()) {
        requireTelegramAuth('ставить реакции');
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
        if (!resp.ok) {
            if (resp.status === 401) {
                chapterReactionsState = prevState;
                renderReactions(chapterReactionsState);
                handleAuthRejected('Сессия Telegram не активна. Войдите ещё раз, чтобы ставить реакции.');
                return;
            }
            throw new Error(data.error || `HTTP ${resp.status}`);
        }
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
handleReaderCacheVersionChange();
checkWebAppBuildVersion();
registerReaderServiceWorker();
bindReaderKeyboardAwareUI();
bindDelegatedSelectionEvents();
updateLibraryFilterButtons();
restoreSettings();
syncAdminModeControls();
loadSiteAuthState().then(() => loadData());
initTypoReporter();
initGestures();
initReaderScrollListeners();
