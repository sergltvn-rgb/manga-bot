(function initLibraryViewModule(global) {
    const root = global.ReaderModules = global.ReaderModules || {};

    function createLibraryViewManager(config) {
        const getAllData = (config && config.getAllData) ? config.getAllData : (() => ({ series: [] }));
        const getServerBookmarks = (config && config.getServerBookmarks) ? config.getServerBookmarks : (() => []);
        const isRead = (config && config.isRead) ? config.isRead : (() => false);
        const safeGetLocal = (config && config.safeGetLocal) ? config.safeGetLocal : (() => ({}));
        const safeSetLocal = (config && config.safeSetLocal) ? config.safeSetLocal : (() => {});
        const escapeHtml = (config && config.escapeHtml) ? config.escapeHtml : ((value) => String(value || ''));

        let readingStats = safeGetLocal('reader_stats', { timeSpentSeconds: 0 });
        if (!readingStats || typeof readingStats !== 'object') {
            readingStats = { timeSpentSeconds: 0 };
        }
        if (typeof readingStats.timeSpentSeconds !== 'number') {
            readingStats.timeSpentSeconds = 0;
        }

        let tickerStarted = false;
        let tickerId = null;

        function startReadingStatsTicker() {
            if (tickerStarted) return;
            tickerStarted = true;

            tickerId = global.setInterval(() => {
                const readerScreen = global.document.getElementById('screen-reader');
                if (readerScreen && readerScreen.classList.contains('active') && !global.document.hidden) {
                    readingStats.timeSpentSeconds += 5;
                    if (readingStats.timeSpentSeconds % 60 === 0) {
                        safeSetLocal('reader_stats', readingStats);
                        updateLibraryStats();
                    }
                }
            }, 5000);
        }

        function stopReadingStatsTicker() {
            if (tickerId) {
                global.clearInterval(tickerId);
                tickerId = null;
            }
            tickerStarted = false;
        }

        function updateLibraryStats() {
            const timeEl = global.document.getElementById('stat-time');
            const chEl = global.document.getElementById('stat-chapters');
            if (!timeEl || !chEl) return;

            const allData = getAllData() || { series: [] };
            const readMap = safeGetLocal('reader_progress', {});
            const totalChaptersRead = Object.keys(readMap || {}).length;
            chEl.textContent = totalChaptersRead;

            const totalMinutes = Math.floor((readingStats.timeSpentSeconds || 0) / 60);
            const hours = Math.floor(totalMinutes / 60);
            const mins = totalMinutes % 60;

            if (hours > 0) {
                timeEl.textContent = `${hours} ч ${mins} м`;
            } else {
                timeEl.textContent = `${mins} м`;
            }
        }

        function renderLibraryTab() {
            const list = global.document.getElementById('library-list');
            if (!list) return;

            const allData = getAllData() || { series: [] };
            const seriesList = Array.isArray(allData.series) ? allData.series : [];

            if (seriesList.length === 0) {
                list.innerHTML = `
                    <div class="empty-state">
                        <div class="empty-icon">📂</div>
                        <h3>Нет данных</h3>
                        <p>Библиотека пуста. Добавьте свои первые ранобэ.</p>
                    </div>
                `;
                return;
            }

            const allLocal = safeGetLocal('reader_last_read', {});
            const serverBookmarks = getServerBookmarks() || [];

            serverBookmarks.forEach((bm) => {
                if (!allLocal[bm.series_id]) {
                    allLocal[bm.series_id] = {
                        seriesId: bm.series_id,
                        volume: bm.volume_id,
                        chapter: bm.chapter_key,
                        ts: new Date(bm.updated_at).getTime() || 0,
                        isServer: true
                    };
                }
            });

            const activeSeriesKeys = Object.keys(allLocal).sort((a, b) => (allLocal[b].ts || 0) - (allLocal[a].ts || 0));

            if (activeSeriesKeys.length === 0) {
                list.innerHTML = `
                    <div class="empty-state">
                        <div class="empty-icon">📝</div>
                        <h3>Вы ещё ничего не читали</h3>
                        <p>Откройте Главную, чтобы выбрать историю.</p>
                    </div>
                `;
                return;
            }

            const itemsHtml = activeSeriesKeys.slice(0, 10).map((key) => {
                const bm = allLocal[key];
                const series = seriesList.find((item) => String(item.id) === String(bm.seriesId || key));
                if (!series) return '';

                let chapterTitle = 'Глава ' + bm.chapter;
                const volume = (series.volumes || []).find((item) => String(item.volume) === String(bm.volume));
                if (volume) {
                    const ch = (volume.chapters || []).find((item) => String(item.chapter) === String(bm.chapter));
                    if (ch && ch.custom_name) chapterTitle = ch.custom_name;
                    else if (ch) chapterTitle = `Глава ${ch.chapter}`;
                }

                const totalChapters = (series.volumes || []).reduce((sum, vol) => sum + ((vol.chapters || []).length), 0);
                const readCount = (series.volumes || []).reduce((sum, vol) => {
                    return sum + (vol.chapters || []).filter((ch) => isRead(series.id, vol.volume, ch.chapter)).length;
                }, 0);

                const progress = totalChapters > 0 ? Math.round((readCount / totalChapters) * 100) : 0;
                const coverImg = series.cover_url
                    ? `<img src="${series.cover_url}" class="library-cover" alt="">`
                    : `<div class="series-icon">📖</div>`;

                return `
                    <div class="series-card" style="margin-bottom:12px;" onclick="selectSeries('${series.id}')">
                        ${coverImg}
                        <div class="series-info">
                            <h3>${escapeHtml(series.title)}</h3>
                            <p style="font-size: 13px; color: var(--text-sec); margin-top:2px;">Остановлено: Том ${bm.volume}, ${chapterTitle}</p>
                            <div class="library-progress-bar">
                                <div class="library-progress-fill" style="width: ${progress}%"></div>
                            </div>
                            <div style="font-size: 11px; margin-top:4px; text-align:right; color: var(--text-sec);">${progress}% прочитано</div>
                        </div>
                        <span class="series-arrow">&rsaquo;</span>
                    </div>
                `;
            }).join('');

            list.innerHTML = itemsHtml;
        }

        return {
            startReadingStatsTicker,
            stopReadingStatsTicker,
            updateLibraryStats,
            renderLibraryTab
        };
    }

    root.createLibraryViewManager = createLibraryViewManager;
})(window);
