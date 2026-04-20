(function initReaderApiModule(global) {
    const root = global.ReaderModules = global.ReaderModules || {};

    function jsonOptions(method, payload) {
        return {
            method,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        };
    }

    function createReaderApi(config) {
        const apiUrl = (config && typeof config.apiUrl === 'string') ? config.apiUrl : '';
        const apiFetch = (config && config.apiFetch) ? config.apiFetch : null;

        function request(path, options) {
            if (typeof apiFetch !== 'function') {
                throw new Error('apiFetch is required');
            }
            return apiFetch(`${apiUrl}${path}`, options);
        }

        return {
            requestRename(objId) {
                return request('/api/rename/request', jsonOptions('POST', { obj_id: objId }));
            },
            resetRename(objId) {
                return request('/api/rename', jsonOptions('DELETE', { obj_id: objId }));
            },
            saveProgress(payload) {
                return request('/api/progress', jsonOptions('POST', payload));
            },
            getProgress(options = {}) {
                return request('/api/progress', options);
            },
            getReader(options = {}) {
                return request('/api/reader', options);
            },
            getLikes(chapterKey) {
                return request(`/api/likes?chapter_key=${encodeURIComponent(chapterKey)}`);
            },
            toggleLike(chapterKey) {
                return request('/api/likes', jsonOptions('POST', { chapter_key: chapterKey }));
            },
            getComments(chapterKey) {
                return request(`/api/comments?chapter_key=${encodeURIComponent(chapterKey)}`);
            },
            reportComment(payload) {
                return request('/api/comments/report', jsonOptions('POST', payload));
            },
            reactToComment(commentId, type) {
                return request('/api/comments/react', jsonOptions('POST', { comment_id: commentId, type }));
            },
            updateComment(commentId, text) {
                return request(`/api/comments/${commentId}`, jsonOptions('PUT', { text }));
            },
            createComment(payload) {
                return request('/api/comments', jsonOptions('POST', payload));
            },
            deleteComment(commentId) {
                return request('/api/comments', jsonOptions('DELETE', { comment_id: commentId }));
            },
            getReactions(chapterKey) {
                return request(`/api/reactions?chapter_key=${encodeURIComponent(chapterKey)}`);
            },
            setReaction(chapterKey, reaction) {
                return request('/api/reactions', jsonOptions('POST', { chapter_key: chapterKey, reaction }));
            },
            updateChapter(payload) {
                return request('/api/chapters', jsonOptions('PUT', payload));
            },
            bulkCreateChapters(payload) {
                return request('/api/chapters/bulk', jsonOptions('POST', payload));
            },
            sortChapters(payload) {
                return request('/api/sort', jsonOptions('PUT', payload));
            },
            submitTypo(payload) {
                return request('/api/typo', jsonOptions('POST', payload));
            }
        };
    }

    root.createReaderApi = createReaderApi;
})(window);
