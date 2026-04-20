(function initTextMarkupModule(global) {
    const root = global.ReaderModules = global.ReaderModules || {};

    function createMarkupUtils() {
        function escapeHtml(str) {
            if (!str) return '';
            return String(str)
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;')
                .replace(/'/g, '&#039;');
        }

        function applyMarkup(text) {
            if (!text) return '';
            let html = escapeHtml(text);
            html = html.replace(/\[b\]([\s\S]+?)\[\/b\]/g, '<strong>$1</strong>');
            html = html.replace(/\[i\]([\s\S]+?)\[\/i\]/g, '<em>$1</em>');
            html = html.replace(/\[s\]([\s\S]+?)\[\/s\]/g, '<del>$1</del>');
            html = html.replace(/\|\|([\s\S]+?)\|\|/g, (match, content) => {
                return `<span class="comment-spoiler" onclick="this.classList.toggle('revealed'); event.stopPropagation();">${content}</span>`;
            });
            html = html.replace(/\[quote\]([\s\S]+?)\[\/quote\]/g, '<blockquote class="comment-quote">$1</blockquote>');
            return html;
        }

        return {
            escapeHtml,
            applyMarkup
        };
    }

    root.createMarkupUtils = createMarkupUtils;
})(window);
