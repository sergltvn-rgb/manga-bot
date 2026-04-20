(function initReaderFlowModule(global) {
    const root = global.ReaderModules = global.ReaderModules || {};

    function createReaderFlowManager(config) {
        const getChapterKey = (config && config.getChapterKey) ? config.getChapterKey : (() => '');
        const getCurrentSeries = (config && config.getCurrentSeries) ? config.getCurrentSeries : (() => null);
        const getCurrentVolume = (config && config.getCurrentVolume) ? config.getCurrentVolume : (() => null);
        const getCurrentChapters = (config && config.getCurrentChapters) ? config.getCurrentChapters : (() => []);
        const getCurrentChapterIdx = (config && config.getCurrentChapterIdx) ? config.getCurrentChapterIdx : (() => 0);
        const getServerBookmarks = (config && config.getServerBookmarks) ? config.getServerBookmarks : (() => []);
        const getSettings = (config && config.getSettings) ? config.getSettings : (() => ({}));
        const getUserId = (config && config.getUserId) ? config.getUserId : (() => '');
        const getApiUrl = (config && config.getApiUrl) ? config.getApiUrl : (() => '');

        const getProgressSyncTimer = (config && config.getProgressSyncTimer) ? config.getProgressSyncTimer : (() => null);
        const setProgressSyncTimer = (config && config.setProgressSyncTimer) ? config.setProgressSyncTimer : (() => {});

        const getScrollResizeObserver = (config && config.getScrollResizeObserver) ? config.getScrollResizeObserver : (() => null);
        const setScrollResizeObserver = (config && config.setScrollResizeObserver) ? config.setScrollResizeObserver : (() => {});
        const getScrollResizeTimeout = (config && config.getScrollResizeTimeout) ? config.getScrollResizeTimeout : (() => null);
        const setScrollResizeTimeout = (config && config.setScrollResizeTimeout) ? config.setScrollResizeTimeout : (() => {});

        const getPrefetchedChapter = (config && config.getPrefetchedChapter) ? config.getPrefetchedChapter : (() => ({ idx: -1, html: null }));
        const setPrefetchedChapter = (config && config.setPrefetchedChapter) ? config.setPrefetchedChapter : (() => {});
        const getPrefetchingIdx = (config && config.getPrefetchingIdx) ? config.getPrefetchingIdx : (() => -1);
        const setPrefetchingIdx = (config && config.setPrefetchingIdx) ? config.setPrefetchingIdx : (() => {});

        const getReaderScrollListenerBound = (config && config.getReaderScrollListenerBound)
            ? config.getReaderScrollListenerBound
            : (() => false);
        const setReaderScrollListenerBound = (config && config.setReaderScrollListenerBound)
            ? config.setReaderScrollListenerBound
            : (() => {});
        const getScrollSaveTimer = (config && config.getScrollSaveTimer) ? config.getScrollSaveTimer : (() => null);
        const setScrollSaveTimer = (config && config.setScrollSaveTimer) ? config.setScrollSaveTimer : (() => {});

        const safeGetLocal = (config && config.safeGetLocal) ? config.safeGetLocal : (() => null);
        const safeSetLocal = (config && config.safeSetLocal) ? config.safeSetLocal : (() => {});
        const saveLastRead = (config && config.saveLastRead) ? config.saveLastRead : (() => {});

        const readerApi = (config && config.readerApi) ? config.readerApi : null;
        const renderTelegraphContent = (config && config.renderTelegraphContent)
            ? config.renderTelegraphContent
            : (() => '');
        const preloadImagesFromHtml = (config && config.preloadImagesFromHtml)
            ? config.preloadImagesFromHtml
            : (() => {});
        const toggleFab = (config && config.toggleFab) ? config.toggleFab : (() => {});

        const fetchFn = (typeof global.fetch === 'function') ? global.fetch.bind(global) : null;

        function getScrollKey() {
            const key = getChapterKey();
            const series = getCurrentSeries();
            const volume = getCurrentVolume();
            if (!key || !series || !volume) return null;
            return `scroll_${series.id}_v${volume.volume}_ch${key}`;
        }

        function saveScrollPosition() {
            const key = getScrollKey();
            if (!key) return;
            const doc = global.document;
            if (!doc) return;

            const el = doc.getElementById('reader-content');
            if (!el) return;

            const pct = el.scrollTop / Math.max(1, el.scrollHeight - el.clientHeight);
            safeSetLocal(key, { pct, ts: Date.now() });
            saveLastRead();

            const chapters = getCurrentChapters();
            const chapterIdx = getCurrentChapterIdx();
            const series = getCurrentSeries();
            const volume = getCurrentVolume();

            if (getApiUrl() && getUserId() && series && volume && chapters[chapterIdx] && readerApi && typeof readerApi.saveProgress === 'function') {
                const activeTimer = getProgressSyncTimer();
                if (activeTimer) clearTimeout(activeTimer);

                const timer = setTimeout(() => {
                    readerApi.saveProgress({
                        series_id: series.id,
                        volume_id: volume.volume,
                        chapter_key: chapters[chapterIdx].chapter,
                        scroll_pos: pct
                    }).catch((e) => console.warn('Progress sync error:', e));
                }, 3000);

                setProgressSyncTimer(timer);
            }
        }

        function restoreScrollPosition() {
            const currentObserver = getScrollResizeObserver();
            if (currentObserver) {
                currentObserver.disconnect();
                setScrollResizeObserver(null);
            }

            const currentTimeout = getScrollResizeTimeout();
            if (currentTimeout) {
                clearTimeout(currentTimeout);
                setScrollResizeTimeout(null);
            }

            const chapters = getCurrentChapters();
            const chapterIdx = getCurrentChapterIdx();
            const series = getCurrentSeries();
            const volume = getCurrentVolume();
            const chapter = chapters[chapterIdx];
            if (!chapter || !series || !volume) return;

            let pctToRestore = null;
            const serverBm = getServerBookmarks().find((item) => item.series_id === series.id);
            if (
                serverBm
                && String(serverBm.volume_id) === String(volume.volume)
                && String(serverBm.chapter_key) === String(chapter.chapter)
            ) {
                pctToRestore = serverBm.scroll_pos;
            }

            if (pctToRestore === null) {
                const key = getScrollKey();
                if (key) {
                    const saved = safeGetLocal(key, null);
                    if (saved) pctToRestore = saved.pct;
                }
            }

            if (pctToRestore === null) return;

            const doc = global.document;
            if (!doc) return;

            const el = doc.getElementById('reader-content');
            if (!el) return;

            let hasRestored = false;
            const resizeObserver = new ResizeObserver(() => {
                const maxScroll = el.scrollHeight - el.clientHeight;
                if (maxScroll > 0) {
                    el.scrollTop = pctToRestore * maxScroll;
                    hasRestored = true;
                }
            });

            setScrollResizeObserver(resizeObserver);
            resizeObserver.observe(el);

            const timeoutId = setTimeout(() => {
                const activeObserver = getScrollResizeObserver();
                if (activeObserver) {
                    activeObserver.disconnect();
                    setScrollResizeObserver(null);
                }

                setScrollResizeTimeout(null);

                if (!hasRestored) {
                    const maxScroll = el.scrollHeight - el.clientHeight;
                    el.scrollTop = pctToRestore * maxScroll;
                }
            }, 5000);

            setScrollResizeTimeout(timeoutId);
        }

        function buildSkeletonLoader() {
            let lines = '';
            const widths = [100, 92, 85, 95, 70, 88, 96, 80, 60, 90, 100, 75, 88, 50];
            for (let i = 0; i < widths.length; i++) {
                lines += `<div class="skeleton-line" style="width:${widths[i]}%;animation-delay:${i * 0.05}s"></div>`;
            }
            return `<div class="skeleton-loader">${lines}</div>`;
        }

        function initImageFadeIn(container) {
            if (!container) return;
            const imgs = container.querySelectorAll('img');
            imgs.forEach((img) => {
                const handleLoad = () => {
                    img.classList.remove('img-loading');
                    img.classList.add('img-loaded');
                };

                if (img.complete) {
                    handleLoad();
                } else {
                    img.classList.add('img-loading');
                    img.addEventListener('load', handleLoad, { once: true });
                    img.addEventListener('error', handleLoad, { once: true });
                }
            });
        }

        function applyIframeDarkMode() {
            const doc = global.document;
            if (!doc) return;

            const iframes = doc.querySelectorAll('.teletype-iframe');
            const settings = getSettings() || {};
            const isDark = settings.theme === 'dark' || settings.theme === 'amoled';

            iframes.forEach((frame) => {
                frame.style.filter = isDark ? 'brightness(0.7) contrast(1.1)' : 'none';
            });
        }

        function prefetchNextChapter() {
            const chapterIdx = getCurrentChapterIdx();
            const chapters = getCurrentChapters();
            const nextIdx = chapterIdx + 1;
            if (nextIdx >= chapters.length) return;

            const prefetched = getPrefetchedChapter();
            if (prefetched.idx === nextIdx || getPrefetchingIdx() === nextIdx) return;

            const chapter = chapters[nextIdx];
            if (!chapter) return;

            setPrefetchingIdx(nextIdx);

            let urlsToLoad = [];
            if (chapter.urls && chapter.urls.length > 0) {
                urlsToLoad = [...chapter.urls];
            } else if (chapter.url) {
                urlsToLoad = [chapter.url];
            }

            const telegraphUrls = urlsToLoad.filter((url) => url.includes('telegra.ph'));
            if (telegraphUrls.length > 0) {
                urlsToLoad = telegraphUrls;
            } else {
                const teletypeUrls = urlsToLoad.filter((url) => url.includes('teletype.in'));
                if (teletypeUrls.length > 0) urlsToLoad = [teletypeUrls[0]];
            }

            if (urlsToLoad.length > 0) {
                const prefetchAbortController = new AbortController();
                setTimeout(() => prefetchAbortController.abort(), 20000);

                const loadPromises = urlsToLoad.map(async (url) => {
                    if (url.includes('teletype.in')) {
                        return `<iframe src="${url}" class="teletype-iframe" frameborder="0" style="width:100%;min-height:85vh;border:none;border-radius:8px;margin-bottom:20px;" loading="lazy"></iframe>`;
                    }

                    const telegraphMatch = url.match(/telegra\.ph\/(.+)/);
                    if (telegraphMatch && fetchFn) {
                        try {
                            const response = await fetchFn(
                                `https://api.telegra.ph/getPage/${telegraphMatch[1]}?return_content=true`,
                                { signal: prefetchAbortController.signal }
                            );
                            const data = await response.json();
                            if (data.ok && data.result && data.result.content) {
                                const html = renderTelegraphContent(data.result.content);
                                preloadImagesFromHtml(html);
                                return html;
                            }
                        } catch (e) {
                            console.warn('Prefetch Telegraph err', e);
                        }
                    }

                    return '';
                });

                Promise.all(loadPromises)
                    .then((results) => {
                        setPrefetchedChapter({ idx: nextIdx, html: results.join('') });
                        setPrefetchingIdx(-1);
                        console.log('Prefetched chapter (with images)', nextIdx + 1);
                    })
                    .catch(() => {
                        setPrefetchingIdx(-1);
                    });
            } else if (chapter.text) {
                const paragraphs = chapter.text
                    .split('\n\n')
                    .map((paragraph) => `<p>${paragraph.trim()}</p>`)
                    .join('');
                setPrefetchedChapter({ idx: nextIdx, html: paragraphs });
                setPrefetchingIdx(-1);
            } else {
                setPrefetchingIdx(-1);
            }
        }

        function initReaderScrollListeners() {
            if (getReaderScrollListenerBound()) return;

            const doc = global.document;
            if (!doc) return;

            const content = doc.getElementById('reader-content');
            const screen = doc.getElementById('screen-reader');
            const progressBar = doc.getElementById('reading-progress-bar');
            if (!content || !screen || !progressBar) return;

            setReaderScrollListenerBound(true);

            let lastScrollTop = 0;
            const threshold = 15;

            content.addEventListener('scroll', () => {
                const scrollTop = content.scrollTop;
                const scrollHeight = content.scrollHeight - content.clientHeight;

                const progress = (scrollTop / Math.max(1, scrollHeight)) * 100;
                progressBar.style.width = `${progress}%`;

                if (Math.abs(scrollTop - lastScrollTop) > threshold) {
                    if (scrollTop > lastScrollTop && scrollTop > 100) {
                        screen.classList.add('immersive');
                        const fab = doc.getElementById('fab-menu');
                        if (fab && !fab.classList.contains('hidden')) toggleFab();
                    } else if (scrollTop < lastScrollTop - 5) {
                        screen.classList.remove('immersive');
                    }

                    lastScrollTop = scrollTop;
                }

                const activeTimer = getScrollSaveTimer();
                if (activeTimer) clearTimeout(activeTimer);

                const timer = setTimeout(saveScrollPosition, 1000);
                setScrollSaveTimer(timer);

                if (progress > 85) {
                    prefetchNextChapter();
                }
            }, { passive: true });
        }

        return {
            getScrollKey,
            saveScrollPosition,
            restoreScrollPosition,
            buildSkeletonLoader,
            initImageFadeIn,
            applyIframeDarkMode,
            prefetchNextChapter,
            initReaderScrollListeners
        };
    }

    root.createReaderFlowManager = createReaderFlowManager;
})(window);
