(function initTypoReporterModule(global) {
    const root = global.ReaderModules = global.ReaderModules || {};

    function createTypoReporterManager(config) {
        const doc = global.document;

        const getApiUrl = (config && config.getApiUrl) ? config.getApiUrl : (() => '');
        const getCurrentChapters = (config && config.getCurrentChapters) ? config.getCurrentChapters : (() => []);
        const getCurrentChapterIdx = (config && config.getCurrentChapterIdx) ? config.getCurrentChapterIdx : (() => 0);
        const getCurrentSeries = (config && config.getCurrentSeries) ? config.getCurrentSeries : (() => null);
        const getCurrentVolume = (config && config.getCurrentVolume) ? config.getCurrentVolume : (() => null);
        const readerApi = (config && config.readerApi) ? config.readerApi : null;
        const showToast = (config && config.showToast) ? config.showToast : (() => {});
        const closeTypoModalHook = (config && config.closeTypoModal) ? config.closeTypoModal : null;
        const getTelegramWebApp = (config && config.getTelegramWebApp)
            ? config.getTelegramWebApp
            : (() => (global.Telegram && global.Telegram.WebApp ? global.Telegram.WebApp : null));

        let typoSelectedText = '';
        let typoContextText = '';
        let typoSelectionRange = null;
        let initialized = false;

        function initTypoReporter() {
            if (initialized || !doc) return;
            initialized = true;

            const readerContent = doc.getElementById('reader-content');
            if (!readerContent) return;

            const tooltip = doc.getElementById('typo-tooltip');
            if (tooltip) {
                tooltip.onclick = null;
                tooltip.removeAttribute('onclick');
                tooltip.onpointerdown = (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    showTypoModal();
                };
            }

            doc.addEventListener('selectionchange', handleSelection);
            doc.addEventListener('mouseup', handleSelection);
        }

        function handleSelection() {
            if (!doc) return;

            const readerScreen = doc.getElementById('screen-reader');
            if (!readerScreen || !readerScreen.classList.contains('active')) return;

            const selection = global.getSelection();
            const tooltip = doc.getElementById('typo-tooltip');
            if (!selection) return;

            if (!selection.rangeCount || selection.isCollapsed || selection.toString().trim().length < 2) {
                if (tooltip) tooltip.classList.remove('visible');
                return;
            }

            const range = selection.getRangeAt(0);
            const selectedText = selection.toString().trim();

            const readerContent = doc.getElementById('reader-content');
            if (!readerContent || !readerContent.contains(range.commonAncestorContainer)) {
                if (tooltip) tooltip.classList.remove('visible');
                return;
            }

            if (selectedText.length > 100) {
                if (tooltip) tooltip.classList.remove('visible');
                return;
            }

            typoSelectedText = selectedText;
            typoSelectionRange = range.cloneRange();

            const startNode = range.startContainer;
            const fullText = startNode.textContent || '';
            const startIdx = Math.max(0, range.startOffset - 60);
            const endIdx = Math.min(fullText.length, range.endOffset + 60);
            typoContextText = fullText.substring(startIdx, endIdx);

            const rect = range.getBoundingClientRect();
            if (tooltip) {
                tooltip.style.left = `${rect.left + rect.width / 2}px`;
                tooltip.style.top = `${rect.top + global.scrollY}px`;
                tooltip.classList.add('visible');
            }
        }

        function showTypoModal() {
            if (!doc) return;

            const modal = doc.getElementById('typo-modal');
            const overlay = doc.getElementById('typo-modal-overlay');
            const contextEl = doc.getElementById('typo-modal-context');
            const tooltip = doc.getElementById('typo-tooltip');
            const commentInput = doc.getElementById('typo-comment');

            if (!modal || !overlay || !contextEl || !commentInput) return;
            if (tooltip) tooltip.classList.remove('visible');

            const escapedSelected = typoSelectedText.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
            const highlightedContext = typoContextText.replace(
                new RegExp(escapedSelected, 'g'),
                `<span class="typo-modal-selected">${typoSelectedText}</span>`
            );

            contextEl.innerHTML = `"...${highlightedContext}..."`;
            commentInput.value = '';
            modal.classList.remove('hidden');
            overlay.classList.remove('hidden');

            if (global.getSelection) {
                global.getSelection().removeAllRanges();
            }
        }

        function closeTypoModal() {
            if (!doc) return;
            const modal = doc.getElementById('typo-modal');
            const overlay = doc.getElementById('typo-modal-overlay');
            if (modal) modal.classList.add('hidden');
            if (overlay) overlay.classList.add('hidden');
        }

        async function submitTypoReport() {
            if (!doc || !readerApi) return;
            if (!getApiUrl()) {
                showToast('\u0420\u0435\u043f\u043e\u0440\u0442\u044b \u0434\u043e\u0441\u0442\u0443\u043f\u043d\u044b \u0442\u043e\u043b\u044c\u043a\u043e \u0432 \u043e\u043d\u043b\u0430\u0439\u043d-\u0440\u0435\u0436\u0438\u043c\u0435.');
                return;
            }

            const commentInput = doc.getElementById('typo-comment');
            const btn = doc.getElementById('typo-submit-btn');
            if (!commentInput || !btn) return;

            const comment = commentInput.value.trim();
            const originalText = btn.innerText;

            const chapters = getCurrentChapters();
            const chapter = chapters[getCurrentChapterIdx()];
            const currentSeries = getCurrentSeries();
            const currentVolume = getCurrentVolume();
            if (!chapter || !currentSeries || !currentVolume) return;

            const chapterKey = `${currentSeries.id}_v${currentVolume.volume}_ch${chapter.chapter}`;

            try {
                btn.disabled = true;
                btn.innerText = '\u231B \u041e\u0442\u043f\u0440\u0430\u0432\u043a\u0430...';

                const resp = await readerApi.submitTypo({
                    chapter_key: chapterKey,
                    selected_text: typoSelectedText,
                    context_text: typoContextText,
                    comment
                });

                const result = await resp.json();
                if (result.ok) {
                    const tg = getTelegramWebApp();
                    if (tg && tg.HapticFeedback) {
                        tg.HapticFeedback.notificationOccurred('success');
                    }

                    showToast('\u2705 \u0421\u043f\u0430\u0441\u0438\u0431\u043e! \u0420\u0435\u043f\u043e\u0440\u0442 \u043e\u0431 \u043e\u043f\u0435\u0447\u0430\u0442\u043a\u0435 \u043e\u0442\u043f\u0440\u0430\u0432\u043b\u0435\u043d.');
                    if (typeof closeTypoModalHook === 'function') closeTypoModalHook();
                    else closeTypoModal();
                } else {
                    showToast('\u041e\u0448\u0438\u0431\u043a\u0430: ' + (result.error || '\u043d\u0435\u0438\u0437\u0432\u0435\u0441\u0442\u043d\u0430\u044f'));
                }
            } catch (e) {
                const msg = e && e.message ? e.message : 'Unknown error';
                showToast('\u041e\u0448\u0438\u0431\u043a\u0430 \u0441\u0435\u0442\u0438: ' + msg);
            } finally {
                btn.disabled = false;
                btn.innerText = originalText;
            }
        }

        return {
            initTypoReporter,
            handleSelection,
            showTypoModal,
            closeTypoModal,
            submitTypoReport,
            getLastSelection: () => typoSelectionRange
        };
    }

    root.createTypoReporterManager = createTypoReporterManager;
})(window);
