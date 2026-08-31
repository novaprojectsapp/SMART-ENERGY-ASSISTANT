let analyticsInterval = null;

function safeNum(value, fallback = 0) {
    const n = Number(value);
    return Number.isFinite(n) ? n : fallback;
}

function fmt(value, digits = 2, fallback = '0.00') {
    const n = safeNum(value);
    if (!Number.isFinite(n)) return fallback;
    return n.toFixed(digits);
}

async function loadAnalytics() {
    const summaryEl = document.getElementById('analytics-summary');
    const dailyEl = document.getElementById('analytics-daily');
    const patternsEl = document.getElementById('analytics-patterns');
    const anomaliesEl = document.getElementById('analytics-anomalies');

    try {
        const summary = await api.getAnalyticsSummary();
        renderAnalyticsSummary(summaryEl, summary);

        const daily = await api.getDailyData(7);
        renderDailyChart(dailyEl, daily);

        const patterns = await api.getPatterns();
        renderPatterns(patternsEl, patterns);

        const anomalies = await api.getAnomalies();
        renderAnomalies(anomaliesEl, anomalies);
    } catch (e) {
        showError(summaryEl, e.message);
    }
}

function renderAnalyticsSummary(container, data) {
    if (data.data_source === 'NO_DATA') {
        showEmpty(container, '📊', 'No Data Available', 'Connect your device to see analytics.');
        return;
    }

    container.innerHTML = `
        <div class="section-card">
            <div class="section-card-header">
                <span class="section-card-title">Energy Summary</span>
                <span class="section-badge measured">MEASURED</span>
            </div>
            <div class="dashboard-grid">
                <div class="stat-card">
                    <div class="stat-card-header"><span class="stat-card-label">Today</span></div>
                    <div class="stat-card-value">${fmt(data.energy && data.energy.today_kwh)}<span class="unit">kWh</span></div>
                </div>
                <div class="stat-card">
                    <div class="stat-card-header"><span class="stat-card-label">This Week</span></div>
                    <div class="stat-card-value">${fmt(data.energy && data.energy.week_kwh)}<span class="unit">kWh</span></div>
                </div>
                <div class="stat-card">
                    <div class="stat-card-header"><span class="stat-card-label">This Month</span></div>
                    <div class="stat-card-value">${fmt(data.energy && data.energy.month_kwh)}<span class="unit">kWh</span></div>
                </div>
                <div class="stat-card">
                    <div class="stat-card-header"><span class="stat-card-label">Avg Daily</span></div>
                    <div class="stat-card-value">${fmt(data.energy && data.energy.avg_daily_kwh)}<span class="unit">kWh</span></div>
                </div>
                <div class="stat-card">
                    <div class="stat-card-header"><span class="stat-card-label">Peak Power</span></div>
                    <div class="stat-card-value">${fmt(data.power && data.power.peak_watts_today, 0, '0')}<span class="unit">W</span></div>
                </div>
                <div class="stat-card">
                    <div class="stat-card-header"><span class="stat-card-label">Today's Cost</span></div>
                    <div class="stat-card-value">₹${fmt(data.cost && data.cost.today_energy_charge)}</div>
                </div>
            </div>
        </div>`;
}

function renderDailyChart(container, data) {
    if (!data.daily_data || data.daily_data.length === 0) {
        showEmpty(container, '📈', 'No Daily Data', 'Need at least one day of data.');
        return;
    }

    let html = `
        <div class="section-card">
            <div class="section-card-header">
                <span class="section-card-title">Daily Energy (Last 7 Days)</span>
            </div>
            <div style="display:flex;gap:12px;align-items:flex-end;height:200px;padding:0 8px;">`;

    const maxKwh = Math.max(...data.daily_data.map(d => safeNum(d.kwh)), 0.1);

    data.daily_data.forEach(d => {
        const kwh = safeNum(d.kwh);
        const height = Math.max(4, (kwh / maxKwh) * 180);
        const dateLabel = d.date ? d.date.slice(5) : '';
        html += `
            <div style="flex:1;display:flex;flex-direction:column;align-items:center;gap:4px;">
                <span style="font-size:11px;color:var(--text-secondary);">${kwh.toFixed(2)}</span>
                <div style="width:100%;height:${height}px;background:linear-gradient(to top,var(--accent),#8b5cf6);border-radius:4px 4px 0 0;min-height:4px;"></div>
                <span style="font-size:10px;color:var(--text-muted);writing-mode:vertical-lr;text-orientation:mixed;">${dateLabel}</span>
            </div>`;
    });

    html += '</div></div>';
    container.innerHTML = html;
}

function renderPatterns(container, data) {
    if (data.status === 'INSUFFICIENT_DATA') {
        showEmpty(container, '🔄', 'No Pattern Data', 'Need more readings for pattern analysis.');
        return;
    }

    let html = `
        <div class="section-card">
            <div class="section-card-header">
                <span class="section-card-title">Usage Pattern (24h)</span>
                <span class="section-badge calculated">CALCULATED</span>
            </div>
            <div style="display:flex;gap:4px;align-items:flex-end;height:160px;padding:0 8px;">`;

    const maxP = Math.max(...data.hourly_profile.map(h => safeNum(h.avg_power)), 1);

    data.hourly_profile.forEach(h => {
        const avgPower = safeNum(h.avg_power);
        const height = Math.max(2, (avgPower / maxP) * 140);
        const color = avgPower > maxP * 0.8 ? 'var(--danger)' : avgPower > maxP * 0.5 ? 'var(--warning)' : 'var(--accent)';
        html += `
            <div style="flex:1;display:flex;flex-direction:column;align-items:center;gap:2px;">
                <div style="width:100%;height:${height}px;background:${color};border-radius:2px 2px 0 0;min-height:1px;opacity:0.8;"></div>
                ${h.hour % 6 === 0 ? `<span style="font-size:9px;color:var(--text-muted);">${h.hour}h</span>` : ''}
            </div>`;
    });

    html += '</div></div>';
    container.innerHTML = html;
}

function renderAnomalies(container, data) {
    if (data.status === 'INSUFFICIENT_DATA') {
        showEmpty(container, '🔍', 'No Anomaly Data', 'Need at least 10 readings for anomaly detection.');
        return;
    }

    let html = `
        <div class="section-card">
            <div class="section-card-header">
                <span class="section-card-title">Anomaly Detection</span>
                <span class="section-badge ${data.anomalies.length > 0 ? 'predicted' : 'measured'}">
                    ${data.anomalies.length > 0 ? 'ANOMALIES FOUND' : 'NORMAL'}
                </span>
            </div>`;

    if (data.anomalies.length === 0) {
        html += `<p style="color:var(--text-secondary);padding:12px 0;">No anomalies detected. Usage is within normal range.</p>`;
    } else {
        html += '<div class="insight-list">';
        data.anomalies.slice(0, 5).forEach(a => {
            html += `
                <div class="insight-item">
                    <div class="insight-dot ${a.type === 'HIGH' ? 'high' : 'info'}"></div>
                    <div>
                        <div class="insight-message">${a.type} anomaly: ${fmt(a.power, 1, '0.0')}W at ${a.timestamp ? formatDate(a.timestamp) : 'unknown time'}</div>
                        <div class="insight-source">Deviation: ${a.deviation}σ from mean</div>
                    </div>
                </div>`;
        });
        html += '</div>';
    }

    html += '</div>';
    container.innerHTML = html;
}

function initAnalytics() {
    loadAnalytics();
}

function destroyAnalytics() {
    if (analyticsInterval) {
        clearInterval(analyticsInterval);
        analyticsInterval = null;
    }
}
