function formatPower(w) {
    if (w >= 1000) return { value: (w / 1000).toFixed(2), unit: 'kW' };
    return { value: w.toFixed(2), unit: 'W' };
}

function formatEnergy(kwh) {
    return { value: kwh.toFixed(4), unit: 'kWh' };
}

function formatCurrency(amount, currency = 'INR') {
    if (currency === 'INR') return `₹${amount.toFixed(2)}`;
    return `${currency} ${amount.toFixed(2)}`;
}

function formatVoltage(v) { return { value: v.toFixed(2), unit: 'V' }; }
function formatCurrent(a) { return { value: a.toFixed(3), unit: 'A' }; }
function formatFreq(hz) { return { value: hz.toFixed(2), unit: 'Hz' }; }
function formatPF(pf) { return { value: pf.toFixed(3), unit: '' }; }

function formatDate(iso) {
    if (!iso) return '--';
    const d = new Date(iso);
    return d.toLocaleString();
}

const FRESH_CONNECTED_S = 10;
const FRESH_STALE_S = 60;

function timeAgo(iso) {
    if (!iso) return 'never';
    const seconds = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
    if (seconds < 60) return `${seconds}s ago`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
    return `${Math.floor(seconds / 86400)}d ago`;
}

function freshnessFromDate(iso) {
    if (!iso) return 'NO_DATA';
    const seconds = (Date.now() - new Date(iso).getTime()) / 1000;
    if (seconds < FRESH_CONNECTED_S) return 'CONNECTED';
    if (seconds < FRESH_STALE_S) return 'STALE';
    return 'OFFLINE';
}

function showError(container, message) {
    container.innerHTML = `<div class="error-state">⚠ ${message}</div>`;
}

function showEmpty(container, icon, title, message) {
    container.innerHTML = `
        <div class="empty-state">
            <div class="icon">${icon}</div>
            <h3>${title}</h3>
            <p>${message}</p>
        </div>`;
}

function showLoading(container) {
    container.innerHTML = '<div style="text-align:center;padding:40px;"><div class="loading-spinner"></div></div>';
}

const PRIMARY_DEVICE_ID = 'ESP32-S3-01';

function getPrimaryDevice(devices, latest) {
    const list = Array.isArray(devices) ? devices : [];
    if (list.length === 0) return null;

    // Same priority as the backend /readings/latest endpoint:
    // the first entry of `latest` is the live primary reading.
    if (latest && latest[0]) {
        const viaLive = list.find(d => d.id === latest[0].device_id);
        if (viaLive) return viaLive;
    }

    const byId = list.find(d => d.id === PRIMARY_DEVICE_ID && d.is_active);
    if (byId) return byId;

    const hardwareIds = new Set(
        (latest || [])
            .filter(r => r.data_source === 'HARDWARE')
            .map(r => r.device_id)
    );
    const byHardware = list.find(d => hardwareIds.has(d.id));
    if (byHardware) return byHardware;

    const byStatus = list.find(d => d.status && d.status !== 'NO_DATA');
    if (byStatus) return byStatus;

    return list[0];
}

function updateDeviceStatus(devices, latest) {
    const label = document.getElementById('device-status-label');
    const dot = document.getElementById('status-dot');
    if (!label || !dot) return;

    const device = getPrimaryDevice(devices, latest);
    if (!device) {
        label.textContent = 'No device';
        dot.className = 'status-dot';
        setWifiIndicator('OFFLINE', 'No Device');
        return;
    }

    const live = (latest || []).find(r => r.device_id === device.id);
    let fresh;
    if (live) {
        fresh = freshnessFromDate(live.timestamp);
    } else if (device.status && device.status !== 'NO_DATA') {
        fresh = device.status;
    } else if (device.last_seen) {
        fresh = freshnessFromDate(device.last_seen);
    } else {
        fresh = 'NO_DATA';
    }

    if (fresh === 'CONNECTED') {
        label.textContent = `${device.name} - Online`;
        dot.className = 'status-dot online';
        setWifiIndicator('ONLINE', 'Wi-Fi Connected');
    } else if (fresh === 'STALE') {
        label.textContent = `${device.name} - Updating`;
        dot.className = 'status-dot';
        const lastSeen = device.last_seen ? ` · Last seen ${timeAgo(device.last_seen)}` : '';
        setWifiIndicator('CONNECTING', `ESP32 Updating${lastSeen}`);
    } else if (fresh === 'OFFLINE') {
        label.textContent = `${device.name} - Offline`;
        dot.className = 'status-dot';
        const lastSeen = device.last_seen ? ` · Last seen ${timeAgo(device.last_seen)}` : '';
        setWifiIndicator('OFFLINE', `ESP32 Offline${lastSeen}`);
    } else {
        label.textContent = `${device.name} - No Data`;
        dot.className = 'status-dot';
        setWifiIndicator('CONNECTING', 'Connecting...');
    }
}

function setWifiIndicator(state, text) {
    const el = document.getElementById('wifi-indicator');
    const label = document.getElementById('wifi-status-label');
    if (!el || !label) return;
    label.textContent = text;
    el.setAttribute('data-state', state.toLowerCase());
}

async function refreshHeaderStatus() {
    try {
        const [devices, latest] = await Promise.all([
            api.getDevices(),
            api.getLatestReadings(),
        ]);
        updateDeviceStatus(devices, latest);
    } catch (e) {
        console.error('Header status refresh failed:', e);
    }
}

function setStatusBadge(container, source) {
    const cls = {
        'MEASURED': 'measured',
        'PREDICTED': 'predicted',
        'CALCULATED': 'calculated',
        'NO_DATA': 'no-data',
        'AI-INFERRED': 'calculated',
    }[source] || 'no-data';

    container.innerHTML = `<span class="section-badge ${cls}">${source}</span>`;
}
