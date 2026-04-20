// ==========================================================================
// Р§РёС‚Р°Р»РєР° СЂР°РЅРѕР±СЌ вЂ” JavaScript v3
// Р—Р°РіСЂСѓР·РєР°/РѕС‚РѕР±СЂР°Р¶РµРЅРёРµ, РїСЂРѕРіСЂРµСЃСЃ С‡С‚РµРЅРёСЏ, Р»Р°Р№РєРё, РєРѕРјРјРµРЅС‚Р°СЂРёРё
// ==========================================================================

const tg = (window.Telegram && window.Telegram.WebApp) ? window.Telegram.WebApp : { expand: () => {}, ready: () => {}, openTelegramLink: (url) => window.open(url, '_blank'), initDataUnsafe: {} };
tg.expand();
tg.ready();

function openChannel() {
    return readerShellUi.openChannel();
}

// === Telegram User ===
const tgUser = tg.initDataUnsafe?.user || {};
const userId = String(tgUser.id || '');
const userName = tgUser.first_name || 'РђРЅРѕРЅРёРј';

// === РЎРѕСЃС‚РѕСЏРЅРёРµ ===
let allData = { series: [] };
let adminIds = []; // РЎРїРёСЃРѕРє ID Р°РґРјРёРЅРёСЃС‚СЂР°С‚РѕСЂРѕРІ РёР· Р‘Р”
let currentSeries = null;
let currentVolume = null;
let currentChapterIdx = 0;
let currentChapters = [];
let isAdminMode = false;
let currentCommentSort = 'top'; 
let allCommentsCache = []; 
let activeCommentEditId = null;
let isImmersive = false;

function toggleAdminMode(enabled) {
    return readerMeta.toggleAdminMode(enabled);
}

async function renameItem(objId) {
    return renameAdmin.renameItem(objId);
}

async function resetCustomName(objId) {
    return renameAdmin.resetCustomName(objId);
}

// === РќР°СЃС‚СЂРѕР№РєРё (РёР· localStorage) ===
function getUserRole(userIdStr) {
    return readerMeta.getUserRole(userIdStr);
}

// SQLite РІРѕР·РІСЂР°С‰Р°РµС‚ РІСЂРµРјСЏ РІ UTC "YYYY-MM-DD HH:MM:SS". РџСЂРµРІСЂР°С‰Р°РµРј РµРіРѕ РІ РІР°Р»РёРґРЅС‹Р№ ISO 8601 UTC.
function formatDate(dateStr) {
    return readerMeta.formatDate(dateStr);
}

function toggleImmersiveMode(force = null) {
    return readerShellUi.toggleImmersiveMode(force);
}

function toggleQuickSwitcher() {
    return readerShellUi.toggleQuickSwitcher();
}

function renderQuickSwitcherList() {
    return readerShellUi.renderQuickSwitcherList();
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
let settings = { ...defaults };
let readChapters = {};
let stateStore = null;
function fallbackGetLocal(key, defaultVal) {
    try {
        const val = localStorage.getItem(key);
        return val ? JSON.parse(val) : defaultVal;
    } catch (e) {
        return defaultVal;
    }
}
function fallbackSetLocal(key, val) {
    try {
        localStorage.setItem(key, JSON.stringify(val));
    } catch (e) {}
}
function safeGetLocal(key, defaultVal) {
    if (stateStore && typeof stateStore.getLocal === 'function') {
        return stateStore.getLocal(key, defaultVal);
    }
    return fallbackGetLocal(key, defaultVal);
}
function safeSetLocal(key, val) {
    if (stateStore && typeof stateStore.setLocal === 'function') {
        stateStore.setLocal(key, val);
        return;
    }
    fallbackSetLocal(key, val);
}

const urlParams = new URLSearchParams(window.location.search);
const API_URL = urlParams.get('api') || (window.location.hostname.includes('github.io') ? '' : window.location.origin);

// === Baseline Telemetry + API Client ===
const appBootStartedAt = (typeof performance !== 'undefined' && performance.now) ? performance.now() : Date.now();
const readerModules = window.ReaderModules || {};
const fallbackStateStore = {
    getLocal: fallbackGetLocal,
    setLocal: fallbackSetLocal,
    loadSettings: () => {
        const loaded = fallbackGetLocal('reader_settings', { ...defaults }) || { ...defaults };
        const normalized = { ...defaults, ...(loaded || {}) };
        if (!normalized.lineHeight) normalized.lineHeight = 1.8;
        if (!normalized.textAlign) normalized.textAlign = 'left';
        if (normalized.indent === undefined) normalized.indent = true;
        if (normalized.paraSpacing === undefined) normalized.paraSpacing = 20;
        if (normalized.letterSpacing === undefined) normalized.letterSpacing = 0;
        if (normalized.paraIndent === undefined) normalized.paraIndent = 25;
        if (normalized.dimmerValue === undefined) normalized.dimmerValue = 0;
        if (normalized.readingMode === undefined) normalized.readingMode = 'scroll';
        return normalized;
    },
    saveSettings: (nextSettings) => fallbackSetLocal('reader_settings', nextSettings || {}),
    loadReadProgress: () => {
        const loaded = fallbackGetLocal('reader_progress', {});
        return (loaded && typeof loaded === 'object') ? loaded : {};
    },
    saveReadProgress: (nextProgress) => fallbackSetLocal('reader_progress', nextProgress || {}),
    getReadKey: (seriesId, volume, chapter) => `${seriesId}_v${volume}_ch${chapter}`
};
stateStore = (typeof readerModules.createStateStore === 'function')
    ? readerModules.createStateStore({ defaults })
    : fallbackStateStore;
settings = (stateStore && typeof stateStore.loadSettings === 'function')
    ? stateStore.loadSettings()
    : fallbackStateStore.loadSettings();
readChapters = (stateStore && typeof stateStore.loadReadProgress === 'function')
    ? stateStore.loadReadProgress()
    : fallbackStateStore.loadReadProgress();

const fallbackNormalizeMetricEndpoint = (url) => {
    try {
        const parsed = new URL(url, window.location.origin);
        return parsed.pathname || '';
    } catch (e) {
        const raw = String(url || '');
        if (raw.startsWith('/')) return raw.split('?')[0];
        const idx = raw.indexOf('/api/');
        return idx >= 0 ? raw.slice(idx).split('?')[0] : raw.slice(0, 120);
    }
};

const telemetry = (typeof readerModules.createTelemetryManager === 'function')
    ? readerModules.createTelemetryManager({
        appBootStartedAt,
        getApiUrl: () => API_URL,
        getUserId: () => userId,
        getAuthHeader: () => (typeof tg !== 'undefined' && tg.initData) ? ('tma ' + tg.initData) : ''
    })
    : {
        queueMetric: () => {},
        flushMetrics: async () => {},
        markAppReady: () => {},
        startChapterOpenMetric: () => {},
        completeChapterOpenMetric: () => {},
        normalizeMetricEndpoint: fallbackNormalizeMetricEndpoint
    };

const queueMetric = telemetry.queueMetric.bind(telemetry);
const flushMetrics = telemetry.flushMetrics.bind(telemetry);
const markAppReady = telemetry.markAppReady.bind(telemetry);
const startChapterOpenMetric = telemetry.startChapterOpenMetric.bind(telemetry);
const completeChapterOpenMetric = telemetry.completeChapterOpenMetric.bind(telemetry);

const apiFetch = (typeof readerModules.createApiFetch === 'function')
    ? readerModules.createApiFetch({
        getTg: () => tg,
        telemetry
    })
    : async function fallbackApiFetch(url, options = {}) {
        if (typeof navigator !== 'undefined' && !navigator.onLine) {
            throw new Error('Offline');
        }
        options.headers = options.headers || {};
        if (typeof tg !== 'undefined' && tg.initData) {
            options.headers['Authorization'] = 'tma ' + tg.initData;
        }
        return fetch(url, options);
    };

const buildJsonOptions = (method, payload) => ({
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
});

const fallbackReaderApiRequest = (path, options = {}) => apiFetch(`${API_URL}${path}`, options);
const fallbackReaderApi = {
    requestRename: (objId) => fallbackReaderApiRequest('/api/rename/request', buildJsonOptions('POST', { obj_id: objId })),
    resetRename: (objId) => fallbackReaderApiRequest('/api/rename', buildJsonOptions('DELETE', { obj_id: objId })),
    saveProgress: (payload) => fallbackReaderApiRequest('/api/progress', buildJsonOptions('POST', payload)),
    getProgress: (options = {}) => fallbackReaderApiRequest('/api/progress', options),
    getReader: (options = {}) => fallbackReaderApiRequest('/api/reader', options),
    getLikes: (chapterKey) => fallbackReaderApiRequest(`/api/likes?chapter_key=${encodeURIComponent(chapterKey)}`),
    toggleLike: (chapterKey) => fallbackReaderApiRequest('/api/likes', buildJsonOptions('POST', { chapter_key: chapterKey })),
    getComments: (chapterKey) => fallbackReaderApiRequest(`/api/comments?chapter_key=${encodeURIComponent(chapterKey)}`),
    reportComment: (payload) => fallbackReaderApiRequest('/api/comments/report', buildJsonOptions('POST', payload)),
    reactToComment: (commentId, type) => fallbackReaderApiRequest('/api/comments/react', buildJsonOptions('POST', { comment_id: commentId, type })),
    updateComment: (commentId, text) => fallbackReaderApiRequest(`/api/comments/${commentId}`, buildJsonOptions('PUT', { text })),
    createComment: (payload) => fallbackReaderApiRequest('/api/comments', buildJsonOptions('POST', payload)),
    deleteComment: (commentId) => fallbackReaderApiRequest('/api/comments', buildJsonOptions('DELETE', { comment_id: commentId })),
    getReactions: (chapterKey) => fallbackReaderApiRequest(`/api/reactions?chapter_key=${encodeURIComponent(chapterKey)}`),
    setReaction: (chapterKey, reaction) => fallbackReaderApiRequest('/api/reactions', buildJsonOptions('POST', { chapter_key: chapterKey, reaction })),
    updateChapter: (payload) => fallbackReaderApiRequest('/api/chapters', buildJsonOptions('PUT', payload)),
    bulkCreateChapters: (payload) => fallbackReaderApiRequest('/api/chapters/bulk', buildJsonOptions('POST', payload)),
    sortChapters: (payload) => fallbackReaderApiRequest('/api/sort', buildJsonOptions('PUT', payload)),
    submitTypo: (payload) => fallbackReaderApiRequest('/api/typo', buildJsonOptions('POST', payload))
};

const readerApi = (typeof readerModules.createReaderApi === 'function')
    ? readerModules.createReaderApi({ apiUrl: API_URL, apiFetch })
    : fallbackReaderApi;

const fallbackReaderFlow = {
    getScrollKey: () => null,
    saveScrollPosition: () => {},
    restoreScrollPosition: () => {},
    buildSkeletonLoader: () => '<div class="skeleton-loader"></div>',
    initImageFadeIn: () => {},
    applyIframeDarkMode: () => {},
    prefetchNextChapter: () => {},
    initReaderScrollListeners: () => {}
};

const readerFlow = (typeof readerModules.createReaderFlowManager === 'function')
    ? readerModules.createReaderFlowManager({
        getChapterKey,
        getCurrentSeries: () => currentSeries,
        getCurrentVolume: () => currentVolume,
        getCurrentChapters: () => currentChapters,
        getCurrentChapterIdx: () => currentChapterIdx,
        getServerBookmarks: () => serverBookmarks,
        getSettings: () => settings,
        getUserId: () => userId,
        getApiUrl: () => API_URL,
        getProgressSyncTimer: () => _progressSyncTimer,
        setProgressSyncTimer: (value) => {
            _progressSyncTimer = value;
        },
        getScrollResizeObserver: () => _scrollResizeObserver,
        setScrollResizeObserver: (value) => {
            _scrollResizeObserver = value;
        },
        getScrollResizeTimeout: () => _scrollResizeTimeout,
        setScrollResizeTimeout: (value) => {
            _scrollResizeTimeout = value;
        },
        getPrefetchedChapter: () => prefetchedChapter,
        setPrefetchedChapter: (value) => {
            prefetchedChapter = value;
        },
        getPrefetchingIdx: () => _prefetchingIdx,
        setPrefetchingIdx: (value) => {
            _prefetchingIdx = value;
        },
        getReaderScrollListenerBound: () => _readerScrollListenerBound,
        setReaderScrollListenerBound: (value) => {
            _readerScrollListenerBound = value;
        },
        getScrollSaveTimer: () => scrollSaveTimer,
        setScrollSaveTimer: (value) => {
            scrollSaveTimer = value;
        },
        safeGetLocal,
        safeSetLocal,
        saveLastRead,
        readerApi,
        renderTelegraphContent,
        preloadImagesFromHtml,
        toggleFab
    })
    : fallbackReaderFlow;

const fallbackMarkupUtils = {
    escapeHtml(str) {
        if (!str) return '';
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    },
    applyMarkup(text) {
        if (!text) return '';
        let html = fallbackMarkupUtils.escapeHtml(text);
        html = html.replace(/\[b\]([\s\S]+?)\[\/b\]/g, '<strong>$1</strong>');
        html = html.replace(/\[i\]([\s\S]+?)\[\/i\]/g, '<em>$1</em>');
        html = html.replace(/\[s\]([\s\S]+?)\[\/s\]/g, '<del>$1</del>');
        html = html.replace(/\|\|([\s\S]+?)\|\|/g, (match, content) => (
            `<span class="comment-spoiler" onclick="this.classList.toggle('revealed'); event.stopPropagation();">${content}</span>`
        ));
        html = html.replace(/\[quote\]([\s\S]+?)\[\/quote\]/g, '<blockquote class="comment-quote">$1</blockquote>');
        return html;
    }
};

const markupUtils = (typeof readerModules.createMarkupUtils === 'function')
    ? readerModules.createMarkupUtils()
    : fallbackMarkupUtils;

const fallbackCommentsView = {
    renderComments: () => {},
    sortComments: () => {},
    editComment: () => {},
    cancelEdit: () => {},
    updateCommentPreview: () => {},
    insertFormatting: () => {},
    getCurrentCommentSort: () => currentCommentSort
};

const commentsView = (typeof readerModules.createCommentsView === 'function')
    ? readerModules.createCommentsView({
        labels: {
            save: '\u0421\u043e\u0445\u0440\u0430\u043d\u0438\u0442\u044c',
            cancel: '\u041e\u0442\u043c\u0435\u043d\u0430',
            preview: '\u041f\u0440\u0435\u0434\u043f\u0440\u043e\u0441\u043c\u043e\u0442\u0440:',
            empty: '\u041f\u043e\u043a\u0430 \u043a\u043e\u043c\u043c\u0435\u043d\u0442\u0430\u0440\u0438\u0435\u0432 \u043d\u0435\u0442. \u0411\u0443\u0434\u044c\u0442\u0435 \u043f\u0435\u0440\u0432\u044b\u043c! \u2728',
            likeTitle: '\u041d\u0440\u0430\u0432\u0438\u0442\u0441\u044f',
            delete: '\u0423\u0434\u0430\u043b\u0438\u0442\u044c',
            edit: '\u0420\u0435\u0434.',
            reply: '\u041e\u0442\u0432\u0435\u0442\u0438\u0442\u044c',
            report: '\u041f\u043e\u0436\u0430\u043b\u043e\u0432\u0430\u0442\u044c\u0441\u044f'
        },
        getAllCommentsCache: () => allCommentsCache,
        getCurrentCommentSort: () => currentCommentSort,
        setCurrentCommentSort: (value) => {
            currentCommentSort = value;
        },
        getActiveCommentEditId: () => activeCommentEditId,
        setActiveCommentEditId: (value) => {
            activeCommentEditId = value;
        },
        getUserId: () => userId,
        getApiUrl: () => API_URL,
        getIsAdminMode: () => isAdminMode,
        getUserRole,
        formatDate,
        escapeHtml,
        applyMarkup
    })
    : fallbackCommentsView;

const fallbackCommentsController = {
    setReply: () => {},
    cancelReply: () => {},
    loadComments: async () => {},
    reportComment: () => {},
    reactToComment: async () => {},
    saveCommentEdit: async () => {},
    postComment: async () => {},
    deleteComment: async () => {}
};

const commentsController = (typeof readerModules.createCommentsController === 'function')
    ? readerModules.createCommentsController({
        getApiUrl: () => API_URL,
        getUserId: () => userId,
        getChapterKey,
        readerApi,
        tg,
        showToast,
        setAllCommentsCache: (comments) => {
            allCommentsCache = comments;
        },
        getActiveCommentEditId: () => activeCommentEditId,
        setActiveCommentEditId: (value) => {
            activeCommentEditId = value;
        },
        renderComments: (comments) => commentsView.renderComments(comments)
    })
    : fallbackCommentsController;

const fallbackFeedbackUi = {
    haptic: () => {},
    showToast: () => {}
};

const feedbackUi = (typeof readerModules.createFeedbackUiManager === 'function')
    ? readerModules.createFeedbackUiManager({
        getDocument: () => document,
        getTelegramWebApp: () => tg
    })
    : fallbackFeedbackUi;

const fallbackReaderShellUi = {
    openChannel: () => {},
    toggleImmersiveMode: () => {},
    toggleQuickSwitcher: () => {},
    renderQuickSwitcherList: () => {},
    getSeriesCover: () => '<div class="series-icon">\uD83D\uDCD6</div>'
};

const readerShellUi = (typeof readerModules.createReaderShellUiManager === 'function')
    ? readerModules.createReaderShellUiManager({
        getTelegramWebApp: () => tg,
        getIsImmersive: () => isImmersive,
        setIsImmersive: (value) => {
            isImmersive = !!value;
        },
        getCurrentChapters: () => currentChapters,
        getCurrentChapterIdx: () => currentChapterIdx,
        getAllData: () => allData,
        toggleFab,
        haptic
    })
    : fallbackReaderShellUi;

const fallbackRenameAdmin = {
    renameItem: async () => {},
    resetCustomName: async () => {}
};

const renameAdmin = (typeof readerModules.createRenameAdminManager === 'function')
    ? readerModules.createRenameAdminManager({
        getApiUrl: () => API_URL,
        getAllData: () => allData,
        getTelegramWebApp: () => tg,
        readerApi,
        showToast,
        loadData,
        confirmFn: (message) => confirm(message)
    })
    : fallbackRenameAdmin;

const fallbackReaderMeta = {
    toggleAdminMode: () => {},
    getUserRole: () => null,
    formatDate: (value) => value
};

const readerMeta = (typeof readerModules.createReaderMetaManager === 'function')
    ? readerModules.createReaderMetaManager({
        getDocument: () => document,
        getAdminIds: () => adminIds,
        setIsAdminMode: (value) => {
            isAdminMode = !!value;
        },
        renderSeriesList,
        renderContinueReading,
        renderVolumeTabs,
        renderChaptersList
    })
    : fallbackReaderMeta;

const fallbackLikesUi = {
    spawnFloatingEmoji: () => {},
    spawnFloatingHearts: () => {},
    updateLikeUI: () => {}
};

const likesUi = (typeof readerModules.createLikesUiManager === 'function')
    ? readerModules.createLikesUiManager({
        getDocument: () => document
    })
    : fallbackLikesUi;

const fallbackSocialInteractions = {
    renderReactions: () => {},
    loadLikes: async () => {},
    toggleLike: async () => {},
    loadReactions: async () => {},
    toggleReaction: async () => {}
};

const socialInteractions = (typeof readerModules.createSocialInteractionsManager === 'function')
    ? readerModules.createSocialInteractionsManager({
        getApiUrl: () => API_URL,
        getUserId: () => userId,
        getChapterKey,
        readerApi,
        updateLikeUI,
        spawnFloatingEmoji,
        haptic,
        showToast,
        onLikeError: (error) => {
            console.warn('Like interaction error:', error);
        },
        onReactionError: (error) => {
            console.warn('Reaction interaction error:', error);
        }
    })
    : fallbackSocialInteractions;

const fallbackChapterAdmin = {
    openEditUrlModal: () => {},
    closeEditUrlModal: () => {},
    saveEditUrl: async () => {},
    openBulkModal: () => {},
    closeBulkModal: () => {},
    executeBulkUpload: async () => {},
    cleanupChapterDnD: () => {},
    initChapterDnD: () => {},
    reorderChapters: async () => {}
};

const chapterAdmin = (typeof readerModules.createChapterAdminManager === 'function')
    ? readerModules.createChapterAdminManager({
        getApiUrl: () => API_URL,
        getCurrentSeries: () => currentSeries,
        getCurrentVolume: () => currentVolume,
        getCurrentChapters: () => currentChapters,
        readerApi,
        renderChaptersList,
        loadData,
        showToast
    })
    : fallbackChapterAdmin;

const fallbackReaderUi = {
    initLightbox: () => {},
    openLightbox: () => {},
    closeLightbox: () => {},
    lightboxNavigate: () => {},
    updateLightboxNav: () => {},
    initLightboxInteractions: () => {},
    buildToC: () => {},
    highlightToCItem: () => {},
    scrollToHeading: () => {},
    toggleToC: () => {},
    toggleAutoscrollSetting: () => {},
    isAutoscrollEnabled: () => false,
    setAutoscrollSpeed: () => {},
    toggleAutoscroll: () => {},
    startAutoscroll: () => {},
    stopAutoscroll: () => {},
    initAutoscrollInteractions: () => {},
    initGestures: () => {}
};

const readerUi = (typeof readerModules.createReaderUiManager === 'function')
    ? readerModules.createReaderUiManager({
        getCurrentChapters: () => currentChapters,
        getCurrentChapterIdx: () => currentChapterIdx,
        getCurrentSeries: () => currentSeries,
        getCurrentVolume: () => currentVolume,
        getReadChapters: () => readChapters,
        navigateChapter,
        backFromReader,
        haptic,
        toggleFab
    })
    : fallbackReaderUi;

const fallbackSettingsUi = {
    setFontSize: () => {},
    setTheme: () => {},
    setTextWidth: () => {},
    setFont: () => {},
    setLineHeight: () => {},
    setLetterSpacing: () => {},
    setParaIndent: () => {},
    setTextAlign: () => {},
    setIndent: () => {},
    toggleSettings: () => {},
    showSettingsTab: () => {},
    updateSettingsUI: () => {},
    setDimmer: () => {},
    applySettings: () => {},
    restoreSettings: () => {}
};

const settingsUi = (typeof readerModules.createSettingsUiManager === 'function')
    ? readerModules.createSettingsUiManager({
        getSettings: () => settings,
        persistSettings: () => saveSettings(),
        applyIframeDarkMode,
        haptic,
        tg
    })
    : fallbackSettingsUi;

const fallbackProgressTracker = {
    saveLastRead: () => {
        if (!currentSeries || !currentVolume) return;
        const chapter = currentChapters[currentChapterIdx];
        if (!chapter) return;
        const last = {
            seriesId: currentSeries.id,
            volume: currentVolume.volume,
            chapterIdx: currentChapterIdx,
            chapter: chapter.chapter,
            ts: Date.now()
        };
        const all = safeGetLocal('reader_last_read', {});
        all[currentSeries.id] = last;
        safeSetLocal('reader_last_read', all);
    },
    getLastRead: (seriesId) => {
        const all = safeGetLocal('reader_last_read', {});
        const local = all[seriesId];
        const serverBm = serverBookmarks.find((item) => String(item.series_id) === String(seriesId));

        if (serverBm && local) {
            const serverTs = new Date(serverBm.updated_at + (serverBm.updated_at.includes('Z') ? '' : ' UTC')).getTime();
            const localTs = local.ts || 0;
            if (serverTs > localTs) {
                return {
                    seriesId: seriesId,
                    volume: serverBm.volume_id,
                    chapter: serverBm.chapter_key,
                    scroll: serverBm.scroll_pos,
                    isServer: true
                };
            }
            return local;
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
    },
    markAsRead: (seriesId, vol, chapter) => {
        readChapters[getReadKey(seriesId, vol, chapter)] = Date.now();
        if (stateStore && typeof stateStore.saveReadProgress === 'function') {
            stateStore.saveReadProgress(readChapters);
            return;
        }
        safeSetLocal('reader_progress', readChapters);
    },
    renderContinueReading: () => {
        const container = document.getElementById('continue-reading-container');
        if (!container) return;

        let latestBm = null;
        if (serverBookmarks.length > 0) {
            latestBm = serverBookmarks[0];
        } else {
            const allLocal = safeGetLocal('reader_last_read', {});
            let latestLocal = null;
            let maxTs = 0;
            for (const seriesId in allLocal) {
                if (allLocal[seriesId].ts > maxTs) {
                    maxTs = allLocal[seriesId].ts;
                    latestLocal = allLocal[seriesId];
                }
            }
            if (latestLocal) {
                latestBm = {
                    series_id: latestLocal.seriesId,
                    volume_id: latestLocal.volume,
                    chapter_key: latestLocal.chapter
                };
            }
        }

        if (!latestBm || !allData.series) {
            container.style.display = 'none';
            return;
        }

        const series = allData.series.find((item) => String(item.id) === String(latestBm.series_id));
        if (!series) {
            container.style.display = 'none';
            return;
        }

        const volume = (series.volumes || []).find((item) => String(item.volume) === String(latestBm.volume_id));
        let chapterTitle = `Р“Р»Р°РІР° ${latestBm.chapter_key}`;
        if (volume) {
            const chapterAttr = (volume.chapters || []).find((item) => String(item.chapter) === String(latestBm.chapter_key));
            if (chapterAttr && chapterAttr.custom_name) chapterTitle = chapterAttr.custom_name;
        }
        const volumeTitle = volume && volume.custom_name ? volume.custom_name : `РўРѕРј ${latestBm.volume_id}`;
        const safeSeriesId = String(series.id).replace(/\\/g, '\\\\').replace(/'/g, "\\'");

        container.style.display = 'block';
        container.innerHTML = `
            <div class="continue-reading-card" onclick="selectSeries('${safeSeriesId}')">
                <div class="continue-reading-icon">рџ”–</div>
                <div class="continue-reading-info">
                    <div class="continue-reading-label">РџСЂРѕРґРѕР»Р¶РёС‚СЊ С‡С‚РµРЅРёРµ</div>
                    <h3 class="continue-reading-title">${escapeHtml(series.title)}</h3>
                    <p class="continue-reading-chapter">${escapeHtml(volumeTitle)}, ${escapeHtml(chapterTitle)}</p>
                </div>
                <div class="continue-reading-arrow">в†’</div>
            </div>
        `;
    }
};

const progressTracker = (typeof readerModules.createProgressTrackerManager === 'function')
    ? readerModules.createProgressTrackerManager({
        getCurrentSeries: () => currentSeries,
        getCurrentVolume: () => currentVolume,
        getCurrentChapterIdx: () => currentChapterIdx,
        getCurrentChapters: () => currentChapters,
        getServerBookmarks: () => serverBookmarks,
        getAllData: () => allData,
        safeGetLocal,
        safeSetLocal,
        getReadChapters: () => readChapters,
        setReadChapters: (value) => {
            readChapters = value || {};
        },
        getReadKey,
        saveReadProgress: (progressMap) => {
            if (stateStore && typeof stateStore.saveReadProgress === 'function') {
                stateStore.saveReadProgress(progressMap || {});
                return;
            }
            safeSetLocal('reader_progress', progressMap || {});
        },
        escapeHtml
    })
    : fallbackProgressTracker;

const fallbackSeriesCatalog = {
    renderSeriesList: () => {},
    selectSeries: () => {},
    renderVolumeTabs: () => {},
    selectVolume: () => {},
    renderChaptersList: () => {}
};

const seriesCatalog = (typeof readerModules.createSeriesCatalogManager === 'function')
    ? readerModules.createSeriesCatalogManager({
        getAllData: () => allData,
        getCurrentSeries: () => currentSeries,
        setCurrentSeries: (value) => {
            currentSeries = value;
        },
        getCurrentVolume: () => currentVolume,
        setCurrentVolume: (value) => {
            currentVolume = value;
        },
        setCurrentChapters: (value) => {
            currentChapters = value || [];
        },
        getIsAdminMode: () => isAdminMode,
        getApiUrl: () => API_URL,
        getLastRead,
        isRead,
        escapeHtml,
        renameItem,
        resetCustomName,
        showScreen,
        openEditUrlModal,
        openBulkModal,
        initChapterDnD,
        cleanupChapterDnD,
        openChapter,
        showEmptyState
    })
    : fallbackSeriesCatalog;

const fallbackReaderBootstrap = {
    loadData: async () => {
        console.warn('Reader bootstrap module is unavailable');
    },
    showEmptyState: () => {
        const list = document.getElementById('series-list');
        if (!list) return;
        list.innerHTML = `
            <div class="empty-state">
                <div class="empty-icon">рџ“љ</div>
                <h3>Р‘РёР±Р»РёРѕС‚РµРєР° РїСѓСЃС‚Р°</h3>
                <p>Р”Р°РЅРЅС‹Рµ РµС‰С‘ РЅРµ Р·Р°РіСЂСѓР¶РµРЅС‹.</p>
            </div>
        `;
    },
    handleStartParam: () => {}
};

const readerBootstrap = (typeof readerModules.createReaderBootstrapManager === 'function')
    ? readerModules.createReaderBootstrapManager({
        getApiUrl: () => API_URL,
        getUserId: () => userId,
        getUrlParams: () => urlParams,
        getTg: () => tg,
        readerApi,
        setServerBookmarks: (value) => {
            serverBookmarks = Array.isArray(value) ? value : [];
        },
        setAllData: (value) => {
            allData = value || { series: [] };
        },
        getAllData: () => allData,
        setAdminIds: (value) => {
            adminIds = Array.isArray(value) ? value : [];
        },
        renderSeriesList,
        renderContinueReading,
        markAppReady,
        setCurrentSeries: (value) => {
            currentSeries = value;
        },
        setCurrentVolume: (value) => {
            currentVolume = value;
        },
        setCurrentChapters: (value) => {
            currentChapters = value || [];
        },
        openChapter
    })
    : fallbackReaderBootstrap;

const fallbackProgressBarManager = {
    getElement: () => null,
    setWidth: () => {},
    initProgressBar: () => {},
    updateProgressBar: () => {}
};

const progressBarManager = (typeof readerModules.createProgressBarManager === 'function')
    ? readerModules.createProgressBarManager({
        getDocument: () => document
    })
    : fallbackProgressBarManager;

const fallbackChapterReader = {
    openChapter: () => {},
    loadChapterContent: () => {},
    renderLoadedContent: () => {},
    navigateChapter: () => {},
    backFromReader: () => {},
    updateNavButtons: () => {},
    preloadImagesFromHtml: () => {},
    renderTelegraphContent: () => ''
};

const chapterReader = (typeof readerModules.createChapterReaderManager === 'function')
    ? readerModules.createChapterReaderManager({
        getCurrentChapters: () => currentChapters,
        getCurrentChapterIdx: () => currentChapterIdx,
        setCurrentChapterIdx: (value) => {
            currentChapterIdx = value;
        },
        getCurrentSeries: () => currentSeries,
        getCurrentVolume: () => currentVolume,
        getIsAdminMode: () => isAdminMode,
        getApiUrl: () => API_URL,
        getPrefetchedChapter: () => prefetchedChapter,
        setPrefetchedChapter: (value) => {
            prefetchedChapter = value || { idx: -1, html: null };
        },
        getChapterAbortController: () => _chapterAbortController,
        setChapterAbortController: (value) => {
            _chapterAbortController = value || null;
        },
        startChapterOpenMetric,
        completeChapterOpenMetric,
        markAsRead,
        showScreen,
        loadLikes,
        loadReactions,
        loadComments,
        initProgressBar,
        setProgressBarWidth: (value) => progressBarManager.setWidth(value),
        initLightbox,
        buildToC,
        initImageFadeIn,
        applyIframeDarkMode,
        restoreScrollPosition,
        haptic,
        saveScrollPosition,
        renderChaptersList,
        openEditUrlModal
    })
    : fallbackChapterReader;

const fallbackLibraryView = {
    startReadingStatsTicker: () => {},
    stopReadingStatsTicker: () => {},
    updateLibraryStats: () => {},
    renderLibraryTab: () => {}
};

const libraryView = (typeof readerModules.createLibraryViewManager === 'function')
    ? readerModules.createLibraryViewManager({
        getAllData: () => allData,
        getServerBookmarks: () => serverBookmarks,
        isRead,
        safeGetLocal,
        safeSetLocal,
        escapeHtml
    })
    : fallbackLibraryView;

const fallbackScreenNavigation = {
    showScreen: () => {},
    toggleFab: () => {},
    fabAction: () => {},
    toggleAdminMenu: () => {},
    closeAdminMenu: () => {},
    renameChapterCurrent: () => {},
    initFabOutsideClickHandler: () => {}
};

const screenNavigation = (typeof readerModules.createScreenNavigationManager === 'function')
    ? readerModules.createScreenNavigationManager({
        getIsAdminMode: () => isAdminMode,
        getProgressBarElement: () => progressBarManager.getElement(),
        saveScrollPosition,
        renderLibraryTab,
        updateLibraryStats,
        haptic,
        toggleToC,
        toggleAutoscrollSetting,
        isAutoscrollEnabled,
        showToast,
        renameItem,
        getCurrentChapters: () => currentChapters,
        getCurrentChapterIdx: () => currentChapterIdx,
        getCurrentSeries: () => currentSeries,
        getCurrentVolume: () => currentVolume
    })
    : fallbackScreenNavigation;

const fallbackReaderContentInteractions = {
    getReaderTopBar: () => null,
    initReaderContentInteractions: () => {}
};

const readerContentInteractions = (typeof readerModules.createReaderContentInteractionsManager === 'function')
    ? readerModules.createReaderContentInteractionsManager({
        updateProgressBar,
        prefetchNextChapter,
        saveScrollPosition,
        haptic,
        toggleFab
    })
    : fallbackReaderContentInteractions;

const fallbackTypoReporter = {
    initTypoReporter: () => {},
    handleSelection: () => {},
    showTypoModal: () => {},
    closeTypoModal: () => {},
    submitTypoReport: async () => {}
};

const typoReporter = (typeof readerModules.createTypoReporterManager === 'function')
    ? readerModules.createTypoReporterManager({
        getApiUrl: () => API_URL,
        getCurrentChapters: () => currentChapters,
        getCurrentChapterIdx: () => currentChapterIdx,
        getCurrentSeries: () => currentSeries,
        getCurrentVolume: () => currentVolume,
        readerApi,
        showToast,
        getTelegramWebApp: () => tg
    })
    : fallbackTypoReporter;

const fallbackAppLifecycle = {
    bindLifecycleEvents: () => {},
    bootstrapApp: () => {},
    initBootstrap: () => {}
};

const appLifecycle = (typeof readerModules.createAppLifecycleManager === 'function')
    ? readerModules.createAppLifecycleManager({
        getDocument: () => document,
        saveScrollPosition,
        flushMetrics,
        restoreSettings,
        loadData,
        initTypoReporter,
        initFabOutsideClickHandler: () => screenNavigation.initFabOutsideClickHandler(),
        initGestures,
        initReaderScrollListeners,
        initReaderContentInteractions,
        initLightboxInteractions,
        initAutoscrollInteractions,
        startReadingStatsTicker: () => libraryView.startReadingStatsTicker()
    })
    : fallbackAppLifecycle;


function getChapterKey() {
    if (!currentSeries || !currentVolume || !currentChapters[currentChapterIdx]) return '';
    return `${currentSeries.id}_v${currentVolume.volume}_ch${currentChapters[currentChapterIdx].chapter}`;
}

function getScrollKey() {
    return readerFlow.getScrollKey();
}

let _progressSyncTimer = null;
let _readerScrollListenerBound = false;
let scrollSaveTimer = null;

function saveScrollPosition() {
    return readerFlow.saveScrollPosition();
}

let _scrollResizeObserver = null; // Р•РґРёРЅСЃС‚РІРµРЅРЅС‹Р№ ResizeObserver РґР»СЏ СЃРєСЂРѕР»Р»Р°
let _scrollResizeTimeout = null; // РўР°Р№РјР°СѓС‚ РґР»СЏ РѕС‡РёСЃС‚РєРё observer

function restoreScrollPosition() {
    return readerFlow.restoreScrollPosition();
}

function saveLastRead() {
    return progressTracker.saveLastRead();
}

function getLastRead(seriesId) {
    return progressTracker.getLastRead(seriesId);
}

// === РџСЂРѕРіСЂРµСЃСЃ-Р±Р°СЂ С‡С‚РµРЅРёСЏ ===

function initProgressBar() {
    return progressBarManager.initProgressBar();
}

function updateProgressBar(el) {
    return progressBarManager.updateProgressBar(el);
}

// ==========================================================================
// Р—РђР“Р РЈР—РљРђ Р”РђРќРќР«РҐ
// ==========================================================================

let serverBookmarks = []; // РҐСЂР°РЅРёС‚ Р·Р°РіСЂСѓР¶РµРЅРЅС‹Рµ Р·Р°РєР»Р°РґРєРё

async function loadData() {
    return readerBootstrap.loadData();
}

function showEmptyState() {
    return readerBootstrap.showEmptyState();
}

function handleStartParam() {
    return readerBootstrap.handleStartParam();
}

function renderSeriesList() {
    return seriesCatalog.renderSeriesList();
}

function selectSeries(seriesId) {
    return seriesCatalog.selectSeries(seriesId);
}

function renderVolumeTabs() {
    return seriesCatalog.renderVolumeTabs();
}

function selectVolume(volNum) {
    return seriesCatalog.selectVolume(volNum);
}

function renderChaptersList() {
    return seriesCatalog.renderChaptersList();
}

function openChapter(idx, usePrefetch = false) {
    return chapterReader.openChapter(idx, usePrefetch);
}

function loadChapterContent(chapter, usePrefetch = false) {
    return chapterReader.loadChapterContent(chapter, usePrefetch);
}

function renderLoadedContent(container, html, chapter) {
    return chapterReader.renderLoadedContent(container, html, chapter);
}

function buildSkeletonLoader() {
    return readerFlow.buildSkeletonLoader();
}

// в… Image Fade-in (РїСѓРЅРєС‚ 6)
function initImageFadeIn(container) {
    return readerFlow.initImageFadeIn(container);
}

// в… Smart Dark Mode РґР»СЏ Teletype iframes (РїСѓРЅРєС‚ 7) - РћС‚РєР»СЋС‡РµРЅРѕ (РІС‹Р·С‹РІР°Р»Рѕ РЅРµРіР°С‚РёРІ)
function applyIframeDarkMode() {
    return readerFlow.applyIframeDarkMode();
}

// в… Silent Prefetch СЃР»РµРґСѓСЋС‰РµР№ РіР»Р°РІС‹ (РїСѓРЅРєС‚ 4)
function prefetchNextChapter() {
    return readerFlow.prefetchNextChapter();
}

// Helper for pre-loading images into browser cache
function preloadImagesFromHtml(html) {
    return chapterReader.preloadImagesFromHtml(html);
}

function renderTelegraphContent(nodes) {
    return chapterReader.renderTelegraphContent(nodes);
}

function navigateChapter(delta) {
    return chapterReader.navigateChapter(delta);
}

function backFromReader() {
    return chapterReader.backFromReader();
}

function updateNavButtons() {
    return chapterReader.updateNavButtons();
}

function spawnFloatingEmoji(emoji, targetEl) {
    return likesUi.spawnFloatingEmoji(emoji, targetEl);
}

function spawnFloatingHearts() {
    return likesUi.spawnFloatingHearts();
}

// duplicate removed

async function loadLikes() {
    return socialInteractions.loadLikes();
}

async function toggleLike() {
    return socialInteractions.toggleLike();
}

function updateLikeUI(count, liked) {
    return likesUi.updateLikeUI(count, liked);
}

// ==========================================================================
// РљРћРњРњР•РќРўРђР РР + Р Р•РђРљР¦РР (Modules)
// ==========================================================================

function setReply(id, name) {
    return commentsController.setReply(id, name);
}

function cancelReply() {
    return commentsController.cancelReply();
}

async function loadComments() {
    return commentsController.loadComments();
}

function renderComments(comments) {
    allCommentsCache = Array.isArray(comments) ? comments : [];
    return commentsView.renderComments(allCommentsCache);
}

function reportComment(id) {
    return commentsController.reportComment(id);
}

async function reactToComment(commentId, type) {
    return commentsController.reactToComment(commentId, type);
}

function sortComments(type) {
    return commentsView.sortComments(type);
}

function editComment(id) {
    return commentsView.editComment(id);
}

function cancelEdit(id) {
    return commentsView.cancelEdit(id);
}

async function saveCommentEdit(id) {
    return commentsController.saveCommentEdit(id);
}

function updateCommentPreview() {
    return commentsView.updateCommentPreview();
}

function insertFormatting(start, end) {
    return commentsView.insertFormatting(start, end);
}

async function postComment() {
    return commentsController.postComment();
}

async function deleteComment(commentId) {
    return commentsController.deleteComment(commentId);
}

function escapeHtml(str) {
    return markupUtils.escapeHtml(str);
}

function applyMarkup(text) {
    return markupUtils.applyMarkup(text);
}

async function loadReactions() {
    return socialInteractions.loadReactions();
}

function renderReactions(data) {
    return socialInteractions.renderReactions(data);
}

async function toggleReaction(type) {
    return socialInteractions.toggleReaction(type);
}

// ==========================================================================
// РќРђР’РР“РђР¦РРЇ Р­РљР РђРќРћР’
// ==========================================================================

function showScreen(name) {
    return screenNavigation.showScreen(name);
}

// ==========================================================================
// РџР РћР“Р Р•РЎРЎ Р§РўР•РќРРЇ
// ==========================================================================

function getReadKey(seriesId, vol, chapter) {
    if (stateStore && typeof stateStore.getReadKey === 'function') {
        return stateStore.getReadKey(seriesId, vol, chapter);
    }
    return `${seriesId}_v${vol}_ch${chapter}`;
}

function isRead(seriesId, vol, chapter) {
    return !!readChapters[getReadKey(seriesId, vol, chapter)];
}

function markAsRead(seriesId, vol, chapter) {
    return progressTracker.markAsRead(seriesId, vol, chapter);
}

function setFontSize(size) {
    return settingsUi.setFontSize(size);
}

function setTheme(theme) {
    return settingsUi.setTheme(theme);
}

function setTextWidth(width) {
    return settingsUi.setTextWidth(width);
}

function setFont(font) {
    return settingsUi.setFont(font);
}

function setLineHeight(lh) {
    return settingsUi.setLineHeight(lh);
}

function setLetterSpacing(ls) {
    return settingsUi.setLetterSpacing(ls);
}

function setParaIndent(px) {
    return settingsUi.setParaIndent(px);
}

function setTextAlign(align) {
    return settingsUi.setTextAlign(align);
}

function setIndent(enabled) {
    return settingsUi.setIndent(enabled);
}

// ==========================================================================
// РќРђРЎРўР РћР™РљР
// ==========================================================================

function toggleSettings() {
    return settingsUi.toggleSettings();
}

function showSettingsTab(tabName) {
    return settingsUi.showSettingsTab(tabName);
}

function updateSettingsUI() {
    return settingsUi.updateSettingsUI();
}

function setDimmer(val) {
    return settingsUi.setDimmer(val);
}

function applySettings() {
    return settingsUi.applySettings();
}

function saveSettings() {

    if (stateStore && typeof stateStore.saveSettings === 'function') {
        stateStore.saveSettings(settings);
        return;
    }
    safeSetLocal('reader_settings', settings);
}

function restoreSettings() {
    return settingsUi.restoreSettings();
}

// ==========================================================================
// РЎРћР‘Р«РўРРЇ РЎРљР РћР›Р›Рђ (Р°РІС‚РѕСЃРѕС…СЂР°РЅРµРЅРёРµ + РїСЂРѕРіСЂРµСЃСЃ-Р±Р°СЂ)
// ==========================================================================

function getReaderTopBar() {
    return readerContentInteractions.getReaderTopBar();
}

function initReaderContentInteractions() {
    return readerContentInteractions.initReaderContentInteractions();
}
function initLifecycleEvents() {
    return appLifecycle.bindLifecycleEvents();
}

// ==========================================================================
// Р›РђР™РљР Р РљРћРњРњР•РќРўРђР РР (SOCIAL) & РџР РћР”РћР›Р–РРўР¬ Р§РўР•РќРР•
// ==========================================================================

function renderContinueReading() {
    return progressTracker.renderContinueReading();
}

function updateLibraryStats() {
    return libraryView.updateLibraryStats();
}

function renderLibraryTab() {
    return libraryView.renderLibraryTab();
}


// ==========================================================================
// LIGHTBOX + TOC + AUTOSCROLL (Modules)
// ==========================================================================

function initLightbox() {
    return readerUi.initLightbox();
}

function openLightbox(idx) {
    return readerUi.openLightbox(idx);
}

function closeLightbox() {
    return readerUi.closeLightbox();
}

function lightboxNavigate(delta) {
    return readerUi.lightboxNavigate(delta);
}

function updateLightboxNav() {
    return readerUi.updateLightboxNav();
}

function initLightboxInteractions() {
    return readerUi.initLightboxInteractions();
}

function buildToC() {
    return readerUi.buildToC();
}

function highlightToCItem(idx) {
    return readerUi.highlightToCItem(idx);
}

function scrollToHeading(idx) {
    return readerUi.scrollToHeading(idx);
}

function toggleToC() {
    return readerUi.toggleToC();
}

function toggleAutoscrollSetting(enabled) {
    return readerUi.toggleAutoscrollSetting(enabled);
}

function isAutoscrollEnabled() {
    return readerUi.isAutoscrollEnabled();
}

function setAutoscrollSpeed(val) {
    return readerUi.setAutoscrollSpeed(val);
}

function toggleAutoscroll() {
    return readerUi.toggleAutoscroll();
}

function startAutoscroll() {
    return readerUi.startAutoscroll();
}

function stopAutoscroll() {
    return readerUi.stopAutoscroll();
}

function initAutoscrollInteractions() {
    return readerUi.initAutoscrollInteractions();
}
// ==========================================================================
// EDIT URL MODAL + BULK + DND (Admin Modules)
// ==========================================================================

function openEditUrlModal(chIdx) {
    return chapterAdmin.openEditUrlModal(chIdx);
}

function closeEditUrlModal() {
    return chapterAdmin.closeEditUrlModal();
}

async function saveEditUrl() {
    return chapterAdmin.saveEditUrl();
}

function openBulkModal() {
    return chapterAdmin.openBulkModal();
}

function closeBulkModal() {
    return chapterAdmin.closeBulkModal();
}

async function executeBulkUpload() {
    return chapterAdmin.executeBulkUpload();
}

function cleanupChapterDnD() {
    return chapterAdmin.cleanupChapterDnD();
}

function initChapterDnD() {
    return chapterAdmin.initChapterDnD();
}

async function reorderChapters(fromIdx, toIdx) {
    return chapterAdmin.reorderChapters(fromIdx, toIdx);
}

// ==========================================================================
// COVER IMAGES (Batch 3)
// ==========================================================================

function getSeriesCover(series) {
    return readerShellUi.getSeriesCover(series);
}


// ==========================================================================
// Р Р•РџРћР Рў РћРџР•Р§РђРўРћРљ (TYPO REPORTER)
// ==========================================================================

function initTypoReporter() {
    return typoReporter.initTypoReporter();
}

function handleSelection() {
    return typoReporter.handleSelection();
}

function showTypoModal() {
    return typoReporter.showTypoModal();
}

function closeTypoModal() {
    return typoReporter.closeTypoModal();
}

async function submitTypoReport() {
    return typoReporter.submitTypoReport();
}

// ==========================================================================
// в… HAPTIC FEEDBACK HELPER (РїСѓРЅРєС‚ 8)
// ==========================================================================

function haptic(style = 'light') {
    return feedbackUi.haptic(style);
}

// === Custom Toasts ===
function showToast(message, type = 'info') {
    return feedbackUi.showToast(message, type);
}

// === Fab Menu ===
function toggleFab() {
    return screenNavigation.toggleFab();
}

function fabAction(action) {
    return screenNavigation.fabAction(action);
}

// ==========================================================================
// ADMIN FLOATING MENU (Phase 4)
// ==========================================================================

function toggleAdminMenu() {
    return screenNavigation.toggleAdminMenu();
}

function closeAdminMenu() {
    return screenNavigation.closeAdminMenu();
}

function renameChapterCurrent() {
    return screenNavigation.renameChapterCurrent();
}

// === Gestures: Swipe Back & Pull to Next ===
function initGestures() {
    return readerUi.initGestures();
}
function initReaderScrollListeners() {
    return readerFlow.initReaderScrollListeners();
}

function bootstrapApp() {
    return appLifecycle.bootstrapApp();
}

initLifecycleEvents();
appLifecycle.initBootstrap();

