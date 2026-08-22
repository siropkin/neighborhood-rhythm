// Neighborhood Rhythm — radar + device table. Vanilla JS, no framework.
// Auth: the dashboard URL carries ?t=<token> (hidden URL). We stash it in
// localStorage and append ?token= to every API/SSE/CSV call — EventSource and
// navigations can't set Authorization headers, so the query param is the path.
const AUTH_TOKEN = (() => {
  let t = new URLSearchParams(location.search).get('t');
  if (t) localStorage.setItem('nr-token', t);
  else t = localStorage.getItem('nr-token') || '';
  return t;
})();
const authQ = AUTH_TOKEN ? '?token=' + encodeURIComponent(AUTH_TOKEN) : '';
const withToken = url => AUTH_TOKEN ? url + (url.includes('?') ? '&' : '?') + 'token=' + encodeURIComponent(AUTH_TOKEN) : url;

const TYPE_COLORS = {
  tv: '#58a6ff', speaker: '#bc8cff', light: '#56d364', phone: '#8b949e',
  laptop: '#79c0ff', tablet: '#a5d6ff', vacuum: '#ff9800',
  'phone-anon': '#7d85b0', 'apple-device': '#bbb', 'samsung-device': '#7fb3ff',
  'iot-esp32': '#56d364', iot: '#56d364', 'iot-serial': '#56d364',
  sensor: '#f0883e', thermostat: '#f0883e', 'google-device': '#4285f4',
  bridge: '#8b949e', fan: '#79c0ff', lock: '#f0883e', outlet: '#56d364',
  switch: '#56d364', camera: '#f0883e',
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
  bridge: 'homekit bridge', fan: 'fan', lock: 'lock', outlet: 'outlet',
  switch: 'switch', camera: 'camera',
  mine: '★ mine',
};
const typeLabel = t => TYPE_LABELS[t] || t;
const colorFor = d => d.is_mine ? '#f0c674' : (TYPE_COLORS[d.last_type] || '#484f58');
// BLE RSSI→distance is ±50% even calibrated; without tx_power it's garbage.
// Cap the displayed distance at 50m — anything beyond is a tx_power-null
// artifact (the radar shows rings, not points, for this reason).
const fmtDist = d => (d == null || d > 50) ? '—' : d.toFixed(1) + 'm';
const BEHAVIOR_LABELS = {
  'always-on': 'always-on', 'active-cyclic': 'cyclic', 'intermittent': 'intermittent',
  'transient': 'visitor', 'rotation': 'rotation', 'mobile': 'mobile', 'unknown': '—',
};
const behaviorLabel = b => BEHAVIOR_LABELS[b] || b;
const colorForType = t => colorFor({is_mine: t === 'mine', last_type: t});
const fmtAgo = ts => {
  if (!ts) return '—';
  const s = Date.now()/1000 - ts;
  if (s < 60) return 'now';
  if (s < 3600) return Math.floor(s/60) + 'm ago';
  if (s < 86400) return Math.floor(s/3600) + 'h ago';
  return Math.floor(s/86400) + 'd ago';
};
const getJSON = async url => {
  // Retry once: gunicorn closes idle keep-alive sockets and Chrome sometimes
  // reuses a just-closed one (ERR_SOCKET_NOT_CONNECTED). A 2nd fetch succeeds.
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      const res = await fetch(withToken(url), { cache: 'no-store' });
      if (!res.ok && attempt === 0) throw new Error('http ' + res.status);
      return await res.json();
    } catch (e) {
      if (attempt === 1) throw e;
    }
  }
};

let state = { devices: [], positions: {}, filter: '', chipFilter: 'all', rogueMacs: new Set(), sortKey: 'last_seen', sortDir: -1, showAll: false, siteId: '' };
const TABLE_LIMIT = 20;

// ---------- Radar ----------
// Bands scale to the real data: sub-meter when everything's close, larger when far.
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

// ---------- charts: 24h rhythm, device-type donut, signal histogram ----------
// Size a canvas to its CSS box × devicePixelRatio so it's crisp on Retina.
// Returns {ctx, W, H} in CSS pixels — draw in CSS coords, the scale handles DPI.
function setupCanvas(id) {
  const c = document.getElementById(id);
  if (!c) return null;
  const dpr = window.devicePixelRatio || 1;
  const W = c.offsetWidth || 360, H = c.offsetHeight || 200;
  c.width = Math.round(W * dpr);
  c.height = Math.round(H * dpr);
  const ctx = c.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, W, H);
  return { ctx, W, H };
}
function drawRhythmChart(rhythm) {
  const cv = setupCanvas('rhythm-chart');
  if (!cv) return;
  const { ctx, W, H } = cv;
  if (!rhythm) return;
  // show the real peak — no 95th-percentile cap. If one hour is 10x the rest,
  // that's the signal (the building's pulse), not noise to hide.
  const max = Math.max(1, Math.max(...rhythm) * 1.1);
  const bw = W / 24;
  for (let h = 0; h < 24; h++) {
    const bh = Math.min((rhythm[h] / max) * (H - 20), H - 20);
    ctx.fillStyle = '#58a6ff';
    ctx.fillRect(h * bw + 1, H - bh - 14, bw - 2, bh);
  }
  ctx.fillStyle = '#8b949e'; ctx.font = '11px monospace';
  ctx.fillText('0', 2, H - 2); ctx.fillText('6', W/4 - 4, H - 2);
  ctx.fillText('12', W/2 - 6, H - 2); ctx.fillText('18', 3*W/4 - 6, H - 2); ctx.fillText('23', W - 16, H - 2);
}

function drawTypeDonut(typeCounts) {
  const cv = setupCanvas('type-chart');
  if (!cv) return;
  const { ctx, W, H } = cv;
  if (!typeCounts) return;
  const entries = Object.entries(typeCounts).sort((a, b) => b[1] - a[1]);
  const total = entries.reduce((s, [, n]) => s + n, 0) || 1;
  const cx = W/2, cy = H/2, r = Math.min(cx, cy) - 10;
  let start = -Math.PI / 2;
  for (const [t, n] of entries) {
    const angle = (n / total) * 2 * Math.PI;
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.arc(cx, cy, r, start, start + angle);
    ctx.closePath();
    ctx.fillStyle = colorForType(t);
    ctx.fill();
    start += angle;
  }
  // hole
  ctx.fillStyle = 'var(--surface)';
  ctx.beginPath(); ctx.arc(cx, cy, r * 0.6, 0, 2*Math.PI); ctx.fill();
  ctx.fillStyle = 'var(--text)'; ctx.font = 'bold 16px monospace'; ctx.textAlign = 'center';
  ctx.fillText(entries.length + ' types', cx, cy);
  ctx.font = '11px monospace'; ctx.fillStyle = 'var(--muted)';
  ctx.fillText(total + ' devices', cx, cy + 16);
  ctx.textAlign = 'start';
  // color-coded legend with count + percentage
  const legend = document.getElementById('type-legend');
  if (legend) {
    legend.innerHTML = entries.map(([t, n]) => {
      const pct = Math.round(n / total * 100);
      return `<span><i style="background:${colorForType(t)}"></i>${typeLabel(t)} ${n} (${pct}%)</span>`;
    }).join('');
  }
}

function drawRssiHistogram(rssiBuckets) {
  const cv = setupCanvas('rssi-chart');
  if (!cv) return;
  const { ctx, W, H } = cv;
  if (!rssiBuckets) return;
  const keys = ['near', 'mid', 'far', 'very far'];
  // one-line label: distance (primary) + dBm range (secondary, in brackets)
  const labels = ['~1m (≥-60)', '~4m (-60 to -70)', '~8m (-70 to -80)', '15m+ (<-80)'];
  // single-hue sequential ramp (dark=near, light=far) — no "closer=better" judgment
  const colors = ['#1f6feb', '#388bfd', '#58a6ff', '#8b949e'];
  const max = Math.max(1, ...keys.map(k => rssiBuckets[k] || 0));
  const bw = W / 4;
  for (let i = 0; i < 4; i++) {
    const v = rssiBuckets[keys[i]] || 0;
    const bh = (v / max) * (H - 30);   // reserve space for the count + one-line label
    ctx.fillStyle = colors[i];
    ctx.fillRect(i * bw + 4, H - bh - 18, bw - 8, bh);
    ctx.fillStyle = '#8b949e'; ctx.font = 'bold 12px monospace'; ctx.textAlign = 'center';
    ctx.fillText(v, i * bw + bw/2, Math.max(12, H - bh - 22));
    ctx.font = (W < 200 ? '8px' : '10px') + ' monospace';
    ctx.fillText(labels[i], i * bw + bw/2, H - 4);
  }
  ctx.textAlign = 'start';
}

// legacy radar (kept for reference, no longer rendered)
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
      <i class="tb-dot" style="background:${colorForType(t)}"></i>
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
    const t = d.is_mine ? 'mine' : (d.last_type || 'unknown');
    seen.add(t);
  }
  const sorted = [...seen].sort((a, b) => typeLabel(a).localeCompare(typeLabel(b)));
  for (const t of sorted) {
    const s = document.createElement('span');
    s.innerHTML = `<i style="background:${colorForType(t)}"></i>${typeLabel(t)}`;
    el.appendChild(s);
  }
}

// ---------- Table ----------
function renderTable() {
  const tb = document.getElementById('device-rows');
  tb.innerHTML = '';
  let rows = state.devices.filter(d => {
    // chip filter: type, or "rogue" (in the new-devices set), or "all"
    const cf = state.chipFilter;
    if (cf !== 'all') {
      if (cf === 'rogue') { if (!state.rogueMacs.has(d.mac)) return false; }
      else if (cf === 'known') { if (!d.is_mine) return false; }
      else if (d.last_type !== cf) return false;
    }
    if (!state.filter) return true;
    const q = state.filter.toLowerCase();
    return (d.last_label || '').toLowerCase().includes(q)
        || (d.my_label || '').toLowerCase().includes(q)
        || (d.oui_name || '').toLowerCase().includes(q)
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
  const shown = state.showAll ? rows : rows.slice(0, TABLE_LIMIT);
  for (const d of shown) {
    const tr = document.createElement('tr');
    const isRogue = state.rogueMacs.has(d.mac);
    if (isRogue) tr.classList.add('rogue-row');
    tr.innerHTML = `
      <td data-label="type"><span class="type-chip${d.is_mine ? ' mine' : ''}" title="${d.last_type || ''}">${typeLabel(d.last_type || '?')}</span></td>
      <td data-label="device" class="dev-name"><b>${d.my_label || d.last_label || '—'}</b> <span class="mono dev-mac">${d.mac}</span></td>
      <td data-label="id" class="num" title="${d.alias_count > 1 ? (d.alias_count + ' identifiers linked as one device') : 'single device'}">${d.alias_count > 1 ? '<b class="alias-link">' + d.alias_count + '↔</b>' : '—'}</td>
      <td data-label="dist" class="num">${fmtDist(d.distance)}</td>
      <td data-label="rssi" class="num">${d.rssi != null ? d.rssi.toFixed(0) : '—'}</td>
      <td data-label="seen" class="num">${fmtAgo(d.last_seen)}</td>
      <td data-label="mine" class="num" title="tap to tag a device as yours"><span class="mine-mark ${d.is_mine ? '' : 'off'}" role="button" aria-label="${d.is_mine ? 'tagged as mine' : 'mark as mine'}" aria-pressed="${d.is_mine}">${d.is_mine ? '★' : '☆'}</span></td>
      <td data-label="" class="rogue-actions">${isRogue ? `<button class="rogue-btn known" data-mac="${d.mac}">Mark known</button><button class="rogue-btn dismiss" data-mac="${d.mac}">Dismiss</button>` : ''}</td>`;
    tr.onclick = () => { location.href = withToken('/device/' + encodeURIComponent(d.mac)); };
    tb.appendChild(tr);
  }
  if (!state.showAll && rows.length > TABLE_LIMIT) {
    const tr = document.createElement('tr');
    tr.className = 'show-all-row';
    tr.innerHTML = `<td colspan="8">show all ${rows.length} devices ▾</td>`;
    tr.onclick = () => { state.showAll = true; renderTable(); };
    tb.appendChild(tr);
  }
  // wire up rogue action buttons (Mark known / Dismiss) in the device table
  // stopPropagation so the row click (→ device page) doesn't fire on button clicks
  tb.querySelectorAll('button.rogue-btn').forEach(b => b.onclick = (e) => {
    e.stopPropagation();
    if (b.classList.contains('known'))
      rogueAction(b.dataset.mac, '/api/rogue/known', {mac: b.dataset.mac});
    else
      rogueAction(b.dataset.mac, `/api/rogue/${encodeURIComponent(b.dataset.mac)}/resolve`, {});
  });
  // mark sorted header
  document.querySelectorAll('th').forEach(th => {
    th.classList.toggle('sorted', th.dataset.sort === state.sortKey);
  });
}

// ---------- rogue devices (new stable-MAC devices not in baseline) ----------
function renderStatusBanner(rogues) {
  const el = document.getElementById('status-banner');
  if (!el) return;
  if (!rogues.length) {
    el.hidden = false;
    el.className = 'status-banner ok';
    el.textContent = '✓ All clear — 0 unrecognized devices. Your building inventory is current.';
  } else {
    el.hidden = false;
    el.className = 'status-banner warn';
    el.innerHTML = `${rogues.length} unrecognized device${rogues.length>1?'s':''} to review — <a href="#" id="review-rogues">review them</a> (filter the table to "new" below)`;
    const link = document.getElementById('review-rogues');
    if (link) link.onclick = (e) => {
      e.preventDefault();
      const chip = document.querySelector('.chip[data-filter="rogue"]');
      if (chip) chip.click();
      document.getElementById('device-table').scrollIntoView({ behavior: 'smooth' });
    };
  }
}
async function rogueAction(mac, endpoint, body) {
  try {
    await fetch(withToken(endpoint), {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body || {}),
    });
    refresh();
  } catch (e) { console.error('rogue action failed', e); }
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
    const siteQ = state.siteId ? '?site_id=' + encodeURIComponent(state.siteId) : '';
    const [stats, now, positions, rogues] = await Promise.all([
      getJSON('/api/stats'), getJSON('/api/now' + siteQ), getJSON('/api/positions'),
      getJSON('/api/rogue' + siteQ),
    ]);
    document.getElementById('s-current').textContent = stats.current;
    document.getElementById('s-total').textContent = stats.total;
    document.getElementById('s-real').textContent = stats.real;
    document.getElementById('s-wifi').textContent = stats.wifi;
    document.getElementById('s-sensors').textContent = stats.sensors;
    document.getElementById('s-scan').textContent = fmtAgo(stats.last_scan);
    // KPI tiles: stable vs random + source breakdown
    document.getElementById('s-stable').textContent = stats.real;
    document.getElementById('s-random').textContent = stats.total - stats.real;
    const sc = stats.source_counts || {};
    document.getElementById('s-src-ble').textContent = sc.ble || 0;
    document.getElementById('s-src-wifi').textContent = sc.wifi || 0;
    document.getElementById('s-src-mdns').textContent = sc.mdns || 0;
    state.devices = now.devices;
    state.positions = positions.positions;
    state.rogueMacs = new Set((rogues.rogues || []).map(r => r.mac));
    drawRhythmChart(stats.rhythm);
    // device types: split mine vs unknown from the active device list so the
    // gold slice shows your devices, not just the raw type distribution
    const typeCounts = {};
    for (const d of now.devices) {
      const t = d.is_mine ? 'mine' : (d.last_type || 'unknown');
      typeCounts[t] = (typeCounts[t] || 0) + 1;
    }
    drawTypeDonut(typeCounts);
    drawRssiHistogram(stats.rssi_buckets);
    renderTable();
    renderStatusBanner(rogues.rogues || []);
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
document.getElementById('btn-export').onclick = () => { window.location = withToken('/api/now?format=csv'); };
document.querySelectorAll('#filter-chips .chip').forEach(chip => chip.onclick = () => {
  document.querySelectorAll('#filter-chips .chip').forEach(c => c.classList.remove('active'));
  chip.classList.add('active');
  state.chipFilter = chip.dataset.filter;
  renderTable();
});
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
// SSE pushes new sightings the moment they land. Throttled: one refresh per
// burst (not one per sighting — that exhausts the browser's connection pool).
let lastSightingId = 0;
let refreshPending = false;
function startStream() {
  const onmsg = (e) => {
    try {
      const s = JSON.parse(e.data);
      if (s.id > lastSightingId) lastSightingId = s.id;
      // throttle: one refresh per burst, not one per message
      if (!refreshPending) {
        refreshPending = true;
        setTimeout(() => { refreshPending = false; refresh(); resetTimer(); }, 1500);
      }
    } catch (err) { /* heartbeat or parse error — ignore */ }
  };
  // EventSource auto-reconnect reuses the *original* URL — which still carries
  // the stale since= from construction, so the server re-seeds to current MAX
  // and sightings that arrived during the disconnect gap are lost. Rebuild
  // with the live lastSightingId so the server replays from where we left off.
  let es = new EventSource(withToken('/stream?since=' + lastSightingId));
  es.onmessage = onmsg;
  function onerror() {
    es.close();
    // Backoff so a server returning 500 doesn't trigger a tight reconnect loop.
    setTimeout(() => {
      es = new EventSource(withToken('/stream?since=' + lastSightingId));
      es.onmessage = onmsg;
      es.onerror = onerror;
    }, 3000);
  }
  es.onerror = onerror;
}

refresh();
resetTimer();
startStream();
// ---------- site selector (multi-tenant) ----------
(async () => {
  try {
    const data = await getJSON('/api/sites');
    const sel = document.getElementById('site-select');
    if (!sel || !data.sites || !data.sites.length) return;
    sel.innerHTML = '<option value="">all sites</option>' +
      data.sites.map(s => `<option value="${s.site_id}">${s.label} (${s.sensors} scanner${s.sensors!==1?'s':''}, ${s.devices} devices)</option>`).join('');
    sel.onchange = () => { state.siteId = sel.value; refresh(); };
  } catch (e) { /* sites endpoint not available or empty — no selector */ }
})();

// ---------- help modal + first-run banner ----------
const helpModal = document.getElementById('help-modal');
const btnHelp = document.getElementById('btn-help');
if (btnHelp && helpModal) {
  btnHelp.onclick = () => { helpModal.hidden = false; };
  const helpClose = document.getElementById('help-close');
  if (helpClose) helpClose.onclick = () => { helpModal.hidden = true; };
  helpModal.onclick = e => { if (e.target === helpModal) helpModal.hidden = true; };
}
// first-run banner: show until the user dismisses it (localStorage)
const firstrun = document.getElementById('firstrun');
if (firstrun && !localStorage.getItem('nr-firstrun-dismissed')) {
  firstrun.hidden = false;
  const dismiss = document.getElementById('firstrun-dismiss');
  if (dismiss) dismiss.onclick = () => {
    firstrun.hidden = true;
    localStorage.setItem('nr-firstrun-dismissed', '1');
  };
}
