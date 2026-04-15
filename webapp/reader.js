// ==========================================================================
// Читалка ранобэ — JavaScript v3
// Загрузка/отображение, прогресс чтения, лайки, комментарии
// ==========================================================================

const tg = window.Telegram.WebApp;
tg.expand();
tg.ready();

// === Telegram User ===
const tgUser = tg.initDataUnsafe?.user || {};
const userId = String(tgUser.id || '');
const userName = tgUser.first_name || 'Аноним';

// === Состояние ===
let allData = { series: [] };
let currentSeries = null;
let currentVolume = null;
let currentChapterIdx = 0;
let currentChapters = [];
let isAdminMode = false;
let currentCommentSort = 'top'; // Сортировка: 'top' или 'new'
let allCommentsCache = []; // Кэш всех комментариев текущей главы
let commentsData = []; // Список для рендеринга (отфильтрован/отсортирован)

// === Typo Report State ===
let typoSelectedText = '';
let typoContextText = '';
let typoSelectionRange = null;

function toggleAdminMode(enabled) {
    isAdminMode = enabled;
    if (document.getElementById('screen-series').classList.contains('active')) renderSeriesList();
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
const defaults = { fontSize: 17, theme: 'light', textWidth: 90, font: 'serif', lineHeight: 1.8, textAlign: 'left', indent: true, paraSpacing: 20 };
let settings = JSON.parse(localStorage.getItem('reader_settings') || 'null') || { ...defaults };
// Миграция старых настроек
if (!settings.lineHeight) settings.lineHeight = 1.8;
if (!settings.textAlign) settings.textAlign = 'left';
if (settings.indent === undefined) settings.indent = true;
if (settings.paraSpacing === undefined) settings.paraSpacing = 20;

let readChapters = JSON.parse(localStorage.getItem('reader_progress') || '{}');

// === Получение API URL из параметров URL ===
// Приоритет: 1) ?api=... из URL 2) window.location.origin (если бот и WebApp на одном хосте)
// На GitHub Pages (без ?api=) остаётся '' — функции, зависящие от API, корректно отключаются
const urlParams = new URLSearchParams(window.location.search);
const API_URL = urlParams.get('api') || (window.location.hostname.includes('github.io') ? '' : window.location.origin);

// === API Wrapper ===
async function apiFetch(url, options = {}) {
    options.headers = options.headers || {};
    if (typeof tg !== 'undefined' && tg.initData) {
        options.headers['Authorization'] = 'tma ' + tg.initData;
    }
    return fetch(url, options);
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
    localStorage.setItem(key, JSON.stringify({ pct, ts: Date.now() }));
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

function restoreScrollPosition() {
    // Убираем предыдущий observer (если был — нет утечки)
    if (_scrollResizeObserver) {
        _scrollResizeObserver.disconnect();
        _scrollResizeObserver = null;
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
            const saved = JSON.parse(localStorage.getItem(key) || 'null');
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
    
    setTimeout(() => {
        if (_scrollResizeObserver) {
            _scrollResizeObserver.disconnect();
            _scrollResizeObserver = null;
        }
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
    const all = JSON.parse(localStorage.getItem('reader_last_read') || '{}');
    all[currentSeries.id] = last;
    localStorage.setItem('reader_last_read', JSON.stringify(all));
}

function getLastRead(seriesId) {
    const all = JSON.parse(localStorage.getItem('reader_last_read') || '{}');
    const local = all[seriesId];

    const serverBm = serverBookmarks.find(b => String(b.series_id) === String(seriesId));
    if (serverBm) {
        return {
            seriesId: seriesId,
            volume: serverBm.volume_id,
            chapter: serverBm.chapter_key,
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

function updateProgressBar() {
    if (!progressBarEl) return;
    const el = document.getElementById('reader-content');
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
            const resp = await apiFetch(API_URL + '/api/reader', { signal: getTimeoutSignal(10000) });
            if (resp.ok) {
                allData = await resp.json();
                console.log("Data loaded from API, series count:", allData.series?.length);
                if (allData.series && allData.series.length > 0) {
                    renderSeriesList();
                    renderContinueReading();
                    handleStartParam(); // ★ Deep link handling (Phase 5)
                    return;
                }
                console.log("API returned empty series list, falling back to JSON...");
            } else {
                console.warn("Reader API returned status:", resp.status);
            }
        } catch (e) {
            console.warn('API fetch error or timeout:', e);
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
        }
    } catch (e) {
        console.error('Fallback JSON fetch error:', e);
    }

    console.log("All data sources failed or empty, showing empty state.");
    showEmptyState();
}

function showEmptyState() {
    document.getElementById('series-list').innerHTML = `
        <div class="empty-state">
            <div class="empty-icon">📚</div>
            <h3>Библиотека пуста</h3>
            <p>Данные ещё не загружены. Добавьте главы через бота или разместите файл chapters_data.json в папке webapp.</p>
        </div>
    `;
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
    const container = document.getElementById('series-list');

    if (!allData.series || allData.series.length === 0) {
        showEmptyState();
        return;
    }

    container.innerHTML = allData.series.map((s, i) => {
        const totalCh = s.volumes.reduce((sum, v) => sum + v.chapters.length, 0);
        const readCount = s.volumes.reduce((sum, v) => {
            return sum + v.chapters.filter(c => isRead(s.id, v.volume, c.chapter)).length;
        }, 0);
        const progress = totalCh > 0 ? Math.round((readCount / totalCh) * 100) : 0;

        // Бейдж «Продолжить»
        const lastRead = getLastRead(s.id);
        let continueBadge = '';
        if (lastRead) {
            continueBadge = `<span class="continue-badge">▶ Продолжить · Гл. ${lastRead.chapter}</span>`;
        }

        const editBtns = isAdminMode ? `
            <button class="admin-edit-btn" title="Переименовать" onclick="renameItem('series_${s.id}'); event.stopPropagation();">&#9998;</button>
            <button class="admin-reset-btn" title="Сброс имени" onclick="resetCustomName('series_${s.id}'); event.stopPropagation();">&#8635;</button>
        ` : '';
        const customBadge = isAdminMode ? `<span class="custom-name-badge">серия</span>` : '';

        // Cover image support (Batch 3)
        const coverEl = s.cover_url
            ? `<img src="${s.cover_url}" class="series-cover-img" alt="${s.title}" loading="lazy">`
            : `<div class="series-icon">${['📖', '📕', '📗', '📘', '📙'][i % 5]}</div>`;

        return `
        <div class="series-card" onclick="selectSeries('${s.id}')">
            ${coverEl}
            <div class="series-info">
                <h3>${s.title}${customBadge}${editBtns}</h3>
                <p>${s.volumes.length} том(ов) &middot; ${totalCh} глав${progress > 0 ? ` &middot; ${progress}%` : ''}</p>
                ${continueBadge}
            </div>
            <span class="series-arrow">&rsaquo;</span>
        </div>`;
    }).join('');
}

function selectSeries(seriesId) {
    currentSeries = allData.series.find(s => s.id === seriesId);
    if (!currentSeries) return;

    document.getElementById('chapters-title').textContent = currentSeries.title;
    renderVolumeTabs();

    // Восстанавливаем последнюю читаемую главу или первый том
    const lastRead = getLastRead(seriesId);
    if (lastRead) {
        const vol = currentSeries.volumes.find(v => v.volume === lastRead.volume);
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
    currentVolume = currentSeries.volumes.find(v => v.volume === volNum);
    if (!currentVolume) return;

    document.querySelectorAll('.vol-tab').forEach(t => {
        t.classList.toggle('active', parseInt(t.dataset.vol) === volNum);
    });

    renderChaptersList();
}

function renderChaptersList() {
    const container = document.getElementById('chapters-list');
    currentChapters = currentVolume.chapters;

    if (currentChapters.length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                <div class="empty-icon">📭</div>
                <h3>Нет глав</h3>
                <p>В этом томе пока нет глав.</p>
            </div>`;
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
    currentChapterIdx = idx;
    const chapter = currentChapters[idx];
    if (!chapter) return;

    document.getElementById('reader-title').textContent = chapter.custom_name || `Глава ${chapter.chapter}`;
    updateNavButtons();
    markAsRead(currentSeries.id, currentVolume.volume, chapter.chapter);
    loadChapterContent(chapter, usePrefetch);

    initProgressBar();
    if (progressBarEl) progressBarEl.style.width = '0%';

    showScreen('reader');

    // Загружаем лайки, реакции и комментарии (для API)
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
let _chapterAbortController = null; // AbortController для отмены загрузки при смене главы

function loadChapterContent(chapter, usePrefetch = false) {
    const container = document.getElementById('reader-text');

    // Отменяем предыдущую загрузку, если была
    if (_chapterAbortController) {
        _chapterAbortController.abort();
        _chapterAbortController = null;
    }

    // Check if we have prefetched content for this chapter
    if (usePrefetch && prefetchedChapter.idx === currentChapterIdx && prefetchedChapter.html) {
        renderLoadedContent(container, prefetchedChapter.html, chapter);
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
            if (signal.aborted) return;
            renderLoadedContent(container, results.join(''), chapter);
        }).catch(err => {
            if (err.name === 'AbortError') return;
            console.error('Chapter load failed:', err);
            container.innerHTML = `
                <div class="empty-state">
                    <div class="empty-icon">❌</div>
                    <h3>Ошибка загрузки главы</h3>
                    <p>Проверьте соединение или используйте VPN.</p>
                    <button class="retry-btn" onclick="loadChapterContent(currentChapters[currentChapterIdx])">🔄 Повторить попытку</button>
                </div>`;
        });

    } else if (chapter.text) {
        const paragraphs = chapter.text.split('\n\n').map(p => `<p>${p.trim()}</p>`).join('');
        renderLoadedContent(container, paragraphs, chapter);
    } else {
        container.innerHTML = `
            <div class="empty-state" style="margin-top:20vh;">
                <div class="empty-icon" style="font-size:4rem;opacity:0.3;">⏳</div>
                <h3 style="margin-top:1.5rem;font-weight:700;">Глава еще не загружена</h3>
                <p style="opacity:0.6;max-width:300px;margin:1rem auto;">Эта часть главы еще находится в переводе или ожидает проверки администратором.</p>
                ${isAdminMode ? `<button class="admin-primary-btn" style="margin-top:2rem;" onclick="openEditUrlModal(currentChapterIdx)">🔗 Добавить ссылку</button>` : ''}
            </div>
        `;
    }

    document.getElementById('reader-content').scrollTop = 0;
}

function renderLoadedContent(container, html, chapter) {
    container.innerHTML = html;

    // --- Расчет примерного времени чтения ---
    const textContent = container.innerText;
    const wordCount = textContent.split(/\s+/).filter(w => w.length > 0).length;
    if (wordCount > 50) {
        const readingTimeMins = Math.max(1, Math.ceil(wordCount / 200)); // В среднем 200 слов в минуту
        const timeBadge = document.createElement('div');
        timeBadge.className = 'reading-time-badge';
        timeBadge.innerHTML = `<svg class="icon-xs" viewBox="0 0 24 24" style="vertical-align:-2px; margin-right:4px;"><circle cx="12" cy="12" r="10" fill="none" stroke="currentColor" stroke-width="2"/><polyline points="12 6 12 12 16 14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>~${readingTimeMins} мин. чтения`;
        container.insertBefore(timeBadge, container.firstChild);
    }
    // ----------------------------------------

    // Инициализируем Lightbox и ToC после загрузки контента
    initLightbox();
    buildToC();

    // ★ Fade-in для изображений
    initImageFadeIn(container);

    // ★ Smart Dark Mode для iframe Teletype
    applyIframeDarkMode();

    if (!container.innerHTML.includes('<iframe')) {
        container.innerHTML += `
        <div class="channel-banner">
            <div class="channel-content">
                <h3>🌸 Присоединяйся к нам!</h3>
                <p>Все свежие переводы, новости и общение — в нашем Telegram-канале.</p>
                <a href="https://t.me/alya_novel" target="_blank" class="channel-btn">
                    Подписаться на канал
                </a>
            </div>
        </div>`;
    }

    // Восстанавливаем позицию скролла
    restoreScrollPosition();
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
    if (prefetchedChapter.idx === nextIdx) return; // уже загружено

    const chapter = currentChapters[nextIdx];
    if (!chapter) return;

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
        const loadPromises = urlsToLoad.map(async (u) => {
            if (u.includes('teletype.in')) {
                return `<iframe src="${u}" class="teletype-iframe" frameborder="0" style="width:100%;min-height:85vh;border:none;border-radius:8px;margin-bottom:20px;" loading="lazy"></iframe>`;
            }
            const telegraphMatch = u.match(/telegra\.ph\/(.+)/);
            if (telegraphMatch) {
                try {
                    const resp = await fetch(`https://api.telegra.ph/getPage/${telegraphMatch[1]}?return_content=true`);
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
            console.log('✅ Prefetched chapter (with images)', nextIdx + 1);
        }).catch(() => { });
    } else if (chapter.text) {
        const paragraphs = chapter.text.split('\n\n').map(p => `<p>${p.trim()}</p>`).join('');
        prefetchedChapter = { idx: nextIdx, html: paragraphs };
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

        document.body.appendChild(el);
        setTimeout(() => el.remove(), 1000);
    }
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
        const data = await resp.json();
        renderComments(data.comments || []);
    } catch (e) {
        console.warn('Comments load error:', e);
    }
}

function renderComments(comments) {
    const list = document.getElementById('comments-list');
    const badge = document.getElementById('comments-count-badge');
    badge.textContent = comments.length > 0 ? `(${comments.length})` : '';

    const countBadge = document.getElementById('comments-count-badge');
    if (countBadge) countBadge.innerText = comments.length > 0 ? `(${comments.length})` : '';

    if (comments.length === 0) {
        list.innerHTML = `<div class="no-comments">Пока нет комментариев. Будьте первым! ✨</div>`;
        return;
    }

    // ★ Фаза 5: Применяем сортировку
    commentsData = [...comments];
    if (currentCommentSort === 'top') {
        // Сортировка по лайкам (интересные)
        commentsData.sort((a, b) => ((b.likes || 0) - (b.dislikes || 0)) - ((a.likes || 0) - (a.dislikes || 0)));
    } else {
        // По дате (новые сверху)
        commentsData.sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
    }

    // Строим дерево
    const commentMap = {};
    const topLevel = [];
    commentsData.forEach(c => {
        c.children = [];
        commentMap[c.id] = c;
    });

    commentsData.forEach(c => {
        if (c.parent_id && commentMap[c.parent_id]) {
            commentMap[c.parent_id].children.push(c);
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

    function parseSpoilers(text) {
        // Заменяем ||текст|| на скрытый спан
        return text.replace(/\|\|([\s\S]+?)\|\|/g, (match, content) => {
            return `<span class="comment-spoiler" onclick="this.classList.toggle('revealed'); event.stopPropagation();">${escapeHtml(content)}</span>`;
        });
    }

    function renderNode(c, isChild = false) {
        const initial = (c.user_name || 'А')[0].toUpperCase();
        const date = formatDate(c.created_at);
        const isOwn = String(c.user_id) === userId;
        const isAdmin = isAdminMode; // Булево значение из глобального состояния
        const color = getAvatarColor(String(c.user_id));
        
        // Кнопки управления
        const deleteBtn = (isOwn || isAdmin) ? `<button class="c-action-btn c-delete" onclick="deleteComment(${c.id})">Удалить</button>` : '';
        const editBtn = isOwn ? `<button class="c-action-btn" onclick="editComment(${c.id})">Ред.</button>` : '';
        const replyBtn = `<button class="c-action-btn" onclick="setReply(${c.id}, '${escapeHtml(c.user_name)}')">Ответить</button>`;

        // Реакции
        const likes = c.likes || 0;
        const dislikes = c.dislikes || 0;
        const userReaction = c.user_reaction; // 'like', 'dislike' или null

        const likeActive = userReaction === 'like' ? 'active' : '';
        const dislikeActive = userReaction === 'dislike' ? 'active' : '';

        // Avatar with Proxy & Fallback
        const avatarUrl = API_URL ? `${API_URL}/api/avatar?user_id=${c.user_id}` : null;
        const avatarHtml = avatarUrl 
            ? `<img src="${avatarUrl}" class="comment-avatar" alt="${initial}" style="background:${color}" onerror="this.onerror=null;this.outerHTML='<div class=&quot;comment-avatar&quot; style=&quot;background:${color}&quot;>${initial}</div>';">`
            : `<div class="comment-avatar" style="background:${color}">${initial}</div>`;

        let html = `
        <div class="comment-item ${isChild ? 'comment-reply' : ''}" id="comment-${c.id}">
            <div class="comment-avatar-container">
                ${avatarHtml}
            </div>
            <div class="comment-content">
                <div class="comment-header">
                    <div class="comment-author">${escapeHtml(c.user_name)}</div>
                    <div class="comment-date">${date}</div>
                </div>
                <div class="comment-text" id="comment-text-${c.id}">${parseSpoilers(c.text)}</div>
                <div class="comment-actions">
                    <div class="comment-reactions">
                        <button class="c-reaction-btn c-like ${likeActive}" onclick="reactToComment(${c.id}, 'like')" title="Нравится">
                            <svg class="icon-xs" viewBox="0 0 24 24"><path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3zM7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
                            <span>${likes}</span>
                        </button>
                    </div>
                    <div class="comment-main-actions">
                        ${replyBtn}
                        ${editBtn}
                        ${deleteBtn}
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

async function reactToComment(commentId, type) {
    if (!API_URL || !userId) {
        showToast('Пожалуйста, авторизуйтесь через бота.');
        return;
    }
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
            showToast('Ошибка при реакции: ' + (data.error || 'неизвестно'));
        }
    } catch (e) {
        showToast('Ошибка сети.');
    }
}

function sortComments(type) {
    currentCommentSort = type;
    document.getElementById('tab-sort-top').classList.toggle('active', type === 'top');
    document.getElementById('tab-sort-new').classList.toggle('active', type === 'new');
    renderComments(allCommentsCache);
}

function editComment(id) {
    const comment = allCommentsCache.find(c => c.id === id);
    if (!comment) return;
    
    const textNode = document.getElementById(`comment-text-${id}`);
    const originalText = comment.text;
    
    textNode.innerHTML = `
        <textarea class="comment-input edit-area" id="edit-input-${id}" rows="3">${escapeHtml(originalText)}</textarea>
        <div class="edit-actions" style="margin-top:8px; display:flex; gap:8px;">
            <button class="comment-submit-btn" style="float:none; padding:6px 14px;" onclick="saveCommentEdit(${id})">Сохранить</button>
            <button class="c-action-btn" onclick="renderComments(allCommentsCache)">Отмена</button>
        </div>
    `;
    document.getElementById(`edit-input-${id}`).focus();
}

async function saveCommentEdit(id) {
    const newText = document.getElementById(`edit-input-${id}`).value.trim();
    if (!newText) return;

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

async function postComment() {
    if (!API_URL || !userId) return;
    const input = document.getElementById('comment-input');
    const text = input.value.trim();
    if (!text) return;

    const key = getChapterKey();
    if (!key) return;

    const btn = document.querySelector('.comment-submit-btn');
    btn.disabled = true;

    try {
        await apiFetch(API_URL + '/api/comments', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                chapter_key: key,
                text: text,
                parent_id: replyingToId
            })
        });
        input.value = '';
        cancelReply();
        await loadComments();
    } catch (e) {
        console.warn('Post comment error:', e);
    } finally {
        btn.disabled = false;
    }
}

async function deleteComment(commentId) {
    if (!API_URL || !userId) return;
    try {
        await apiFetch(API_URL + '/api/comments', {
            method: 'DELETE',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ comment_id: commentId })
        });
        await loadComments();
    } catch (e) {
        console.warn('Delete comment error:', e);
    }
}

function formatDate(dateStr) {
    if (!dateStr) return '';
    try {
        // SQLite ╨▓╨╛╨╖╨▓╤А╨░╤Й╨░╨╡╤В ╨▓╤А╨╡╨╝╤П ╨▓ UTC "YYYY-MM-DD HH:MM:SS". ╨Я╤А╨╡╨▓╤А╨░╤Й╨░╨╡╨╝ ╨╡╨│╨╛ ╨▓ ╨▓╨░╨╗╨╕╨┤╨╜╤Л╨╣ ISO 8601 UTC.
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

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
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
        const data = await resp.json();
        renderReactions(data);
    } catch (e) {
        console.warn('Reactions load error:', e);
    }
}

function renderReactions(data) {
    const bar = document.getElementById('reaction-bar');
    if (!bar) return;

    const list = [
        { type: 'like', text: 'Круто', emoji: '👍', svg: '<svg class="r-svg" viewBox="0 0 24 24"><path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3zM7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"/></svg>' },
        { type: 'heart', text: 'Люблю', emoji: '❤️', svg: '<svg class="r-svg" viewBox="0 0 24 24"><path d="M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.3 1.5 4.05 3 5.5l7 7Z"/></svg>' },
        { type: 'fire', text: 'Огонь', emoji: '🔥', svg: '<svg class="r-svg" viewBox="0 0 24 24"><path d="M8.5 14.5A2.5 2.5 0 0 0 11 12c0-1.38-.5-2-1-3-1.072-2.143-.224-4.054 2-6 .5 2.5 2 4.9 4 6.5 2 1.6 3 3.5 3 5.5a7 7 0 1 1-14 0c0-1.153.433-2.294 1-3a2.5 2.5 0 0 0 2.5 2.5z"/></svg>' },
        { type: 'funny', text: 'Угар', emoji: '😂', svg: '<svg class="r-svg" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><path d="M8 14s1.5 2 4 2 4-2 4-2"/><line x1="9" x2="9.01" y1="9" y2="9"/><line x1="15" x2="15.01" y1="9" y2="9"/></svg>' },
        { type: 'wow', text: 'Ого!', emoji: '😮', svg: '<svg class="r-svg" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><path d="M8 15h8"/><line x1="9" x2="9.01" y1="9" y2="9"/><line x1="15" x2="15.01" y1="9" y2="9"/></svg>' },
        { type: 'sad', text: 'Грустно', emoji: '😢', svg: '<svg class="r-svg" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><path d="M16 16s-1.5-2-4-2-4 2-4 2"/><line x1="9" x2="9.01" y1="9" y2="9"/><line x1="15" x2="15.01" y1="9" y2="9"/></svg>' },
        { type: 'battle', text: 'Эпик', emoji: '⚔️', svg: '<svg class="r-svg" viewBox="0 0 24 24"><polyline points="14.5 17.5 3 6 3 3 6 3 17.5 14.5"/><line x1="13" x2="19" y1="19" y2="13"/><line x1="16" x2="20" y1="16" y2="20"/><line x1="19" x2="21" y1="21" y2="19"/></svg>' }
    ];

    const reactions = data.reactions || {};
    const user_reaction = data.user_reaction;

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

async function toggleReaction(type) {
    if (!API_URL || !userId) {
        showToast('Авторизуйтесь в боте для реакций');
        return;
    }
    const key = getChapterKey();
    if (!key) return;

    // Visual Feedback
    const itemEl = document.querySelector(`.reaction-item.type-${type}`);
    const emojiMap = { like: '👍', heart: '❤️', fire: '🔥', funny: '😂', wow: '😮', sad: '😢', battle: '⚔️' };
    
    haptic('medium');
    if (itemEl && !itemEl.classList.contains('active')) {
        spawnFloatingEmoji(emojiMap[type] || '✨', itemEl);
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
        if (data.ok) {
            await loadReactions();
        }
    } catch (e) {
        showToast('Ошибка сети.');
    }
}

// ==========================================================================
// НАВИГАЦИЯ ЭКРАНОВ
// ==========================================================================

function showScreen(name) {
    // Если уходим из читалки — сохраняем позицию
    if (document.getElementById('screen-reader').classList.contains('active') && name !== 'reader') {
        saveScrollPosition();
        if (progressBarEl) progressBarEl.style.width = '0%';
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
    localStorage.setItem('reader_progress', JSON.stringify(readChapters));
}

// ==========================================================================
// НАСТРОЙКИ
// ==========================================================================

function toggleSettings() {
    const overlay = document.getElementById('settings-overlay');
    const panel = document.getElementById('settings-panel');
    overlay.classList.toggle('hidden');
    panel.classList.toggle('hidden');
}

function setFontSize(size) {
    settings.fontSize = size;
    applySettings();
    saveSettings();
    document.querySelectorAll('[data-size]').forEach(b => {
        b.classList.toggle('active', parseInt(b.dataset.size) === size);
    });
}

function setTheme(theme) {
    settings.theme = theme;
    applySettings();
    saveSettings();
    document.querySelectorAll('[data-theme]').forEach(b => {
        b.classList.toggle('active', b.dataset.theme === theme);
    });
}

function setTextWidth(width) {
    settings.textWidth = parseInt(width);
    applySettings();
    saveSettings();
}

function setFont(font) {
    settings.font = font;
    applySettings();
    saveSettings();
    document.querySelectorAll('[data-font]').forEach(b => {
        b.classList.toggle('active', b.dataset.font === font);
    });
}

function setLineHeight(lh) {
    settings.lineHeight = parseFloat(lh);
    applySettings();
    saveSettings();
    document.querySelectorAll('[data-lh]').forEach(b => {
        b.classList.toggle('active', parseFloat(b.dataset.lh) === settings.lineHeight);
    });
}

function setTextAlign(align) {
    settings.textAlign = align;
    applySettings();
    saveSettings();
    document.querySelectorAll('[data-align]').forEach(b => {
        b.classList.toggle('active', b.dataset.align === align);
    });
}

function setIndent(enabled) {
    settings.indent = enabled;
    applySettings();
    saveSettings();
}

function setParaSpacing(val) {
    settings.paraSpacing = parseInt(val);
    applySettings();
    saveSettings();
}

function applySettings() {
    // Тема
    document.body.className = '';
    if (settings.theme !== 'light') {
        document.body.classList.add(`theme-${settings.theme}`);
    }

    // Шрифт и размер
    const readerText = document.getElementById('reader-text');
    if (readerText) {
        readerText.style.fontSize = settings.fontSize + 'px';
        readerText.style.maxWidth = settings.textWidth + '%';
        readerText.style.lineHeight = settings.lineHeight;

        // Шрифт
        readerText.classList.remove('font-sans', 'font-slab', 'font-mono');
        if (settings.font === 'sans') readerText.classList.add('font-sans');
        if (settings.font === 'slab') readerText.classList.add('font-slab');
        if (settings.font === 'mono') readerText.classList.add('font-mono');

        // Выравнивание
        readerText.classList.toggle('align-justify', settings.textAlign === 'justify');

        // Отступы
        readerText.classList.toggle('indent-on', settings.indent);

        // Отступ между абзацами
        readerText.style.setProperty('--para-spacing', settings.paraSpacing + 'px');
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
            light: '#ffffff', sepia: '#f4ead5',
            dark: '#1a1a2e', amoled: '#000000'
        };
        tg.setHeaderColor(colors[settings.theme] || '#ffffff');
    } catch (e) { }
}

function saveSettings() {
    localStorage.setItem('reader_settings', JSON.stringify(settings));
}

function restoreSettings() {
    document.querySelectorAll('[data-size]').forEach(b => {
        b.classList.toggle('active', parseInt(b.dataset.size) === settings.fontSize);
    });
    document.querySelectorAll('[data-theme]').forEach(b => {
        b.classList.toggle('active', b.dataset.theme === settings.theme);
    });
    document.querySelectorAll('[data-font]').forEach(b => {
        b.classList.toggle('active', b.dataset.font === settings.font);
    });
    document.querySelectorAll('[data-lh]').forEach(b => {
        b.classList.toggle('active', parseFloat(b.dataset.lh) === settings.lineHeight);
    });
    document.querySelectorAll('[data-align]').forEach(b => {
        b.classList.toggle('active', b.dataset.align === settings.textAlign);
    });
    document.getElementById('width-slider').value = settings.textWidth;
    document.getElementById('para-spacing-slider').value = settings.paraSpacing;

    const indentToggle = document.getElementById('indent-toggle');
    if (indentToggle) indentToggle.checked = settings.indent;

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
        readerContent.addEventListener('scroll', () => {
            updateProgressBar();

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
                lastScrollY = currentScroll;
            }

            // Автосохранение позиции (debounced)
            clearTimeout(scrollSaveTimer);
            scrollSaveTimer = setTimeout(() => {
                saveScrollPosition();
            }, 800);

            // ★ Prefetch следующей главы при 80% прокрутки (пункт 4)
            const scrollPct = readerContent.scrollTop / Math.max(1, readerContent.scrollHeight - readerContent.clientHeight);
            if (scrollPct > 0.8) {
                prefetchNextChapter();
            }
        });

        // ★ Tap-to-Scroll zones (пункт 2)
        readerContent.addEventListener('click', (e) => {
            // Игнорируем клики по ссылкам, кнопкам, изображениям, textarea, input
            if (e.target.closest('a, button, img, textarea, input, .social-section, .comment-form, iframe')) return;

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
    }
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
        const allLocal = JSON.parse(localStorage.getItem('reader_last_read') || '{}');
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
        <div class="continue-reading-card" onclick="selectSeries('${series.id}')">
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
    const container = document.getElementById('reader-text');
    const tocList = document.getElementById('toc-list');
    const tocBtn = document.getElementById('toc-toggle-btn');
    if (!container || !tocList || !tocBtn) return;

    const headings = container.querySelectorAll('h2, h3, h4');
    tocItems = Array.from(headings);

    if (tocItems.length === 0) {
        tocBtn.style.display = 'none';
        return;
    }

    tocBtn.style.display = 'flex';
    // Assign IDs to headings
    tocItems.forEach((h, i) => {
        if (!h.id) h.id = `toc-heading-${i}`;
    });

    tocList.innerHTML = tocItems.map((h, i) => {
        const level = h.tagName.toLowerCase();
        const cssClass = level === 'h3' ? 'toc-h3' : level === 'h4' ? 'toc-h4' : '';
        return `<div class="toc-item ${cssClass}" data-toc-idx="${i}" onclick="scrollToHeading(${i})">${h.textContent}</div>`;
    }).join('');

    // IntersectionObserver for active heading
    if (tocObserver) tocObserver.disconnect();
    tocObserver = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                const idx = tocItems.indexOf(entry.target);
                if (idx !== -1) highlightToCItem(idx);
            }
        });
    }, { root: document.getElementById('reader-content'), rootMargin: '-10% 0px -70% 0px', threshold: 0.1 });

    tocItems.forEach(h => tocObserver.observe(h));
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
    document.getElementById('toc-overlay').classList.toggle('hidden');
    document.getElementById('toc-panel').classList.toggle('hidden');
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

let readingStats = JSON.parse(localStorage.getItem('reader_stats') || '{"timeSpentSeconds":0}');

// Track reading time when in 'reader' screen
setInterval(() => {
    if (document.getElementById('screen-reader').classList.contains('active') && !document.hidden) {
        readingStats.timeSpentSeconds += 5;
        if (readingStats.timeSpentSeconds % 60 === 0) { // save every minute
            localStorage.setItem('reader_stats', JSON.stringify(readingStats));
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

function renderLibraryTab() {
    const list = document.getElementById('library-list');
    if (!list) return;

    if (!allData || !allData.series || allData.series.length === 0) {
        list.innerHTML = `
            <div class="empty-state">
                <div class="empty-icon">📂</div>
                <h3>Нет данных</h3>
                <p>Библиотека пуста. Добавьте свои первые ранобэ.</p>
            </div>
        `;
        return;
    }

    // Get last read data
    const allLocal = JSON.parse(localStorage.getItem('reader_last_read') || '{}');

    // Combine local with server bookmarks if missing
    serverBookmarks.forEach(bm => {
        if (!allLocal[bm.series_id]) {
            allLocal[bm.series_id] = {
                seriesId: bm.series_id,
                volume: bm.volume_id,
                chapter: bm.chapter_key,
                ts: new Date(bm.updated_at).getTime() || 0,
                isServer: true
            };
        }
    });

    const activeSeriesKeys = Object.keys(allLocal).sort((a, b) => (allLocal[b].ts || 0) - (allLocal[a].ts || 0));

    if (activeSeriesKeys.length === 0) {
        list.innerHTML = `
            <div class="empty-state">
                <div class="empty-icon">📝</div>
                <h3>Вы ещё ничего не читали</h3>
                <p>Откройте Главную, чтобы выбрать историю.</p>
            </div>
        `;
        return;
    }

    const itemsHtml = activeSeriesKeys.slice(0, 10).map(key => {
        const bm = allLocal[key];
        const s = allData.series.find(x => String(x.id) === String(bm.seriesId || key));
        if (!s) return '';

        let chTitle = "Глава " + bm.chapter;
        const v = s.volumes.find(v => String(v.volume) === String(bm.volume));
        if (v) {
            const ch = v.chapters.find(c => String(c.chapter) === String(bm.chapter));
            if (ch && ch.custom_name) chTitle = ch.custom_name;
            else if (ch) chTitle = `Глава ${ch.chapter}`;
        }

        // Progress calc
        const totalCh = s.volumes.reduce((sum, v) => sum + v.chapters.length, 0);
        const readCount = s.volumes.reduce((sum, v) => {
            return sum + v.chapters.filter(c => isRead(s.id, v.volume, c.chapter)).length;
        }, 0);
        const progress = totalCh > 0 ? Math.round((readCount / totalCh) * 100) : 0;
        const coverImg = s.cover_url ? `<img src="${s.cover_url}" class="library-cover" alt="">` : `<div class="series-icon">📖</div>`;

        return `
        <div class="series-card" style="margin-bottom:12px;" onclick="selectSeries('${s.id}')">
            ${coverImg}
            <div class="series-info">
                <h3>${s.title}</h3>
                <p style="font-size: 13px; color: var(--text-sec); margin-top:2px;">Остановлено: Том ${bm.volume}, ${chTitle}</p>
                <div class="library-progress-bar">
                    <div class="library-progress-fill" style="width: ${progress}%"></div>
                </div>
                <div style="font-size: 11px; margin-top:4px; text-align:right; color: var(--text-sec);">${progress}% прочитано</div>
            </div>
            <span class="series-arrow">&rsaquo;</span>
        </div>`;
    }).join('');

    list.innerHTML = itemsHtml;
}

// ==========================================================================
// DRAG-N-DROP CHAPTER SORT (Admin, Batch 3)
// ==========================================================================

let dragSrcIdx = null;

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

function initTypoReporter() {
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

function initGestures() {
    const reader = document.getElementById('screen-reader');
    const content = document.getElementById('reader-content');
    const indicator = document.getElementById('swipe-back-indicator');
    const pullNext = document.getElementById('pull-next-indicator');

    if (!reader || !content || !indicator || !pullNext) return;

    reader.addEventListener('pointerdown', (e) => {
        touchStartX = e.clientX;
        gestureTouchStartY = e.clientY;
        isSwipeActive = touchStartX < 35; // edge detection
    }, { passive: true });

    reader.addEventListener('pointermove', (e) => {
        if (!isSwipeActive) return;
        let deltaX = e.clientX - touchStartX;
        let deltaY = Math.abs(e.clientY - gestureTouchStartY);

        // Добавлен порог по Y чтобы не срабатывало при скролле (Баг 1)
        if (deltaX > 10 && deltaY < 40) { 
            indicator.style.opacity = Math.min(deltaX / 100, 0.8);
            // Сохраняем translateY(-50%) для центрирования (Баг 3)
            indicator.style.transform = `translateY(-50%) scaleY(${Math.min(0.5 + deltaX / 200, 1)}) translateX(${deltaX / 2}px)`;
        }
    }, { passive: true });

    reader.addEventListener('pointerup', (e) => {
        let deltaX = e.clientX - touchStartX;
        indicator.style.opacity = 0;
        indicator.style.transform = 'translateY(-50%) translateX(-100%)'; 

        if (isSwipeActive && deltaX > 85) {
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
            preloadNextChapter();
        }
    }, { passive: true });
}

restoreSettings();
loadData();
initTypoReporter();
initGestures();
initReaderScrollListeners();
