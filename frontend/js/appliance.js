function initAppliance() {
    loadApplianceData();
}

async function loadApplianceData() {
    const activityEl = document.getElementById('appliance-activity');
    const modelsEl = document.getElementById('appliance-models');

    try {
        const [activity, models] = await Promise.all([
            api.getApplianceActivity(),
            api.getApplianceModels(),
        ]);

        renderApplianceActivity(activityEl, activity);
        renderApplianceModels(modelsEl, models);
    } catch (e) {
        showError(activityEl, e.message);
    }
}

function renderApplianceActivity(container, data) {
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
                    <p>${data.message}</p>
                    <p style="margin-top:12px;color:var(--danger);font-size:13px;">REAL HARDWARE VALIDATION REQUIRED</p>
                </div>
            </div>`;
        return;
    }

    let html = `
        <div class="section-card">
            <div class="section-card-header">
                <span class="section-card-title">Appliance Activity</span>
                <span class="section-badge calculated">AI-INFERRED</span>
            </div>`;

    if (data.status === 'NO_DATA') {
        html += `<div class="empty-state" style="padding:20px;"><p>No appliance activity recorded.</p></div>`;
    } else {
        html += `
            <div style="margin-bottom:12px;font-size:12px;color:var(--text-muted);">
                Model: ${data.model_version} | Hardware Validated: ${data.hardware_validated ? 'Yes' : 'No'} | ${formatDate(data.timestamp)}
            </div>
            <div class="appliance-grid">`;

        const appliances = typeof data.appliances === 'string' ? JSON.parse(data.appliances) : data.appliances;

        if (Array.isArray(appliances)) {
            appliances.forEach((a, i) => {
                const state = a.state || 'UNKNOWN';
                html += `
                    <div class="appliance-card">
                        <div class="name">${a.name || `Appliance ${i+1}`}</div>
                        <div class="state ${state.toLowerCase()}">${state}</div>
                        <div class="confidence">${a.confidence ? `${(a.confidence * 100).toFixed(0)}% confidence` : ''}</div>
                    </div>`;
            });
        }

        html += '</div>';
    }

    html += '</div>';
    container.innerHTML = html;
}

function renderApplianceModels(container, data) {
    if (!data || data.length === 0) {
        container.innerHTML = `
            <div class="section-card">
                <div class="section-card-header">
                    <span class="section-card-title">Trained Models</span>
                </div>
                <div class="empty-state" style="padding:20px;">
                    <p>No models trained yet. Run the training pipeline with real hardware data.</p>
                </div>
            </div>`;
        return;
    }

    let rows = '';
    data.forEach(m => {
        rows += `
            <tr>
                <td>${m.model_version}</td>
                <td>${m.model_type}</td>
                <td>${m.training_source}</td>
                <td>${m.hardware_validated ? '✅ Yes' : '❌ No'}</td>
                <td>${m.status}</td>
                <td>${m.accuracy ? `${(m.accuracy * 100).toFixed(1)}%` : '--'}</td>
                <td>${formatDate(m.created_at)}</td>
            </tr>`;
    });

    container.innerHTML = `
        <div class="section-card">
            <div class="section-card-header">
                <span class="section-card-title">Trained Models</span>
            </div>
            <table class="slab-table">
                <thead><tr><th>Version</th><th>Type</th><th>Source</th><th>HW Validated</th><th>Status</th><th>Accuracy</th><th>Created</th></tr></thead>
                <tbody>${rows}</tbody>
            </table>
        </div>`;
}
