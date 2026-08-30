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
// Escape attacker-controlled data (BLE device names, mDNS hostnames) before
// innerHTML — a malicious advertiser could otherwise run JS in the dashboard
// and steal the API token from localStorage.
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

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
      if (!res.ok) throw new Error('http ' + res.status);
      return await res.json();
    } catch (e) {
      if (attempt === 1) throw e;
    }
  }
};

let state = { devices: [], rogues: [], filter: '', chipFilter: 'all', rogueMacs: new Set(), sortKey: 'last_seen', sortDir: -1, showAll: false, siteId: '' };
const TABLE_LIMIT = 20;

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
// resolve a CSS variable to its computed hex/rgb value — canvas ignores 'var(--x)'
const _cssCache = {};
function cssVar(name) {
  if (_cssCache[name]) return _cssCache[name];
  const v = getComputedStyle(document.body).getPropertyValue(name).trim();
  _cssCache[name] = v || '#8b949e';
  return _cssCache[name];
}
function truncate(s, n) { return s.length > n ? s.slice(0, n - 1) + '…' : s; }
// redraw all charts from cached state (refresh, resize, theme change)
function redrawCharts() {
  const sc = state._lastStats || {};
  drawRhythmChart(sc.rhythm);
  drawRssiHistogram(sc.rssi_buckets);
  const typeCounts = {};
  for (const d of state.devices) {
    const t = d.is_mine ? 'mine' : (d.last_type || 'unknown');
    typeCounts[t] = (typeCounts[t] || 0) + 1;
  }
  drawTypeDonut(typeCounts);
}
// canvas colors come from CSS vars — drop the cache + redraw on theme flip
matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
  for (const k in _cssCache) delete _cssCache[k];
  redrawCharts();
});
function drawRhythmChart(rhythm) {
  const cv = setupCanvas('rhythm-chart');
  if (!cv) return;
  const { ctx, W, H } = cv;
  if (!rhythm) return;
  // show the real peak — no 95th-percentile cap. If one hour is 10x the rest,
  // that's the signal (the building's pulse), not noise to hide.
  const peakVal = Math.max(...rhythm);
  const max = Math.max(1, peakVal * 1.1);
  const padL = 28, padR = 4, padB = 16, padT = 8;
  const plotW = W - padL - padR, plotH = H - padB - padT;
  // y-axis ticks + gridlines
  const yTicks = 4;
  ctx.strokeStyle = cssVar('--border'); ctx.fillStyle = cssVar('--muted');
  ctx.lineWidth = 1; ctx.font = '10px monospace'; ctx.textAlign = 'right'; ctx.textBaseline = 'middle';
  for (let i = 0; i <= yTicks; i++) {
    const v = Math.round((max / yTicks) * i);
    const y = padT + plotH - (v / max) * plotH;
    ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(W - padR, y); ctx.globalAlpha = i === 0 ? 1 : 0.4; ctx.stroke(); ctx.globalAlpha = 1;
    ctx.fillText(v, padL - 4, y);
  }
  // bars
  const bw = plotW / 24;
  const peakHour = peakVal > 0 ? rhythm.indexOf(peakVal) : -1;  // -1: no gold bar on an all-zero chart
  ctx.textAlign = 'center'; ctx.textBaseline = 'alphabetic';
  for (let h = 0; h < 24; h++) {
    const bh = (rhythm[h] / max) * plotH;
    ctx.fillStyle = h === peakHour ? cssVar('--gold') : '#58a6ff';
    ctx.fillRect(padL + h * bw + 1, padT + plotH - bh, bw - 2, bh);
    // label the peak bar with its count
    if (h === peakHour && peakVal > 0) {
      ctx.fillStyle = cssVar('--text'); ctx.font = 'bold 10px monospace';
      ctx.fillText(peakVal, padL + h * bw + bw / 2, padT + plotH - bh - 2);
      ctx.font = '10px monospace';
    }
  }
  // x-axis hour labels
  ctx.fillStyle = cssVar('--muted'); ctx.font = '10px monospace';
  ctx.fillText('0', padL + 0 * bw + bw / 2, H - 2);
  ctx.fillText('6', padL + 6 * bw + bw / 2, H - 2);
  ctx.fillText('12', padL + 12 * bw + bw / 2, H - 2);
  ctx.fillText('18', padL + 18 * bw + bw / 2, H - 2);
  ctx.fillText('23', padL + 23 * bw + bw / 2, H - 2);
  ctx.textAlign = 'start';
}

// colorblind-safe categorical palette (Okabe-Ito derived), assigned in fixed order
const TYPE_PALETTE = ['#0072b2', '#e69f00', '#009e73', '#cc79a5', '#56b4e9', '#d55e00', '#f0c674', '#999999', '#a020f0', '#228b22', '#ff1493', '#4169e1'];
function drawTypeDonut(typeCounts) {
  const cv = setupCanvas('type-chart');
  if (!cv) return;
  const { ctx, W, H } = cv;
  if (!typeCounts) return;
  const entries = Object.entries(typeCounts).sort((a, b) => b[1] - a[1]);
  const total = entries.reduce((s, [, n]) => s + n, 0) || 1;
  const max = Math.max(1, ...entries.map(([, n]) => n));
  // horizontal bar chart — better than a donut for many small categories
  const padL = 4, padR = 40, rowH = Math.min(22, (H - 4) / entries.length), gap = 3;
  const labelW = Math.min(110, W * 0.4);
  const barX = padL + labelW + 6;
  const barW = W - barX - padR;
  ctx.textBaseline = 'middle'; ctx.font = '12px sans-serif';
  entries.forEach(([t, n], i) => {
    const y = 2 + i * rowH;
    const color = TYPE_PALETTE[i % TYPE_PALETTE.length];
    ctx.fillStyle = cssVar('--text'); ctx.textAlign = 'left';
    ctx.fillText(truncate(typeLabel(t), 18), padL, y + rowH / 2);
    ctx.fillStyle = color;
    const w = (n / max) * barW;
    ctx.fillRect(barX, y + gap / 2, w, rowH - gap);
    // count label: inside long bars (near-black reads on every palette color),
    // outside short ones — the old fixed-x label overlapped full-width bars
    const label = n + ' (' + Math.round(n / total * 100) + '%)';
    if (w > 70) {
      ctx.fillStyle = '#0d1117'; ctx.textAlign = 'right';
      ctx.fillText(label, barX + w - 5, y + rowH / 2);
    } else {
      ctx.fillStyle = cssVar('--muted'); ctx.textAlign = 'left';
      ctx.fillText(label, barX + w + 5, y + rowH / 2);
    }
  });
  ctx.textAlign = 'start'; ctx.textBaseline = 'alphabetic';
  // legend below the chart (accessible text list)
  const legend = document.getElementById('type-legend');
  if (legend) {
    legend.innerHTML = '<span class="legend-head">' + entries.length + ' types, ' + total + ' devices</span>' +
      entries.map(([t, n], i) => {
        const pct = Math.round(n / total * 100);
        const color = TYPE_PALETTE[i % TYPE_PALETTE.length];
        return `<span><i style="background:${color}"></i>${esc(typeLabel(t))}<span class="legend-count">${n} (${pct}%)</span></span>`;
      }).join('');
  }
}

function drawRssiHistogram(rssiBuckets) {
  const cv = setupCanvas('rssi-chart');
  if (!cv) return;
  const { ctx, W, H } = cv;
  if (!rssiBuckets) return;
  const keys = ['near', 'mid', 'far', 'very far'];
  // distance label (primary) + dBm range (secondary); shortened on narrow canvases
  const fullLabels = ['~1m (≥-60)', '~4m (-60 to -70)', '~8m (-70 to -80)', '15m+ (<-80)'];
  const shortLabels = ['~1m', '~4m', '~8m', '15m+'];
  const labels = W < 480 ? shortLabels : fullLabels;  // full labels collide below ~480px
  // single-hue sequential ramp (dark=near, light=far) — no "closer=better" judgment
  const colors = ['#1f6feb', '#388bfd', '#58a6ff', '#8b949e'];
  const max = Math.max(1, ...keys.map(k => rssiBuckets[k] || 0));
  const padL = 24, padR = 4, padB = 24, padT = 8;
  const plotW = W - padL - padR, plotH = H - padB - padT;
  // y-axis ticks
  const yTicks = 3;
  ctx.strokeStyle = cssVar('--border'); ctx.fillStyle = cssVar('--muted');
  ctx.lineWidth = 1; ctx.font = '10px monospace'; ctx.textAlign = 'right'; ctx.textBaseline = 'middle';
  for (let i = 0; i <= yTicks; i++) {
    const v = Math.round((max / yTicks) * i);
    const y = padT + plotH - (v / max) * plotH;
    ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(W - padR, y); ctx.globalAlpha = i === 0 ? 1 : 0.4; ctx.stroke(); ctx.globalAlpha = 1;
    ctx.fillText(v, padL - 4, y);
  }
  const bw = plotW / 4;
  ctx.textAlign = 'center'; ctx.textBaseline = 'alphabetic';
  for (let i = 0; i < 4; i++) {
    const v = rssiBuckets[keys[i]] || 0;
    const bh = (v / max) * plotH;
    const x = padL + i * bw;
    ctx.fillStyle = colors[i];
    ctx.fillRect(x + 4, padT + plotH - bh, bw - 8, bh);
    // count label inside top of bar (or above if bar too short)
    ctx.fillStyle = bh > 18 ? cssVar('--surface') : cssVar('--muted');
    ctx.font = 'bold 12px monospace';
    ctx.fillText(v, x + bw / 2, bh > 18 ? padT + plotH - bh + 13 : padT + plotH - bh - 3);
    // x-axis label
    ctx.fillStyle = cssVar('--muted'); ctx.font = (W < 200 ? '8px' : '10px') + ' monospace';
    ctx.fillText(labels[i], x + bw / 2, H - 4);
  }
  ctx.textAlign = 'start';
}

// ---------- Table ----------
function renderTable() {
  const tb = document.getElementById('device-rows');
  tb.innerHTML = '';
  // "unrecognized" chip shows ALL open rogue events (not just currently-active
  // devices) — the banner count must match what the review filter shows.
  let rows = state.chipFilter === 'rogue'
    ? state.rogues.map(r => ({
        mac: r.mac, last_type: r.device_class, last_label: r.label, my_label: null,
        oui_name: r.oui_name, alias_count: 1, distance: r.distance, rssi: r.rssi,
        last_seen: r.device_last_seen, is_mine: 0,
        behavior: r.behavior && r.behavior.behavior,
      }))
    : state.devices.filter(d => {
      const cf = state.chipFilter;
      if (cf === 'known' && !d.is_mine) return false;
      if (cf !== 'all' && cf !== 'known' && d.last_type !== cf) return false;
      return true;
    });
  if (state.filter) {
    const q = state.filter.toLowerCase();
    rows = rows.filter(d =>
      (d.last_label || '').toLowerCase().includes(q)
      || (d.my_label || '').toLowerCase().includes(q)
      || (d.oui_name || '').toLowerCase().includes(q)
      || d.mac.toLowerCase().includes(q)
      || (d.last_type || '').toLowerCase().includes(q));
  }
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
    const isRogue = state.rogueMacs.has(d.mac.toUpperCase());
    if (isRogue) tr.classList.add('rogue-row');
    tr.innerHTML = `
      <td data-label="type"><span class="type-chip${d.is_mine ? ' mine' : ''}" title="${esc(d.last_type || '')}">${esc(typeLabel(d.last_type || '?'))}</span></td>
      <td data-label="device" class="dev-name"><b>${esc(d.my_label || d.last_label || '—')}</b> <span class="mono dev-mac">${esc(d.mac)}</span>${d.behavior ? `<span class="rogue-behavior">${esc(behaviorLabel(d.behavior))}</span>` : ''}</td>
      <td data-label="id" class="num" title="${d.alias_count > 1 ? (d.alias_count + ' identifiers linked as one device') : 'single device'}">${d.alias_count > 1 ? '<b class="alias-link">' + d.alias_count + '↔</b>' : '—'}</td>
      <td data-label="dist" class="num">${fmtDist(d.distance)}</td>
      <td data-label="rssi" class="num">${d.rssi != null ? d.rssi.toFixed(0) : '—'}</td>
      <td data-label="seen" class="num">${fmtAgo(d.last_seen)}</td>
      <td data-label="mine" class="num" title="tap to tag a device as yours"><span class="mine-mark ${d.is_mine ? '' : 'off'}" data-mac="${esc(d.mac)}" role="button" tabindex="0" aria-label="${d.is_mine ? 'tagged as mine' : 'mark as mine'}" aria-pressed="${d.is_mine}">${d.is_mine ? '★' : '☆'}</span></td>
      <td data-label="" class="rogue-actions">${isRogue ? `<button class="rogue-btn known" data-mac="${esc(d.mac)}">Mark known</button><button class="rogue-btn dismiss" data-mac="${esc(d.mac)}">Dismiss</button>` : ''}</td>`;
    tr.onclick = () => { location.href = withToken('/device/' + encodeURIComponent(d.mac)); };
    tb.appendChild(tr);
  }
  if (!state.showAll && rows.length > TABLE_LIMIT) {
    const tr = document.createElement('tr');
    tr.className = 'show-all-row';
    tr.innerHTML = `<td colspan="8">showing ${TABLE_LIMIT} of ${rows.length} — show all ▾</td>`;
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
  // mine star: tapping it opens the device page (where the "mark as mine" button
  // lives) — stopPropagation so the row click fires once, not twice.
  tb.querySelectorAll('.mine-mark').forEach(m => {
    const go = (e) => {
      e.stopPropagation();
      location.href = withToken('/device/' + encodeURIComponent(m.dataset.mac));
    };
    m.onclick = go;
    m.onkeydown = (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(e); } };
  });
  // mark sorted header + direction
  document.querySelectorAll('th').forEach(th => {
    const isSorted = th.dataset.sort === state.sortKey;
    th.classList.toggle('sorted', isSorted);
    th.classList.toggle('asc', isSorted && state.sortDir === 1);
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
    el.innerHTML = `${rogues.length} unrecognized device${rogues.length>1?'s':''} to review — <a href="#" id="review-rogues">review them</a>`;
    const reviewRogues = () => {
      const chip = document.querySelector('.chip[data-filter="rogue"]');
      if (chip) chip.click();
      document.getElementById('device-table').scrollIntoView({ behavior: 'smooth' });
    };
    const link = document.getElementById('review-rogues');
    if (link) link.onclick = (e) => { e.preventDefault(); reviewRogues(); };
    el.onclick = (e) => { if (e.target !== link) reviewRogues(); };
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
let refreshing = false;
async function refresh() {
  if (refreshing) return;  // SSE burst + timer + manual click can overlap
  refreshing = true;
  setIndicators('active');
  try {
    const siteQ = state.siteId ? '?site_id=' + encodeURIComponent(state.siteId) : '';
    const [stats, now, rogues] = await Promise.all([
      getJSON('/api/stats?tzoff=' + new Date().getTimezoneOffset()), getJSON('/api/now' + siteQ),
      getJSON('/api/rogue' + siteQ),
    ]);
    document.getElementById('s-current').textContent = stats.current;
    document.getElementById('s-total').textContent = stats.total.toLocaleString();
    document.getElementById('s-wifi').textContent = stats.wifi;
    document.getElementById('s-sensors').textContent = stats.sensors;
    document.getElementById('s-scan').textContent = fmtAgo(stats.last_scan);
    // KPI tiles: stable vs random (same 24h window, computed server-side)
    document.getElementById('s-stable').textContent = stats.stable.toLocaleString();
    document.getElementById('s-random').textContent = stats.random.toLocaleString();
    const sc = stats.source_counts || {};
    document.getElementById('s-src-ble').textContent = sc.ble || 0;
    document.getElementById('s-src-wifi').textContent = sc.wifi || 0;
    document.getElementById('s-src-mdns').textContent = sc.mdns || 0;
    state.devices = now.devices;
    state.rogues = rogues.rogues || [];
    // normalize case: rogue_events MACs can be lowercase, /api/now uppercase
    state.rogueMacs = new Set(state.rogues.map(r => r.mac.toUpperCase()));
    state._lastStats = stats;
    redrawCharts();
    renderTable();
    renderStatusBanner(state.rogues);
    setIndicators('ok');
    // hide the first-load overlay + reveal content once we have data
    const loading = document.getElementById('loading');
    if (loading) loading.classList.add('hidden');
    const content = document.getElementById('content');
    if (content) content.classList.remove('content-hidden');
  } catch (e) {
    setIndicators('');
    console.error('refresh failed', e);
    // first-load failure: don't leave the spinner up forever — say what happened
    const loading = document.getElementById('loading');
    if (loading && !loading.classList.contains('hidden')) {
      loading.innerHTML = `<span>couldn't reach the scanner (${esc(e.message)}) — <a href="">retry</a></span>`;
    }
  } finally {
    refreshing = false;
  }
}

// ---------- wire up ----------
document.getElementById('filter').oninput = e => { state.filter = e.target.value; renderTable(); };
document.getElementById('btn-refresh').onclick = () => { refresh(); resetTimer(); };
document.getElementById('btn-export').onclick = () => {
  const siteQ = state.siteId ? '&site_id=' + encodeURIComponent(state.siteId) : '';
  window.location = withToken('/api/now?format=csv' + siteQ);
};
document.querySelectorAll('#filter-chips .chip').forEach(chip => chip.onclick = () => {
  document.querySelectorAll('#filter-chips .chip').forEach(c => c.classList.remove('active'));
  chip.classList.add('active');
  state.chipFilter = chip.dataset.filter;
  renderTable();
});
document.querySelectorAll('th[data-sort]').forEach(th => {
  th.tabIndex = 0;  // keyboard-sortable
  const sort = () => {
    const k = th.dataset.sort;
    if (state.sortKey === k) state.sortDir *= -1;
    else { state.sortKey = k; state.sortDir = (k === 'label' ? 1 : -1); }
    renderTable();
  };
  th.onclick = sort;
  th.onkeydown = e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); sort(); } };
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
        setTimeout(() => {
          refreshPending = false;
          if (document.hidden) return;  // tab in background — skip the Pi queries
          refresh(); resetTimer();
        }, 1500);
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
// re-render charts on resize so canvas content reflows to the CSS box
let _resizeTimer;
window.addEventListener('resize', () => {
  clearTimeout(_resizeTimer);
  _resizeTimer = setTimeout(() => { if (state.devices) redrawCharts(); }, 150);
});
// ---------- site selector (multi-tenant) ----------
(async () => {
  try {
    const data = await getJSON('/api/sites');
    const sel = document.getElementById('site-select');
    if (!sel || !data.sites || !data.sites.length) return;  // stays hidden
    sel.innerHTML = '<option value="">all sites</option>' +
      data.sites.map(s => `<option value="${esc(s.site_id)}">${esc(s.label)} (${s.sensors} scanner${s.sensors!==1?'s':''}, ${s.devices} devices)</option>`).join('');
    sel.hidden = false;
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
  document.addEventListener('keydown', e => { if (e.key === 'Escape') helpModal.hidden = true; });
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
  const glossaryLink = document.getElementById('firstrun-glossary');
  if (glossaryLink) glossaryLink.onclick = (e) => { e.preventDefault(); if (helpModal) helpModal.hidden = false; };
}
