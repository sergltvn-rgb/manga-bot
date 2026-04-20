(function initScreenNavigationModule(global) {
    const root = global.ReaderModules = global.ReaderModules || {};

    function createScreenNavigationManager(config) {
        const doc = global.document;

        const getIsAdminMode = (config && config.getIsAdminMode) ? config.getIsAdminMode : (() => false);
        const getProgressBarElement = (config && config.getProgressBarElement) ? config.getProgressBarElement : (() => null);

        const saveScrollPosition = (config && config.saveScrollPosition) ? config.saveScrollPosition : (() => {});
        const renderLibraryTab = (config && config.renderLibraryTab) ? config.renderLibraryTab : (() => {});
        const updateLibraryStats = (config && config.updateLibraryStats) ? config.updateLibraryStats : (() => {});

        const haptic = (config && config.haptic) ? config.haptic : (() => {});
        const toggleToC = (config && config.toggleToC) ? config.toggleToC : (() => {});
        const toggleAutoscrollSetting = (config && config.toggleAutoscrollSetting) ? config.toggleAutoscrollSetting : (() => {});
        const isAutoscrollEnabled = (config && config.isAutoscrollEnabled) ? config.isAutoscrollEnabled : (() => false);
        const showToast = (config && config.showToast) ? config.showToast : (() => {});

        const renameItem = (config && config.renameItem) ? config.renameItem : (() => {});
        const getCurrentChapters = (config && config.getCurrentChapters) ? config.getCurrentChapters : (() => []);
        const getCurrentChapterIdx = (config && config.getCurrentChapterIdx) ? config.getCurrentChapterIdx : (() => 0);
        const getCurrentSeries = (config && config.getCurrentSeries) ? config.getCurrentSeries : (() => null);
        const getCurrentVolume = (config && config.getCurrentVolume) ? config.getCurrentVolume : (() => null);

        let fabTimeout = null;
        let fabOutsideClickBound = false;

        function closeAdminMenu() {
            if (!doc) return;
            const btn = doc.getElementById('admin-fab-btn');
            const menu = doc.getElementById('admin-menu');
            if (btn) btn.classList.remove('open');
            if (menu) menu.classList.add('hidden');
        }

        function showScreen(name) {
            if (!doc) return;

            const readerScreen = doc.getElementById('screen-reader');
            if (readerScreen && readerScreen.classList.contains('active') && name !== 'reader') {
                saveScrollPosition();
                const progressBarEl = getProgressBarElement();
                if (progressBarEl) progressBarEl.style.width = '0%';
            }

            const screens = doc.querySelectorAll('.screen');
            screens.forEach((screen) => screen.classList.remove('active', 'slide-left'));

            const targetScreen = doc.getElementById(`screen-${name}`);
            if (targetScreen) targetScreen.classList.add('active');

            const adminFab = doc.getElementById('admin-fab-container');
            if (adminFab) {
                adminFab.style.display = (name === 'reader' && getIsAdminMode()) ? 'flex' : 'none';
                closeAdminMenu();
            }

            const navTabs = doc.querySelectorAll('.nav-tab');
            if (navTabs.length > 0) {
                navTabs.forEach((tab) => tab.classList.remove('active'));

                const activeTab = doc.getElementById(`tab-${name}`);
                if (activeTab) activeTab.classList.add('active');

                const bottomNav = doc.getElementById('main-bottom-nav');
                if (bottomNav) {
                    bottomNav.style.display = name === 'reader' ? 'none' : 'flex';
                }
            }

            if (name === 'library') {
                renderLibraryTab();
                updateLibraryStats();
            }
        }

        function toggleFab() {
            if (!doc) return;
            const btn = doc.getElementById('fab-btn');
            const menu = doc.getElementById('fab-menu');
            const close = doc.getElementById('fab-icon-close');

            if (!btn || !menu) return;

            if (fabTimeout) {
                global.clearTimeout(fabTimeout);
                fabTimeout = null;
            }

            const isOpening = !btn.classList.contains('fab-open');
            haptic('medium');

            if (isOpening) {
                menu.classList.remove('hidden');
                if (close) close.classList.remove('hidden');
                global.requestAnimationFrame(() => {
                    global.requestAnimationFrame(() => {
                        btn.classList.add('fab-open');
                        menu.classList.add('fab-menu-visible');
                    });
                });
            } else {
                btn.classList.remove('fab-open');
                menu.classList.remove('fab-menu-visible');
                fabTimeout = global.setTimeout(() => menu.classList.add('hidden'), 400);
            }
        }

        function fabAction(action) {
            if (!doc) return;
            toggleFab();

            if (action === 'toc') {
                toggleToC();
                return;
            }

            if (action === 'autoscroll') {
                const toggle = doc.getElementById('autoscroll-toggle');
                if (toggle) {
                    toggle.checked = !toggle.checked;
                    toggleAutoscrollSetting(toggle.checked);
                    showToast(toggle.checked
                        ? '\u0410\u0432\u0442\u043e\u0441\u043a\u0440\u043e\u043b\u043b \u0432\u043a\u043b\u044e\u0447\u0435\u043d'
                        : '\u0410\u0432\u0442\u043e\u0441\u043a\u0440\u043e\u043b\u043b \u0432\u044b\u043a\u043b\u044e\u0447\u0435\u043d');
                } else {
                    const nextEnabled = !isAutoscrollEnabled();
                    toggleAutoscrollSetting(nextEnabled);
                    showToast(nextEnabled
                        ? '\u0410\u0432\u0442\u043e\u0441\u043a\u0440\u043e\u043b\u043b \u0432\u043a\u043b\u044e\u0447\u0435\u043d'
                        : '\u0410\u0432\u0442\u043e\u0441\u043a\u0440\u043e\u043b\u043b \u0432\u044b\u043a\u043b\u044e\u0447\u0435\u043d');
                }
                return;
            }

            if (action === 'comments') {
                const social = doc.getElementById('social-section');
                const content = doc.getElementById('reader-content');
                if (social && content) {
                    content.scrollTo({
                        top: social.offsetTop,
                        behavior: 'smooth'
                    });
                }
            }
        }

        function toggleAdminMenu() {
            if (!doc) return;
            const btn = doc.getElementById('admin-fab-btn');
            const menu = doc.getElementById('admin-menu');
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

        function renameChapterCurrent() {
            closeAdminMenu();

            const chapters = getCurrentChapters();
            const chapterIdx = getCurrentChapterIdx();
            const ch = chapters[chapterIdx];
            const series = getCurrentSeries();
            const volume = getCurrentVolume();

            if (!ch || !series || !volume) return;
            renameItem(`chap_${series.id}_${volume.volume}_${ch.chapter}`);
        }

        function initFabOutsideClickHandler() {
            if (!doc || fabOutsideClickBound) return;
            fabOutsideClickBound = true;

            doc.addEventListener('click', (event) => {
                const fabContainer = event.target.closest('.fab-container');
                const menu = doc.getElementById('fab-menu');
                if (!fabContainer && menu && menu.classList.contains('fab-menu-visible')) {
                    toggleFab();
                }
            });
        }

        return {
            showScreen,
            toggleFab,
            fabAction,
            toggleAdminMenu,
            closeAdminMenu,
            renameChapterCurrent,
            initFabOutsideClickHandler
        };
    }

    root.createScreenNavigationManager = createScreenNavigationManager;
})(window);
