(function initFeedbackUiModule(global) {
    const root = global.ReaderModules = global.ReaderModules || {};

    function createFeedbackUiManager(config) {
        const getDocument = (config && config.getDocument)
            ? config.getDocument
            : (() => global.document);

        const getTelegramWebApp = (config && config.getTelegramWebApp)
            ? config.getTelegramWebApp
            : (() => global.Telegram && global.Telegram.WebApp ? global.Telegram.WebApp : null);

        function haptic(style = 'light') {
            try {
                const tg = getTelegramWebApp();
                if (!tg || !tg.HapticFeedback) return;

                if (style === 'success') tg.HapticFeedback.notificationOccurred('success');
                else if (style === 'error') tg.HapticFeedback.notificationOccurred('error');
                else tg.HapticFeedback.impactOccurred(style);
            } catch (e) {
                // noop
            }
        }

        function showToast(message, type = 'info') {
            const doc = getDocument();
            if (!doc) return;

            const container = doc.getElementById('toast-container');
            if (!container) return;

            const toast = doc.createElement('div');
            toast.className = `toast toast-${type}`;

            let icon = '';
            if (type === 'success') icon = '<svg class="icon-sm" viewBox="0 0 24 24"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/><polyline points="22 4 12 14.01 9 11.01" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>';
            else if (type === 'error') icon = '<svg class="icon-sm" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10" fill="none" stroke="currentColor" stroke-width="2"/><line x1="15" y1="9" x2="9" y2="15" fill="none" stroke="currentColor" stroke-width="2"/><line x1="9" y1="9" x2="15" y2="15" fill="none" stroke="currentColor" stroke-width="2"/></svg>';
            else icon = '<svg class="icon-sm" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10" fill="none" stroke="currentColor" stroke-width="2"/><line x1="12" y1="16" x2="12" y2="12" fill="none" stroke="currentColor" stroke-width="2"/><line x1="12" y1="8" x2="12.01" y2="8" fill="none" stroke="currentColor" stroke-width="2"/></svg>';

            toast.innerHTML = `${icon}<span>${message}</span>`;
            container.appendChild(toast);

            global.setTimeout(() => toast.classList.add('show'), 10);
            global.setTimeout(() => {
                toast.classList.remove('show');
                global.setTimeout(() => toast.remove(), 400);
            }, 3000);
        }

        return {
            haptic,
            showToast
        };
    }

    root.createFeedbackUiManager = createFeedbackUiManager;
})(window);
