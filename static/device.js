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
      <div class="d-sub">${d.oui_name || 'unknown manufacturer'} · ${d.mac}</div>

      <div class="d-grid">
        <div class="d-stat"><b>${d.sighting_count}</b><label>sightings</label></div>
        <div class="d-stat"><b>${names.length}</b><label>names advertised</label></div>
        <div class="d-stat"><b>${Object.keys(bySensor).length}</b><label>sensors</label></div>
        <div class="d-stat"><b>${fmtAgo(d.last_seen)}</b><label>last seen</label></div>
        <div class="d-stat"><b>${fmtAgo(d.first_seen)}</b><label>first seen</label></div>
        <div class="d-stat"><b>${d.is_mine ? '★ mine' : '☆'}</b><label>tagged</label></div>
      </div>

      <div class="d-section">
        <h3>signal over time</h3>
        <canvas id="signal-spark" class="d-spark"></canvas>
        ${rssiSeries.length ? `<span class="d-hint">${rssiSeries.length} readings, ${Math.min(...rssiSeries).toFixed(0)} to ${Math.max(...rssiSeries).toFixed(0)} dBm</span>` : '<span class="d-hint">no signal data (mDNS device)</span>'}
      </div>

      ${names.length ? `<div class="d-section"><h3>names advertised</h3><div class="d-names">${names.map(n => `<div class="d-name">${n}</div>`).join('')}</div></div>` : ''}

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
  } catch (e) {
    document.getElementById('d-content').innerHTML = `<p>error: ${e}</p>`;
  } finally {
    btn.classList.remove('active');
  }
}

document.getElementById('btn-refresh').onclick = load;
load();
