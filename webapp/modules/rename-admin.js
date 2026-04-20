(function initRenameAdminModule(global) {
    const root = global.ReaderModules = global.ReaderModules || {};

    function createRenameAdminManager(config) {
        const getApiUrl = (config && config.getApiUrl) ? config.getApiUrl : (() => '');
        const getAllData = (config && config.getAllData) ? config.getAllData : (() => ({}));
        const getTelegramWebApp = (config && config.getTelegramWebApp)
            ? config.getTelegramWebApp
            : (() => (global.Telegram && global.Telegram.WebApp ? global.Telegram.WebApp : null));
        const readerApi = (config && config.readerApi) ? config.readerApi : null;
        const showToast = (config && config.showToast) ? config.showToast : (() => {});
        const loadData = (config && config.loadData) ? config.loadData : (async () => {});
        const confirmFn = (config && config.confirmFn) ? config.confirmFn : ((message) => global.confirm(message));

        async function renameItem(objId) {
            if (!getApiUrl()) {
                showToast('\u041f\u0435\u0440\u0435\u0438\u043c\u0435\u043d\u043e\u0432\u0430\u043d\u0438\u0435 \u0434\u043e\u0441\u0442\u0443\u043f\u043d\u043e \u0442\u043e\u043b\u044c\u043a\u043e \u043f\u0440\u0438 \u043f\u043e\u0434\u043a\u043b\u044e\u0447\u0435\u043d\u043d\u043e\u043c API.');
                return;
            }
            if (!readerApi) return;

            try {
                const resp = await readerApi.requestRename(objId);
                const data = await resp.json();
                if (data.ok) {
                    const allData = getAllData() || {};
                    const botUsername = allData.bot_username || 'Alyamangapage_bot';
                    const tg = getTelegramWebApp();
                    const url = 'https://t.me/' + botUsername + '?start=ren_' + data.short_id;
                    if (tg && typeof tg.openTelegramLink === 'function') {
                        tg.openTelegramLink(url);
                    } else {
                        global.open(url, '_blank');
                    }
                    if (tg && typeof tg.close === 'function') {
                        tg.close();
                    }
                } else {
                    showToast('\u041e\u0448\u0438\u0431\u043a\u0430: ' + (data.error || '\u043d\u0435\u0438\u0437\u0432\u0435\u0441\u0442\u043d\u0430\u044f'));
                }
            } catch (e) {
                const msg = e && e.message ? e.message : 'Unknown error';
                showToast('\u041e\u0448\u0438\u0431\u043a\u0430 \u0441\u0435\u0442\u0438: ' + msg);
            }
        }

        async function resetCustomName(objId) {
            if (!getApiUrl()) {
                showToast('\u0421\u0431\u0440\u043e\u0441 \u0434\u043e\u0441\u0442\u0443\u043f\u0435\u043d \u0442\u043e\u043b\u044c\u043a\u043e \u0447\u0435\u0440\u0435\u0437 \u043f\u0440\u044f\u043c\u043e\u0435 \u043f\u043e\u0434\u043a\u043b\u044e\u0447\u0435\u043d\u0438\u0435 (\u043d\u0435 GitHub Pages).');
                return;
            }
            if (!readerApi) return;

            const ok = confirmFn(`\u0421\u0431\u0440\u043e\u0441\u0438\u0442\u044c \u043a\u0430\u0441\u0442\u043e\u043c\u043d\u043e\u0435 \u0438\u043c\u044f \"${objId}\" \u043d\u0430 \u0434\u0435\u0444\u043e\u043b\u0442?`);
            if (!ok) return;

            try {
                const resp = await readerApi.resetRename(objId);
                const result = await resp.json();
                if (result.ok) {
                    await loadData();
                    showToast('\u2705 \u0418\u043c\u044f \u0441\u0431\u0440\u043e\u0448\u0435\u043d\u043e \u043d\u0430 \u0434\u0435\u0444\u043e\u043b\u0442.');
                } else {
                    showToast('\u041e\u0448\u0438\u0431\u043a\u0430: ' + (result.error || '\u043d\u0435\u0438\u0437\u0432\u0435\u0441\u0442\u043d\u0430\u044f'));
                }
            } catch (e) {
                const msg = e && e.message ? e.message : 'Unknown error';
                showToast('\u041e\u0448\u0438\u0431\u043a\u0430 \u0441\u0435\u0442\u0438: ' + msg);
            }
        }

        return {
            renameItem,
            resetCustomName
        };
    }

    root.createRenameAdminManager = createRenameAdminManager;
})(window);
