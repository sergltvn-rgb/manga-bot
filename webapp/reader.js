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

function toggleAdminMode(enabled) {
    isAdminMode = enabled;
    if (document.getElementById('screen-series').classList.contains('active')) renderSeriesList();
    if (document.getElementById('screen-chapters').classList.contains('active')) {
        renderVolumeTabs();
        renderChaptersList();
    }
}

function renameItem(objId) {
    const bot_username = allData.bot_username || "Alyamangapage_bot";
    tg.openTelegramLink('https://t.me/' + bot_username + '?start=rename_' + objId);
    tg.close();
}

// === Настройки (из localStorage) ===
const defaults = { fontSize: 17, theme: 'light', textWidth: 90, font: 'serif', lineHeight: 1.8, textAlign: 'left', indent: true };
let settings = JSON.parse(localStorage.getItem('reader_settings') || 'null') || { ...defaults };
// Миграция старых настроек
if (!settings.lineHeight) settings.lineHeight = 1.8;
if (!settings.textAlign) settings.textAlign = 'left';
if (settings.indent === undefined) settings.indent = true;

let readChapters = JSON.parse(localStorage.getItem('reader_progress') || '{}');

// === Получение API URL из параметров URL ===
const urlParams = new URLSearchParams(window.location.search);
const API_URL = urlParams.get('api') || '';

// === Сохранение позиции чтения ===
function getScrollKey() {
    if (!currentSeries || !currentVolume) return null;
    return `scroll_${currentSeries.id}_v${currentVolume.volume}_ch${currentChapters[currentChapterIdx]?.chapter}`;
}

function saveScrollPosition() {
    const key = getScrollKey();
    if (!key) return;
    const el = document.getElementById('reader-content');
    if (!el) return;
    const pct = el.scrollTop / Math.max(1, el.scrollHeight - el.clientHeight);
    localStorage.setItem(key, JSON.stringify({ pct, ts: Date.now() }));
    // Также сохраняем «последнюю открытую» для серии
    saveLastRead();
}

function restoreScrollPosition() {
    const key = getScrollKey();
    if (!key) return;
    const saved = JSON.parse(localStorage.getItem(key) || 'null');
    if (!saved) return;
    const el = document.getElementById('reader-content');
    if (!el) return;
    // Ждём чтобы контент отрендерился
    setTimeout(() => {
        const maxScroll = el.scrollHeight - el.clientHeight;
        el.scrollTop = saved.pct * maxScroll;
    }, 300);
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
    return all[seriesId] || null;
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

async function loadData() {
    if (API_URL) {
        try {
            const resp = await fetch(API_URL + '/api/reader', { signal: AbortSignal.timeout(8000) });
            if (resp.ok) {
                allData = await resp.json();
                if (allData.series && allData.series.length > 0) {
                    renderSeriesList();
                    return;
                }
            }
        } catch (e) {
            console.warn('API недоступен:', e);
        }
    }

    try {
        const resp = await fetch('chapters_data.json?v=' + Date.now());
        if (resp.ok) {
            allData = await resp.json();
            renderSeriesList();
            return;
        }
    } catch (e) {
        console.warn('Статический JSON не найден:', e);
    }

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

// ==========================================================================
// РЕНДЕР ЭКРАНОВ
// ==========================================================================

function renderSeriesList() {
    const container = document.getElementById('series-list');
    
    if (!allData.series || allData.series.length === 0) {
        showEmptyState();
        return;
    }

    const icons = ['📖', '📕', '📗', '📘', '📙'];
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

        const editBtn = isAdminMode ? `<button class="admin-edit-btn" onclick="renameItem('series_${s.id.replace('series_', '')}'); event.stopPropagation();">✏️</button>` : '';
        
        return `
        <div class="series-card" onclick="selectSeries('${s.id}')">
            <div class="series-icon">${icons[i % icons.length]}</div>
            <div class="series-info">
                <h3>${s.title}${editBtn}</h3>
                <p>${s.volumes.length} том(ов) · ${totalCh} глав${progress > 0 ? ` · ${progress}%` : ''}</p>
                ${continueBadge}
            </div>
            <span class="series-arrow">›</span>
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
        const editBtn = isAdminMode ? `<button class="admin-edit-btn" onclick="renameItem('vol_${currentSeries.id}_${v.volume}'); event.stopPropagation();">✏️</button>` : '';
        return `
        <button class="vol-tab" data-vol="${v.volume}" onclick="selectVolume(${v.volume})">
            ${volName}${editBtn}
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
        const editBtn = isAdminMode ? `<button class="admin-edit-btn" onclick="renameItem('chap_${currentSeries.id}_${currentVolume.volume}_${ch.chapter}'); event.stopPropagation();">✏️</button>` : '';
        const isCurrent = lastChapter && String(ch.chapter) === String(lastChapter);
        
        return `
        <div class="chapter-item ${readClass}${isCurrent ? ' current-chapter' : ''}" onclick="openChapter(${idx})">
            <div class="chapter-num">${idx + 1}</div>
            <div class="chapter-name">${chapName}${editBtn}</div>
            ${isCurrent ? '<span style="font-size:12px;color:var(--accent);font-weight:600;">◀</span>' : ''}
            <span class="chapter-read-mark">✓</span>
        </div>`;
    }).join('');
}

// ==========================================================================
// ЧТЕНИЕ
// ==========================================================================

function openChapter(idx) {
    currentChapterIdx = idx;
    const chapter = currentChapters[idx];
    if (!chapter) return;
    
    document.getElementById('reader-title').textContent = chapter.custom_name || `Глава ${chapter.chapter}`;
    updateNavButtons();
    markAsRead(currentSeries.id, currentVolume.volume, chapter.chapter);
    loadChapterContent(chapter);
    
    initProgressBar();
    if (progressBarEl) progressBarEl.style.width = '0%';
    
    showScreen('reader');
    
    // Загружаем лайки и комментарии (для API)
    if (API_URL) {
        loadLikes();
        loadComments();
        document.getElementById('social-section').style.display = 'block';
    } else {
        document.getElementById('social-section').style.display = 'none';
    }
}

function loadChapterContent(chapter) {
    const container = document.getElementById('reader-text');
    
    let urlsToLoad = [];
    if (chapter.urls && chapter.urls.length > 0) {
        urlsToLoad = chapter.urls;
    } else if (chapter.url) {
        urlsToLoad = [chapter.url];
    }
    
    if (urlsToLoad.length > 0) {
        container.innerHTML = `<div class="loading-spinner"><div class="spinner"></div><p>Загрузка...</p></div>`;
        
        const loadPromises = urlsToLoad.map(async (u) => {
            const telegraphMatch = u.match(/telegra\.ph\/(.+)/);
            if (telegraphMatch) {
                try {
                    const resp = await fetch(`https://api.telegra.ph/getPage/${telegraphMatch[1]}?return_content=true`);
                    const data = await resp.json();
                    if (data.ok && data.result && data.result.content) {
                        return renderTelegraphContent(data.result.content);
                    }
                } catch (e) {
                    console.warn("Telegraph API err", e);
                }
            }
            return `<iframe src="${u}" frameborder="0" style="width:100%;min-height:80vh;border:none;border-radius:8px;margin-bottom:20px;"></iframe>`;
        });
        
        Promise.all(loadPromises).then(results => {
            container.innerHTML = results.join('<div class="chapter-divider" style="text-align:center; margin: 40px 0;">❖ ❖ ❖</div>');
            
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
        });
    } else if (chapter.text) {
        const paragraphs = chapter.text.split('\n\n').map(p => `<p>${p.trim()}</p>`).join('');
        container.innerHTML = paragraphs;
        
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
        
        restoreScrollPosition();
    } else {
        container.innerHTML = `
            <div class="empty-state">
                <div class="empty-icon">📄</div>
                <h3>Контент недоступен</h3>
                <p>Эта глава ещё не добавлена.</p>
            </div>`;
    }
    
    document.getElementById('reader-content').scrollTop = 0;
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
        openChapter(newIdx);
    }
}

function backFromReader() {
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

function getChapterKey() {
    if (!currentSeries || !currentVolume) return '';
    return `${currentSeries.id}_v${currentVolume.volume}_ch${currentChapters[currentChapterIdx]?.chapter}`;
}

async function loadLikes() {
    if (!API_URL) return;
    const key = getChapterKey();
    if (!key) return;
    try {
        const resp = await fetch(API_URL + `/api/likes?chapter_key=${encodeURIComponent(key)}&user_id=${encodeURIComponent(userId)}`);
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
        const resp = await fetch(API_URL + '/api/likes', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ chapter_key: key, user_id: userId })
        });
        const data = await resp.json();
        
        const btn = document.getElementById('like-btn');
        if (data.liked) btn.classList.add('just-liked');
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
    icon.textContent = liked ? '❤️' : '🤍';
    countEl.textContent = count > 0 ? count : '';
}

// ==========================================================================
// КОММЕНТАРИИ
// ==========================================================================

async function loadComments() {
    if (!API_URL) return;
    const key = getChapterKey();
    if (!key) return;
    try {
        const resp = await fetch(API_URL + `/api/comments?chapter_key=${encodeURIComponent(key)}`);
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
    
    if (comments.length === 0) {
        list.innerHTML = '<div class="no-comments">Пока нет комментариев. Будьте первым! ✨</div>';
        return;
    }
    
    list.innerHTML = comments.map(c => {
        const initial = (c.user_name || 'А')[0].toUpperCase();
        const date = formatDate(c.created_at);
        const isOwn = String(c.user_id) === userId;
        const deleteBtn = isOwn ? `<button class="comment-delete-btn" onclick="deleteComment(${c.id})">🗑</button>` : '';
        
        return `
        <div class="comment-item" id="comment-${c.id}">
            <div class="comment-header">
                <div class="comment-avatar">${initial}</div>
                <div class="comment-meta">
                    <div class="comment-author">${escapeHtml(c.user_name)}</div>
                    <div class="comment-date">${date}</div>
                </div>
                ${deleteBtn}
            </div>
            <div class="comment-text">${escapeHtml(c.text)}</div>
        </div>`;
    }).join('');
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
        await fetch(API_URL + '/api/comments', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                chapter_key: key,
                user_id: userId,
                user_name: userName,
                text: text
            })
        });
        input.value = '';
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
        await fetch(API_URL + '/api/comments', {
            method: 'DELETE',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ comment_id: commentId, user_id: userId })
        });
        await loadComments();
    } catch (e) {
        console.warn('Delete comment error:', e);
    }
}

function formatDate(dateStr) {
    if (!dateStr) return '';
    try {
        const d = new Date(dateStr + (dateStr.includes('T') ? '' : 'T00:00:00'));
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
        readerText.classList.remove('font-sans', 'font-slab');
        if (settings.font === 'sans') readerText.classList.add('font-sans');
        if (settings.font === 'slab') readerText.classList.add('font-slab');
        
        // Выравнивание
        readerText.classList.toggle('align-justify', settings.textAlign === 'justify');
        
        // Отступы
        readerText.classList.toggle('indent-on', settings.indent);
    }
    
    // Social section width
    const socialSection = document.getElementById('social-section');
    if (socialSection) {
        socialSection.style.maxWidth = settings.textWidth + '%';
    }
    
    // Telegram header
    try {
        const colors = {
            light: '#ffffff', sepia: '#f4ead5',
            dark: '#1a1a2e', amoled: '#000000'
        };
        tg.setHeaderColor(colors[settings.theme] || '#ffffff');
    } catch (e) {}
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
    
    const indentToggle = document.getElementById('indent-toggle');
    if (indentToggle) indentToggle.checked = settings.indent;
    
    applySettings();
}

// ==========================================================================
// СОБЫТИЯ СКРОЛЛА (автосохранение + прогресс-бар)
// ==========================================================================

let scrollSaveTimer = null;

document.addEventListener('DOMContentLoaded', () => {
    const readerContent = document.getElementById('reader-content');
    if (readerContent) {
        readerContent.addEventListener('scroll', () => {
            updateProgressBar();

            // Автосохранение позиции (debounced)
            clearTimeout(scrollSaveTimer);
            scrollSaveTimer = setTimeout(() => {
                saveScrollPosition();
            }, 800);
        });
    }
});

// Сохраняем при уходе из приложения
window.addEventListener('beforeunload', () => {
    saveScrollPosition();
});

// ==========================================================================
// ИНИЦИАЛИЗАЦИЯ
// ==========================================================================

restoreSettings();
loadData();
