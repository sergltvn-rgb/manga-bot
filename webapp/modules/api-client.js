(function initApiClientModule(global) {
    const root = global.ReaderModules = global.ReaderModules || {};

    function nowTs() {
        if (typeof global.performance !== 'undefined' && global.performance.now) {
            return global.performance.now();
        }
        return Date.now();
    }

    function createApiFetch(config) {
        const getTg = (config && config.getTg) ? config.getTg : (() => null);
        const telemetry = (config && config.telemetry) ? config.telemetry : null;

        return async function apiFetch(url, options = {}) {
            if (typeof global.navigator !== 'undefined' && !global.navigator.onLine) {
                throw new Error('Offline');
            }

            options.headers = options.headers || {};
            const tg = getTg();
            if (tg && tg.initData) {
                options.headers['Authorization'] = 'tma ' + tg.initData;
            }

            const startedAt = nowTs();
            const endpoint = telemetry?.normalizeMetricEndpoint
                ? telemetry.normalizeMetricEndpoint(url)
                : '';
            const isMetricsEndpoint = endpoint.includes('/api/metrics/');

            try {
                const response = await fetch(url, options);
                const elapsed = Math.max(0, Math.round(nowTs() - startedAt));
                if (!isMetricsEndpoint && telemetry?.queueMetric) {
                    telemetry.queueMetric('client_api_call_ms', elapsed, { endpoint, status: response.status });
                    if (!response.ok) {
                        telemetry.queueMetric('client_api_error', 1, { endpoint, status: response.status });
                    }
                }
                return response;
            } catch (e) {
                const elapsed = Math.max(0, Math.round(nowTs() - startedAt));
                if (!isMetricsEndpoint && telemetry?.queueMetric) {
                    telemetry.queueMetric('client_api_call_ms', elapsed, { endpoint, status: 0 });
                    telemetry.queueMetric('client_api_error', 1, {
                        endpoint,
                        status: 0,
                        meta: { error: e?.name || 'fetch_error' }
                    });
                }
                throw e;
            }
        };
    }

    root.createApiFetch = createApiFetch;
})(window);
