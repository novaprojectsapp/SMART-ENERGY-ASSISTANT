async function loadCoach() {
    const container = document.getElementById('coach-content');
    if (!container) return;

    try {
        const recs = await api.getRecommendations();

        if (recs.status === 'NO_DATA') {
            showEmpty(container, '🎓', 'No Data Yet', recs.message);
            return;
        }

        if (recs.recommendations.length === 0) {
            container.innerHTML = `
                <div class="section-card">
                    <div class="section-card-header">
                        <span class="section-card-title">Energy Coach</span>
                        <span class="section-badge measured">MEASURED</span>
                    </div>
                    <div class="empty-state" style="padding:20px;">
                        <p>No specific recommendations at this time. Keep monitoring!</p>
                    </div>
                </div>`;
            return;
        }

        let html = `
            <div class="section-card">
                <div class="section-card-header">
                    <span class="section-card-title">Energy Coach</span>
                    <span class="section-badge measured">MEASURED</span>
                </div>
                <div style="margin-bottom:16px;font-size:13px;color:var(--text-secondary);">
                    Average daily usage: ${recs.summary.avg_daily_kwh} kWh | Weekly: ${recs.summary.weekly_kwh} kWh
                </div>
                <div class="coach-list">`;

        recs.recommendations.forEach(r => {
            html += `
                <div class="coach-item ${r.priority.toLowerCase()}">
                    <div class="coach-message">${r.message}</div>
                    <div class="coach-type">Source: ${r.data_source} | Type: ${r.type} | Priority: ${r.priority}</div>
                </div>`;
        });

        html += '</div></div>';
        container.innerHTML = html;
    } catch (e) {
        showError(container, e.message);
    }
}

function initCoach() {
    loadCoach();
}
