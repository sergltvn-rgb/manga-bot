(function initReaderMetaModule(global) {
    const root = global.ReaderModules = global.ReaderModules || {};

    function createReaderMetaManager(config) {
        const getDocument = (config && config.getDocument) ? config.getDocument : (() => global.document);
        const getAdminIds = (config && config.getAdminIds) ? config.getAdminIds : (() => []);
        const setIsAdminMode = (config && config.setIsAdminMode) ? config.setIsAdminMode : (() => {});
        const renderSeriesList = (config && config.renderSeriesList) ? config.renderSeriesList : (() => {});
        const renderContinueReading = (config && config.renderContinueReading) ? config.renderContinueReading : (() => {});
        const renderVolumeTabs = (config && config.renderVolumeTabs) ? config.renderVolumeTabs : (() => {});
        const renderChaptersList = (config && config.renderChaptersList) ? config.renderChaptersList : (() => {});

        function toggleAdminMode(enabled) {
            setIsAdminMode(!!enabled);

            const doc = getDocument();
            if (!doc) return;

            const screenSeries = doc.getElementById('screen-series');
            if (screenSeries && screenSeries.classList.contains('active')) {
                renderSeriesList();
            }

            const screenChapters = doc.getElementById('screen-chapters');
            if (screenChapters && enabled) {
                screenChapters.classList.add('admin-enabled');
            }

            renderContinueReading();

            if (screenChapters && screenChapters.classList.contains('active')) {
                renderVolumeTabs();
                renderChaptersList();
            }
        }

        function getUserRole(userIdStr) {
            const adminIds = getAdminIds();
            if (Array.isArray(adminIds) && adminIds.includes(userIdStr)) {
                return { text: '\u0410\u0434\u043c\u0438\u043d', css: 'badge-admin' };
            }
            return null;
        }

        function formatDate(dateStr) {
            if (!dateStr) return '';
            try {
                const safeDateStr = dateStr.includes('T') ? dateStr : dateStr.replace(' ', 'T') + 'Z';
                const date = new Date(safeDateStr);
                const now = new Date();
                const diff = now - date;
                const mins = Math.floor(diff / 60000);

                if (mins < 1) return '\u0442\u043e\u043b\u044c\u043a\u043e \u0447\u0442\u043e';
                if (mins < 60) return `${mins} \u043c\u0438\u043d. \u043d\u0430\u0437\u0430\u0434`;

                const hours = Math.floor(mins / 60);
                if (hours < 24) return `${hours} \u0447. \u043d\u0430\u0437\u0430\u0434`;

                const days = Math.floor(hours / 24);
                if (days < 7) return `${days} \u0434\u043d. \u043d\u0430\u0437\u0430\u0434`;

                return date.toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' });
            } catch (e) {
                return dateStr;
            }
        }

        return {
            toggleAdminMode,
            getUserRole,
            formatDate
        };
    }

    root.createReaderMetaManager = createReaderMetaManager;
})(window);
