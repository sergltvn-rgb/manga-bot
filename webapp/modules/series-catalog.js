(function initSeriesCatalogModule(global) {
    const root = global.ReaderModules = global.ReaderModules || {};

    function createSeriesCatalogManager(config) {
        const doc = global.document;
        const nav = global.navigator || {};
        const hasTouchInput = ('ontouchstart' in global)
            || ((nav && typeof nav.maxTouchPoints === 'number') ? nav.maxTouchPoints > 0 : false)
            || ((nav && typeof nav.msMaxTouchPoints === 'number') ? nav.msMaxTouchPoints > 0 : false);

        const getAllData = (config && config.getAllData) ? config.getAllData : (() => ({ series: [] }));
        const getCurrentSeries = (config && config.getCurrentSeries) ? config.getCurrentSeries : (() => null);
        const setCurrentSeries = (config && config.setCurrentSeries) ? config.setCurrentSeries : (() => {});
        const getCurrentVolume = (config && config.getCurrentVolume) ? config.getCurrentVolume : (() => null);
        const setCurrentVolume = (config && config.setCurrentVolume) ? config.setCurrentVolume : (() => {});
        const setCurrentChapters = (config && config.setCurrentChapters) ? config.setCurrentChapters : (() => {});

        const getIsAdminMode = (config && config.getIsAdminMode) ? config.getIsAdminMode : (() => false);
        const getApiUrl = (config && config.getApiUrl) ? config.getApiUrl : (() => '');

        const getLastRead = (config && config.getLastRead) ? config.getLastRead : (() => null);
        const isRead = (config && config.isRead) ? config.isRead : (() => false);
        const escapeHtml = (config && config.escapeHtml) ? config.escapeHtml : ((value) => String(value || ''));

        const renameItem = (config && config.renameItem) ? config.renameItem : (() => {});
        const resetCustomName = (config && config.resetCustomName) ? config.resetCustomName : (() => {});
        const showScreen = (config && config.showScreen) ? config.showScreen : (() => {});
        const openEditUrlModal = (config && config.openEditUrlModal) ? config.openEditUrlModal : (() => {});
        const openBulkModal = (config && config.openBulkModal) ? config.openBulkModal : (() => {});
        const initChapterDnD = (config && config.initChapterDnD) ? config.initChapterDnD : (() => {});
        const cleanupChapterDnD = (config && config.cleanupChapterDnD) ? config.cleanupChapterDnD : (() => {});
        const openChapter = (config && config.openChapter) ? config.openChapter : (() => {});
        const showEmptyState = (config && config.showEmptyState) ? config.showEmptyState : (() => {});

        let chapterActivationBound = false;
        let lastTouchChapterOpenAt = 0;

        function isChapterControlTarget(target) {
            if (!target || !target.closest) return false;
            return !!target.closest('.admin-edit-btn, .admin-reset-btn, .admin-link-btn, .drag-handle');
        }

        function resolveChapterIdx(eventTarget) {
            if (!eventTarget || !eventTarget.closest) return null;
            if (isChapterControlTarget(eventTarget)) return null;

            const item = eventTarget.closest('.chapter-item');
            if (!item) return null;

            const idx = parseInt(item.dataset.chapterIdx, 10);
            return Number.isInteger(idx) ? idx : null;
        }

        function bindChapterActivation(container) {
            if (!container || chapterActivationBound) return;
            chapterActivationBound = true;

            container.addEventListener('click', (event) => {
                if (Date.now() - lastTouchChapterOpenAt < 450) return;
                const idx = resolveChapterIdx(event.target);
                if (idx === null) return;

                event.preventDefault();
                openChapter(idx);
            });

            container.addEventListener('touchend', (event) => {
                const idx = resolveChapterIdx(event.target);
                if (idx === null) return;

                lastTouchChapterOpenAt = Date.now();
                event.preventDefault();
                openChapter(idx);
            }, { passive: false });
        }

        function renderSeriesList() {
            const container = doc.getElementById('series-list');
            if (!container) return;

            const allData = getAllData() || { series: [] };
            const seriesList = Array.isArray(allData.series) ? allData.series : [];

            if (seriesList.length === 0) {
                showEmptyState();
                return;
            }

            container.innerHTML = seriesList.map((series, idx) => {
                const volumes = Array.isArray(series.volumes) ? series.volumes : [];
                const totalChapters = volumes.reduce((sum, volume) => sum + ((volume.chapters || []).length), 0);
                const readCount = volumes.reduce((sum, volume) => {
                    return sum + (volume.chapters || []).filter((chapter) => isRead(series.id, volume.volume, chapter.chapter)).length;
                }, 0);
                const progress = totalChapters > 0 ? Math.round((readCount / totalChapters) * 100) : 0;

                const lastRead = getLastRead(series.id);
                const continueBadge = lastRead
                    ? `<span class="continue-badge">&#9654; \u041f\u0440\u043e\u0434\u043e\u043b\u0436\u0438\u0442\u044c &middot; \u0413\u043b. ${escapeHtml(lastRead.chapter)}</span>`
                    : '';

                const safeSeriesId = String(series.id).replace(/\\/g, '\\\\').replace(/'/g, "\\'");
                const isAdminMode = !!getIsAdminMode();
                const editButtons = isAdminMode ? `
                    <button class="admin-edit-btn" title="\u041f\u0435\u0440\u0435\u0438\u043c\u0435\u043d\u043e\u0432\u0430\u0442\u044c" onclick="renameItem('series_${safeSeriesId}'); event.stopPropagation();">&#9998;</button>
                    <button class="admin-reset-btn" title="\u0421\u0431\u0440\u043e\u0441 \u0438\u043c\u0435\u043d\u0438" onclick="resetCustomName('series_${safeSeriesId}'); event.stopPropagation();">&#8635;</button>
                ` : '';
                const customBadge = isAdminMode ? `<span class="custom-name-badge">\u0441\u0435\u0440\u0438\u044f</span>` : '';
                const coverElement = series.cover_url
                    ? `<img src="${series.cover_url}" class="series-cover-img" alt="${escapeHtml(series.title)}" loading="lazy">`
                    : `<div class="series-icon">${['\uD83D\uDCD6', '\uD83D\uDCD5', '\uD83D\uDCD7', '\uD83D\uDCD8', '\uD83D\uDCD9'][idx % 5]}</div>`;

                return `
                    <div class="series-card" onclick="selectSeries('${safeSeriesId}')">
                        ${coverElement}
                        <div class="series-info">
                            <h3>${escapeHtml(series.title)}${customBadge}${editButtons}</h3>
                            <p>${volumes.length} \u0442\u043e\u043c(\u043e\u0432) &middot; ${totalChapters} \u0433\u043b\u0430\u0432${progress > 0 ? ` &middot; ${progress}%` : ''}</p>
                            ${continueBadge}
                        </div>
                        <span class="series-arrow">&rsaquo;</span>
                    </div>
                `;
            }).join('');
        }

        function selectSeries(seriesId) {
            const allData = getAllData() || { series: [] };
            const seriesList = Array.isArray(allData.series) ? allData.series : [];
            const nextSeries = seriesList.find((series) => String(series.id) === String(seriesId));
            setCurrentSeries(nextSeries || null);
            if (!nextSeries) return;

            const title = doc.getElementById('chapters-title');
            if (title) title.textContent = nextSeries.title;

            renderVolumeTabs();

            const lastRead = getLastRead(seriesId);
            if (lastRead) {
                const volume = (nextSeries.volumes || []).find((item) => String(item.volume) === String(lastRead.volume));
                if (volume) {
                    selectVolume(lastRead.volume);
                    showScreen('chapters');
                    return;
                }
            }

            if ((nextSeries.volumes || []).length > 0) {
                selectVolume(nextSeries.volumes[0].volume);
            }

            showScreen('chapters');
        }

        function renderVolumeTabs() {
            const tabs = doc.getElementById('volume-tabs');
            const currentSeries = getCurrentSeries();
            if (!tabs || !currentSeries) return;

            const volumes = Array.isArray(currentSeries.volumes) ? currentSeries.volumes : [];
            if (volumes.length <= 1) {
                tabs.style.display = 'none';
                return;
            }

            tabs.style.display = 'flex';
            tabs.innerHTML = volumes.map((volume) => {
                const volumeName = volume.custom_name || `\u0422\u043e\u043c ${volume.volume}`;
                const hasCustomName = !!volume.custom_name;
                const isAdminMode = !!getIsAdminMode();
                const safeSeriesId = String(currentSeries.id).replace(/\\/g, '\\\\').replace(/'/g, "\\'");
                const editButtons = isAdminMode ? `
                    <button class="admin-edit-btn" title="\u041f\u0435\u0440\u0435\u0438\u043c\u0435\u043d\u043e\u0432\u0430\u0442\u044c" onclick="renameItem('vol_${safeSeriesId}_${volume.volume}'); event.stopPropagation();">&#9998;</button>
                    ${hasCustomName ? `<button class="admin-reset-btn" title="\u0421\u0431\u0440\u043e\u0441" onclick="resetCustomName('vol_${safeSeriesId}_${volume.volume}'); event.stopPropagation();">&#8635;</button>` : ''}
                ` : '';

                return `
                    <button class="vol-tab" data-vol="${volume.volume}" onclick="selectVolume(${volume.volume})">
                        ${hasCustomName && isAdminMode ? '<span class="custom-name-badge">\u043a\u0430\u0441\u0442\u043e\u043c</span>' : ''}${escapeHtml(volumeName)}${editButtons}
                    </button>
                `;
            }).join('');
        }

        function selectVolume(volumeNum) {
            const currentSeries = getCurrentSeries();
            if (!currentSeries) return;

            const nextVolume = (currentSeries.volumes || []).find((volume) => String(volume.volume) === String(volumeNum));
            setCurrentVolume(nextVolume || null);
            if (!nextVolume) return;

            doc.querySelectorAll('.vol-tab').forEach((tab) => {
                tab.classList.toggle('active', parseInt(tab.dataset.vol, 10) === parseInt(volumeNum, 10));
            });

            renderChaptersList();
        }

        function renderChaptersList() {
            cleanupChapterDnD();

            const container = doc.getElementById('chapters-list');
            const currentSeries = getCurrentSeries();
            const currentVolume = getCurrentVolume();
            if (!container || !currentSeries || !currentVolume) return;

            const chapters = Array.isArray(currentVolume.chapters) ? currentVolume.chapters : [];
            setCurrentChapters(chapters);

            if (chapters.length === 0) {
                container.innerHTML = `
                    <div class="empty-state">
                        <div class="empty-icon">\uD83D\uDCEC</div>
                        <h3>\u041d\u0435\u0442 \u0433\u043b\u0430\u0432</h3>
                        <p>\u0412 \u044d\u0442\u043e\u043c \u0442\u043e\u043c\u0435 \u043f\u043e\u043a\u0430 \u043d\u0435\u0442 \u0433\u043b\u0430\u0432.</p>
                    </div>
                `;
                return;
            }

            const lastRead = getLastRead(currentSeries.id);
            const lastChapter = lastRead && String(lastRead.volume) === String(currentVolume.volume) ? lastRead.chapter : null;
            const safeSeriesId = String(currentSeries.id).replace(/\\/g, '\\\\').replace(/'/g, "\\'");
            const isAdminMode = !!getIsAdminMode();
            const desktopDnDEnabled = isAdminMode && !hasTouchInput;

            container.innerHTML = chapters.map((chapter, idx) => {
                const readClass = isRead(currentSeries.id, currentVolume.volume, chapter.chapter) ? 'read' : '';
                const chapterName = chapter.custom_name || `\u0413\u043b\u0430\u0432\u0430 ${chapter.chapter}`;
                const hasCustom = !!chapter.custom_name;
                const linkButton = isAdminMode
                    ? `<button class="admin-link-btn" title="\u0420\u0435\u0434\u0430\u043a\u0442\u0438\u0440\u043e\u0432\u0430\u0442\u044c \u0441\u0441\u044b\u043b\u043a\u0443" onclick="openEditUrlModal(${idx}); event.stopPropagation();">&#128279;</button>`
                    : '';
                const editButtons = isAdminMode ? `
                    <button class="admin-edit-btn" title="\u041f\u0435\u0440\u0435\u0438\u043c\u0435\u043d\u043e\u0432\u0430\u0442\u044c" onclick="renameItem('chap_${safeSeriesId}_${currentVolume.volume}_${chapter.chapter}'); event.stopPropagation();">&#9998;</button>
                    ${hasCustom ? `<button class="admin-reset-btn" title="\u0421\u0431\u0440\u043e\u0441 \u043d\u0430 \u0434\u0435\u0444\u043e\u043b\u0442" onclick="resetCustomName('chap_${safeSeriesId}_${currentVolume.volume}_${chapter.chapter}'); event.stopPropagation();">&#8635;</button>` : ''}
                ` : '';
                const customBadge = (isAdminMode && hasCustom) ? '<span class="custom-name-badge">\u043a\u0430\u0441\u0442\u043e\u043c</span>' : '';
                const isCurrent = lastChapter && String(chapter.chapter) === String(lastChapter);

                return `
                    <div class="chapter-item ${readClass}${isCurrent ? ' current-chapter' : ''}" data-chapter-idx="${idx}" ${desktopDnDEnabled ? 'draggable="true"' : ''}>
                        ${isAdminMode ? '<div class="drag-handle" title="\u041f\u0435\u0440\u0435\u0442\u0430\u0449\u0438\u0442\u044c">\u283F</div>' : ''}
                        <div class="chapter-num">${idx + 1}</div>
                        <div class="chapter-name">${escapeHtml(chapterName)}${customBadge}${linkButton}${editButtons}</div>
                        ${isCurrent ? '<span style="font-size:12px;color:var(--accent);font-weight:600;">\u25C4</span>' : ''}
                        <span class="chapter-read-mark">\u2713</span>
                    </div>
                `;
            }).join('');

            if (isAdminMode && getApiUrl()) {
                container.innerHTML += `<button class="admin-bulk-btn" onclick="openBulkModal()">\uD83D\uDCE6 \u041c\u0430\u0441\u0441\u043e\u0432\u043e\u0435 \u0434\u043e\u0431\u0430\u0432\u043b\u0435\u043d\u0438\u0435 \u0433\u043b\u0430\u0432</button>`;
            }

            bindChapterActivation(container);

            if (isAdminMode) {
                initChapterDnD();
            }
        }

        return {
            renderSeriesList,
            selectSeries,
            renderVolumeTabs,
            selectVolume,
            renderChaptersList
        };
    }

    root.createSeriesCatalogManager = createSeriesCatalogManager;
})(window);
