(function initProgressTrackerModule(global) {
    const root = global.ReaderModules = global.ReaderModules || {};

    function createProgressTrackerManager(config) {
        const doc = global.document;

        const getCurrentSeries = (config && config.getCurrentSeries) ? config.getCurrentSeries : (() => null);
        const getCurrentVolume = (config && config.getCurrentVolume) ? config.getCurrentVolume : (() => null);
        const getCurrentChapterIdx = (config && config.getCurrentChapterIdx) ? config.getCurrentChapterIdx : (() => 0);
        const getCurrentChapters = (config && config.getCurrentChapters) ? config.getCurrentChapters : (() => []);
        const getServerBookmarks = (config && config.getServerBookmarks) ? config.getServerBookmarks : (() => []);
        const getAllData = (config && config.getAllData) ? config.getAllData : (() => ({ series: [] }));
        const safeGetLocal = (config && config.safeGetLocal) ? config.safeGetLocal : (() => ({}));
        const safeSetLocal = (config && config.safeSetLocal) ? config.safeSetLocal : (() => {});
        const getReadChapters = (config && config.getReadChapters) ? config.getReadChapters : (() => ({}));
        const setReadChapters = (config && config.setReadChapters) ? config.setReadChapters : (() => {});
        const getReadKey = (config && config.getReadKey) ? config.getReadKey : ((seriesId, volume, chapter) => `${seriesId}_v${volume}_ch${chapter}`);
        const saveReadProgress = (config && config.saveReadProgress) ? config.saveReadProgress : (() => {});
        const escapeHtml = (config && config.escapeHtml) ? config.escapeHtml : ((value) => String(value || ''));

        function saveLastRead() {
            const series = getCurrentSeries();
            const volume = getCurrentVolume();
            if (!series || !volume) return;

            const chapters = getCurrentChapters();
            const chapterIdx = getCurrentChapterIdx();
            const chapter = chapters[chapterIdx];
            if (!chapter) return;

            const last = {
                seriesId: series.id,
                volume: volume.volume,
                chapterIdx: chapterIdx,
                chapter: chapter.chapter,
                ts: Date.now()
            };

            const all = safeGetLocal('reader_last_read', {});
            all[series.id] = last;
            safeSetLocal('reader_last_read', all);
        }

        function parseServerTimestamp(value) {
            if (!value) return 0;
            const text = String(value);
            const normalized = text.includes('Z') ? text : `${text} UTC`;
            const parsed = new Date(normalized).getTime();
            return Number.isFinite(parsed) ? parsed : 0;
        }

        function getLastRead(seriesId) {
            const all = safeGetLocal('reader_last_read', {});
            const local = all[seriesId];
            const serverBookmarks = getServerBookmarks();
            const serverBookmark = serverBookmarks.find((item) => String(item.series_id) === String(seriesId));

            if (serverBookmark && local) {
                const serverTs = parseServerTimestamp(serverBookmark.updated_at);
                const localTs = local.ts || 0;
                if (serverTs > localTs) {
                    return {
                        seriesId: seriesId,
                        volume: serverBookmark.volume_id,
                        chapter: serverBookmark.chapter_key,
                        scroll: serverBookmark.scroll_pos,
                        isServer: true
                    };
                }
                return local;
            }

            if (serverBookmark) {
                return {
                    seriesId: seriesId,
                    volume: serverBookmark.volume_id,
                    chapter: serverBookmark.chapter_key,
                    scroll: serverBookmark.scroll_pos,
                    isServer: true
                };
            }

            return local || null;
        }

        function markAsRead(seriesId, volume, chapter) {
            const map = getReadChapters() || {};
            map[getReadKey(seriesId, volume, chapter)] = Date.now();
            setReadChapters(map);
            saveReadProgress(map);
        }

        function getLatestBookmark() {
            const serverBookmarks = getServerBookmarks();
            if (Array.isArray(serverBookmarks) && serverBookmarks.length > 0) {
                return serverBookmarks[0];
            }

            const allLocal = safeGetLocal('reader_last_read', {});
            let latestLocal = null;
            let maxTs = 0;
            Object.keys(allLocal || {}).forEach((seriesId) => {
                const item = allLocal[seriesId];
                const ts = item && item.ts ? item.ts : 0;
                if (ts > maxTs) {
                    maxTs = ts;
                    latestLocal = item;
                }
            });

            if (!latestLocal) return null;
            return {
                series_id: latestLocal.seriesId,
                volume_id: latestLocal.volume,
                chapter_key: latestLocal.chapter,
                ts: latestLocal.ts || 0
            };
        }

        function renderContinueReading() {
            const container = doc.getElementById('continue-reading-container');
            if (!container) return;

            const latestBookmark = getLatestBookmark();
            const allData = getAllData() || { series: [] };
            const seriesList = Array.isArray(allData.series) ? allData.series : [];

            if (!latestBookmark || seriesList.length === 0) {
                container.style.display = 'none';
                return;
            }

            const series = seriesList.find((item) => String(item.id) === String(latestBookmark.series_id));
            if (!series) {
                container.style.display = 'none';
                return;
            }

            const volumes = Array.isArray(series.volumes) ? series.volumes : [];
            const volume = volumes.find((item) => String(item.volume) === String(latestBookmark.volume_id));

            let chapterTitle = `Глава ${latestBookmark.chapter_key}`;
            if (volume && Array.isArray(volume.chapters)) {
                const chapterAttr = volume.chapters.find((item) => String(item.chapter) === String(latestBookmark.chapter_key));
                if (chapterAttr && chapterAttr.custom_name) {
                    chapterTitle = chapterAttr.custom_name;
                }
            }

            const volumeTitle = volume && volume.custom_name ? volume.custom_name : `Том ${latestBookmark.volume_id}`;
            const safeSeriesId = String(series.id).replace(/\\/g, '\\\\').replace(/'/g, "\\'");

            container.style.display = 'block';
            container.innerHTML = `
                <div class="continue-reading-card" onclick="selectSeries('${safeSeriesId}')">
                    <div class="continue-reading-icon">🔖</div>
                    <div class="continue-reading-info">
                        <div class="continue-reading-label">Продолжить чтение</div>
                        <h3 class="continue-reading-title">${escapeHtml(series.title)}</h3>
                        <p class="continue-reading-chapter">${escapeHtml(volumeTitle)}, ${escapeHtml(chapterTitle)}</p>
                    </div>
                    <div class="continue-reading-arrow">→</div>
                </div>
            `;
        }

        return {
            saveLastRead,
            getLastRead,
            markAsRead,
            renderContinueReading
        };
    }

    root.createProgressTrackerManager = createProgressTrackerManager;
})(window);
