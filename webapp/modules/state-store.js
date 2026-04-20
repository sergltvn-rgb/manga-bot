(function initStateStoreModule(global) {
    const root = global.ReaderModules = global.ReaderModules || {};

    function createStateStore(config) {
        const defaults = (config && config.defaults) ? config.defaults : {};

        function getLocal(key, defaultVal) {
            try {
                const val = global.localStorage.getItem(key);
                return val ? JSON.parse(val) : defaultVal;
            } catch (e) {
                return defaultVal;
            }
        }

        function setLocal(key, val) {
            try {
                global.localStorage.setItem(key, JSON.stringify(val));
            } catch (e) {
                // ignore quota/private mode errors
            }
        }

        function migrateSettings(settings) {
            const next = Object.assign({}, settings || {});
            if (!next.lineHeight) next.lineHeight = 1.8;
            if (!next.textAlign) next.textAlign = 'left';
            if (next.indent === undefined) next.indent = true;
            if (next.paraSpacing === undefined) next.paraSpacing = 20;
            if (next.letterSpacing === undefined) next.letterSpacing = 0;
            if (next.paraIndent === undefined) next.paraIndent = 25;
            if (next.dimmerValue === undefined) next.dimmerValue = 0;
            if (next.readingMode === undefined) next.readingMode = 'scroll';
            return next;
        }

        function loadSettings() {
            let settings;
            try {
                settings = JSON.parse(global.localStorage.getItem('reader_settings') || 'null') || Object.assign({}, defaults);
            } catch (e) {
                settings = Object.assign({}, defaults);
            }
            return migrateSettings(settings);
        }

        function saveSettings(settings) {
            setLocal('reader_settings', settings || {});
        }

        function loadReadProgress() {
            try {
                return JSON.parse(global.localStorage.getItem('reader_progress') || '{}');
            } catch (e) {
                return {};
            }
        }

        function saveReadProgress(progress) {
            setLocal('reader_progress', progress || {});
        }

        function getReadKey(seriesId, volume, chapter) {
            return `${seriesId}_v${volume}_ch${chapter}`;
        }

        return {
            getLocal,
            setLocal,
            loadSettings,
            saveSettings,
            loadReadProgress,
            saveReadProgress,
            getReadKey
        };
    }

    root.createStateStore = createStateStore;
})(window);
