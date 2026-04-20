(function initAppLifecycleModule(global) {
    const root = global.ReaderModules = global.ReaderModules || {};

    function createAppLifecycleManager(config) {
        const getDocument = (config && config.getDocument) ? config.getDocument : (() => global.document);
        const saveScrollPosition = (config && config.saveScrollPosition) ? config.saveScrollPosition : (() => {});
        const flushMetrics = (config && config.flushMetrics) ? config.flushMetrics : (() => {});

        const restoreSettings = (config && config.restoreSettings) ? config.restoreSettings : (() => {});
        const loadData = (config && config.loadData) ? config.loadData : (() => {});
        const initTypoReporter = (config && config.initTypoReporter) ? config.initTypoReporter : (() => {});
        const initFabOutsideClickHandler = (config && config.initFabOutsideClickHandler) ? config.initFabOutsideClickHandler : (() => {});
        const initGestures = (config && config.initGestures) ? config.initGestures : (() => {});
        const initReaderScrollListeners = (config && config.initReaderScrollListeners) ? config.initReaderScrollListeners : (() => {});
        const initReaderContentInteractions = (config && config.initReaderContentInteractions) ? config.initReaderContentInteractions : (() => {});
        const initLightboxInteractions = (config && config.initLightboxInteractions) ? config.initLightboxInteractions : (() => {});
        const initAutoscrollInteractions = (config && config.initAutoscrollInteractions) ? config.initAutoscrollInteractions : (() => {});
        const startReadingStatsTicker = (config && config.startReadingStatsTicker) ? config.startReadingStatsTicker : (() => {});

        let appBootstrapped = false;
        let lifecycleEventsBound = false;

        function bindLifecycleEvents() {
            if (lifecycleEventsBound) return;
            lifecycleEventsBound = true;

            global.addEventListener('beforeunload', () => {
                saveScrollPosition();
                flushMetrics(true);
            });

            const doc = getDocument();
            if (doc) {
                doc.addEventListener('visibilitychange', () => {
                    if (doc.visibilityState === 'hidden') {
                        flushMetrics(true);
                    }
                });
            }
        }

        function bootstrapApp() {
            if (appBootstrapped) return;
            appBootstrapped = true;

            restoreSettings();
            loadData();
            initTypoReporter();
            initFabOutsideClickHandler();
            initGestures();
            initReaderScrollListeners();
            initReaderContentInteractions();
            initLightboxInteractions();
            initAutoscrollInteractions();
            startReadingStatsTicker();
        }

        function initBootstrap() {
            const doc = getDocument();
            if (!doc) {
                bootstrapApp();
                return;
            }

            if (doc.readyState === 'loading') {
                doc.addEventListener('DOMContentLoaded', bootstrapApp, { once: true });
            } else {
                bootstrapApp();
            }
        }

        return {
            bindLifecycleEvents,
            bootstrapApp,
            initBootstrap
        };
    }

    root.createAppLifecycleManager = createAppLifecycleManager;
})(window);
