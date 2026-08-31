let analyticsInterval = null;

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
                    <div class="stat-card-value">${data.energy.today_kwh.toFixed(2)}<span class="unit">kWh</span></div>
                </div>
                <div class="stat-card">
                    <div class="stat-card-header"><span class="stat-card-label">This Week</span></div>
                    <div class="stat-card-value">${data.energy.week_kwh.toFixed(2)}<span class="unit">kWh</span></div>
                </div>
                <div class="stat-card">
                    <div class="stat-card-header"><span class="stat-card-label">This Month</span></div>
                    <div class="stat-card-value">${data.energy.month_kwh.toFixed(2)}<span class="unit">kWh</span></div>
                </div>
                <div class="stat-card">
                    <div class="stat-card-header"><span class="stat-card-label">Avg Daily</span></div>
                    <div class="stat-card-value">${data.energy.avg_daily_kwh.toFixed(2)}<span class="unit">kWh</span></div>
                </div>
                <div class="stat-card">
                    <div class="stat-card-header"><span class="stat-card-label">Peak Power</span></div>
                    <div class="stat-card-value">${data.power.peak_watts.toFixed(0)}<span class="unit">W</span></div>
                </div>
                <div class="stat-card">
                    <div class="stat-card-header"><span class="stat-card-label">Today's Cost</span></div>
                    <div class="stat-card-value">₹${data.cost.today_energy_charge.toFixed(2)}</div>
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

    const maxKwh = Math.max(...data.daily_data.map(d => d.kwh), 0.1);

    data.daily_data.forEach(d => {
        const height = Math.max(4, (d.kwh / maxKwh) * 180);
        html += `
            <div style="flex:1;display:flex;flex-direction:column;align-items:center;gap:4px;">
                <span style="font-size:11px;color:var(--text-secondary);">${d.kwh.toFixed(2)}</span>
                <div style="width:100%;height:${height}px;background:linear-gradient(to top,var(--accent),#8b5cf6);border-radius:4px 4px 0 0;min-height:4px;"></div>
                <span style="font-size:10px;color:var(--text-muted);writing-mode:vertical-lr;text-orientation:mixed;">${d.date.slice(5)}</span>
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

    const maxP = Math.max(...data.hourly_profile.map(h => h.avg_power), 1);

    data.hourly_profile.forEach(h => {
        const height = Math.max(2, (h.avg_power / maxP) * 140);
        const color = h.avg_power > maxP * 0.8 ? 'var(--danger)' : h.avg_power > maxP * 0.5 ? 'var(--warning)' : 'var(--accent)';
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
                        <div class="insight-message">${a.type} anomaly: ${a.power.toFixed(1)}W at ${formatDate(a.timestamp)}</div>
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
