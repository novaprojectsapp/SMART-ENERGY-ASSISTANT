let whatIfInterval = null;

async function loadWhatIf() {
    const formEl = document.getElementById('whatif-form');
    const resultsEl = document.getElementById('whatif-results');

    if (formEl) {
        formEl.innerHTML = `
            <div class="input-group">
                <label>Reduction Percentage</label>
                <input type="number" id="whatif-percent" value="20" min="1" max="100" placeholder="e.g., 20">
            </div>
            <button class="btn btn-primary" onclick="runWhatIf()">Simulate</button>`;

        resultsEl.innerHTML = `
            <div class="empty-state" style="grid-column:1/-1;">
                <div class="icon">🔮</div>
                <h3>What-If Simulator</h3>
                <p>Enter a reduction percentage to see estimated savings.</p>
            </div>`;
    }
}

async function runWhatIf() {
    const percent = parseFloat(document.getElementById('whatif-percent').value);
    const resultsEl = document.getElementById('whatif-results');

    if (isNaN(percent) || percent < 0 || percent > 100) {
        resultsEl.innerHTML = '<div class="error-state">Please enter a valid percentage (0-100).</div>';
        return;
    }

    showLoading(resultsEl);

    try {
        const data = await api.simulateWhatIf(percent);

        if (data.status === 'INSUFFICIENT_DATA') {
            showEmpty(resultsEl, '🔮', 'No Data', data.message);
            return;
        }

        resultsEl.innerHTML = `
            <div class="whatif-results">
                <div class="whatif-result-card">
                    <h4>Monthly Equivalent</h4>
                    <div class="whatif-row"><span class="label">Baseline</span><span class="value">${data.monthly_equivalent.baseline_kwh} kWh = ₹${data.monthly_equivalent.baseline_charge}</span></div>
                    <div class="whatif-row"><span class="label">Scenario</span><span class="value">${data.monthly_equivalent.scenario_kwh} kWh = ₹${data.monthly_equivalent.scenario_charge}</span></div>
                    <div class="whatif-row"><span class="label">Savings</span><span class="value savings">₹${data.monthly_equivalent.estimated_savings}/month</span></div>
                </div>
                <div class="whatif-result-card">
                    <h4>${data.billing_period.months}-Month Billing Period</h4>
                    <div class="whatif-row"><span class="label">Baseline</span><span class="value">${data.billing_period.baseline_kwh} kWh = ₹${data.billing_period.baseline_charge}</span></div>
                    <div class="whatif-row"><span class="label">Scenario</span><span class="value">${data.billing_period.scenario_kwh} kWh = ₹${data.billing_period.scenario_charge}</span></div>
                    <div class="whatif-row"><span class="label">Savings</span><span class="value savings">₹${data.billing_period.estimated_savings} per billing period</span></div>
                </div>
            </div>`;
    } catch (e) {
        showError(resultsEl, e.message);
    }
}

function initWhatIf() {
    loadWhatIf();
}

function destroyWhatIf() {
    if (whatIfInterval) {
        clearInterval(whatIfInterval);
        whatIfInterval = null;
    }
}
