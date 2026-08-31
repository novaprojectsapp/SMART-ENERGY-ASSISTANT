const API_BASE = '/api/v1';

const api = {
    async get(path) {
        try {
            const res = await fetch(`${API_BASE}${path}`);
            if (!res.ok) {
                const err = await res.json().catch(() => ({ error: res.statusText }));
                throw new Error(err.detail || err.error || 'Request failed');
            }
            return res.json();
        } catch (e) {
            if (e.name === 'TypeError' && e.message.includes('fetch')) {
                throw new Error('Server unreachable');
            }
            throw e;
        }
    },

    async post(path, data) {
        try {
            const res = await fetch(`${API_BASE}${path}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data),
            });
            if (!res.ok) {
                const err = await res.json().catch(() => ({ error: res.statusText }));
                throw new Error(err.detail || err.error || 'Request failed');
            }
            return res.json();
        } catch (e) {
            if (e.name === 'TypeError' && e.message.includes('fetch')) {
                throw new Error('Server unreachable');
            }
            throw e;
        }
    },

    async put(path, data) {
        try {
            const res = await fetch(`${API_BASE}${path}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data),
            });
            if (!res.ok) {
                const err = await res.json().catch(() => ({ error: res.statusText }));
                throw new Error(err.detail || err.error || 'Request failed');
            }
            return res.json();
        } catch (e) {
            if (e.name === 'TypeError' && e.message.includes('fetch')) {
                throw new Error('Server unreachable');
            }
            throw e;
        }
    },

    async DELETE(path) {
        try {
            const res = await fetch(`${API_BASE}${path}`, { method: 'DELETE' });
            if (!res.ok) {
                const err = await res.json().catch(() => ({ error: res.statusText }));
                throw new Error(err.detail || err.error || 'Request failed');
            }
            return res.json();
        } catch (e) {
            if (e.name === 'TypeError' && e.message.includes('fetch')) {
                throw new Error('Server unreachable');
            }
            throw e;
        }
    },

    health: () => api.get('/health'),
    getDevices: () => api.get('/devices'),
    getDevice: (id) => api.get(`/devices/${id}`),
    getDeviceStatus: (id) => api.get(`/devices/${id}/status`),
    getLatestReadings: () => api.get('/readings/latest'),
    getDeviceReadings: (id, limit = 50) => api.get(`/devices/${id}/readings?limit=${limit}`),
    getAnalyticsSummary: (deviceId) => api.get(`/analytics/summary${deviceId ? '?device_id=' + deviceId : ''}`),
    getHourlyData: (days, deviceId) => api.get(`/analytics/hourly?days=${days}${deviceId ? '&device_id=' + deviceId : ''}`),
    getDailyData: (days, deviceId) => api.get(`/analytics/daily?days=${days}${deviceId ? '&device_id=' + deviceId : ''}`),
    getAnomalies: (deviceId) => api.get(`/analytics/anomalies${deviceId ? '?device_id=' + deviceId : ''}`),
    getPatterns: (deviceId) => api.get(`/analytics/patterns${deviceId ? '?device_id=' + deviceId : ''}`),
    getBillingToday: (deviceId) => api.get(`/billing/today${deviceId ? '?device_id=' + deviceId : ''}`),
    getBillingPredict: (days, deviceId) => api.get(`/billing/predict?days=${days}${deviceId ? '&device_id=' + deviceId : ''}`),
    getBillingTariff: () => api.get('/billing/tariff'),
    getAiInsights: (deviceId) => api.get(`/ai/insights${deviceId ? '?device_id=' + deviceId : ''}`),
    getApplianceActivity: () => api.get('/appliances/activity'),
    getApplianceModels: () => api.get('/appliances/models'),
    voiceQuery: (text, deviceId) => api.post('/voice/query', { text, device_id: deviceId }),
    getRecommendations: (deviceId) => api.get(`/recommendations${deviceId ? '?device_id=' + deviceId : ''}`),
    simulateWhatIf: (reductionPercent, deviceId) => api.post('/what-if', { reduction_percent: reductionPercent, device_id: deviceId }),
    getSettings: () => api.get('/settings'),
    getReports: (days, deviceId) => api.get(`/reports/energy-summary?days=${days}${deviceId ? '&device_id=' + deviceId : ''}`),
    getAppliances: () => api.get('/appliances'),
    createAppliance: (data) => api.post('/appliances', data),
    updateAppliance: (id, data) => api.put(`/appliances/${id}`, data),
    deleteAppliance: (id) => api.DELETE(`/appliances/${id}`),
    controlAppliance: (applianceId, action, source = 'USER') => api.post(`/appliances/${applianceId}/control`, { appliance_id: applianceId, action, source }),
    getSchedules: () => api.get('/schedules'),
    createSchedule: (data) => api.post('/schedules', data),
    updateSchedule: (id, data) => api.put(`/schedules/${id}`, data),
    deleteSchedule: (id) => api.DELETE(`/schedules/${id}`),
    enableSchedule: (id) => api.post(`/schedules/${id}/enable`),
    disableSchedule: (id) => api.post(`/schedules/${id}/disable`),
    getControlCommands: (limit = 50) => api.get(`/control-commands?limit=${limit}`),
    runScheduler: () => api.post('/scheduler/run'),
};
