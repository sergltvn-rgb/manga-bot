(function initReaderShellUiModule(global) {
    const root = global.ReaderModules = global.ReaderModules || {};

    function createReaderShellUiManager(config) {
        const doc = global.document;

        const getTelegramWebApp = (config && config.getTelegramWebApp)
            ? config.getTelegramWebApp
            : (() => (global.Telegram && global.Telegram.WebApp ? global.Telegram.WebApp : null));

        const getIsImmersive = (config && config.getIsImmersive) ? config.getIsImmersive : (() => false);
        const setIsImmersive = (config && config.setIsImmersive) ? config.setIsImmersive : (() => {});

        const getCurrentChapters = (config && config.getCurrentChapters) ? config.getCurrentChapters : (() => []);
        const getCurrentChapterIdx = (config && config.getCurrentChapterIdx) ? config.getCurrentChapterIdx : (() => 0);
        const getAllData = (config && config.getAllData) ? config.getAllData : (() => ({ series: [] }));

        const renderQuickSwitcherListHook = (config && config.renderQuickSwitcherList)
            ? config.renderQuickSwitcherList
            : null;
        const toggleFab = (config && config.toggleFab) ? config.toggleFab : (() => {});
        const haptic = (config && config.haptic) ? config.haptic : (() => {});

        function openChannel() {
            const tg = getTelegramWebApp();
            if (tg && typeof tg.openTelegramLink === 'function') {
                tg.openTelegramLink('https://t.me/alya_novel');
            } else {
                global.open('https://t.me/alya_novel', '_blank');
            }
        }

        function toggleImmersiveMode(force = null) {
            const nextValue = force !== null ? force : !getIsImmersive();
            setIsImmersive(nextValue);

            if (!doc) return;
            const header = doc.querySelector('.reader-header');
            const bottomBar = doc.getElementById('reader-bottom-bar');
            const fab = doc.getElementById('fab-container');

            if (nextValue) {
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
            if (!doc) return;

            const switcher = doc.getElementById('quick-switcher');
            const overlay = doc.getElementById('quick-switcher-overlay');
            if (!switcher) return;

            const fabMenu = doc.getElementById('fab-menu');
            if (fabMenu && !fabMenu.classList.contains('hidden')) toggleFab();

            const isActive = switcher.classList.contains('active');
            if (!isActive) {
                if (typeof renderQuickSwitcherListHook === 'function') {
                    renderQuickSwitcherListHook();
                } else {
                    renderQuickSwitcherList();
                }
                switcher.classList.add('active');
                overlay?.classList.add('active');
                haptic('light');
            } else {
                switcher.classList.remove('active');
                const toc = doc.getElementById('toc-panel');
                if (!toc || !toc.classList.contains('active')) {
                    overlay?.classList.remove('active');
                }
            }
        }

        function renderQuickSwitcherList() {
            if (!doc) return;
            const list = doc.getElementById('quick-switcher-list');
            if (!list) return;

            const chapters = getCurrentChapters();
            if (!Array.isArray(chapters)) return;
            const currentIdx = getCurrentChapterIdx();

            list.innerHTML = chapters.map((ch, idx) => `
                <div class="quick-switcher-item ${idx === currentIdx ? 'active' : ''}" 
                     onclick="openChapter(${idx}); toggleQuickSwitcher();">
                    ${ch.custom_name || '\u0413\u043b\u0430\u0432\u0430 ' + ch.chapter}
                </div>
            `).join('');
        }

        function getSeriesCover(series) {
            if (!series) return '<div class="series-icon">\uD83D\uDCD6</div>';
            if (series.cover_url) {
                return `<img src="${series.cover_url}" class="series-cover-img" alt="${series.title}" loading="lazy">`;
            }
            const allData = getAllData() || { series: [] };
            const icons = ['\uD83D\uDCD6', '\uD83D\uDCD5', '\uD83D\uDCD7', '\uD83D\uDCD8', '\uD83D\uDCD9'];
            const idx = Array.isArray(allData.series) ? allData.series.indexOf(series) % icons.length : 0;
            return `<div class="series-icon">${icons[idx >= 0 ? idx : 0]}</div>`;
        }

        return {
            openChannel,
            toggleImmersiveMode,
            toggleQuickSwitcher,
            renderQuickSwitcherList,
            getSeriesCover
        };
    }

    root.createReaderShellUiManager = createReaderShellUiManager;
})(window);
