(function initSocialInteractionsModule(global) {
    const root = global.ReaderModules = global.ReaderModules || {};

    function createSocialInteractionsManager(config) {
        const getApiUrl = (config && config.getApiUrl) ? config.getApiUrl : (() => '');
        const getUserId = (config && config.getUserId) ? config.getUserId : (() => '');
        const getChapterKey = (config && config.getChapterKey) ? config.getChapterKey : (() => '');
        const readerApi = (config && config.readerApi) ? config.readerApi : null;

        const updateLikeUI = (config && config.updateLikeUI) ? config.updateLikeUI : (() => {});
        const spawnFloatingEmoji = (config && config.spawnFloatingEmoji) ? config.spawnFloatingEmoji : (() => {});
        const haptic = (config && config.haptic) ? config.haptic : (() => {});
        const showToast = (config && config.showToast) ? config.showToast : (() => {});
        const onLikeError = (config && config.onLikeError) ? config.onLikeError : (() => {});
        const onReactionError = (config && config.onReactionError) ? config.onReactionError : (() => {});

        const getLikeButton = (config && config.getLikeButton)
            ? config.getLikeButton
            : (() => (global.document ? global.document.getElementById('like-btn') : null));

        const getReactionItem = (config && config.getReactionItem)
            ? config.getReactionItem
            : ((type) => (global.document ? global.document.querySelector(`.reaction-item.type-${type}`) : null));

        const getReactionBar = (config && config.getReactionBar)
            ? config.getReactionBar
            : (() => (global.document ? global.document.getElementById('reaction-bar') : null));

        let likesReqId = 0;
        let reactionsReqId = 0;
        let isReacting = false;

        const reactionEmojiMap = {
            like: '\u{1F44D}',
            heart: '\u2764\uFE0F',
            fire: '\u{1F525}',
            funny: '\u{1F602}',
            wow: '\u{1F62E}',
            sad: '\u{1F622}',
            battle: '\u2694\uFE0F'
        };

        const reactionView = [
            { type: 'like', text: '\u041d\u0440\u0430\u0432\u0438\u0442\u0441\u044f', svg: '<svg class="r-svg" viewBox="0 0 24 24"><path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3zM7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"/></svg>' },
            { type: 'heart', text: '\u041b\u044e\u0431\u043e\u0432\u044c', svg: '<svg class="r-svg" viewBox="0 0 24 24"><path d="M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.3 1.5 4.05 3 5.5l7 7Z"/></svg>' },
            { type: 'fire', text: '\u041e\u0433\u043e\u043d\u044c', svg: '<svg class="r-svg" viewBox="0 0 24 24"><path d="M8.5 14.5A2.5 2.5 0 0 0 11 12c0-1.38-.5-2-1-3-1.072-2.143-.224-4.054 2-6 .5 2.5 2 4.9 4 6.5 2 1.6 3 3.5 3 5.5a7 7 0 1 1-14 0c0-1.153.433-2.294 1-3a2.5 2.5 0 0 0 2.5 2.5z"/></svg>' },
            { type: 'funny', text: '\u0421\u043c\u0435\u0448\u043d\u043e', svg: '<svg class="r-svg" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><path d="M8 14s1.5 2 4 2 4-2 4-2"/><line x1="9" x2="9.01" y1="9" y2="9"/><line x1="15" x2="15.01" y1="9" y2="9"/></svg>' },
            { type: 'wow', text: '\u0412\u0430\u0443', svg: '<svg class="r-svg" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><path d="M8 15h8"/><line x1="9" x2="9.01" y1="9" y2="9"/><line x1="15" x2="15.01" y1="9" y2="9"/></svg>' },
            { type: 'sad', text: '\u0413\u0440\u0443\u0441\u0442\u043d\u043e', svg: '<svg class="r-svg" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10"/><path d="M16 16s-1.5-2-4-2-4 2-4 2"/><line x1="9" x2="9.01" y1="9" y2="9"/><line x1="15" x2="15.01" y1="9" y2="9"/></svg>' },
            { type: 'battle', text: '\u0411\u0438\u0442\u0432\u0430', svg: '<svg class="r-svg" viewBox="0 0 24 24"><polyline points="14.5 17.5 3 6 3 3 6 3 17.5 14.5"/><line x1="13" x2="19" y1="19" y2="13"/><line x1="16" x2="20" y1="16" y2="20"/><line x1="19" x2="21" y1="21" y2="19"/></svg>' }
        ];

        function hasApi() {
            return !!getApiUrl();
        }

        function hasUser() {
            return !!getUserId();
        }

        function renderReactions(data) {
            const bar = getReactionBar();
            if (!bar) return;

            const reactions = (data && data.reactions) ? data.reactions : {};
            const userReaction = data ? data.user_reaction : null;

            bar.innerHTML = reactionView.map((item) => {
                const count = reactions[item.type] || 0;
                const active = userReaction === item.type ? 'active' : '';
                return `
                    <div class="reaction-item ${active} type-${item.type}" onclick="toggleReaction('${item.type}')" title="${item.text}">
                        <div class="reaction-icon-wrapper">${item.svg}</div>
                        <span class="reaction-count">${count > 0 ? count : ''}</span>
                    </div>
                `;
            }).join('');
        }

        async function loadLikes() {
            if (!hasApi() || !readerApi) return;
            const key = getChapterKey();
            if (!key) return;

            const reqId = ++likesReqId;
            try {
                const resp = await readerApi.getLikes(key);
                const data = await resp.json();
                if (reqId !== likesReqId) return;
                if (key !== getChapterKey()) return;
                updateLikeUI(data.count, data.liked);
            } catch (e) {
                onLikeError(e);
            }
        }

        async function toggleLike() {
            if (!hasApi() || !hasUser() || !readerApi) return;
            const key = getChapterKey();
            if (!key) return;

            try {
                const resp = await readerApi.toggleLike(key);
                const data = await resp.json();
                if (key !== getChapterKey()) return;

                const btn = getLikeButton();
                if (btn && data.liked) {
                    btn.classList.add('just-liked');
                    spawnFloatingEmoji('\u2764\uFE0F', btn);
                }
                setTimeout(() => {
                    if (btn) btn.classList.remove('just-liked');
                }, 500);

                updateLikeUI(data.count, data.liked);
            } catch (e) {
                onLikeError(e);
            }
        }

        async function loadReactions() {
            if (!hasApi() || !readerApi) return;
            const key = getChapterKey();
            if (!key) return;

            const reqId = ++reactionsReqId;
            try {
                const resp = await readerApi.getReactions(key);
                const data = await resp.json();
                if (reqId !== reactionsReqId) return;
                if (key !== getChapterKey()) return;
                renderReactions(data);
            } catch (e) {
                onReactionError(e);
            }
        }

        async function toggleReaction(type) {
            if (!hasApi() || !hasUser() || !readerApi) {
                showToast('\u0410\u0432\u0442\u043e\u0440\u0438\u0437\u0443\u0439\u0442\u0435\u0441\u044c \u0432 \u0431\u043e\u0442\u0435 \u0434\u043b\u044f \u0440\u0435\u0430\u043a\u0446\u0438\u0439');
                return;
            }
            if (isReacting) return;

            const key = getChapterKey();
            if (!key) return;

            isReacting = true;
            const itemEl = getReactionItem(type);
            haptic('medium');
            if (itemEl && !itemEl.classList.contains('active')) {
                spawnFloatingEmoji(reactionEmojiMap[type] || '\u2728', itemEl);
            }

            try {
                const resp = await readerApi.setReaction(key, type);
                const data = await resp.json();
                if (data.ok) {
                    await loadReactions();
                }
            } catch (e) {
                showToast('\u041e\u0448\u0438\u0431\u043a\u0430 \u0441\u0435\u0442\u0438.');
                onReactionError(e);
            } finally {
                isReacting = false;
            }
        }

        return {
            renderReactions,
            loadLikes,
            toggleLike,
            loadReactions,
            toggleReaction
        };
    }

    root.createSocialInteractionsManager = createSocialInteractionsManager;
})(window);