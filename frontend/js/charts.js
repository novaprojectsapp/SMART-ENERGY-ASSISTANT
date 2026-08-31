// Minimal chart utility using SVG
function renderBarChart(container, data, options = {}) {
    const { height = 200, barColor = 'var(--accent)', label = '' } = options;

    if (!data || data.length === 0) {
        container.innerHTML = `<div class="empty-state"><p>No data to display.</p></div>`;
        return;
    }

    const max = Math.max(...data.map(d => d.value), 0.1);
    const barWidth = Math.max(10, Math.floor(600 / data.length) - 4);

    let bars = '';
    data.forEach((d, i) => {
        const h = Math.max(4, (d.value / max) * (height - 40));
        const x = i * (barWidth + 4) + 20;
        bars += `
            <rect x="${x}" y="${height - 20 - h}" width="${barWidth}" height="${h}"
                  fill="${barColor}" rx="2" opacity="0.85"/>
            <text x="${x + barWidth/2}" y="${height - 24 - h}" text-anchor="middle"
                  fill="var(--text-secondary)" font-size="10">${d.value.toFixed(1)}</text>
            <text x="${x + barWidth/2}" y="${height - 4}" text-anchor="middle"
                  fill="var(--text-muted)" font-size="9">${d.label}</text>`;
    });

    const totalWidth = data.length * (barWidth + 4) + 40;

    container.innerHTML = `
        ${label ? `<div style="font-size:12px;color:var(--text-muted);margin-bottom:8px;">${label}</div>` : ''}
        <svg width="100%" viewBox="0 0 ${totalWidth} ${height}" style="overflow:visible;">
            ${bars}
        </svg>`;
}

function renderLineChart(container, data, options = {}) {
    const { height = 200, color = 'var(--accent)', label = '' } = options;

    if (!data || data.length === 0) {
        container.innerHTML = `<div class="empty-state"><p>No data to display.</p></div>`;
        return;
    }

    const max = Math.max(...data.map(d => d.value), 0.1);
    const min = 0;
    const range = max - min || 1;
    const step = (600 - 40) / Math.max(1, data.length - 1);

    let path = '';
    let dots = '';
    data.forEach((d, i) => {
        const x = i * step + 20;
        const y = height - 30 - ((d.value - min) / range) * (height - 50);
        path += i === 0 ? `M${x},${y}` : ` L${x},${y}`;
        dots += `<circle cx="${x}" cy="${y}" r="3" fill="${color}"/>`;
    });

    container.innerHTML = `
        ${label ? `<div style="font-size:12px;color:var(--text-muted);margin-bottom:8px;">${label}</div>` : ''}
        <svg width="100%" viewBox="0 0 640 ${height}" style="overflow:visible;">
            <path d="${path}" fill="none" stroke="${color}" stroke-width="2"/>
            ${dots}
        </svg>`;
}
