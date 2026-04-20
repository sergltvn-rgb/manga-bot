(function initReaderContentInteractionsModule(global) {
    const root = global.ReaderModules = global.ReaderModules || {};

    function createReaderContentInteractionsManager(config) {
        const doc = global.document;

        const updateProgressBar = (config && config.updateProgressBar) ? config.updateProgressBar : (() => {});
        const prefetchNextChapter = (config && config.prefetchNextChapter) ? config.prefetchNextChapter : (() => {});
        const saveScrollPosition = (config && config.saveScrollPosition) ? config.saveScrollPosition : (() => {});
        const haptic = (config && config.haptic) ? config.haptic : (() => {});
        const toggleFab = (config && config.toggleFab) ? config.toggleFab : (() => {});

        let scrollSaveTimer = null;
        let lastScrollY = 0;
        let uiHidden = false;
        let interactionsBound = false;

        function getReaderTopBar() {
            if (!doc) return null;
            return doc.getElementById('reader-header') || doc.getElementById('reader-top-bar');
        }

        function initReaderContentInteractions() {
            if (!doc || interactionsBound) return;

            const readerContent = doc.getElementById('reader-content');
            if (!readerContent) return;
            interactionsBound = true;

            let ticking = false;
            readerContent.addEventListener('scroll', () => {
                if (ticking) return;

                global.requestAnimationFrame(() => {
                    updateProgressBar(readerContent);

                    const currentScroll = readerContent.scrollTop;
                    const topBar = getReaderTopBar();
                    const bottomBar = doc.getElementById('reader-bottom-bar');

                    if (topBar && bottomBar) {
                        if (currentScroll > lastScrollY + 8 && currentScroll > 100) {
                            if (!uiHidden) {
                                topBar.classList.add('bars-hidden');
                                bottomBar.classList.add('bars-hidden');
                                uiHidden = true;

                                const menu = doc.getElementById('fab-menu');
                                if (menu && !menu.classList.contains('hidden')) toggleFab();
                            }
                        } else if (currentScroll < lastScrollY - 5) {
                            if (uiHidden) {
                                topBar.classList.remove('bars-hidden');
                                bottomBar.classList.remove('bars-hidden');
                                uiHidden = false;
                            }
                        }
                    }

                    lastScrollY = currentScroll <= 0 ? 0 : currentScroll;

                    global.clearTimeout(scrollSaveTimer);
                    scrollSaveTimer = global.setTimeout(() => {
                        const pct = currentScroll / Math.max(1, readerContent.scrollHeight - readerContent.clientHeight);
                        if (pct > 0.8) prefetchNextChapter();
                        saveScrollPosition();
                    }, 500);

                    ticking = false;
                });
                ticking = true;
            }, { passive: true });

            readerContent.addEventListener('click', (e) => {
                if (e.target.closest('a, button, img, textarea, input, .social-section, .comment-form, iframe')) return;

                const rect = readerContent.getBoundingClientRect();
                const relativeY = (e.clientY - rect.top) / rect.height;
                const pageHeight = readerContent.clientHeight * 0.85;

                if (relativeY < 0.3) {
                    readerContent.scrollBy({ top: -pageHeight, behavior: 'smooth' });
                    haptic('light');
                } else if (relativeY > 0.7) {
                    readerContent.scrollBy({ top: pageHeight, behavior: 'smooth' });
                    haptic('light');
                } else {
                    const topBar = getReaderTopBar();
                    const bottomBar = doc.getElementById('reader-bottom-bar');
                    if (topBar && bottomBar) {
                        topBar.classList.toggle('bars-hidden');
                        bottomBar.classList.toggle('bars-hidden');
                        uiHidden = !uiHidden;
                        haptic('light');
                    }
                }
            });
        }

        return {
            getReaderTopBar,
            initReaderContentInteractions
        };
    }

    root.createReaderContentInteractionsManager = createReaderContentInteractionsManager;
})(window);
