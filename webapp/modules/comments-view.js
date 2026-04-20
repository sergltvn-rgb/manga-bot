(function initCommentsViewModule(global) {
    const root = global.ReaderModules = global.ReaderModules || {};

    function createCommentsView(config) {
        const labels = (config && config.labels) ? config.labels : {};
        const getAllCommentsCache = (config && config.getAllCommentsCache) ? config.getAllCommentsCache : (() => []);
        const getCurrentCommentSort = (config && config.getCurrentCommentSort) ? config.getCurrentCommentSort : (() => 'top');
        const setCurrentCommentSort = (config && config.setCurrentCommentSort) ? config.setCurrentCommentSort : (() => {});
        const getActiveCommentEditId = (config && config.getActiveCommentEditId) ? config.getActiveCommentEditId : (() => null);
        const setActiveCommentEditId = (config && config.setActiveCommentEditId) ? config.setActiveCommentEditId : (() => {});
        const getUserId = (config && config.getUserId) ? config.getUserId : (() => '');
        const getApiUrl = (config && config.getApiUrl) ? config.getApiUrl : (() => '');
        const getIsAdminMode = (config && config.getIsAdminMode) ? config.getIsAdminMode : (() => false);
        const getUserRole = (config && config.getUserRole) ? config.getUserRole : (() => null);
        const formatDate = (config && config.formatDate) ? config.formatDate : ((value) => String(value || ''));
        const escapeHtml = (config && config.escapeHtml) ? config.escapeHtml : ((value) => String(value || ''));
        const applyMarkup = (config && config.applyMarkup) ? config.applyMarkup : ((value) => String(value || ''));

        const saveLabel = labels.save || '\u0421\u043e\u0445\u0440\u0430\u043d\u0438\u0442\u044c';
        const cancelLabel = labels.cancel || '\u041e\u0442\u043c\u0435\u043d\u0430';
        const previewLabel = labels.preview || '\u041f\u0440\u0435\u0434\u043f\u0440\u043e\u0441\u043c\u043e\u0442\u0440:';
        const emptyLabel = labels.empty || '\u041f\u043e\u043a\u0430 \u043a\u043e\u043c\u043c\u0435\u043d\u0442\u0430\u0440\u0438\u0435\u0432 \u043d\u0435\u0442. \u0411\u0443\u0434\u044c\u0442\u0435 \u043f\u0435\u0440\u0432\u044b\u043c!';
        const likeTitle = labels.likeTitle || '\u041d\u0440\u0430\u0432\u0438\u0442\u0441\u044f';
        const deleteLabel = labels.delete || '\u0423\u0434\u0430\u043b\u0438\u0442\u044c';
        const editLabel = labels.edit || '\u0418\u0437\u043c\u0435\u043d\u0438\u0442\u044c';
        const replyLabel = labels.reply || '\u041e\u0442\u0432\u0435\u0442\u0438\u0442\u044c';
        const reportLabel = labels.report || '\u0416\u0430\u043b\u043e\u0431\u0430';

        function parseDate(value) {
            if (!value) return 0;
            const normalized = String(value).includes('T') ? String(value) : String(value).replace(' ', 'T') + 'Z';
            return new Date(normalized).getTime();
        }

        function getAvatarColor(userIdValue) {
            const colors = ['#7785ff', '#ff7f66', '#15aabf', '#63c174', '#c77dff', '#ff6b6b', '#f59f00'];
            if (!userIdValue) return colors[0];
            let hash = 0;
            for (let i = 0; i < userIdValue.length; i++) {
                hash = userIdValue.charCodeAt(i) + ((hash << 5) - hash);
            }
            return colors[Math.abs(hash) % colors.length];
        }

        function findCommentById(id) {
            const comments = getAllCommentsCache() || [];
            return comments.find((comment) => String(comment.id) === String(id));
        }

        function renderNode(comment, isChild) {
            const userName = String(comment.user_name || 'User');
            const initial = userName[0] ? userName[0].toUpperCase() : '?';
            const date = formatDate(comment.created_at);
            const isOwn = String(comment.user_id) === String(getUserId());
            const viewerIsAdmin = !!getIsAdminMode();
            const color = getAvatarColor(String(comment.user_id || ''));

            const role = getUserRole(String(comment.user_id || ''));
            const roleBadge = role ? `<span class="comment-role-badge ${role.css}">${role.text}</span>` : '';

            const deleteBtn = (isOwn || viewerIsAdmin)
                ? `<button class="c-action-btn c-delete" onclick="deleteComment(${comment.id})">${deleteLabel}</button>`
                : '';
            const editBtn = isOwn
                ? `<button class="c-action-btn" onclick="editComment(${comment.id})">${editLabel}</button>`
                : '';

            const safeReplyName = JSON.stringify(userName);
            const replyBtn = `<button class="c-action-btn" onclick="setReply(${comment.id}, ${safeReplyName})">${replyLabel}</button>`;
            const reportBtn = !isOwn
                ? `<button class="c-action-btn" onclick="reportComment(${comment.id})">${reportLabel}</button>`
                : '';

            const likes = comment.likes || 0;
            const userReaction = comment.user_reaction;
            const likeActive = userReaction === 'like' ? 'active' : '';

            const apiUrl = getApiUrl();
            const avatarUrl = apiUrl && comment.user_id ? `${apiUrl}/api/avatar?user_id=${comment.user_id}` : null;
            const avatarHtml = avatarUrl
                ? `<img src="${avatarUrl}" class="comment-avatar" alt="${initial}" style="background:${color}" onerror="this.onerror=null;this.outerHTML='<div class=&quot;comment-avatar&quot; style=&quot;background:${color}&quot;>${initial}</div>';">`
                : `<div class="comment-avatar" style="background:${color}">${initial}</div>`;

            let html = `
                <div class="comment-item ${isChild ? 'comment-reply' : ''}" id="comment-${comment.id}">
                    ${isChild ? '<div class="comment-branch"></div><div class="comment-branch-curve"></div>' : ''}
                    <div class="comment-content">
                        <div class="comment-header">
                            ${avatarHtml}
                            <div class="comment-author">${escapeHtml(userName)}${roleBadge}</div>
                            <div class="comment-date" style="margin-left:auto;">${date}</div>
                        </div>
                        <div class="comment-text" id="comment-text-${comment.id}">${applyMarkup(comment.text || '')}</div>
                        <div class="comment-actions">
                            <div class="comment-reactions">
                                <button class="c-reaction-btn c-like ${likeActive}" onclick="reactToComment(${comment.id}, 'like')" title="${likeTitle}">
                                    <svg class="icon-xs" viewBox="0 0 24 24"><path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3zM7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
                                    <span>${likes}</span>
                                </button>
                            </div>
                            <div class="comment-main-actions">
                                ${replyBtn}
                                ${editBtn}
                                ${deleteBtn}
                                ${reportBtn}
                            </div>
                        </div>
                    </div>
                </div>
            `;

            if (comment.children && comment.children.length > 0) {
                html += `<div class="comment-children">${comment.children.map((child) => renderNode(child, true)).join('')}</div>`;
            }

            return html;
        }

        function renderComments(comments) {
            const list = global.document.getElementById('comments-list');
            if (!list) return;

            const safeComments = Array.isArray(comments) ? comments : [];

            const countBadge = global.document.getElementById('comments-count-badge');
            if (countBadge) {
                countBadge.textContent = safeComments.length > 0 ? `(${safeComments.length})` : '';
            }

            if (safeComments.length === 0) {
                list.innerHTML = `<div class="no-comments">${emptyLabel}</div>`;
                return;
            }

            safeComments.forEach((comment) => {
                if (comment._ts === undefined) {
                    comment._ts = parseDate(comment.created_at);
                }
            });

            const sorted = [...safeComments];
            if (getCurrentCommentSort() === 'top') {
                sorted.sort((a, b) => {
                    const diff = (b.likes || 0) - (a.likes || 0);
                    return diff !== 0 ? diff : b._ts - a._ts;
                });
            } else {
                sorted.sort((a, b) => b._ts - a._ts);
            }

            const commentMap = {};
            const topLevel = [];

            sorted.forEach((comment) => {
                comment.children = [];
                commentMap[comment.id] = comment;
            });

            sorted.forEach((comment) => {
                if (comment.parent_id && commentMap[comment.parent_id]) {
                    commentMap[comment.parent_id].children.push(comment);
                } else {
                    topLevel.push(comment);
                }
            });

            list.innerHTML = topLevel.map((comment) => renderNode(comment, false)).join('');
        }

        function sortComments(type) {
            setCurrentCommentSort(type);

            const topTab = global.document.getElementById('tab-sort-top');
            if (topTab) topTab.classList.toggle('active', type === 'top');

            const newTab = global.document.getElementById('tab-sort-new');
            if (newTab) newTab.classList.toggle('active', type === 'new');

            renderComments(getAllCommentsCache() || []);
        }

        function editComment(id) {
            setActiveCommentEditId(id);

            const comment = findCommentById(id);
            if (!comment) return;

            const textNode = global.document.getElementById(`comment-text-${id}`);
            if (!textNode) return;

            const originalText = comment.text || '';
            textNode.innerHTML = `
                <textarea class="comment-input edit-area" id="edit-input-${id}" rows="3">${escapeHtml(originalText)}</textarea>
                <div class="edit-actions" style="margin-top:8px; display:flex; gap:8px;">
                    <button class="comment-submit-btn" style="float:none; padding:6px 14px;" onclick="saveCommentEdit('${id}')">${saveLabel}</button>
                    <button class="c-action-btn" onclick="cancelEdit('${id}')">${cancelLabel}</button>
                </div>
            `;

            const input = global.document.getElementById(`edit-input-${id}`);
            if (input) input.focus();
        }

        function cancelEdit(id) {
            setActiveCommentEditId(null);

            const comment = findCommentById(id);
            if (comment) {
                const textNode = global.document.getElementById(`comment-text-${id}`);
                if (textNode) {
                    textNode.innerHTML = applyMarkup(comment.text || '');
                }
                return;
            }

            renderComments(getAllCommentsCache() || []);
        }

        function updateCommentPreview() {
            const input = global.document.getElementById('comment-input');
            const preview = global.document.getElementById('comment-preview-area');
            if (!input || !preview) return;

            const value = input.value.trim();
            if (value) {
                preview.classList.remove('hidden');
                preview.innerHTML = '<div style="font-size: 11px; opacity: 0.5; margin-bottom: 4px; font-weight: 700; text-transform: uppercase;">' + previewLabel + '</div>' + applyMarkup(value);
                return;
            }

            preview.classList.add('hidden');
            preview.innerHTML = '';
        }

        function insertFormatting(start, end) {
            const activeEditId = getActiveCommentEditId();
            const inputId = activeEditId ? `edit-input-${activeEditId}` : 'comment-input';
            const input = global.document.getElementById(inputId);
            if (!input) return;

            const startPos = (typeof input.selectionStart === 'number') ? input.selectionStart : input.value.length;
            const endPos = (typeof input.selectionEnd === 'number') ? input.selectionEnd : input.value.length;
            const text = input.value;
            const selectedText = text.substring(startPos, endPos);

            const before = text.substring(0, startPos);
            const after = text.substring(endPos, text.length);

            input.value = before + start + selectedText + end + after;
            input.focus();

            const newPos = startPos + start.length + selectedText.length + end.length;
            if (typeof input.setSelectionRange === 'function') {
                input.setSelectionRange(newPos, newPos);
            }

            updateCommentPreview();
        }

        return {
            renderComments,
            sortComments,
            editComment,
            cancelEdit,
            updateCommentPreview,
            insertFormatting,
            getCurrentCommentSort
        };
    }

    root.createCommentsView = createCommentsView;
})(window);