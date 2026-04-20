(function initReaderBootstrapModule(global) {
    const root = global.ReaderModules = global.ReaderModules || {};

    function createReaderBootstrapManager(config) {
        const getApiUrl = (config && config.getApiUrl) ? config.getApiUrl : (() => '');
        const getUserId = (config && config.getUserId) ? config.getUserId : (() => '');
        const getUrlParams = (config && config.getUrlParams) ? config.getUrlParams : (() => new URLSearchParams(global.location.search));
        const getTg = (config && config.getTg) ? config.getTg : (() => ({ initDataUnsafe: {} }));

        const readerApi = (config && config.readerApi) ? config.readerApi : null;
        const setServerBookmarks = (config && config.setServerBookmarks) ? config.setServerBookmarks : (() => {});
        const setAllData = (config && config.setAllData) ? config.setAllData : (() => {});
        const getAllData = (config && config.getAllData) ? config.getAllData : (() => ({ series: [] }));
        const setAdminIds = (config && config.setAdminIds) ? config.setAdminIds : (() => {});

        const renderSeriesList = (config && config.renderSeriesList) ? config.renderSeriesList : (() => {});
        const renderContinueReading = (config && config.renderContinueReading) ? config.renderContinueReading : (() => {});
        const markAppReady = (config && config.markAppReady) ? config.markAppReady : (() => {});

        const setCurrentSeries = (config && config.setCurrentSeries) ? config.setCurrentSeries : (() => {});
        const setCurrentVolume = (config && config.setCurrentVolume) ? config.setCurrentVolume : (() => {});
        const setCurrentChapters = (config && config.setCurrentChapters) ? config.setCurrentChapters : (() => {});
        const openChapter = (config && config.openChapter) ? config.openChapter : (() => {});

        function showEmptyState() {
            const list = global.document.getElementById('series-list');
            if (!list) return;
            list.innerHTML = `
                <div class="empty-state">
                    <div class="empty-icon">📚</div>
                    <h3>Библиотека пуста</h3>
                    <p>Данные ещё не загружены. Добавьте главы через бота или разместите файл chapters_data.json в папке webapp.</p>
                </div>
            `;
        }

        function handleStartParam() {
            const tg = getTg();
            const urlParams = getUrlParams();
            const start = tg.initDataUnsafe?.start_param || urlParams.get('tgWebAppStartParam');
            if (!start) return;

            const match = start.match(/^chapter_([^_]+)_([^_]+)_([^_]+)$/);
            if (!match) return;

            const [, seriesId, volumeNum, chapterKey] = match;
            const allData = getAllData() || { series: [] };
            const seriesList = Array.isArray(allData.series) ? allData.series : [];
            const series = seriesList.find((item) => String(item.id) === String(seriesId));
            if (!series) return;

            const volume = (series.volumes || []).find((item) => String(item.volume) === String(volumeNum));
            if (!volume) return;

            const chapters = volume.chapters || [];
            const chapterIdx = chapters.findIndex((item) => String(item.chapter) === String(chapterKey));

            setCurrentSeries(series);
            setCurrentVolume(volume);
            setCurrentChapters(chapters);

            if (chapterIdx !== -1) {
                openChapter(chapterIdx);
            } else if (chapters.length > 0) {
                openChapter(0);
            }
        }

        async function loadData() {
            console.log('Starting loadData...');

            const getTimeoutSignal = (ms) => {
                if (global.AbortSignal && typeof global.AbortSignal.timeout === 'function') {
                    return global.AbortSignal.timeout(ms);
                }
                const controller = new AbortController();
                setTimeout(() => controller.abort(), ms);
                return controller.signal;
            };

            const apiUrl = getApiUrl();
            const userId = getUserId();

            if (apiUrl && userId && readerApi && typeof readerApi.getProgress === 'function') {
                console.log('Fetching progress from API...');
                try {
                    const response = await readerApi.getProgress({ signal: getTimeoutSignal(5000) });
                    if (response.ok) {
                        const payload = await response.json();
                        setServerBookmarks(payload.bookmarks || []);
                    } else {
                        console.warn('Progress API returned status:', response.status);
                    }
                } catch (error) {
                    console.warn('Bookmarks load warning:', error);
                }
            }

            if (apiUrl && readerApi && typeof readerApi.getReader === 'function') {
                console.log('Fetching reader data from API:', apiUrl + '/api/reader');
                try {
                    const response = await readerApi.getReader({ signal: getTimeoutSignal(10000) });
                    if (response.ok) {
                        const payload = await response.json();
                        setAllData(payload || { series: [] });

                        if (Array.isArray(payload.admin_ids)) {
                            setAdminIds(payload.admin_ids.map((id) => String(id)));
                        }

                        if (payload.series && payload.series.length > 0) {
                            renderSeriesList();
                            renderContinueReading();
                            markAppReady('api');
                            handleStartParam();
                            return;
                        }
                        console.log('API returned empty series list, falling back to JSON...');
                    } else {
                        console.warn('Reader API returned status:', response.status);
                    }
                } catch (error) {
                    console.warn('API fetch error or timeout:', error);
                }
            } else {
                console.log('No API_URL configured, skipping API fetch.');
            }

            console.log('Fetching fallback chapters_data.json...');
            try {
                const response = await global.fetch('chapters_data.json?v=' + Date.now(), {
                    signal: getTimeoutSignal(5000)
                });
                if (response.ok) {
                    const payload = await response.json();
                    setAllData(payload || { series: [] });
                    if (payload.series && payload.series.length > 0) {
                        renderSeriesList();
                        renderContinueReading();
                        markAppReady('fallback_json');
                        handleStartParam();
                        return;
                    }
                } else {
                    console.warn('Fallback JSON fetch failed with status:', response.status);
                }
            } catch (error) {
                console.error('Fallback JSON fetch error:', error);
            }

            console.log('All data sources failed or empty, showing empty state.');
            markAppReady('empty_state');
            showEmptyState();
        }

        return {
            loadData,
            showEmptyState,
            handleStartParam
        };
    }

    root.createReaderBootstrapManager = createReaderBootstrapManager;
})(window);
