function initCost() {
    loadCostData();
}

async function loadCostData() {
    const todayEl = document.getElementById('cost-today');
    const predictEl = document.getElementById('cost-predict');
    const tariffEl = document.getElementById('cost-tariff');

    try {
        const [today, predict, tariff] = await Promise.all([
            api.getBillingToday(),
            api.getBillingPredict(30),
            api.getBillingTariff(),
        ]);

        renderCostToday(todayEl, today);
        renderCostPredict(predictEl, predict);
        renderCostTariff(tariffEl, tariff);
    } catch (e) {
        showError(todayEl, e.message);
    }
}

function renderCostToday(container, data) {
    container.innerHTML = `
        <div class="section-card">
            <div class="section-card-header">
                <span class="section-card-title">Today's Energy Charge</span>
                <span class="section-badge measured">MEASURED</span>
            </div>
            <div class="dashboard-grid" style="grid-template-columns:repeat(auto-fit,minmax(160px,1fr));">
                <div class="stat-card">
                    <div class="stat-card-label">Energy Today</div>
                    <div class="stat-card-value" style="font-size:24px;">${data.measured_kwh.toFixed(4)}<span class="unit">kWh</span></div>
                </div>
                <div class="stat-card">
                    <div class="stat-card-label">Today's Charge</div>
                    <div class="stat-card-value" style="font-size:24px;">₹${data.energy_charge_today.toFixed(2)}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-card-label">Monthly Equivalent</div>
                    <div class="stat-card-value" style="font-size:24px;">₹${data.monthly_equivalent_estimate.toFixed(2)}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-card-label">${data.billing_period_months}-Month Estimate</div>
                    <div class="stat-card-value" style="font-size:24px;">₹${data.billing_period_estimate.toFixed(2)}</div>
                </div>
            </div>
        </div>`;
}

function renderCostPredict(container, data) {
    if (data.status === 'INSUFFICIENT_DATA') {
        showEmpty(container, '🔮', 'Prediction Unavailable', data.message);
        return;
    }

    container.innerHTML = `
        <div class="section-card">
            <div class="section-card-header">
                <span class="section-card-title">Bill Prediction</span>
                <span class="section-badge predicted">PREDICTED</span>
            </div>
            <div style="margin-bottom:12px;font-size:13px;color:var(--text-secondary);">
                Based on ${data.input_window_days}-day average: ${data.avg_daily_kwh} kWh/day
            </div>
            <div class="dashboard-grid" style="grid-template-columns:repeat(auto-fit,minmax(200px,1fr));">
                <div class="stat-card">
                    <div class="stat-card-label">Monthly Equivalent</div>
                    <div style="margin-top:8px;">
                        <div>${data.monthly_equivalent.projected_kwh} kWh</div>
                        <div style="font-size:20px;font-weight:700;color:var(--accent);">₹${data.monthly_equivalent.energy_charge}</div>
                    </div>
                </div>
                <div class="stat-card">
                    <div class="stat-card-label">${data.billing_period.months}-Month Billing Period</div>
                    <div style="margin-top:8px;">
                        <div>${data.billing_period.projected_kwh} kWh</div>
                        <div style="font-size:20px;font-weight:700;color:var(--accent);">₹${data.billing_period.energy_charge}</div>
                    </div>
                </div>
            </div>
        </div>`;
}

function renderCostTariff(container, data) {
    let rows = '';
    data.slabs.forEach(s => {
        rows += `<tr><td>${s.slab_number}</td><td>${s.min_units} - ${s.max_units || '∞'}</td><td>₹${s.rate_per_unit}/unit</td><td>${s.description}</td></tr>`;
    });

    container.innerHTML = `
        <div class="section-card">
            <div class="section-card-header">
                <span class="section-card-title">${data.tariff_name}</span>
            </div>
            <div style="font-size:13px;color:var(--text-secondary);margin-bottom:16px;">
                Region: ${data.region} | Version: ${data.version} | Currency: ${data.currency} | Billing Period: ${data.billing_period_months} months
            </div>
            <table class="slab-table">
                <thead><tr><th>Slab</th><th>Units</th><th>Rate</th><th>Description</th></tr></thead>
                <tbody>${rows}</tbody>
            </table>
        </div>`;
}
