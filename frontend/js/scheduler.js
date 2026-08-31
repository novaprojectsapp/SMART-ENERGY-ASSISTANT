let schedulerDevices = [];
let schedulerAppliances = [];
let schedulerSchedules = [];

function initScheduler() {
    loadSchedulerData();
}

async function loadSchedulerData() {
    const container = document.getElementById('scheduler-page');
    if (!container) return;
    container.innerHTML = '<div style="text-align:center;padding:40px;"><div class="loading-spinner"></div></div>';
    try {
        const [devices, appliances, schedules, commands] = await Promise.all([
            api.getDevices(),
            api.getAppliances(),
            api.getSchedules(),
            api.getControlCommands(20),
        ]);
        schedulerDevices = devices;
        schedulerAppliances = appliances;
        schedulerSchedules = schedules;
        renderScheduler(container, commands);
    } catch (e) {
        showError(container, e.message);
    }
}

function dayName(d) {
    return ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'][((d + 1) % 7)];
}

function fmtDays(days) {
    if (!days || days.length === 0) return 'Every day';
    if (days.length === 7) return 'Every day';
    return days.map(d => dayName(d)).join(', ');
}

function formatTimeShort(iso) {
    if (!iso) return '—';
    try {
        const d = new Date(iso);
        if (isNaN(d.getTime())) return '—';
        const hh = String(d.getHours()).padStart(2, '0');
        const mm = String(d.getMinutes()).padStart(2, '0');
        return `${hh}:${mm}`;
    } catch (e) {
        return '—';
    }
}

function renderScheduler(container, commands) {
    const controllable = schedulerAppliances.filter(a => a.control_capable);

    let appCards = '';
    if (schedulerAppliances.length === 0) {
        appCards = '<div class="empty-state" style="padding:20px;"><p>No appliances registered yet. Add one below.</p></div>';
    } else {
        appCards = '<div class="appliance-grid">';
        schedulerAppliances.forEach(a => {
            const type = (a.type || 'OTHER').toLowerCase();
            appCards += `
                <div class="appliance-card">
                    <div class="name">${a.name} <span class="appl-ch">#${a.channel}</span></div>
                    <div class="type-tag">${a.type}${a.control_capable ? '' : ' · NO CONTROL'}</div>
                    <div class="controls">
                        <button class="btn btn-secondary btn-sm" ${a.control_capable ? '' : 'disabled'} onclick="manualControl('${a.id}','ON')">ON</button>
                        <button class="btn btn-secondary btn-sm" ${a.control_capable ? '' : 'disabled'} onclick="manualControl('${a.id}','OFF')">OFF</button>
                        <button class="btn btn-danger btn-sm" onclick="removeAppliance('${a.id}','${esc(a.name)}')">✕</button>
                    </div>
                </div>`;
        });
        appCards += '</div>';
    }

    let schedRows = '';
    if (schedulerSchedules.length === 0) {
        schedRows = '<div class="empty-state" style="padding:20px;"><p>No schedules yet. Create one to automatically control your appliances.</p></div>';
    } else {
        let rows = '';
        schedulerSchedules.forEach(s => {
            const app = schedulerAppliances.find(a => a.id === s.appliance_id);
            const appName = app ? app.name : s.appliance_id;
            const timeStr = s.off_time
                ? `ON ${s.on_time} → OFF ${s.off_time}`
                : `${s.action} ${s.start_time}`;
            const nextStr = s.off_time
                ? `${s.next_on_at ? 'ON ' + formatTimeShort(s.next_on_at) : '—'} / ${s.next_off_at ? 'OFF ' + formatTimeShort(s.next_off_at) : '—'}`
                : (s.next_execution_at ? formatTimeShort(s.next_execution_at) : '—');
            rows += `
                <tr>
                    <td>${appName}</td>
                    <td><span class="badge ${s.action === 'ON' ? 'badge-on' : 'badge-off'}">${s.action}</span></td>
                    <td>${timeStr}</td>
                    <td>${s.schedule_type} · ${fmtDays(s.days_of_week)}</td>
                    <td class="next-col">${nextStr}</td>
                    <td><span class="badge ${s.enabled ? 'badge-on' : 'badge-off'}">${s.enabled ? 'Enabled' : 'Disabled'}</span></td>
                    <td class="sched-actions">
                        <button class="btn btn-secondary btn-sm" onclick="editSchedule('${s.id}')">Edit</button>
                        <button class="btn btn-secondary btn-sm" onclick="toggleSchedule('${s.id}')">${s.enabled ? 'Disable' : 'Enable'}</button>
                        <button class="btn btn-danger btn-sm" onclick="deleteSchedule('${s.id}')">Delete</button>
                    </td>
                </tr>`;
        });
        schedRows = `<div style="overflow-x:auto;"><table class="slab-table">
            <thead><tr><th>Appliance</th><th>Action</th><th>On / Off Time</th><th>Repeat</th><th>Next</th><th>Status</th><th>Actions</th></tr></thead>
            <tbody>${rows}</tbody></table></div>`;
    }

    let history = '';
    if (commands && commands.length) {
        history = '<div class="section-card"><div class="section-card-header"><span class="section-card-title">Control Command History</span><span class="section-badge no-data">RECENT</span></div><div style="overflow-x:auto;"><table class="slab-table"><thead><tr><th>Time</th><th>Action</th><th>Source</th><th>Status</th><th>Message</th></tr></thead><tbody>';
        commands.forEach(c => {
            const app = schedulerAppliances.find(a => a.id === c.appliance_id);
            history += `<tr><td>${formatDate(c.created_at)}</td><td>${c.action}</td><td>${c.source}</td><td><span class="badge badge-off">${c.status}</span></td><td>${c.message}</td></tr>`;
        });
        history += '</tbody></table></div><div class="sched-footnote">Hardware control is not connected yet — commands are recorded as SIMULATED/PENDING until ESP32 relay control firmware is integrated.</div></div>';
    }

    container.innerHTML = `
        <div class="dashboard-grid" style="margin-bottom:20px;">
            <div class="stat-card">
                <div class="stat-card-header"><span class="stat-card-label">Connected Appliances</span><div class="stat-card-icon power">🔌</div></div>
                <div class="stat-card-value">${schedulerAppliances.length}<span class="unit"></span></div>
                <div class="stat-card-sub">${controllable.length} controllable</div>
            </div>
            <div class="stat-card">
                <div class="stat-card-header"><span class="stat-card-label">Active Schedules</span><div class="stat-card-icon energy">⏰</div></div>
                <div class="stat-card-value">${schedulerSchedules.filter(s => s.enabled).length}<span class="unit"></span></div>
                <div class="stat-card-sub">${schedulerSchedules.length} total</div>
            </div>
            <div class="stat-card">
                <div class="stat-card-header"><span class="stat-card-label">Control Status</span><div class="stat-card-icon voltage">⚙</div></div>
                <div class="stat-card-value" style="font-size:14px;">PENDING HARDWARE</div>
                <div class="stat-card-sub">Relay control not connected</div>
            </div>
        </div>

        <div class="section-card">
            <div class="section-card-header">
                <span class="section-card-title">Connected Appliances</span>
                <button class="btn btn-primary" onclick="showAddAppliance()">+ Add Appliance</button>
            </div>
            ${appCards}
        </div>

        <div class="section-card">
            <div class="section-card-header">
                <span class="section-card-title">Schedules</span>
                <button class="btn btn-primary" onclick="showAddSchedule()">+ Add Schedule</button>
            </div>
            ${schedRows}
        </div>

        <div id="scheduler-forms"></div>
        ${history}
    `;
}

function esc(s) {
    return (s || '').replace(/[\\"']/g, '\\$&');
}

function showAddAppliance() {
    const deviceOptions = schedulerDevices.map(d => `<option value="${d.id}">${d.name}</option>`).join('');
    const types = ['BULB', 'LIGHT', 'FAN', 'TV', 'AC', 'PUMP', 'SOCKET', 'OTHER'];
    const typeOptions = types.map(t => `<option value="${t}">${t}</option>`).join('');
    const forms = document.getElementById('scheduler-forms');
    forms.innerHTML = `
        <div class="section-card">
            <div class="section-card-header"><span class="section-card-title">Add Appliance</span></div>
            <form id="add-appliance-form" class="sched-form">
                <label>Appliance Name <input name="name" required maxlength="128"></label>
                <label>Type <select name="type">${typeOptions}</select></label>
                <label>Control Channel <input name="channel" type="number" min="0" max="32" value="1"></label>
                <label>Device <select name="device_id"><option value="">—</option>${deviceOptions}</select></label>
                <div class="sched-actions">
                    <button type="submit" class="btn btn-primary">Save Appliance</button>
                    <button type="button" class="btn btn-secondary" onclick="closeForm()">Cancel</button>
                </div>
            </form>
        </div>`;
    document.getElementById('add-appliance-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        const f = e.target;
        const payload = {
            name: f.name.value.trim(),
            type: f.type.value,
            channel: parseInt(f.channel.value || '1', 10),
            device_id: f.device_id.value || '',
            control_capable: true,
        };
        try {
            await api.createAppliance(payload);
            closeForm();
            loadSchedulerData();
        } catch (err) { alert('Error: ' + err.message); }
    });
    window.scrollTo({ top: 99999, behavior: 'smooth' });
}

function showAddSchedule() {
    if (schedulerAppliances.length === 0) {
        alert('Please register an appliance first.');
        return;
    }
    const appOptions = schedulerAppliances.filter(a => a.control_capable)
        .map(a => `<option value="${a.id}">${a.name}</option>`).join('');
    const days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
        .map((d, i) => `<label class="day-chk"><input type="checkbox" name="wday" value="${i}"> ${d}</label>`).join('');
    const forms = document.getElementById('scheduler-forms');
    forms.innerHTML = `
        <div class="section-card">
            <div class="section-card-header"><span class="section-card-title">Add Schedule</span></div>
            <form id="add-schedule-form" class="sched-form">
                <label>Appliance <select name="appliance_id" required>${appOptions}</select></label>
                <div class="time-pair">
                    <label>ON Time <input name="on_time" type="time" required></label>
                    <label>OFF Time <input name="off_time" type="time" placeholder="optional"></label>
                </div>
                <div class="sched-hint">Set both ON and OFF times for an automatic on/off pair. Overnight pairs (e.g. ON 23:00 → OFF 06:00) are allowed — the OFF fires the next day.</div>
                <label>Repeat <select name="schedule_type" onchange="toggleDays(this.value)">
                    <option value="DAILY">Every day (Daily)</option>
                    <option value="WEEKLY">Specific days (Weekly)</option>
                    <option value="ONCE">Once</option>
                </select></label>
                <div id="weekly-days" style="display:none;">${days}</div>
                <label class="chk"><input type="checkbox" name="enabled" checked> Enabled</label>
                <div class="sched-actions">
                    <button type="submit" class="btn btn-primary">Save Schedule</button>
                    <button type="button" class="btn btn-secondary" onclick="closeForm()">Cancel</button>
                </div>
            </form>
        </div>`;
    document.getElementById('add-schedule-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        const f = e.target;
        const days = Array.from(f.querySelectorAll('input[name="wday"]:checked')).map(x => parseInt(x.value, 10));
        const payload = {
            appliance_id: f.appliance_id.value,
            action: 'ON',
            schedule_type: f.schedule_type.value,
            on_time: f.on_time.value,
            off_time: f.off_time.value || null,
            days_of_week: f.schedule_type.value === 'WEEKLY' ? days : [],
            enabled: f.enabled.checked,
        };
        try {
            await api.createSchedule(payload);
            closeForm();
            loadSchedulerData();
        } catch (err) { alert('Error: ' + err.message); }
    });
    window.scrollTo({ top: 99999, behavior: 'smooth' });
}

function toggleDays(value) {
    const el = document.getElementById('weekly-days');
    if (el) el.style.display = value === 'WEEKLY' ? 'block' : 'none';
}

function closeForm() {
    const forms = document.getElementById('scheduler-forms');
    if (forms) forms.innerHTML = '';
}

async function manualControl(applianceId, action) {
    try {
        const result = await api.controlAppliance(applianceId, action, 'USER');
        alert(result.message || 'Control command recorded.');
    } catch (err) { alert('Error: ' + err.message); }
}

async function removeAppliance(id, name) {
    if (!confirm(`Remove appliance "${name}"? This also deletes its schedules.`)) return;
    try {
        await api.deleteAppliance(id);
        loadSchedulerData();
    } catch (err) { alert('Error: ' + err.message); }
}

async function toggleSchedule(id) {
    const s = schedulerSchedules.find(x => x.id === id);
    try {
        if (s && s.enabled) await api.disableSchedule(id);
        else await api.enableSchedule(id);
        loadSchedulerData();
    } catch (err) { alert('Error: ' + err.message); }
}

async function deleteSchedule(id) {
    if (!confirm('Delete this schedule?')) return;
    try {
        await api.deleteSchedule(id);
        loadSchedulerData();
    } catch (err) { alert('Error: ' + err.message); }
}

function editSchedule(id) {
    const s = schedulerSchedules.find(x => x.id === id);
    if (!s) return;
    const appOptions = schedulerAppliances.filter(a => a.control_capable)
        .map(a => `<option value="${a.id}" ${a.id === s.appliance_id ? 'selected' : ''}>${a.name}</option>`).join('');
    const days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
        .map((d, i) => `<label class="day-chk"><input type="checkbox" name="wday" value="${i}" ${(s.days_of_week || []).includes(i) ? 'checked' : ''}> ${d}</label>`).join('');
    const forms = document.getElementById('scheduler-forms');
    forms.innerHTML = `
        <div class="section-card">
            <div class="section-card-header"><span class="section-card-title">Edit Schedule</span></div>
            <form id="edit-schedule-form" class="sched-form">
                <label>Appliance <select name="appliance_id" required>${appOptions}</select></label>
                <div class="time-pair">
                    <label>ON Time <input name="on_time" type="time" value="${s.on_time || s.start_time}" required></label>
                    <label>OFF Time <input name="off_time" type="time" value="${s.off_time || ''}"></label>
                </div>
                <label>Repeat <select name="schedule_type" onchange="toggleDaysEdit(this.value)">
                    <option value="DAILY" ${s.schedule_type === 'DAILY' ? 'selected' : ''}>Every day</option>
                    <option value="WEEKLY" ${s.schedule_type === 'WEEKLY' ? 'selected' : ''}>Specific days</option>
                    <option value="ONCE" ${s.schedule_type === 'ONCE' ? 'selected' : ''}>Once</option>
                </select></label>
                <div id="edit-weekly-days" style="display:${s.schedule_type === 'WEEKLY' ? 'block' : 'none'};">${days}</div>
                <label class="chk"><input type="checkbox" name="enabled" ${s.enabled ? 'checked' : ''}> Enabled</label>
                <div class="sched-actions">
                    <button type="submit" class="btn btn-primary">Update Schedule</button>
                    <button type="button" class="btn btn-secondary" onclick="closeForm()">Cancel</button>
                </div>
            </form>
        </div>`;
    document.getElementById('edit-schedule-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        const f = e.target;
        const days = Array.from(f.querySelectorAll('input[name="wday"]:checked')).map(x => parseInt(x.value, 10));
        const payload = {
            appliance_id: f.appliance_id.value,
            action: 'ON',
            schedule_type: f.schedule_type.value,
            on_time: f.on_time.value,
            off_time: f.off_time.value || null,
            days_of_week: f.schedule_type.value === 'WEEKLY' ? days : [],
            enabled: f.enabled.checked,
        };
        try {
            await api.updateSchedule(id, payload);
            closeForm();
            loadSchedulerData();
        } catch (err) { alert('Error: ' + err.message); }
    });
    window.scrollTo({ top: 99999, behavior: 'smooth' });
}

function toggleDaysEdit(value) {
    const el = document.getElementById('edit-weekly-days');
    if (el) el.style.display = value === 'WEEKLY' ? 'block' : 'none';
}

