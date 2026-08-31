let dashboardInterval = null;

async function loadDashboard() {
    const cardsEl = document.getElementById('live-cards');
    const connectionEl = document.getElementById('connection-section');
    const applianceEl = document.getElementById('appliance-section');
    const insightsEl = document.getElementById('insights-section');
    const billingEl = document.getElementById('billing-section');

    try {
        const [devices, latest, health] = await Promise.all([
            api.getDevices(),
            api.getLatestReadings(),
            api.health(),
        ]);

        updateDeviceStatus(devices);
        renderConnectionCard(connectionEl, devices, latest, health);

        if (!latest || latest.length === 0) {
            cardsEl.innerHTML = `
                <div class="waiting-state" style="grid-column: 1 / -1;">
                    <div class="icon">📡</div>
                    <h3>Waiting for Device Data</h3>
                    <p>Connect your ESP32-S3 device to start receiving energy measurements.</p>
                </div>`;
            if (applianceEl) applianceEl.innerHTML = '';
            if (insightsEl) insightsEl.innerHTML = '';
            if (billingEl) billingEl.innerHTML = '';
            return;
        }

        renderLiveCards(cardsEl, latest[0]);
        loadApplianceSection(applianceEl);
        loadInsightsSection(insightsEl);
        loadBillingSection(billingEl);
    } catch (e) {
        cardsEl.innerHTML = `<div class="error-state" style="grid-column: 1 / -1;">⚠ ${e.message}</div>`;
    }
}

function updateDeviceStatus(devices) {
    const label = document.getElementById('device-status-label');
    const dot = document.getElementById('status-dot');
    if (!label || !dot) return;

    if (devices.length === 0) {
        label.textContent = 'No device';
        dot.className = 'status-dot';
        setWifiIndicator('OFFLINE', 'No Device');
        return;
    }

    const d = devices[0];
    if (d.status === 'ONLINE') {
        label.textContent = `${d.name} - Online`;
        dot.className = 'status-dot online';
        setWifiIndicator('ONLINE', 'Wi-Fi Connected');
    } else if (d.status === 'OFFLINE') {
        label.textContent = `${d.name} - Offline`;
        dot.className = 'status-dot';
        const lastSeen = d.last_seen ? ` · Last seen ${timeAgo(d.last_seen)}` : '';
        setWifiIndicator('OFFLINE', `ESP32 Offline${lastSeen}`);
    } else {
        label.textContent = `${d.name} - No Data`;
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

function connectionState(devices) {
    if (!devices || devices.length === 0) return 'NO_DEVICE';
    const d = devices[0];
    if (d.status === 'ONLINE') return 'ONLINE';
    if (d.status === 'OFFLINE') {
        return d.last_seen ? 'STALE_DATA' : 'OFFLINE';
    }
    return 'CONNECTING';
}

function renderConnectionCard(container, devices, latest, health) {
    if (!container) return;
    const device = devices && devices[0];
    const hasReading = latest && latest.length > 0;
    const latestReading = hasReading ? latest[0] : null;
    const dataSource = latestReading && latestReading.data_source ? latestReading.data_source : (hasReading ? 'HARDWARE' : '—');
    const state = connectionState(devices);
    const lastSeen = device && device.last_seen ? timeAgo(device.last_seen) : null;

    const serverDown = !health || health.status !== 'ok';

    const pzemState = hasReading ? 'ok' : 'wait';
    const espState = state === 'ONLINE' ? 'ok' : (state === 'CONNECTING' || state === 'NO_DEVICE' ? 'wait' : 'down');
    const wifiState = state === 'ONLINE' ? 'ok' : (state === 'NO_DEVICE' ? 'wait' : 'down');
    const serverState = !serverDown ? 'ok' : 'down';

    const stateMeta = {
        NO_DEVICE: { label: 'NO DEVICE', tone: 'no-data', hint: 'No ESP32 device has connected to this assistant yet.' },
        CONNECTING: { label: 'CONNECTING', tone: 'connecting', hint: 'Device is registered but has not reported measurements yet.' },
        ONLINE: { label: 'CONNECTED', tone: 'online', hint: 'ESP32 is streaming live measurements over Wi-Fi.' },
        OFFLINE: { label: 'OFFLINE', tone: 'offline', hint: 'Device is registered but has no measurement history.' },
        STALE_DATA: { label: 'STALE DATA', tone: 'offline', hint: lastSeen ? `ESP32 last reported ${lastSeen}. Wi-Fi link is down.` : 'ESP32 has not reported recently. Wi-Fi link is down.' },
    }[state];

    container.innerHTML = `
        <div class="section-card connection-card">
            <div class="section-card-header">
                <span class="section-card-title">Data Connection</span>
                <span class="section-badge ${stateMeta.tone}">${stateMeta.label}</span>
            </div>
            <div class="connection-banner">
                <div class="connection-dot ${stateMeta.tone}"></div>
                <div class="connection-status">
                    <div class="connection-state">${stateMeta.label}</div>
                    <div class="connection-hint">${stateMeta.hint}</div>
                </div>
                <div class="connection-datasource">
                    <span class="ds-label">Data Source</span>
                    <span class="ds-value ${dataSource === 'SIMULATOR' ? 'sim' : ''}">${dataSource}</span>
                </div>
            </div>
            <div class="connection-chain">
                <div class="chain-node ${pzemState}">
                    <div class="chain-icon">🔌</div>
                    <div class="chain-name">PZEM-004T</div>
                    <div class="chain-state">${hasReading ? 'Delivering' : 'Waiting'}</div>
                </div>
                <div class="chain-link ${espState === 'ok' ? 'ok' : 'down'}"></div>
                <div class="chain-node ${espState}">
                    <div class="chain-icon">📟</div>
                    <div class="chain-name">ESP32-S3</div>
                    <div class="chain-state">${espState === 'ok' ? 'Publishing' : state === 'CONNECTING' ? 'Connecting' : 'No signal'}</div>
                </div>
                <div class="chain-link ${wifiState === 'ok' ? 'ok' : 'down'}"></div>
                <div class="chain-node ${wifiState}">
                    <div class="chain-icon">📶</div>
                    <div class="chain-name">Wi-Fi</div>
                    <div class="chain-state">${wifiState === 'ok' ? 'Connected' : 'Disconnected'}</div>
                </div>
                <div class="chain-link ${serverState === 'ok' ? 'ok' : 'down'}"></div>
                <div class="chain-node ${serverState}">
                    <div class="chain-icon">💻</div>
                    <div class="chain-name">Laptop / API</div>
                    <div class="chain-state">${serverState === 'ok' ? 'Server online' : 'Server offline'}</div>
                </div>
            </div>
            <div class="connection-footnote">Measured: PZEM → Serial → ESP32-S3 → Wi-Fi → Laptop → Assistant</div>
        </div>`;
}

function renderLiveCards(container, reading) {
    const p = formatPower(reading.power);
    const v = formatVoltage(reading.voltage);
    const c = formatCurrent(reading.current);

    container.innerHTML = `
        <div class="stat-card live">
            <div class="stat-card-header">
                <span class="stat-card-label">Live Power</span>
                <div class="stat-card-icon power">⚡</div>
            </div>
            <div class="stat-card-value">${p.value}<span class="unit">${p.unit}</span></div>
            <div class="stat-card-sub">Updated ${timeAgo(reading.timestamp)}</div>
        </div>
        <div class="stat-card">
            <div class="stat-card-header">
                <span class="stat-card-label">Voltage</span>
                <div class="stat-card-icon voltage">🔌</div>
            </div>
            <div class="stat-card-value">${v.value}<span class="unit">${v.unit}</span></div>
        </div>
        <div class="stat-card">
            <div class="stat-card-header">
                <span class="stat-card-label">Current</span>
                <div class="stat-card-icon current">〰</div>
            </div>
            <div class="stat-card-value">${c.value}<span class="unit">${c.unit}</span></div>
        </div>
        <div class="stat-card">
            <div class="stat-card-header">
                <span class="stat-card-label">Frequency</span>
                <div class="stat-card-icon frequency">〰</div>
            </div>
            <div class="stat-card-value">${reading.frequency.toFixed(2)}<span class="unit">Hz</span></div>
        </div>
        <div class="stat-card">
            <div class="stat-card-header">
                <span class="stat-card-label">Power Factor</span>
                <div class="stat-card-icon pf">⚡</div>
            </div>
            <div class="stat-card-value">${reading.power_factor.toFixed(3)}<span class="unit"></span></div>
        </div>
        <div class="stat-card">
            <div class="stat-card-header">
                <span class="stat-card-label">Data Source</span>
                <div class="stat-card-icon energy">📊</div>
            </div>
            <div class="stat-card-value" style="font-size:18px;">${reading.data_source}</div>
            <div class="stat-card-sub">${formatDate(reading.timestamp)}</div>
        </div>`;
}

async function loadApplianceSection(container) {
    if (!container) return;
    try {
        const data = await api.getApplianceActivity();
        if (data.status === 'AI_MODEL_NOT_AVAILABLE') {
            container.innerHTML = `
                <div class="section-card">
                    <div class="section-card-header">
                        <span class="section-card-title">Appliance Activity</span>
                        <span class="section-badge no-data">MODEL N/A</span>
                    </div>
                    <div class="empty-state" style="padding:30px;">
                        <div class="icon">🤖</div>
                        <h3>AI Model Not Available</h3>
                        <p>Real hardware validation is required before appliance recognition can be enabled.</p>
                    </div>
                </div>`;
            return;
        }

        let html = `
            <div class="section-card">
                <div class="section-card-header">
                    <span class="section-card-title">Appliance Activity</span>
                    <span class="section-badge calculated">AI-INFERRED</span>
                </div>
                <div class="appliance-grid">
                    <div class="appliance-card">
                        <div class="name">Bulb 1</div>
                        <div class="state unknown">UNKNOWN</div>
                        <div class="confidence">Model not available</div>
                    </div>
                    <div class="appliance-card">
                        <div class="name">Bulb 2</div>
                        <div class="state unknown">UNKNOWN</div>
                        <div class="confidence">Model not available</div>
                    </div>
                </div>
            </div>`;
        container.innerHTML = html;
    } catch (e) {
        container.innerHTML = '';
    }
}

async function loadInsightsSection(container) {
    if (!container) return;
    try {
        const data = await api.getAiInsights();
        if (data.status === 'INSUFFICIENT_DATA') {
            container.innerHTML = `
                <div class="section-card">
                    <div class="section-card-header">
                        <span class="section-card-title">AI Insights</span>
                        <span class="section-badge no-data">NO DATA</span>
                    </div>
                    <div class="empty-state" style="padding:30px;">
                        <p>${data.message}</p>
                    </div>
                </div>`;
            return;
        }

        let html = `
            <div class="section-card">
                <div class="section-card-header">
                    <span class="section-card-title">AI Insights</span>
                    <span class="section-badge calculated">CALCULATED</span>
                </div>
                <div class="insight-list">`;

        data.insights.forEach(i => {
            html += `
                <div class="insight-item">
                    <div class="insight-dot ${i.severity.toLowerCase()}"></div>
                    <div>
                        <div class="insight-message">${i.message}</div>
                        <div class="insight-source">Source: ${i.data_source}</div>
                    </div>
                </div>`;
        });

        html += '</div></div>';
        container.innerHTML = html;
    } catch (e) {
        container.innerHTML = '';
    }
}

async function loadBillingSection(container) {
    if (!container) return;
    try {
        const data = await api.getBillingToday();
        let html = `
            <div class="section-card">
                <div class="section-card-header">
                    <span class="section-card-title">Today's Energy Charge</span>
                    <span class="section-badge measured">MEASURED</span>
                </div>`;

        if (data.measured_kwh === 0) {
            html += `<div class="empty-state" style="padding:20px;"><p>No consumption data for today.</p></div>`;
        } else {
            html += `
                <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:16px;margin-bottom:16px;">
                    <div>
                        <div style="font-size:12px;color:var(--text-muted);text-transform:uppercase;">Energy Today</div>
                        <div style="font-size:24px;font-weight:700;">${data.measured_kwh.toFixed(4)} <span style="font-size:14px;color:var(--text-muted);">kWh</span></div>
                    </div>
                    <div>
                        <div style="font-size:12px;color:var(--text-muted);text-transform:uppercase;">Today's Charge</div>
                        <div style="font-size:24px;font-weight:700;">₹${data.energy_charge_today.toFixed(2)}</div>
                    </div>
                    <div>
                        <div style="font-size:12px;color:var(--text-muted);text-transform:uppercase;">Monthly Equivalent</div>
                        <div style="font-size:24px;font-weight:700;">₹${data.monthly_equivalent_estimate.toFixed(2)}</div>
                    </div>
                    <div>
                        <div style="font-size:12px;color:var(--text-muted);text-transform:uppercase;">${data.billing_period_months}-Month Estimate</div>
                        <div style="font-size:24px;font-weight:700;">₹${data.billing_period_estimate.toFixed(2)}</div>
                    </div>
                </div>`;

            if (data.slab_breakdown && data.slab_breakdown.length > 0) {
                html += `
                    <table class="slab-table">
                        <thead><tr><th>Slab</th><th>Units</th><th>Rate</th><th>Charge</th><th>Description</th></tr></thead>
                        <tbody>`;
                data.slab_breakdown.forEach(s => {
                    html += `<tr><td>${s.slab}</td><td>${s.units}</td><td>₹${s.rate}/unit</td><td>₹${s.charge.toFixed(2)}</td><td>${s.description}</td></tr>`;
                });
                html += '</tbody></table>';
            }
        }

        html += '</div>';
        container.innerHTML = html;
    } catch (e) {
        container.innerHTML = '';
    }
}

function initDashboard() {
    loadDashboard();
    dashboardInterval = setInterval(loadDashboard, 5000);
}

function destroyDashboard() {
    if (dashboardInterval) {
        clearInterval(dashboardInterval);
        dashboardInterval = null;
    }
}
