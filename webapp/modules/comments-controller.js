(function initCommentsControllerModule(global) {
    const root = global.ReaderModules = global.ReaderModules || {};

    function createCommentsController(config) {
        const getApiUrl = (config && config.getApiUrl) ? config.getApiUrl : (() => '');
        const getUserId = (config && config.getUserId) ? config.getUserId : (() => '');
        const getChapterKey = (config && config.getChapterKey) ? config.getChapterKey : (() => '');
        const readerApi = (config && config.readerApi) ? config.readerApi : null;
        const tg = (config && config.tg) ? config.tg : null;

        const showToast = (config && config.showToast) ? config.showToast : (() => {});
        const setAllCommentsCache = (config && config.setAllCommentsCache) ? config.setAllCommentsCache : (() => {});
        const getActiveCommentEditId = (config && config.getActiveCommentEditId)
            ? config.getActiveCommentEditId
            : (() => null);
        const setActiveCommentEditId = (config && config.setActiveCommentEditId)
            ? config.setActiveCommentEditId
            : (() => {});
        const renderComments = (config && config.renderComments) ? config.renderComments : (() => {});

        let commentsReqId = 0;
        let replyingToId = null;

        function hasApi() {
            return !!getApiUrl() && !!readerApi;
        }

        function hasUser() {
            return !!getUserId();
        }

        function setReply(id, name) {
            replyingToId = id;

            const indicator = global.document.getElementById('reply-indicator');
            const nameNode = global.document.getElementById('reply-to-name');
            const input = global.document.getElementById('comment-input');

            if (indicator) indicator.style.display = 'flex';
            if (nameNode) nameNode.textContent = name;
            if (input) input.focus();
        }

        function cancelReply() {
            replyingToId = null;

            const indicator = global.document.getElementById('reply-indicator');
            const nameNode = global.document.getElementById('reply-to-name');

            if (indicator) indicator.style.display = 'none';
            if (nameNode) nameNode.textContent = '';
        }

        async function loadComments() {
            if (!hasApi()) return;

            const key = getChapterKey();
            if (!key) return;

            const reqId = ++commentsReqId;
            try {
                const resp = await readerApi.getComments(key);
                const data = await resp.json();

                if (reqId !== commentsReqId) return;
                if (key !== getChapterKey()) return;

                const comments = data.comments || [];
                setAllCommentsCache(comments);

                const countBadge = global.document.getElementById('comments-count-badge');
                if (countBadge) {
                    countBadge.textContent = comments.length > 0 ? `(${comments.length})` : '';
                }

                if (!getActiveCommentEditId()) {
                    renderComments(comments);
                }
            } catch (e) {
                console.warn('Comments load error:', e);
            }
        }

        function reportComment(id) {
            if (!hasApi()) return;

            const overlay = global.document.createElement('div');
            overlay.className = 'modal-overlay active';
            overlay.style.zIndex = '99999';
            overlay.innerHTML = `
                <div class="modal-container" style="padding: 20px; background: var(--bg); border-radius: 12px; width: 90%; max-width: 400px; margin: auto; position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); box-shadow: var(--shadow);">
                    <h3 style="margin-bottom: 12px; font-size: 18px;">\u0416\u0430\u043b\u043e\u0431\u0430 \u043d\u0430 \u043a\u043e\u043c\u043c\u0435\u043d\u0442\u0430\u0440\u0438\u0439</h3>
                    <p style="margin-bottom: 12px; font-size: 14px; opacity: 0.8;">\u0423\u043a\u0430\u0436\u0438\u0442\u0435 \u043f\u0440\u0438\u0447\u0438\u043d\u0443 \u0436\u0430\u043b\u043e\u0431\u044b (\u0441\u043f\u0430\u043c, \u043e\u0441\u043a\u043e\u0440\u0431\u043b\u0435\u043d\u0438\u044f \u0438 \u0442.\u0434.):</p>
                    <textarea id="report-reason-input" class="comment-input" rows="3" style="width: 100%; box-sizing: border-box; margin-bottom: 16px; border: 1px solid var(--divider); padding: 8px; border-radius: 8px; background: var(--input-bg); color: var(--text);"></textarea>
                    <div style="display: flex; gap: 8px; justify-content: flex-end;">
                        <button class="c-action-btn" id="report-cancel-btn">\u041e\u0442\u043c\u0435\u043d\u0430</button>
                        <button class="comment-submit-btn" id="report-submit-btn" style="float: none;">\u041e\u0442\u043f\u0440\u0430\u0432\u0438\u0442\u044c</button>
                    </div>
                </div>
            `;
            global.document.body.appendChild(overlay);

            const cancelBtn = global.document.getElementById('report-cancel-btn');
            const submitBtn = global.document.getElementById('report-submit-btn');

            if (cancelBtn) {
                cancelBtn.onclick = () => {
                    global.document.body.removeChild(overlay);
                };
            }

            if (submitBtn) {
                submitBtn.onclick = () => {
                    const reasonInput = global.document.getElementById('report-reason-input');
                    const reason = reasonInput ? reasonInput.value.trim() : '';
                    if (!reason) {
                        showToast('\u041f\u0440\u0438\u0447\u0438\u043d\u0430 \u043d\u0435 \u043c\u043e\u0436\u0435\u0442 \u0431\u044b\u0442\u044c \u043f\u0443\u0441\u0442\u043e\u0439');
                        return;
                    }
                    global.document.body.removeChild(overlay);

                    const commentEl = global.document.getElementById(`comment-text-${id}`);
                    const commentText = commentEl ? commentEl.innerText : '';
                    readerApi.reportComment({ comment_id: id, reason, comment_text: commentText })
                        .then((r) => r.json())
                        .then((data) => {
                            if (data.ok) showToast('\u0416\u0430\u043b\u043e\u0431\u0430 \u043e\u0442\u043f\u0440\u0430\u0432\u043b\u0435\u043d\u0430 \u043c\u043e\u0434\u0435\u0440\u0430\u0442\u043e\u0440\u0430\u043c.');
                            else showToast('\u041e\u0448\u0438\u0431\u043a\u0430: ' + data.error);
                        })
                        .catch(() => showToast('\u041e\u0448\u0438\u0431\u043a\u0430 \u0441\u0435\u0442\u0438.'));
                };
            }
        }

        async function reactToComment(commentId, type) {
            if (!hasApi() || !hasUser()) {
                showToast('\u041f\u043e\u0436\u0430\u043b\u0443\u0439\u0441\u0442\u0430, \u0430\u0432\u0442\u043e\u0440\u0438\u0437\u0443\u0439\u0442\u0435\u0441\u044c \u0447\u0435\u0440\u0435\u0437 \u0431\u043e\u0442\u0430.');
                return;
            }

            try {
                const resp = await readerApi.reactToComment(commentId, type);
                const data = await resp.json();
                if (data.ok) {
                    await loadComments();
                } else {
                    showToast('\u041e\u0448\u0438\u0431\u043a\u0430 \u043f\u0440\u0438 \u0440\u0435\u0430\u043a\u0446\u0438\u0438: ' + (data.error || '\u043d\u0435\u0438\u0437\u0432\u0435\u0441\u0442\u043d\u043e'));
                }
            } catch (e) {
                showToast('\u041e\u0448\u0438\u0431\u043a\u0430 \u0441\u0435\u0442\u0438.');
            }
        }

        async function saveCommentEdit(id) {
            const input = global.document.getElementById(`edit-input-${id}`);
            const newText = input ? input.value.trim() : '';
            if (!newText) {
                showToast('\u041a\u043e\u043c\u043c\u0435\u043d\u0442\u0430\u0440\u0438\u0439 \u043d\u0435 \u043c\u043e\u0436\u0435\u0442 \u0431\u044b\u0442\u044c \u043f\u0443\u0441\u0442\u044b\u043c');
                return;
            }

            try {
                const resp = await readerApi.updateComment(id, newText);
                const data = await resp.json();
                if (data.ok) {
                    setActiveCommentEditId(null);
                    await loadComments();
                    showToast('\u041a\u043e\u043c\u043c\u0435\u043d\u0442\u0430\u0440\u0438\u0439 \u0438\u0437\u043c\u0435\u043d\u0435\u043d');
                } else {
                    showToast('\u041e\u0448\u0438\u0431\u043a\u0430: ' + (data.error || '\u043d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c'));
                }
            } catch (e) {
                showToast('\u041e\u0448\u0438\u0431\u043a\u0430 \u0441\u0435\u0442\u0438.');
            }
        }

        async function postComment() {
            if (!hasApi() || !hasUser()) return;

            const input = global.document.getElementById('comment-input');
            const text = input ? input.value.trim() : '';
            if (!text) {
                showToast('\u041a\u043e\u043c\u043c\u0435\u043d\u0442\u0430\u0440\u0438\u0439 \u043d\u0435 \u043c\u043e\u0436\u0435\u0442 \u0431\u044b\u0442\u044c \u043f\u0443\u0441\u0442\u044b\u043c');
                return;
            }

            const key = getChapterKey();
            if (!key) return;

            const btn = global.document.querySelector('.comment-submit-btn');
            if (btn) btn.disabled = true;

            try {
                const resp = await readerApi.createComment({
                    chapter_key: key,
                    text,
                    parent_id: replyingToId
                });

                if (!resp.ok) {
                    const err = await resp.json().catch(() => ({}));
                    throw new Error(err.error || '\u041e\u0448\u0438\u0431\u043a\u0430 \u0441\u0435\u0440\u0432\u0435\u0440\u0430 \u043f\u0440\u0438 \u043e\u0442\u043f\u0440\u0430\u0432\u043a\u0435');
                }

                if (input) input.value = '';
                cancelReply();
                await loadComments();
            } catch (e) {
                console.error('Post comment error:', e);
                if (tg && typeof tg.showAlert === 'function') {
                    tg.showAlert('\u041e\u0448\u0438\u0431\u043a\u0430: ' + e.message);
                } else {
                    showToast('\u041e\u0448\u0438\u0431\u043a\u0430: ' + e.message);
                }
            } finally {
                if (btn) btn.disabled = false;
            }
        }

        async function deleteComment(commentId) {
            if (!hasApi() || !hasUser()) return;

            const isConfirmed = await new Promise((resolve) => {
                if (tg && typeof tg.showConfirm === 'function') {
                    tg.showConfirm('\u0423\u0434\u0430\u043b\u0438\u0442\u044c \u043a\u043e\u043c\u043c\u0435\u043d\u0442\u0430\u0440\u0438\u0439?', resolve);
                } else {
                    resolve(global.confirm('\u0423\u0434\u0430\u043b\u0438\u0442\u044c \u043a\u043e\u043c\u043c\u0435\u043d\u0442\u0430\u0440\u0438\u0439?'));
                }
            });
            if (!isConfirmed) return;

            try {
                const resp = await readerApi.deleteComment(commentId);
                if (!resp.ok) {
                    const errData = await resp.json().catch(() => ({}));
                    throw new Error(errData.error || '\u041e\u0448\u0438\u0431\u043a\u0430 \u0441\u0435\u0440\u0432\u0435\u0440\u0430 \u043f\u0440\u0438 \u0443\u0434\u0430\u043b\u0435\u043d\u0438\u0438');
                }
                await loadComments();
            } catch (e) {
                console.warn('Delete comment error:', e);
                showToast('\u041e\u0448\u0438\u0431\u043a\u0430 \u0443\u0434\u0430\u043b\u0435\u043d\u0438\u044f: ' + e.message);
            }
        }

        return {
            setReply,
            cancelReply,
            loadComments,
            reportComment,
            reactToComment,
            saveCommentEdit,
            postComment,
            deleteComment
        };
    }

    root.createCommentsController = createCommentsController;
})(window);
