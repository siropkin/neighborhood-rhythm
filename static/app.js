// Neighborhood Rhythm — radar + device table. Vanilla JS, no framework.
const TYPE_COLORS = {
  tv: '#58a6ff', speaker: '#bc8cff', light: '#56d364', phone: '#8b949e',
  laptop: '#79c0ff', tablet: '#a5d6ff', vacuum: '#ff9800',
  'phone-anon': '#7d85b0', 'apple-device': '#bbb', 'samsung-device': '#7fb3ff',
  'iot-esp32': '#56d364', iot: '#56d364', 'iot-serial': '#56d364',
  sensor: '#f0883e', thermostat: '#f0883e', 'google-device': '#4285f4',
};
// Friendly display names for the raw type keys. Keys stay stable in the data.
const TYPE_LABELS = {
  'phone-anon': 'phone (unknown)',
  'iot-esp32': 'iot device',
  iot: 'iot device',
  'iot-serial': 'iot device',
  'apple-device': 'apple device',
  'samsung-device': 'samsung device',
  'google-device': 'google device',
  tv: 'tv', speaker: 'speaker', light: 'light', phone: 'phone',
  laptop: 'laptop', tablet: 'tablet', vacuum: 'robot vacuum',
  sensor: 'sensor', thermostat: 'thermostat', unknown: 'unknown',
  mine: '★ mine',
};
const typeLabel = t => TYPE_LABELS[t] || t;
const colorFor = d => d.is_mine ? '#f0c674' : (TYPE_COLORS[d.last_type] || '#484f58');
const fmtAgo = ts => {
  if (!ts) return '—';
  const s = Date.now()/1000 - ts;
  if (s < 60) return 'now';
  if (s < 3600) return Math.floor(s/60) + 'm';
  if (s < 86400) return Math.floor(s/3600) + 'h';
  return Math.floor(s/86400) + 'd';
};
const getJSON = async url => {
  // Retry once on failure — gunicorn closes idle keep-alive connections and
  // Chrome sometimes reuses a just-closed socket (ERR_SOCKET_NOT_CONNECTED).
  // A second fetch opens a fresh connection and succeeds.
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      const res = await fetch(url, { cache: 'no-store' });
      if (!res.ok && attempt === 0) throw new Error('http ' + res.status);
      return await res.json();
    } catch (e) {
      if (attempt === 1) throw e;
    }
  }
};

let state = { devices: [], positions: {}, filter: '', sortKey: 'last_seen', sortDir: -1 };

// ---------- Radar ----------
// Pick ring bands that fit the real data. Scales down to sub-meter when
// everything is close (e.g. max 1.4m -> 0.3/0.6/0.9/1.2/1.5), up to large
// ranges when things are far. ~5 bands, rounded to a sensible precision.
function pickBands(maxDist) {
  const ceil = Math.max(maxDist, 0.5);
  // pick a "nice top" a bit above the real max, with precision that fits.
  const niceStep = (c) => {
    const pow = Math.pow(10, Math.floor(Math.log10(c)));
    const n = c / pow;
    let step;
    if (n <= 1) step = 0.2 * pow;
    else if (n <= 2) step = 0.5 * pow;
    else if (n <= 5) step = 1 * pow;
    else step = 2 * pow;
    return step;
  };
  const step = niceStep(ceil);
  const top = Math.ceil(ceil / step) * step;
  const bands = [];
  for (let v = step; v <= top + 1e-9; v += step) bands.push(Math.round(v * 100) / 100);
  return bands.length ? bands : [top];
}

function drawRadar() {
  const c = document.getElementById('radar');
  const ctx = c.getContext('2d');
  const W = c.width, H = c.height;
  ctx.clearRect(0, 0, W, H);
  const cx = W/2, cy = H/2;
  const maxR = Math.min(cx, cy) - 24;

  // max real distance across all positioned devices
  let maxDist = 0;
  for (const d of state.devices) {
    const p = state.positions[d.mac];
    if (!p) continue;
    const dd = p.type === 'ring' ? p.distance
             : p.type === 'ring_pair' ? Math.max(...p.distances)
             : Math.hypot(p.x || 0, p.y || 0);
    if (dd != null) maxDist = Math.max(maxDist, dd);
  }
  const bands = pickBands(maxDist);
  const bandMax = bands[bands.length - 1];
  // log scale so near + far both visible, anchored to bandMax not a fixed 101.
  const d2r = d => Math.min(maxR, Math.log10((d||0) + 1) / Math.log10(bandMax + 1) * maxR);

  ctx.strokeStyle = '#30363d'; ctx.fillStyle = '#8b949e'; ctx.lineWidth = 1;
  ctx.font = '10px "SF Mono", monospace';
  for (const b of bands) {
    const r = d2r(b);
    ctx.beginPath(); ctx.arc(cx, cy, r, 0, 2*Math.PI); ctx.stroke();
    ctx.fillText(b + 'm', cx + 3, cy - r + 11);
  }
  // crosshair
  ctx.strokeStyle = '#21262d';
  ctx.beginPath(); ctx.moveTo(cx, 8); ctx.lineTo(cx, H-8);
  ctx.moveTo(8, cy); ctx.lineTo(W-8, cy); ctx.stroke();

  // center = you
  ctx.fillStyle = '#58a6ff';
  ctx.beginPath(); ctx.arc(cx, cy, 5, 0, 2*Math.PI); ctx.fill();
  ctx.fillStyle = '#8b949e'; ctx.fillText('you', cx - 9, cy + 18);

  for (const d of state.devices) {
    const p = state.positions[d.mac];
    const col = colorFor(d);
    if (!p) continue;
    if (p.type === 'ring') {
      ctx.strokeStyle = col; ctx.globalAlpha = .55; ctx.lineWidth = 2;
      ctx.beginPath(); ctx.arc(cx, cy, d2r(p.distance), 0, 2*Math.PI); ctx.stroke();
      ctx.globalAlpha = 1;
    } else if (p.type === 'ring_pair') {
      ctx.strokeStyle = col; ctx.globalAlpha = .3; ctx.lineWidth = 1.5;
      for (const dd of p.distances) { ctx.beginPath(); ctx.arc(cx, cy, d2r(dd), 0, 2*Math.PI); ctx.stroke(); }
      ctx.globalAlpha = 1;
    } else if (p.type === 'point') {
      ctx.fillStyle = col;
      ctx.beginPath(); ctx.arc(cx + p.x, cy - p.y, 4, 0, 2*Math.PI); ctx.fill();
    }
  }
}

// ---------- Type breakdown (bar + counts beside the radar) ----------
function renderTypeBreakdown() {
  const el = document.getElementById('type-breakdown');
  if (!el) return;
  const counts = {};
  for (const d of state.devices) {
    const t = d.is_mine ? 'mine' : (d.last_type || 'unknown');
    counts[t] = (counts[t] || 0) + 1;
  }
  const sorted = Object.entries(counts).sort((a, b) => b[1] - a[1]);
  const max = Math.max(1, ...sorted.map(s => s[1]));
  el.innerHTML = sorted.map(([t, n]) => `
    <div class="tb-row">
      <i class="tb-dot" style="background:${colorFor({is_mine: t==='mine', last_type: t})}"></i>
      <span class="tb-name" title="${t}">${typeLabel(t)}</span>
      <span class="tb-bar"><span style="width:${(n/max*100).toFixed(0)}%"></span></span>
      <span class="tb-count">${n}</span>
    </div>`).join('');
}

function renderLegend() {
  const seen = new Set();
  const el = document.getElementById('radar-legend');
  el.innerHTML = '';
  for (const d of state.devices) {
    const t = d.is_mine ? 'mine' : d.last_type;
    if (seen.has(t)) continue;
    seen.add(t);
    const s = document.createElement('span');
    s.innerHTML = `<i style="background:${colorFor(d)}"></i>${typeLabel(t)}`;
    el.appendChild(s);
  }
}

// ---------- Table ----------
function renderTable() {
  const tb = document.getElementById('device-rows');
  tb.innerHTML = '';
  let rows = state.devices.filter(d => {
    if (!state.filter) return true;
    const q = state.filter.toLowerCase();
    return (d.last_label || '').toLowerCase().includes(q)
        || (d.my_label || '').toLowerCase().includes(q)
        || d.mac.toLowerCase().includes(q)
        || d.last_type.toLowerCase().includes(q);
  });
  const k = state.sortKey, dir = state.sortDir;
  rows.sort((a, b) => {
    let av = a[k], bv = b[k];
    if (k === 'label') { av = a.my_label || a.last_label || a.mac; bv = b.my_label || b.last_label || b.mac; }
    if (typeof av === 'string') av = av.toLowerCase();
    if (typeof bv === 'string') bv = bv.toLowerCase();
    if (av == null) return 1; if (bv == null) return -1;
    return (av < bv ? -1 : av > bv ? 1 : 0) * dir;
  });
  for (const d of rows) {
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td><span class="type-chip${d.is_mine ? ' mine' : ''}" title="${d.last_type || ''}">${typeLabel(d.last_type || '?')}</span></td>
      <td class="dev-name"><b>${d.my_label || d.last_label || '—'}</b> <span class="mono dev-mac">${d.mac}</span></td>
      <td class="num">${d.distance != null ? d.distance.toFixed(1) + 'm' : '—'}</td>
      <td class="num">${d.rssi != null ? d.rssi.toFixed(0) : '—'}</td>
      <td class="num">${fmtAgo(d.last_seen)}</td>
      <td class="num"><span class="mine-mark ${d.is_mine ? '' : 'off'}">${d.is_mine ? '★' : '☆'}</span></td>`;
    tr.onclick = () => { location.href = '/device/' + encodeURIComponent(d.mac); };
    tb.appendChild(tr);
  }
  // mark sorted header
  document.querySelectorAll('th').forEach(th => {
    th.classList.toggle('sorted', th.dataset.sort === state.sortKey);
  });
}

// ---------- refresh ----------
const REFRESH_MS = 30000;
let refreshTimer, countdownTimer, secsLeft = 30;
function setIndicators(state) {
  const el = document.getElementById('refresh-indicator');
  if (el) { el.className = 'refresh-indicator ' + state; }
  const btn = document.getElementById('btn-refresh');
  if (btn) { btn.classList.toggle('active', state === 'active'); }
}
async function refresh() {
  setIndicators('active');
  try {
    const [stats, now, positions] = await Promise.all([
      getJSON('/api/stats'), getJSON('/api/now'), getJSON('/api/positions'),
    ]);
    document.getElementById('s-current').textContent = stats.current;
    document.getElementById('s-total').textContent = stats.total;
    document.getElementById('s-mine').textContent = stats.mine;
    document.getElementById('s-wifi').textContent = stats.wifi;
    document.getElementById('s-sensors').textContent = stats.sensors;
    document.getElementById('s-scan').textContent = fmtAgo(stats.last_scan);
    state.devices = now.devices;
    state.positions = positions.positions;
    drawRadar();
    renderLegend();
    renderTypeBreakdown();
    renderTable();
    setIndicators('ok');
    // hide the first-load overlay + reveal content once we have data
    const loading = document.getElementById('loading');
    if (loading) loading.classList.add('hidden');
    const content = document.getElementById('content');
    if (content) content.classList.remove('content-hidden');
  } catch (e) {
    setIndicators('');
    console.error('refresh failed', e);
  }
}

// ---------- wire up ----------
document.getElementById('filter').oninput = e => { state.filter = e.target.value; renderTable(); };
document.getElementById('btn-refresh').onclick = () => { refresh(); resetTimer(); };
document.querySelectorAll('th[data-sort]').forEach(th => {
  th.onclick = () => {
    const k = th.dataset.sort;
    if (state.sortKey === k) state.sortDir *= -1;
    else { state.sortKey = k; state.sortDir = (k === 'label' ? 1 : -1); }
    renderTable();
  };
});
function resetTimer() {
  clearInterval(refreshTimer);
  clearInterval(countdownTimer);
  secsLeft = REFRESH_MS / 1000;
  updateCountdown();
  // auto-refresh resets the countdown each time it fires, so the timer
  // never gets stuck at 0.
  refreshTimer = setInterval(() => { refresh(); secsLeft = REFRESH_MS / 1000; }, REFRESH_MS);
  countdownTimer = setInterval(() => { secsLeft = Math.max(0, secsLeft - 1); updateCountdown(); }, 1000);
}
function updateCountdown() {
  const el = document.getElementById('refresh-countdown');
  if (el) el.textContent = secsLeft + 's';
}

// ---------- live updates via SSE ----------
// The collector writes sightings every 5 min; SSE pushes them the moment they
// land, so the dashboard refreshes instantly instead of waiting for the 30s
// timer. Falls back to the timer if SSE drops (EventSource auto-reconnects).
let lastSightingId = 0;
function startStream() {
  const es = new EventSource('/stream?since=' + lastSightingId);
  es.onmessage = (e) => {
    try {
      const s = JSON.parse(e.data);
      if (s.id && s.id > lastSightingId) {
        lastSightingId = s.id;
        refresh();          // new sighting landed — pull fresh state
        resetTimer();       // restart the countdown
      }
    } catch (err) { /* heartbeat or parse error — ignore */ }
  };
  es.onerror = () => { /* EventSource auto-reconnects; nothing to do */ };
}

refresh();
resetTimer();
startStream();
