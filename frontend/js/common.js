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

function timeAgo(iso) {
    if (!iso) return 'never';
    const seconds = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
    if (seconds < 60) return `${seconds}s ago`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
    return `${Math.floor(seconds / 86400)}d ago`;
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
