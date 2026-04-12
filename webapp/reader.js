// ==========================================================================
// Читалка ранобэ — JavaScript
// Загружает данные из API бота, отображает тома/главы, открывает для чтения
// ==========================================================================

const tg = window.Telegram.WebApp;
tg.expand();
tg.ready();

// === Состояние ===
let allData = { series: [] };
let currentSeries = null;
let currentVolume = null;
let currentChapterIdx = 0;
let currentChapters = [];

// === Настройки (из localStorage) ===
const defaults = { fontSize: 17, theme: 'light', textWidth: 90, font: 'serif' };
let settings = JSON.parse(localStorage.getItem('reader_settings') || 'null') || { ...defaults };
let readChapters = JSON.parse(localStorage.getItem('reader_progress') || '{}');

// === Получение API URL из параметров URL ===
const urlParams = new URLSearchParams(window.location.search);
const API_URL = urlParams.get('api') || '';

// ==========================================================================
// ЗАГРУЗКА ДАННЫХ
// ==========================================================================

async function loadData() {
    // Пробуем загрузить из API бота
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

    // Fallback: пробуем загрузить статический JSON
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

    // Нет данных
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
        
        return `
        <div class="series-card" onclick="selectSeries('${s.id}')">
            <div class="series-icon">${icons[i % icons.length]}</div>
            <div class="series-info">
                <h3>${s.title}</h3>
                <p>${s.volumes.length} том(ов) · ${totalCh} глав${progress > 0 ? ` · ${progress}%` : ''}</p>
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
    
    // Показываем первый том
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
    tabs.innerHTML = currentSeries.volumes.map(v => 
        `<button class="vol-tab" data-vol="${v.volume}" onclick="selectVolume(${v.volume})">
            Том ${v.volume}
        </button>`
    ).join('');
}

function selectVolume(volNum) {
    currentVolume = currentSeries.volumes.find(v => v.volume === volNum);
    if (!currentVolume) return;
    
    // Обновляем активный таб
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
    
    container.innerHTML = currentChapters.map((ch, idx) => {
        const readClass = isRead(currentSeries.id, currentVolume.volume, ch.chapter) ? 'read' : '';
        return `
        <div class="chapter-item ${readClass}" onclick="openChapter(${idx})">
            <div class="chapter-num">${idx + 1}</div>
            <div class="chapter-name">Глава ${ch.chapter}</div>
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
    
    // Обновляем заголовок
    document.getElementById('reader-title').textContent = `Глава ${chapter.chapter}`;
    
    // Обновляем навигацию
    updateNavButtons();
    
    // Отмечаем как прочитанную
    markAsRead(currentSeries.id, currentVolume.volume, chapter.chapter);
    
    // Загружаем контент
    loadChapterContent(chapter);
    
    showScreen('reader');
}

function loadChapterContent(chapter) {
    const container = document.getElementById('reader-text');
    
    if (chapter.url) {
        // Проверяем — это Telegraph ссылка?
        const telegraphMatch = chapter.url.match(/telegra\.ph\/(.+)/);
        
        if (telegraphMatch) {
            // Загружаем контент через Telegraph API
            container.innerHTML = `<div class="loading-spinner"><div class="spinner"></div><p>Загрузка...</p></div>`;
            
            fetch(`https://api.telegra.ph/getPage/${telegraphMatch[1]}?return_content=true`)
                .then(r => r.json())
                .then(data => {
                    if (data.ok && data.result && data.result.content) {
                        container.innerHTML = renderTelegraphContent(data.result.content);
                    } else {
                        // Если Telegraph API не работает — показываем в iframe
                        container.innerHTML = `<iframe src="${chapter.url}" frameborder="0" style="width:100%;min-height:80vh;border:none;border-radius:8px;"></iframe>`;
                    }
                })
                .catch(() => {
                    container.innerHTML = `<iframe src="${chapter.url}" frameborder="0" style="width:100%;min-height:80vh;border:none;border-radius:8px;"></iframe>`;
                });
        } else {
            // Обычная ссылка — открываем в iframe
            container.innerHTML = `<iframe src="${chapter.url}" frameborder="0" style="width:100%;min-height:80vh;border:none;border-radius:8px;"></iframe>`;
        }
    } else if (chapter.text) {
        // Встроенный текст
        const paragraphs = chapter.text.split('\n\n').map(p => `<p>${p.trim()}</p>`).join('');
        container.innerHTML = paragraphs;
    } else {
        container.innerHTML = `
            <div class="empty-state">
                <div class="empty-icon">📄</div>
                <h3>Контент недоступен</h3>
                <p>Эта глава ещё не добавлена.</p>
            </div>`;
    }
    
    // Добавляем красивую ссылку на канал в конце (если это не iframe)
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
    
    // Скроллим наверх
    document.getElementById('reader-content').scrollTop = 0;
}

function renderTelegraphContent(nodes) {
    if (!Array.isArray(nodes)) return '';
    return nodes.map(node => {
        if (typeof node === 'string') return node;
        if (!node.tag) return '';
        
        const children = node.children ? renderTelegraphContent(node.children) : '';
        const attrs = node.attrs ? Object.entries(node.attrs).map(([k, v]) => `${k}="${v}"`).join(' ') : '';
        
        // Обрабатываем изображения
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
    const newIdx = currentChapterIdx + delta;
    if (newIdx >= 0 && newIdx < currentChapters.length) {
        openChapter(newIdx);
    }
}

function updateNavButtons() {
    document.getElementById('prev-chapter-btn').disabled = currentChapterIdx === 0;
    document.getElementById('next-chapter-btn').disabled = currentChapterIdx >= currentChapters.length - 1;
    document.getElementById('chapter-indicator').textContent = `${currentChapterIdx + 1} / ${currentChapters.length}`;
}

// ==========================================================================
// НАВИГАЦИЯ ЭКРАНОВ
// ==========================================================================

function showScreen(name) {
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
    // Обновляем активную кнопку
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
        readerText.classList.toggle('font-sans', settings.font === 'sans');
    }
    
    // Обновляем Telegram header
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
    // Восстанавливаем UI настроек
    document.querySelectorAll('[data-size]').forEach(b => {
        b.classList.toggle('active', parseInt(b.dataset.size) === settings.fontSize);
    });
    document.querySelectorAll('[data-theme]').forEach(b => {
        b.classList.toggle('active', b.dataset.theme === settings.theme);
    });
    document.querySelectorAll('[data-font]').forEach(b => {
        b.classList.toggle('active', b.dataset.font === settings.font);
    });
    document.getElementById('width-slider').value = settings.textWidth;
    
    applySettings();
}

// ==========================================================================
// ИНИЦИАЛИЗАЦИЯ
// ==========================================================================

restoreSettings();
loadData();
