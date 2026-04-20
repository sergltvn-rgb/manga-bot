(function initLikesUiModule(global) {
    const root = global.ReaderModules = global.ReaderModules || {};

    function createLikesUiManager(config) {
        const getDocument = (config && config.getDocument)
            ? config.getDocument
            : (() => global.document);

        function spawnFloatingEmoji(emoji, targetEl) {
            const doc = getDocument();
            if (!doc || !targetEl) return;

            const rect = targetEl.getBoundingClientRect();
            const count = 6;

            const fragment = doc.createDocumentFragment();
            for (let i = 0; i < count; i++) {
                const el = doc.createElement('div');
                el.className = 'floating-emoji';
                el.innerHTML = emoji;

                const rx = (Math.random() * 60 - 30);
                const ry = (Math.random() * 20 - 10);

                el.style.left = `${rect.left + rect.width / 2 + rx}px`;
                el.style.top = `${rect.top + rect.height / 2 + ry}px`;

                el.style.setProperty('--tx', `${Math.random() * 100 - 50}px`);
                el.style.setProperty('--ty', `-${Math.random() * 150 + 100}px`);
                el.style.setProperty('--r', `${Math.random() * 90 - 45}deg`);
                el.style.setProperty('--r0', `${Math.random() * 40 - 20}deg`);
                el.style.animationDelay = `${Math.random() * 0.2}s`;

                fragment.appendChild(el);
                global.setTimeout(() => el.remove(), 1000);
            }

            if (doc.body) doc.body.appendChild(fragment);
        }

        function spawnFloatingHearts() {
            const doc = getDocument();
            if (!doc) return;
            const btn = doc.getElementById('like-btn');
            spawnFloatingEmoji('\u2764\uFE0F', btn);
        }

        function updateLikeUI(count, liked) {
            const doc = getDocument();
            if (!doc) return;

            const btn = doc.getElementById('like-btn');
            const icon = doc.getElementById('like-icon');
            const countEl = doc.getElementById('like-count');
            if (!btn || !countEl) return;

            btn.classList.toggle('liked', liked);

            if (icon) {
                const path = icon.querySelector('path');
                if (path) {
                    path.setAttribute('fill', liked ? '#ff6b81' : 'none');
                    path.setAttribute('stroke', liked ? '#ff6b81' : 'currentColor');
                }
            }

            countEl.textContent = count > 0 ? count : '';
        }

        return {
            spawnFloatingEmoji,
            spawnFloatingHearts,
            updateLikeUI
        };
    }

    root.createLikesUiManager = createLikesUiManager;
})(window);
