(function initChapterReaderModule(global) {
    const root = global.ReaderModules = global.ReaderModules || {};

    function createChapterReaderManager(config) {
        const doc = global.document;

        const getCurrentChapters = (config && config.getCurrentChapters) ? config.getCurrentChapters : (() => []);
        const getCurrentChapterIdx = (config && config.getCurrentChapterIdx) ? config.getCurrentChapterIdx : (() => 0);
        const setCurrentChapterIdx = (config && config.setCurrentChapterIdx) ? config.setCurrentChapterIdx : (() => {});
        const getCurrentSeries = (config && config.getCurrentSeries) ? config.getCurrentSeries : (() => null);
        const getCurrentVolume = (config && config.getCurrentVolume) ? config.getCurrentVolume : (() => null);
        const getIsAdminMode = (config && config.getIsAdminMode) ? config.getIsAdminMode : (() => false);
        const getApiUrl = (config && config.getApiUrl) ? config.getApiUrl : (() => '');

        const getPrefetchedChapter = (config && config.getPrefetchedChapter) ? config.getPrefetchedChapter : (() => ({ idx: -1, html: null }));
        const setPrefetchedChapter = (config && config.setPrefetchedChapter) ? config.setPrefetchedChapter : (() => {});
        const getChapterAbortController = (config && config.getChapterAbortController) ? config.getChapterAbortController : (() => null);
        const setChapterAbortController = (config && config.setChapterAbortController) ? config.setChapterAbortController : (() => {});

        const startChapterOpenMetric = (config && config.startChapterOpenMetric) ? config.startChapterOpenMetric : (() => {});
        const completeChapterOpenMetric = (config && config.completeChapterOpenMetric) ? config.completeChapterOpenMetric : (() => {});

        const markAsRead = (config && config.markAsRead) ? config.markAsRead : (() => {});
        const showScreen = (config && config.showScreen) ? config.showScreen : (() => {});
        const loadLikes = (config && config.loadLikes) ? config.loadLikes : (() => {});
        const loadReactions = (config && config.loadReactions) ? config.loadReactions : (() => {});
        const loadComments = (config && config.loadComments) ? config.loadComments : (() => {});
        const initProgressBar = (config && config.initProgressBar) ? config.initProgressBar : (() => {});
        const setProgressBarWidth = (config && config.setProgressBarWidth) ? config.setProgressBarWidth : (() => {});
        const initLightbox = (config && config.initLightbox) ? config.initLightbox : (() => {});
        const buildToC = (config && config.buildToC) ? config.buildToC : (() => {});
        const initImageFadeIn = (config && config.initImageFadeIn) ? config.initImageFadeIn : (() => {});
        const applyIframeDarkMode = (config && config.applyIframeDarkMode) ? config.applyIframeDarkMode : (() => {});
        const restoreScrollPosition = (config && config.restoreScrollPosition) ? config.restoreScrollPosition : (() => {});
        const haptic = (config && config.haptic) ? config.haptic : (() => {});
        const saveScrollPosition = (config && config.saveScrollPosition) ? config.saveScrollPosition : (() => {});
        const renderChaptersList = (config && config.renderChaptersList) ? config.renderChaptersList : (() => {});
        const openEditUrlModal = (config && config.openEditUrlModal) ? config.openEditUrlModal : (() => {});
        const renderTelegraphContentHook = (config && config.renderTelegraphContent) ? config.renderTelegraphContent : null;
        const preloadImagesFromHtmlHook = (config && config.preloadImagesFromHtml) ? config.preloadImagesFromHtml : null;

        function normalizeChapterUrls(chapter) {
            let urls = [];
            if (chapter.urls && chapter.urls.length > 0) {
                urls = [...chapter.urls];
            } else if (chapter.url) {
                urls = [chapter.url];
            }

            const telegraphUrls = urls.filter((url) => url.includes('telegra.ph'));
            if (telegraphUrls.length > 0) {
                return telegraphUrls;
            }

            const teletypeUrls = urls.filter((url) => url.includes('teletype.in'));
            if (teletypeUrls.length > 0) {
                return [teletypeUrls[0]];
            }

            return urls;
        }

        function openChapter(idx, usePrefetch = false) {
            const chapters = getCurrentChapters();
            setCurrentChapterIdx(idx);

            const chapter = chapters[idx];
            if (!chapter) return;

            if (!chapter.chapter) {
                console.warn('Chapter object missing required properties:', chapter);
                return;
            }

            const series = getCurrentSeries();
            const volume = getCurrentVolume();
            startChapterOpenMetric(chapter, {
                seriesId: series?.id || '',
                volume: volume?.volume || ''
            });

            const content = doc.getElementById('reader-content');
            if (content) content.classList.add('loading');

            const titleHeader = doc.getElementById('chapter-title-header');
            if (titleHeader) titleHeader.textContent = chapter.custom_name || `Глава ${chapter.chapter}`;

            updateNavButtons();

            if (series && volume) {
                markAsRead(series.id, volume.volume, chapter.chapter);
            }

            loadChapterContent(chapter, usePrefetch);

            initProgressBar();
            setProgressBarWidth(0);

            const switcher = doc.getElementById('quick-switcher');
            if (switcher) switcher.classList.add('hidden');

            showScreen('reader');

            if (getApiUrl()) {
                loadLikes();
                loadReactions();
                loadComments();
                const social = doc.getElementById('social-section');
                if (social) social.style.display = 'block';
            } else {
                const social = doc.getElementById('social-section');
                if (social) social.style.display = 'none';
            }
        }

        function loadChapterContent(chapter, usePrefetch = false) {
            const container = doc.getElementById('reader-text');
            if (!container || !chapter) return;

            const activeAbortController = getChapterAbortController();
            if (activeAbortController) {
                activeAbortController.abort();
                setChapterAbortController(null);
            }

            const currentIdx = getCurrentChapterIdx();
            const prefetched = getPrefetchedChapter();
            if (usePrefetch && prefetched && prefetched.idx === currentIdx && prefetched.html) {
                renderLoadedContent(container, prefetched.html, chapter);
                setPrefetchedChapter({ idx: -1, html: null });
                return;
            }

            const urlsToLoad = normalizeChapterUrls(chapter);

            if (urlsToLoad.length > 0) {
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

                const controller = new AbortController();
                const signal = controller.signal;
                setChapterAbortController(controller);

                global.setTimeout(() => {
                    const currentController = getChapterAbortController();
                    if (currentController && currentController === controller && !currentController.signal.aborted) {
                        currentController.abort(new Error('Timeout'));
                    }
                }, 15000);

                const loadPromises = urlsToLoad.map(async (url) => {
                    if (url.includes('teletype.in')) {
                        return `<iframe src="${url}" class="teletype-iframe" frameborder="0" style="width:100%;min-height:85vh;border:none;border-radius:8px;margin-bottom:20px;" loading="lazy"></iframe>`;
                    }

                    const telegraphMatch = url.match(/telegra\.ph\/(.+)/);
                    if (telegraphMatch) {
                        try {
                            const response = await global.fetch(`https://api.telegra.ph/getPage/${telegraphMatch[1]}?return_content=true`, { signal });
                            const payload = await response.json();
                            if (payload.ok && payload.result && payload.result.content) {
                                return renderTelegraphContent(payload.result.content);
                            }
                        } catch (error) {
                            if (error && error.name === 'AbortError') throw error;
                            console.warn('Telegraph API err', error);
                        }
                    }

                    return `<iframe src="${url}" frameborder="0" style="width:100%;min-height:80vh;border:none;border-radius:8px;margin-bottom:20px;"></iframe>`;
                });

                Promise.all(loadPromises).then((results) => {
                    const chapters = getCurrentChapters();
                    const chapterIdx = getCurrentChapterIdx();
                    if (signal.aborted || chapter !== chapters[chapterIdx]) return;
                    renderLoadedContent(container, results.join(''), chapter);
                }).catch((error) => {
                    if (error && error.name === 'AbortError') return;
                    console.error('Chapter load failed:', error);
                    container.innerHTML = `
                        <div class="empty-state">
                            <div class="empty-icon">❌</div>
                            <h3>Ошибка загрузки главы</h3>
                            <p>Проверьте соединение или используйте VPN.</p>
                            <button class="retry-btn" onclick="loadChapterContent(currentChapters[currentChapterIdx])">🔄 Повторить попытку</button>
                        </div>
                    `;
                });
            } else if (chapter.text) {
                const paragraphs = chapter.text.split('\n\n').map((paragraph) => `<p>${paragraph.trim()}</p>`).join('');
                renderLoadedContent(container, paragraphs, chapter);
            } else {
                const isAdminMode = !!getIsAdminMode();
                const chapterIdx = getCurrentChapterIdx();
                const adminButton = isAdminMode
                    ? `<button class="admin-primary-btn" style="margin-top:2rem;" onclick="openEditUrlModal(${chapterIdx})">🔗 Добавить ссылку</button>`
                    : '';
                container.innerHTML = `
                    <div class="empty-state" style="margin-top:20vh;">
                        <div class="empty-icon" style="font-size:4rem;opacity:0.3;">⏳</div>
                        <h3 style="margin-top:1.5rem;font-weight:700;">Глава еще не загружена</h3>
                        <p style="opacity:0.6;max-width:300px;margin:1rem auto;">Эта часть главы еще находится в переводе или ожидает проверки администратором.</p>
                        ${adminButton}
                    </div>
                `;
            }

            const readerContent = doc.getElementById('reader-content');
            if (readerContent) readerContent.scrollTop = 0;
        }

        function renderLoadedContent(container, html, chapter) {
            if (!container) return;
            container.innerHTML = html;

            const contentArea = doc.getElementById('reader-content');
            if (contentArea) {
                global.setTimeout(() => contentArea.classList.remove('loading'), 100);
            }

            const textContent = container.innerText || '';
            const wordCount = textContent.split(/\s+/).filter((word) => word.length > 0).length;
            if (wordCount > 50) {
                const readingTimeMins = Math.max(1, Math.ceil(wordCount / 200));
                const timeBadge = doc.createElement('div');
                timeBadge.className = 'reading-time-badge';
                timeBadge.innerHTML = `<svg class="icon-xs" viewBox="0 0 24 24" style="vertical-align:-2px; margin-right:4px;"><circle cx="12" cy="12" r="10" fill="none" stroke="currentColor" stroke-width="2"/><polyline points="12 6 12 12 16 14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>~${readingTimeMins} мин. чтения`;
                container.insertBefore(timeBadge, container.firstChild);
            }

            initLightbox();
            buildToC();
            initImageFadeIn(container);
            applyIframeDarkMode();
            restoreScrollPosition();
            completeChapterOpenMetric();

            if (typeof preloadImagesFromHtmlHook === 'function') {
                preloadImagesFromHtmlHook(html, chapter);
            }
        }

        function navigateChapter(delta) {
            saveScrollPosition();
            const newIdx = getCurrentChapterIdx() + delta;
            const chapters = getCurrentChapters();
            if (newIdx < 0 || newIdx >= chapters.length) return;

            haptic('medium');

            const container = doc.getElementById('reader-text');
            if (!container) {
                openChapter(newIdx, true);
                return;
            }

            const direction = delta > 0 ? 'left' : 'right';
            container.classList.add(`slide-out-${direction}`);
            global.setTimeout(() => {
                container.classList.remove(`slide-out-${direction}`);
                const oppositeDirection = direction === 'left' ? 'right' : 'left';
                container.classList.add(`slide-in-${oppositeDirection}`);
                openChapter(newIdx, true);
                global.requestAnimationFrame(() => {
                    global.requestAnimationFrame(() => {
                        container.classList.remove(`slide-in-${oppositeDirection}`);
                    });
                });
            }, 200);
        }

        function backFromReader() {
            haptic('light');
            saveScrollPosition();
            showScreen('chapters');
            renderChaptersList();
        }

        function updateNavButtons() {
            const chapters = getCurrentChapters();
            const chapterIdx = getCurrentChapterIdx();

            const prev = doc.getElementById('prev-chapter-btn');
            const next = doc.getElementById('next-chapter-btn');
            const indicator = doc.getElementById('chapter-indicator');

            if (prev) prev.disabled = chapterIdx === 0;
            if (next) next.disabled = chapterIdx >= chapters.length - 1;
            if (indicator) indicator.textContent = `${chapterIdx + 1} / ${chapters.length}`;
        }

        function preloadImagesFromHtml(html) {
            if (typeof preloadImagesFromHtmlHook === 'function') {
                return preloadImagesFromHtmlHook(html);
            }

            const tmp = doc.createElement('div');
            tmp.innerHTML = html;
            const images = tmp.querySelectorAll('img');
            images.forEach((img) => {
                const preloader = new Image();
                preloader.src = img.src;
            });
        }

        function renderTelegraphContent(nodes) {
            if (typeof renderTelegraphContentHook === 'function') {
                return renderTelegraphContentHook(nodes);
            }

            if (!Array.isArray(nodes)) return '';
            return nodes.map((node) => {
                if (typeof node === 'string') return node;
                if (!node || !node.tag) return '';

                const children = node.children ? renderTelegraphContent(node.children) : '';
                const attrs = node.attrs
                    ? Object.entries(node.attrs).map(([key, value]) => `${key}="${value}"`).join(' ')
                    : '';

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

        return {
            openChapter,
            loadChapterContent,
            renderLoadedContent,
            navigateChapter,
            backFromReader,
            updateNavButtons,
            preloadImagesFromHtml,
            renderTelegraphContent
        };
    }

    root.createChapterReaderManager = createChapterReaderManager;
})(window);
