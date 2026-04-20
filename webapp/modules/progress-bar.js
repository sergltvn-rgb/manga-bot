(function initProgressBarModule(global) {
    const root = global.ReaderModules = global.ReaderModules || {};

    function createProgressBarManager(config) {
        const getDocument = (config && config.getDocument)
            ? config.getDocument
            : (() => global.document);

        let progressBarEl = null;

        function getElement() {
            return progressBarEl;
        }

        function setWidth(value) {
            if (!progressBarEl) return;
            progressBarEl.style.width = `${value}%`;
        }

        function initProgressBar() {
            const doc = getDocument();
            if (!doc) return;

            if (!progressBarEl) {
                progressBarEl = doc.getElementById('reading-progress-bar') || doc.querySelector('.reading-progress-bar');
            }

            if (!progressBarEl) {
                progressBarEl = doc.createElement('div');
                progressBarEl.id = 'reading-progress-bar';
                progressBarEl.className = 'reading-progress-bar';
                doc.body.appendChild(progressBarEl);
            }

            progressBarEl.style.width = '0%';
        }

        function updateProgressBar(el) {
            const doc = getDocument();
            if (!progressBarEl || !doc) return;

            let target = el;
            if (!target) target = doc.getElementById('reader-content');
            if (!target) return;

            const max = target.scrollHeight - target.clientHeight;
            const pct = max > 0 ? (target.scrollTop / max) * 100 : 0;
            progressBarEl.style.width = Math.min(100, pct) + '%';
        }

        return {
            getElement,
            setWidth,
            initProgressBar,
            updateProgressBar
        };
    }

    root.createProgressBarManager = createProgressBarManager;
})(window);
