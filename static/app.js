// Neighborhood Rhythm — radar + device table. Vanilla JS, no framework.
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
      const res = await fetch(url, { cache: 'no-store' });
      if (!res.ok && attempt === 0) throw new Error('http ' + res.status);
      return await res.json();
    } catch (e) {
      if (attempt === 1) throw e;
    }
  }
};

let state = { devices: [], positions: {}, filter: '', chipFilter: 'all', rogueMacs: new Set(), sortKey: 'last_seen', sortDir: -1, showAll: false };
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
    if (state.rogueMacs.has(d.mac)) tr.classList.add('rogue-row');
    tr.innerHTML = `
      <td data-label="type"><span class="type-chip${d.is_mine ? ' mine' : ''}" title="${d.last_type || ''}">${typeLabel(d.last_type || '?')}</span></td>
      <td data-label="device" class="dev-name"><b>${d.my_label || d.last_label || '—'}</b> <span class="mono dev-mac">${d.mac}</span></td>
      <td data-label="id" class="num" title="${d.alias_count > 1 ? (d.alias_count + ' identifiers linked as one device') : 'single device'}">${d.alias_count > 1 ? '<b class="alias-link">' + d.alias_count + '↔</b>' : '—'}</td>
      <td data-label="dist" class="num">${fmtDist(d.distance)}</td>
      <td data-label="rssi" class="num">${d.rssi != null ? d.rssi.toFixed(0) : '—'}</td>
      <td data-label="seen" class="num">${fmtAgo(d.last_seen)}</td>
      <td data-label="mine" class="num" title="tap to tag a device as yours"><span class="mine-mark ${d.is_mine ? '' : 'off'}" role="button" aria-label="${d.is_mine ? 'tagged as mine' : 'mark as mine'}" aria-pressed="${d.is_mine}">${d.is_mine ? '★' : '☆'}</span></td>`;
    tr.onclick = () => { location.href = '/device/' + encodeURIComponent(d.mac); };
    tb.appendChild(tr);
  }
  if (!state.showAll && rows.length > TABLE_LIMIT) {
    const tr = document.createElement('tr');
    tr.className = 'show-all-row';
    tr.innerHTML = `<td colspan="7">show all ${rows.length} devices ▾</td>`;
    tr.onclick = () => { state.showAll = true; renderTable(); };
    tb.appendChild(tr);
  }
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
    el.textContent = `${rogues.length} unrecognized device${rogues.length>1?'s':''} to review below — mark the ones you recognize as known, investigate the rest.`;
  }
}
async function rogueAction(mac, endpoint, body) {
  try {
    await fetch(endpoint, {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body || {}),
    });
    refresh();
  } catch (e) { console.error('rogue action failed', e); }
}
function renderRogue(rogues) {
  const panel = document.getElementById('rogue-panel');
  if (!panel) return;
  const tb = document.getElementById('rogue-rows');
  const count = document.getElementById('rogue-count');
  if (!rogues || !rogues.length) {
    panel.hidden = true;
    tb.innerHTML = '';
    return;
  }
  panel.hidden = false;
  count.textContent = rogues.length;
  tb.innerHTML = rogues.map(r => `
    <tr>
      <td class="dev-name rogue-name" data-mac="${r.mac}"><b>${r.label || r.mac}</b> <span class="mono dev-mac">${r.mac}</span>${r.behavior && r.behavior.behavior ? ` <span class="rogue-behavior">${behaviorLabel(r.behavior.behavior)}</span>` : ''}</td>
      <td>${r.oui_name || '—'}</td>
      <td><span class="type-chip">${typeLabel(r.device_class || '?')}</span></td>
      <td>${r.source || '—'}</td>
      <td class="num">${r.rssi != null ? r.rssi.toFixed(0) : '—'}</td>
      <td class="num">${fmtDist(r.distance)}</td>
      <td class="num">${fmtAgo(r.device_last_seen || r.ts)}</td>
      <td class="rogue-actions">
        <button class="rogue-btn known" data-mac="${r.mac}">Mark known</button>
        <button class="rogue-btn dismiss" data-mac="${r.mac}">Dismiss</button>
      </td>
    </tr>`).join('');
  // click the device name → device details page (like the main table)
  tb.querySelectorAll('td.rogue-name').forEach(td =>
    td.onclick = () => { location.href = '/device/' + encodeURIComponent(td.dataset.mac); });
  tb.querySelectorAll('button.known').forEach(b => b.onclick = () =>
    rogueAction(b.dataset.mac, '/api/rogue/known', {mac: b.dataset.mac}));
  tb.querySelectorAll('button.dismiss').forEach(b => b.onclick = () =>
    rogueAction(b.dataset.mac, `/api/rogue/${encodeURIComponent(b.dataset.mac)}/resolve`, {}));
  const markAll = document.getElementById('rogue-mark-all');
  if (markAll) markAll.onclick = async () => {
    for (const r of rogues) {
      await fetch('/api/rogue/known', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({mac: r.mac}) });
    }
    refresh();
  };
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
    const [stats, now, positions, rogues] = await Promise.all([
      getJSON('/api/stats'), getJSON('/api/now'), getJSON('/api/positions'),
      getJSON('/api/rogue'),
    ]);
    document.getElementById('s-current').textContent = stats.current;
    document.getElementById('s-total').textContent = stats.total;
    document.getElementById('s-real').textContent = stats.real;
    document.getElementById('s-wifi').textContent = stats.wifi;
    document.getElementById('s-sensors').textContent = stats.sensors;
    document.getElementById('s-scan').textContent = fmtAgo(stats.last_scan);
    state.devices = now.devices;
    state.positions = positions.positions;
    state.rogueMacs = new Set((rogues.rogues || []).map(r => r.mac));
    drawRadar();
    renderLegend();
    renderTypeBreakdown();
    renderTable();
    renderRogue(rogues.rogues);
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
document.getElementById('btn-export').onclick = () => { window.location = '/api/now?format=csv'; };
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
  let es = new EventSource('/stream?since=' + lastSightingId);
  es.onmessage = onmsg;
  function onerror() {
    es.close();
    // Backoff so a server returning 500 doesn't trigger a tight reconnect loop.
    setTimeout(() => {
      es = new EventSource('/stream?since=' + lastSightingId);
      es.onmessage = onmsg;
      es.onerror = onerror;
    }, 3000);
  }
  es.onerror = onerror;
}

refresh();
resetTimer();
startStream();

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
