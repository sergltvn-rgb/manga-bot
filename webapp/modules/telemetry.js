(function initTelemetryModule(global) {
    const root = global.ReaderModules = global.ReaderModules || {};

    function nowTs() {
        if (typeof global.performance !== 'undefined' && global.performance.now) {
            return global.performance.now();
        }
        return Date.now();
    }

    function normalizeMetricEndpoint(url) {
        try {
            const base = (global.location && global.location.origin) ? global.location.origin : '';
            const parsed = new URL(url, base);
            return parsed.pathname || '';
        } catch (e) {
            const raw = String(url || '');
            if (raw.startsWith('/')) return raw.split('?')[0];
            const idx = raw.indexOf('/api/');
            if (idx >= 0) return raw.slice(idx).split('?')[0];
            return raw.slice(0, 120);
        }
    }

    function createTelemetryManager(config) {
        const getApiUrl = (config && config.getApiUrl) ? config.getApiUrl : (() => '');
        const getUserId = (config && config.getUserId) ? config.getUserId : (() => '');
        const getAuthHeader = (config && config.getAuthHeader) ? config.getAuthHeader : (() => '');
        const appBootStartedAt = (config && Number.isFinite(config.appBootStartedAt))
            ? config.appBootStartedAt
            : nowTs();

        let appReadyMetricSent = false;
        let chapterOpenStartedAt = 0;
        let chapterOpenMetricCtx = null;
        const state = {
            queue: [],
            flushTimer: null,
            isFlushing: false
        };

        function telemetryEnabled() {
            return !!getApiUrl() && !!getUserId();
        }

        function scheduleMetricsFlush(delayMs = 3500) {
            if (!telemetryEnabled()) return;
            clearTimeout(state.flushTimer);
            state.flushTimer = setTimeout(() => {
                flushMetrics();
            }, delayMs);
        }

        function queueMetric(metric, value, extra = {}) {
            if (!telemetryEnabled()) return;
            const num = Number(value);
            if (!Number.isFinite(num)) return;

            state.queue.push({
                metric,
                value: num,
                endpoint: extra.endpoint || '',
                status: Number.isFinite(Number(extra.status)) ? Number(extra.status) : null,
                meta: extra.meta || {}
            });

            if (state.queue.length > 120) {
                state.queue = state.queue.slice(-120);
            }

            if (state.queue.length >= 20) {
                flushMetrics();
            } else {
                scheduleMetricsFlush();
            }
        }

        async function flushMetrics(force = false) {
            if (!telemetryEnabled()) return;
            if (state.isFlushing) return;
            if (state.queue.length === 0) return;
            if (typeof global.navigator !== 'undefined' && !global.navigator.onLine) return;

            const apiUrl = getApiUrl();
            if (!apiUrl) return;

            state.isFlushing = true;
            clearTimeout(state.flushTimer);

            const maxBatch = force ? 60 : 30;
            const batch = state.queue.splice(0, maxBatch);
            try {
                const headers = { 'Content-Type': 'application/json' };
                const authHeader = getAuthHeader();
                if (authHeader) headers['Authorization'] = authHeader;

                const resp = await fetch(`${apiUrl}/api/metrics/client`, {
                    method: 'POST',
                    headers,
                    body: JSON.stringify({ events: batch }),
                    keepalive: !!force
                });
                if (!resp.ok) {
                    state.queue = batch.concat(state.queue).slice(-120);
                }
            } catch (e) {
                state.queue = batch.concat(state.queue).slice(-120);
            } finally {
                state.isFlushing = false;
                if (state.queue.length > 0) {
                    scheduleMetricsFlush(2000);
                }
            }
        }

        function markAppReady(source = 'unknown') {
            if (appReadyMetricSent) return;
            appReadyMetricSent = true;
            const ttiMs = Math.max(0, Math.round(nowTs() - appBootStartedAt));
            queueMetric('client_tti_ms', ttiMs, { meta: { source } });
        }

        function startChapterOpenMetric(chapter, ctx = {}) {
            chapterOpenStartedAt = nowTs();
            chapterOpenMetricCtx = {
                series_id: ctx.seriesId || '',
                volume: ctx.volume || '',
                chapter: chapter?.chapter || ''
            };
        }

        function completeChapterOpenMetric() {
            if (!chapterOpenStartedAt || !chapterOpenMetricCtx) return;
            const elapsed = Math.max(0, Math.round(nowTs() - chapterOpenStartedAt));
            queueMetric('client_chapter_open_ms', elapsed, {
                endpoint: '/chapter/open',
                meta: chapterOpenMetricCtx
            });
            chapterOpenStartedAt = 0;
            chapterOpenMetricCtx = null;
        }

        return {
            telemetryEnabled,
            normalizeMetricEndpoint,
            queueMetric,
            flushMetrics,
            markAppReady,
            startChapterOpenMetric,
            completeChapterOpenMetric
        };
    }

    root.createTelemetryManager = createTelemetryManager;
})(window);
