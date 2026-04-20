(function initChapterAdminModule(global) {
    const root = global.ReaderModules = global.ReaderModules || {};

    function createChapterAdminManager(config) {
        const getApiUrl = (config && config.getApiUrl) ? config.getApiUrl : (() => '');
        const getCurrentSeries = (config && config.getCurrentSeries) ? config.getCurrentSeries : (() => null);
        const getCurrentVolume = (config && config.getCurrentVolume) ? config.getCurrentVolume : (() => null);
        const getCurrentChapters = (config && config.getCurrentChapters) ? config.getCurrentChapters : (() => []);
        const readerApi = (config && config.readerApi) ? config.readerApi : null;
        const renderChaptersList = (config && config.renderChaptersList) ? config.renderChaptersList : (() => {});
        const loadData = (config && config.loadData) ? config.loadData : (async () => {});
        const showToast = (config && config.showToast) ? config.showToast : (() => {});

        let editUrlChapterIdx = null;
        let dragSrcIdx = null;
        let touchDragItem = null;

        function hasApi() {
            return !!getApiUrl() && !!readerApi;
        }

        function getChapters() {
            const chapters = getCurrentChapters();
            return Array.isArray(chapters) ? chapters : [];
        }

        function openEditUrlModal(chIdx) {
            const chapters = getChapters();
            if (!chapters[chIdx]) return;

            editUrlChapterIdx = chIdx;
            const chapter = chapters[chIdx];

            const chapterName = chapter.custom_name || `\u0413\u043b\u0430\u0432\u0430 ${chapter.chapter}`;
            const chapterNameEl = global.document.getElementById('edit-url-chapter-name');
            if (chapterNameEl) chapterNameEl.textContent = chapterName;

            const currentUrl = (chapter.urls && chapter.urls.length > 0)
                ? chapter.urls.join('\n')
                : (chapter.url || '');
            const input = global.document.getElementById('edit-url-input');
            if (input) input.value = currentUrl;

            const overlay = global.document.getElementById('edit-url-overlay');
            const modal = global.document.getElementById('edit-url-modal');
            if (overlay) overlay.classList.remove('hidden');
            if (modal) modal.classList.remove('hidden');

            setTimeout(() => {
                const focusInput = global.document.getElementById('edit-url-input');
                if (focusInput) focusInput.focus();
            }, 350);
        }

        function closeEditUrlModal() {
            const overlay = global.document.getElementById('edit-url-overlay');
            const modal = global.document.getElementById('edit-url-modal');
            if (overlay) overlay.classList.add('hidden');
            if (modal) modal.classList.add('hidden');
            editUrlChapterIdx = null;
        }

        async function saveEditUrl() {
            if (editUrlChapterIdx === null || !hasApi()) return;

            const chapters = getChapters();
            const chapter = chapters[editUrlChapterIdx];
            const series = getCurrentSeries();
            const volume = getCurrentVolume();
            if (!chapter || !series || !volume) return;

            const input = global.document.getElementById('edit-url-input');
            const newUrl = input ? input.value.trim() : '';

            const saveBtn = global.document.getElementById('edit-url-save');
            if (saveBtn) {
                saveBtn.disabled = true;
                saveBtn.textContent = '\u0421\u043e\u0445\u0440\u0430\u043d\u0435\u043d\u0438\u0435...';
            }

            try {
                const resp = await readerApi.updateChapter({
                    series_id: series.id,
                    volume: volume.volume,
                    chapter: chapter.chapter,
                    url: newUrl
                });
                const result = await resp.json();
                if (result.ok) {
                    const urlArr = newUrl.split('\n').map((url) => url.trim()).filter((url) => url.length > 0);
                    chapter.urls = urlArr;
                    chapter.url = urlArr[0] || '';
                    closeEditUrlModal();
                    showToast('\u2705 \u0421\u0441\u044b\u043b\u043a\u0430 \u043e\u0431\u043d\u043e\u0432\u043b\u0435\u043d\u0430!');
                } else {
                    showToast('\u041e\u0448\u0438\u0431\u043a\u0430: ' + (result.error || '\u043d\u0435\u0438\u0437\u0432\u0435\u0441\u0442\u043d\u0430\u044f'));
                }
            } catch (e) {
                showToast('\u041e\u0448\u0438\u0431\u043a\u0430 \u0441\u0435\u0442\u0438: ' + e.message);
            } finally {
                if (saveBtn) {
                    saveBtn.disabled = false;
                    saveBtn.textContent = '\u0421\u043e\u0445\u0440\u0430\u043d\u0438\u0442\u044c';
                }
            }
        }

        function openBulkModal() {
            const input = global.document.getElementById('bulk-upload-input');
            const overlay = global.document.getElementById('bulk-upload-overlay');
            const modal = global.document.getElementById('bulk-upload-modal');

            if (input) input.value = '';
            if (overlay) overlay.classList.remove('hidden');
            if (modal) modal.classList.remove('hidden');

            setTimeout(() => {
                const focusInput = global.document.getElementById('bulk-upload-input');
                if (focusInput) focusInput.focus();
            }, 350);
        }

        function closeBulkModal() {
            const overlay = global.document.getElementById('bulk-upload-overlay');
            const modal = global.document.getElementById('bulk-upload-modal');
            if (overlay) overlay.classList.add('hidden');
            if (modal) modal.classList.add('hidden');
        }

        async function executeBulkUpload() {
            if (!hasApi()) return;

            const series = getCurrentSeries();
            const volume = getCurrentVolume();
            const chapters = getChapters();
            if (!series || !volume) return;

            const input = global.document.getElementById('bulk-upload-input');
            const raw = input ? input.value.trim() : '';
            if (!raw) {
                showToast('\u0412\u0441\u0442\u0430\u0432\u044c\u0442\u0435 \u0441\u0441\u044b\u043b\u043a\u0438');
                return;
            }

            const urls = raw.split('\n').map((url) => url.trim()).filter((url) => url.length > 0);
            if (urls.length === 0) {
                showToast('\u041d\u0435\u0442 \u0432\u0430\u043b\u0438\u0434\u043d\u044b\u0445 \u0441\u0441\u044b\u043b\u043e\u043a');
                return;
            }

            const lastChapterNumber = chapters.length > 0
                ? Math.max(...chapters.map((chapter) => parseInt(chapter.chapter, 10) || 0))
                : 0;

            const saveBtn = global.document.getElementById('bulk-upload-save');
            if (saveBtn) {
                saveBtn.disabled = true;
                saveBtn.textContent = `\u0414\u043e\u0431\u0430\u0432\u043b\u0435\u043d\u0438\u0435 ${urls.length} \u0433\u043b\u0430\u0432...`;
            }

            try {
                const resp = await readerApi.bulkCreateChapters({
                    series_id: series.id,
                    volume: volume.volume,
                    start_chapter: lastChapterNumber + 1,
                    urls
                });
                const result = await resp.json();
                if (result.ok) {
                    closeBulkModal();
                    showToast(`\u2705 \u0414\u043e\u0431\u0430\u0432\u043b\u0435\u043d\u043e ${result.added} \u0433\u043b\u0430\u0432!`);
                    await loadData();
                } else {
                    showToast('\u041e\u0448\u0438\u0431\u043a\u0430: ' + (result.error || '\u043d\u0435\u0438\u0437\u0432\u0435\u0441\u0442\u043d\u0430\u044f'));
                }
            } catch (e) {
                showToast('\u041e\u0448\u0438\u0431\u043a\u0430 \u0441\u0435\u0442\u0438: ' + e.message);
            } finally {
                if (saveBtn) {
                    saveBtn.disabled = false;
                    saveBtn.textContent = '\u0414\u043e\u0431\u0430\u0432\u0438\u0442\u044c';
                }
            }
        }

        function handleDragStart(e) {
            const item = e.currentTarget;
            if (!item) return;

            dragSrcIdx = parseInt(item.dataset.chapterIdx, 10);
            item.classList.add('dragging');

            if (e.dataTransfer) {
                e.dataTransfer.effectAllowed = 'move';
                e.dataTransfer.setData('text/plain', String(dragSrcIdx));
            }
        }

        function handleDragOver(e) {
            e.preventDefault();
            if (e.dataTransfer) {
                e.dataTransfer.dropEffect = 'move';
            }
        }

        function handleDragEnter(e) {
            const item = e.currentTarget;
            if (item) item.classList.add('drag-over');
        }

        function handleDragLeave(e) {
            const item = e.currentTarget;
            if (item) item.classList.remove('drag-over');
        }

        function handleDrop(e) {
            e.preventDefault();

            const item = e.currentTarget;
            if (item) item.classList.remove('drag-over');

            const destIdx = item ? parseInt(item.dataset.chapterIdx, 10) : NaN;
            if (Number.isInteger(dragSrcIdx) && Number.isInteger(destIdx) && dragSrcIdx !== destIdx) {
                reorderChapters(dragSrcIdx, destIdx);
            }
        }

        function clearDnDClasses() {
            global.document.querySelectorAll('.chapter-item').forEach((item) => {
                item.classList.remove('dragging', 'drag-over');
            });
        }

        function handleDragEnd() {
            clearDnDClasses();
            dragSrcIdx = null;
        }

        function touchDragStart(e) {
            e.preventDefault();

            const handle = e.currentTarget;
            const item = handle && handle.closest ? handle.closest('.chapter-item') : null;
            if (!item) return;

            touchDragItem = item;
            dragSrcIdx = parseInt(item.dataset.chapterIdx, 10);
            item.classList.add('dragging');

            global.document.addEventListener('touchmove', touchDragMove, { passive: false });
            global.document.addEventListener('touchend', touchDragEnd);
        }

        function touchDragMove(e) {
            e.preventDefault();
            const touch = e.touches && e.touches[0];
            if (!touch) return;

            const elements = global.document.elementsFromPoint(touch.clientX, touch.clientY);
            const target = elements.find((el) => el.classList && el.classList.contains('chapter-item') && el !== touchDragItem);

            global.document.querySelectorAll('.chapter-item').forEach((item) => item.classList.remove('drag-over'));
            if (target) target.classList.add('drag-over');
        }

        function touchDragEnd(e) {
            global.document.removeEventListener('touchmove', touchDragMove);
            global.document.removeEventListener('touchend', touchDragEnd);

            const touch = e.changedTouches && e.changedTouches[0];
            if (touch) {
                const elements = global.document.elementsFromPoint(touch.clientX, touch.clientY);
                const target = elements.find((el) => el.classList && el.classList.contains('chapter-item') && el !== touchDragItem);
                if (target && Number.isInteger(dragSrcIdx)) {
                    const destIdx = parseInt(target.dataset.chapterIdx, 10);
                    if (Number.isInteger(destIdx) && dragSrcIdx !== destIdx) {
                        reorderChapters(dragSrcIdx, destIdx);
                    }
                }
            }

            clearDnDClasses();
            touchDragItem = null;
            dragSrcIdx = null;
        }

        function cleanupChapterDnD() {
            const container = global.document.getElementById('chapters-list');
            if (!container) return;

            const items = container.querySelectorAll('.chapter-item');
            items.forEach((item) => {
                item.removeEventListener('dragstart', handleDragStart);
                item.removeEventListener('dragover', handleDragOver);
                item.removeEventListener('drop', handleDrop);
                item.removeEventListener('dragend', handleDragEnd);
                item.removeEventListener('dragenter', handleDragEnter);
                item.removeEventListener('dragleave', handleDragLeave);

                const handle = item.querySelector('.drag-handle');
                if (handle) {
                    handle.removeEventListener('touchstart', touchDragStart);
                }
            });

            global.document.removeEventListener('touchmove', touchDragMove);
            global.document.removeEventListener('touchend', touchDragEnd);
            touchDragItem = null;
            dragSrcIdx = null;
        }

        function initChapterDnD() {
            const container = global.document.getElementById('chapters-list');
            if (!container) return;

            cleanupChapterDnD();

            const items = container.querySelectorAll('.chapter-item');
            items.forEach((item) => {
                if (item.getAttribute('draggable') === 'true') {
                    item.addEventListener('dragstart', handleDragStart);
                    item.addEventListener('dragover', handleDragOver);
                    item.addEventListener('drop', handleDrop);
                    item.addEventListener('dragend', handleDragEnd);
                    item.addEventListener('dragenter', handleDragEnter);
                    item.addEventListener('dragleave', handleDragLeave);
                }

                const handle = item.querySelector('.drag-handle');
                if (handle) {
                    handle.addEventListener('touchstart', touchDragStart, { passive: false });
                }
            });
        }

        async function reorderChapters(fromIdx, toIdx) {
            const chapters = getChapters();
            if (
                !Number.isInteger(fromIdx) ||
                !Number.isInteger(toIdx) ||
                fromIdx < 0 ||
                toIdx < 0 ||
                fromIdx >= chapters.length ||
                toIdx >= chapters.length
            ) {
                return;
            }

            const moved = chapters.splice(fromIdx, 1)[0];
            chapters.splice(toIdx, 0, moved);
            renderChaptersList();

            if (!hasApi()) return;

            const series = getCurrentSeries();
            const volume = getCurrentVolume();
            if (!series || !volume) return;

            const order = chapters.map((chapter) => chapter.chapter);
            try {
                await readerApi.sortChapters({
                    series_id: series.id,
                    volume: volume.volume,
                    order
                });
            } catch (e) {
                console.warn('Sort sync error:', e);
            }
        }

        return {
            openEditUrlModal,
            closeEditUrlModal,
            saveEditUrl,
            openBulkModal,
            closeBulkModal,
            executeBulkUpload,
            cleanupChapterDnD,
            initChapterDnD,
            reorderChapters
        };
    }

    root.createChapterAdminManager = createChapterAdminManager;
})(window);
