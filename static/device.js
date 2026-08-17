// Device details page. Fetches /api/device/<mac> and renders full history.
const MAC = decodeURIComponent(location.pathname.replace('/device/', ''));
const fmt = ts => ts ? new Date(ts*1000).toLocaleString() : '—';
const fmtAgo = ts => {
  if (!ts) return '—';
  const s = Date.now()/1000 - ts;
  if (s < 60) return 'now';
  if (s < 3600) return Math.floor(s/60) + 'm ago';
  if (s < 86400) return Math.floor(s/3600) + 'h ago';
  return Math.floor(s/86400) + 'd ago';
};
const BEHAVIOR_LABELS = {
  'always-on': 'always-on', 'active-cyclic': 'active-cyclic',
  'intermittent': 'intermittent', 'transient': 'transient',
  'mobile': 'mobile', 'unknown': '—',
};
const behaviorLabel = b => BEHAVIOR_LABELS[b] || b;
const behaviorHint = b => {
  const noSignal = b.rssi_std == null;  // mDNS / no radio readings
  const hints = {
    'always-on': noSignal
      ? 'Seen every scan, all day — fixed infrastructure (no radio signal; mDNS service).'
      : 'Seen every scan, all day, tight signal — fixed infrastructure.',
    'active-cyclic': 'Present 24/7 but sightings spike on a usage cycle (cleaning, playing).',
    'intermittent': 'On/off gaps — a device with a usage cycle (light, TV).',
    'transient': 'Short bounded presence — a visitor who came and left.',
    'mobile': 'Wide signal spread — moving (phone in a pocket, not fixed).',
    'unknown': 'Not enough sightings to classify yet.',
  };
  return hints[b.behavior] || '';
};

function sparkline(canvas, values) {
  const ctx = canvas.getContext('2d');
  const W = canvas.width = canvas.offsetWidth || 600, H = canvas.height = 80;
  ctx.clearRect(0, 0, W, H);
  if (values.length < 2) return;
  const min = Math.min(...values), max = Math.max(...values);
  const span = max - min || 1;
  ctx.strokeStyle = '#58a6ff'; ctx.lineWidth = 1.5;
  ctx.beginPath();
  values.forEach((v, i) => {
    const x = (i / (values.length - 1)) * (W - 2) + 1;
    const y = H - 2 - ((v - min) / span) * (H - 4);
    i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
  });
  ctx.stroke();
}

async function load() {
  const btn = document.getElementById('btn-refresh');
  btn.classList.add('active');
  try {
    const res = await fetch('/api/device/' + encodeURIComponent(MAC));
    if (!res.ok) {
      document.getElementById('d-content').innerHTML = `<p>device not found</p>`;
      return;
    }
    const data = await res.json();
    const d = data.device;
    const sightings = data.sightings || [];
    const b = data.behavior;
    const fp = data.fingerprint;
    document.title = (d.my_label || d.last_label || MAC) + ' — Neighborhood Rhythm';
    document.getElementById('d-title').textContent = d.my_label || d.last_label || MAC;

    const names = [...new Set(sightings.map(s => s.name).filter(Boolean))];
    const rssiSeries = sightings.map(s => s.rssi).filter(r => r != null);
    const bySensor = {};
    for (const s of sightings) {
      bySensor[s.sensor_id] = (bySensor[s.sensor_id] || 0) + 1;
    }

    document.getElementById('d-content').innerHTML = `
      <div class="d-header">
        <span class="type-chip${d.is_mine ? ' mine' : ''}">${d.last_type || '?'}</span>
        <h2>${d.my_label || d.last_label || 'unnamed'}</h2>
      </div>
      <div class="d-sub">${d.oui_name || (d.last_label || 'unknown manufacturer')} · ${d.mac}</div>

      <div class="d-grid">
        <div class="d-stat"><b>${d.sighting_count}</b><label>sightings</label></div>
        <div class="d-stat"><b>${names.length}</b><label>names advertised</label></div>
        <div class="d-stat"><b>${Object.keys(bySensor).length}</b><label>sensors</label></div>
        <div class="d-stat"><b>${fmtAgo(d.last_seen)}</b><label>last seen</label></div>
        <div class="d-stat"><b>${fmtAgo(d.first_seen)}</b><label>first seen</label></div>
        <div class="d-stat"><b>${d.is_mine ? '★ mine' : '☆'}</b><label>tagged</label></div>
      </div>

      ${b ? `<div class="d-section">
        <h3>behavior</h3>
        <div class="d-grid">
          <div class="d-stat"><b>${behaviorLabel(b.behavior)}</b><label>pattern</label></div>
          <div class="d-stat"><b>${b.active_hours}</b><label>active hours/day</label></div>
          ${b.stationarity ? `<div class="d-stat"><b>${b.stationarity}</b><label>stationarity</label></div>` : ''}
          ${b.rssi_std != null ? `<div class="d-stat"><b>${b.rssi_std.toFixed(1)} dB</b><label>rssi spread</label></div>` : ''}
          ${b.dwell_s != null ? `<div class="d-stat"><b>${Math.round(b.dwell_s/60)} min</b><label>dwell</label></div>` : ''}
        </div>
        <span class="d-hint">${behaviorHint(b)}</span>
      </div>` : ''}

      ${fp && fp.aliases && fp.aliases.length > 1 ? `<div class="d-section">
        <h3>device fingerprint</h3>
        <span class="d-hint">${fp.aliases.length} identifiers linked as one device (cross-radio / rotation):</span>
        <div class="d-names">${fp.aliases.map(a => `<div class="d-name">${a.mac} <span class="d-hint">· ${a.source} · ${a.link_method}</span></div>`).join('')}</div>
      </div>` : ''}

      <div class="d-section">
        <h3>signal over time</h3>
        <canvas id="signal-spark" class="d-spark"></canvas>
        ${rssiSeries.length ? `<span class="d-hint">${rssiSeries.length} readings, ${Math.min(...rssiSeries).toFixed(0)} to ${Math.max(...rssiSeries).toFixed(0)} dBm</span>` : '<span class="d-hint">no signal data (mDNS device)</span>'}
      </div>

      ${names.length ? `<div class="d-section"><h3>names advertised</h3><div class="d-names">${names.map(n => `<div class="d-name">${n}</div>`).join('')}</div></div>` : ''}

      ${(() => {
        // find the latest sighting with decoded enrichment (extra)
        const enriched = sightings.filter(s => s.extra).slice(-1)[0];
        if (!enriched || !enriched.extra) return '';
        let e;
        try { e = JSON.parse(enriched.extra); } catch { return ''; }
        const parts = [];
        if (e.apple) {
          const a = e.apple;
          const lines = [];
          if (a.model) lines.push(`model: ${a.model}`);
          if (a.battery != null) lines.push(`battery: ${a.battery}%`);
          if (a.device) lines.push(`type: ${a.device}`);
          if (a.types) lines.push(`continuity: ${a.types.join(', ')}`);
          if (lines.length) parts.push(`<b>Apple</b>${lines.map(l => `<div class="d-name">${l}</div>`).join('')}`);
        }
        if (e.sensor) {
          const s = e.sensor;
          const lines = Object.entries(s).map(([k,v]) => `${k}: ${v}`);
          parts.push(`<b>Sensor</b>${lines.map(l => `<div class="d-name">${l}</div>`).join('')}`);
        }
        return parts.length ? `<div class="d-section"><h3>decoded payload</h3><div class="d-names">${parts.join('')}</div></div>` : '';
      })()}

      <div class="d-section">
        <h3>recent sightings</h3>
        <div class="table-wrap">
          <table>
            <thead><tr><th>time</th><th>sensor</th><th class="num">rssi</th><th class="num">distance</th><th>source</th></tr></thead>
            <tbody>
            ${sightings.slice(-30).reverse().map(s => `
              <tr>
                <td>${fmt(s.ts)}</td>
                <td>${s.sensor_id}</td>
                <td class="num">${s.rssi != null ? s.rssi.toFixed(0) + ' dBm' : '—'}</td>
                <td class="num">${s.distance != null ? s.distance.toFixed(1) + 'm' : '—'}</td>
                <td>${s.source}</td>
              </tr>`).join('')}
            </tbody>
          </table>
        </div>
      </div>

      <button class="btn${d.is_mine ? ' mine' : ''}" id="d-tag">${d.is_mine ? '★ tagged mine — untag' : 'tag as mine'}</button>
      <input id="d-tag-label" class="d-tag-input" placeholder="label (optional)" value="${d.my_label || ''}">
      <button class="btn${d.tracked ? ' tracked' : ''}" id="d-track">${d.tracked ? '◉ tracking — stop' : '◉ track this device'}</button>
    `;

    if (rssiSeries.length >= 2) sparkline(document.getElementById('signal-spark'), rssiSeries);

    document.getElementById('d-tag').onclick = async () => {
      const mine = !d.is_mine;
      const label = document.getElementById('d-tag-label').value || (mine ? (d.last_label || 'my device') : null);
      await fetch('/api/device/' + encodeURIComponent(MAC) + '/tag', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ is_mine: mine, my_label: label }),
      });
      load();
    };
    document.getElementById('d-track').onclick = async () => {
      const tracked = !d.tracked;
      await fetch('/api/device/' + encodeURIComponent(MAC) + '/track', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ tracked: tracked ? 1 : 0 }),
      });
      load();
    };
  } catch (e) {
    document.getElementById('d-content').innerHTML = `<p>error: ${e}</p>`;
  } finally {
    btn.classList.remove('active');
  }
}

document.getElementById('btn-refresh').onclick = load;
load();
