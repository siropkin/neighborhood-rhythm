// Device details page. Fetches /api/device/<mac> and renders full history.
// Auth token (see app.js) — carried via ?token= since fetch/EventSource can't
// set headers on a navigation. Shared localStorage key 'nr-token'.
const AUTH_TOKEN = (() => {
  let t = new URLSearchParams(location.search).get('t');
  if (t) localStorage.setItem('nr-token', t);
  else t = localStorage.getItem('nr-token') || '';
  return t;
})();
const withToken = url => AUTH_TOKEN ? url + (url.includes('?') ? '&' : '?') + 'token=' + encodeURIComponent(AUTH_TOKEN) : url;
// escape attacker-controlled data (device names, mDNS hostnames) before innerHTML
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const MAC = (() => {
  try { return decodeURIComponent(location.pathname.split('/device/')[1] || ''); }
  catch { return (location.pathname.split('/device/')[1] || ''); }  // malformed %xx — use raw
})();
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
  'rotation': 'rotation', 'mobile': 'mobile', 'unknown': '—',
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
    'rotation': 'Short-lived random MAC — one of a phone\'s rotated addresses (not a visitor).',
    'mobile': 'Wide signal spread — moving (phone in a pocket, not fixed).',
    'unknown': 'Not enough sightings to classify yet.',
  };
  return hints[b.behavior] || '';
};
const TIME_PATTERN_LABELS = {
  'always-on': 'always-on', 'day-active': 'day-active (9-5)',
  'evening': 'evening (after-hours)', 'night-only': 'night-only (suspicious)',
  'transient': 'transient (visitor)', 'irregular': 'irregular', 'unknown': '—',
};
const timePatternLabel = p => TIME_PATTERN_LABELS[p] || p;

function sparkline(canvas, pts) {  // pts: [[ts, rssi], ...]
  const dpr = window.devicePixelRatio || 1;
  const W = canvas.offsetWidth || 600, H = 80;
  canvas.width = Math.round(W * dpr); canvas.height = Math.round(H * dpr);
  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, W, H);
  if (pts.length < 2) return;
  const values = pts.map(p => p[1]);
  const min = Math.min(...values), max = Math.max(...values);
  const span = max - min || 1;
  const step = (W - 34) / (pts.length - 1);
  ctx.strokeStyle = '#58a6ff'; ctx.lineWidth = 1.5;
  ctx.beginPath();
  pts.forEach((p, i) => {
    const x = i * step + 30;  // leave room for the dBm scale
    const y = H - 2 - ((p[1] - min) / span) * (H - 4);
    i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
  });
  ctx.stroke();
  // dBm scale: max top-left, min bottom-left (higher = stronger/closer)
  ctx.fillStyle = '#8b949e'; ctx.font = '10px monospace'; ctx.textAlign = 'left';
  ctx.fillText(max.toFixed(0), 2, 10);
  ctx.fillText(min.toFixed(0), 2, H - 3);
  // hover: vertical strip per reading
  tipZones(canvas.id, pts.map((p, i) => ({
    x: 30 + i * step - step / 2, y: 0, w: Math.max(step, 2), h: H,
    text: `${fmtAgo(p[0])} — ${p[1].toFixed(0)} dBm`,
  })));
}

async function load() {
  const btn = document.getElementById('btn-refresh');
  btn.classList.add('active');
  try {
    const res = await fetch(withToken('/api/device/' + encodeURIComponent(MAC)));
    if (!res.ok) {
      document.getElementById('d-content').innerHTML = `<p>device not found</p>`;
      return;
    }
    const data = await res.json();
    const d = data.device;
    const sightings = data.sightings || [];
    const b = data.behavior;
    const fp = data.fingerprint;
    const tp = data.time_pattern;
    document.title = (d.my_label || d.last_label || MAC) + ' — Neighborhood Rhythm';
    document.getElementById('d-title').textContent = d.my_label || d.last_label || MAC;

    const names = [...new Set(sightings.map(s => s.name).filter(Boolean))];
    const rssiPts = sightings.filter(s => s.rssi != null).map(s => [s.ts, s.rssi]);
    const rssiSeries = rssiPts.map(p => p[1]);
    const bySensor = {};
    for (const s of sightings) {
      bySensor[s.sensor_id] = (bySensor[s.sensor_id] || 0) + 1;
    }

    document.getElementById('d-content').innerHTML = `
      <div class="d-header">
        <span class="type-chip${d.is_mine ? ' mine' : ''}">${esc(d.last_type || '?')}</span>
        <h2>${esc(d.my_label || d.last_label || 'unnamed')}</h2>
      </div>
      <div class="d-sub">${esc(d.oui_name || (d.last_label || 'unknown manufacturer'))} · ${esc(d.mac)}</div>

      <div class="d-actions">
        <button class="btn${d.is_mine ? ' mine' : ''}" id="d-tag">${d.is_mine ? '★ my device — untag' : '☆ mark as my device'}</button>
        <input id="d-tag-label" class="d-tag-input" placeholder="your name for it (optional)" value="${esc(d.my_label || '')}">
      </div>
      <p class="d-hint d-actions-hint">marking as yours adds a gold ★ and groups it under "known" on the dashboard${d.is_mine ? ' — edit the name and it saves when you leave the field' : ''}</p>

      ${data.rogue ? `<div class="status-banner warn" style="margin:12px 0">
        ⚠ Unrecognized device — not in your known baseline.
        <button class="rogue-btn known" id="d-known">Mark known</button>
        <button class="rogue-btn dismiss" id="d-dismiss">Dismiss</button>
      </div>` : (data.is_known ? `<div class="status-banner ok" style="margin:12px 0">✓ in your known baseline</div>` : '')}

      <div class="d-grid">
        <div class="d-stat"><b>${d.sighting_count.toLocaleString()}</b><label>sightings</label></div>
        <div class="d-stat"><b>${names.length}</b><label>name${names.length !== 1 ? 's' : ''} advertised</label></div>
        <div class="d-stat"><b>${Object.keys(bySensor).length}</b><label>scanner${Object.keys(bySensor).length !== 1 ? 's' : ''}</label></div>
        <div class="d-stat"><b>${fmtAgo(d.last_seen)}</b><label>last seen</label></div>
        <div class="d-stat"><b>${fmtAgo(d.first_seen)}</b><label>first seen</label></div>
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

      ${tp && tp.pattern && tp.pattern !== 'unknown' ? `<div class="d-section">
        <h3>when is it seen?</h3>
        <div class="d-grid" style="margin-bottom:12px">
          <div class="d-stat"><b>${timePatternLabel(tp.pattern)}</b><label>pattern</label></div>
          ${tp.peak_hour != null ? `<div class="d-stat"><b>${tp.peak_hour}:00</b><label>peak hour</label></div>` : ''}
        </div>
        <canvas id="time-histogram" class="d-spark"></canvas>
        <span class="d-hint">detections by hour of day — gold bar is the busiest hour. Flat = always on; a bump = a usage pattern (e.g. evenings).</span>
      </div>` : ''}

      ${fp && fp.aliases && fp.aliases.length > 1 ? `<div class="d-section">
        <h3>device fingerprint</h3>
        <span class="d-hint">${fp.aliases.length} identifiers linked as one device (cross-radio / rotation):</span>
        <div class="d-names">${fp.aliases.map(a => `<div class="d-name">${esc(a.mac)} <span class="d-hint">· ${esc(a.source)} · ${esc(a.link_method)}</span></div>`).join('')}</div>
      </div>` : ''}

      <div class="d-section">
        <h3>how strong is the signal?</h3>
        <canvas id="signal-spark" class="d-spark"></canvas>
        ${rssiSeries.length ? `<span class="d-hint">signal strength (dBm) over the last ${rssiSeries.length} sightings, oldest → newest — higher line = closer to the scanner. Range ${Math.min(...rssiSeries).toFixed(0)} to ${Math.max(...rssiSeries).toFixed(0)} dBm.</span>` : '<span class="d-hint">no signal data (mDNS device)</span>'}
      </div>

      ${names.length ? `<div class="d-section"><h3>names advertised</h3><div class="d-names">${names.map(n => `<div class="d-name">${esc(n)}</div>`).join('')}</div></div>` : ''}

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
          if (lines.length) parts.push(`<b>Apple</b>${lines.map(l => `<div class="d-name">${esc(l)}</div>`).join('')}`);
        }
        if (e.sensor) {
          const s = e.sensor;
          const lines = Object.entries(s).map(([k,v]) => `${k}: ${v}`);
          parts.push(`<b>Sensor</b>${lines.map(l => `<div class="d-name">${esc(l)}</div>`).join('')}`);
        }
        return parts.length ? `<div class="d-section"><h3>decoded payload</h3><div class="d-names">${parts.join('')}</div></div>` : '';
      })()}

      <div class="d-section">
        <h3>recent sightings</h3>
        <div class="table-wrap">
          <table>
            <thead><tr><th>time</th><th>sensor</th><th class="num">rssi</th><th class="num">distance</th><th>source</th></tr></thead>
            <tbody>
            ${(() => {
              // collapse consecutive identical sightings (same sensor+source+distance)
              // into a summary row — the 30 identical ble rows become one "N×" row
              const recent = sightings.slice(-30).reverse();
              const rows = [];
              let group = [];
              for (const s of recent) {
                const prev = group[group.length - 1];
                if (prev && prev.sensor_id === s.sensor_id && prev.source === s.source && prev.distance === s.distance) {
                  group.push(s);
                } else {
                  if (group.length) rows.push(group);
                  group = [s];
                }
              }
              if (group.length) rows.push(group);
              return rows.map(g => {
                const s = g[0];
                const n = g.length;
                return `<tr>
                  <td>${n > 1 ? n + '× ' : ''}${fmt(s.ts)}</td>
                  <td>${esc(s.sensor_id)}</td>
                  <td class="num">${s.rssi != null ? s.rssi.toFixed(0) + ' dBm' : '—'}</td>
                  <td class="num">${s.distance != null && s.distance <= 50 ? s.distance.toFixed(1) + 'm' : '—'}</td>
                  <td>${esc(s.source)}</td>
                </tr>`;
              }).join('');
            })()}
            </tbody>
          </table>
        </div>
      </div>

    `;

    if (rssiPts.length >= 2) sparkline(document.getElementById('signal-spark'), rssiPts);

    // detection-time histogram (24 bars, one per hour)
    if (tp && tp.hours) {
      const hc = document.getElementById('time-histogram');
      if (hc) {
        const dpr = window.devicePixelRatio || 1;
        const W = hc.offsetWidth || 600, H = 80;
        hc.width = Math.round(W * dpr); hc.height = Math.round(H * dpr);
        const ctx = hc.getContext('2d');
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        ctx.clearRect(0, 0, W, H);
        const max = Math.max(1, ...Object.values(tp.hours));
        const padL = 26, padB = 12, plotH = H - padB;
        const bw = (W - padL) / 24;
        // y-axis scale (0 + max) so bar heights mean something
        ctx.fillStyle = '#8b949e'; ctx.font = '10px monospace'; ctx.textAlign = 'left';
        ctx.fillText(max, 2, 9);
        ctx.fillText('0', 2, plotH - 1);
        for (let h = 0; h < 24; h++) {
          const v = tp.hours[h] || 0;
          const bh = (v / max) * (plotH - 14);
          // same language as the dashboard rhythm chart: blue bars, gold peak
          ctx.fillStyle = (tp.peak_hour === h) ? '#f0c674' : '#58a6ff';
          ctx.fillRect(padL + h * bw + 1, plotH - bh, bw - 2, bh);
        }
        // peak count above the gold bar
        if (tp.peak_hour != null && tp.hours[tp.peak_hour]) {
          const pb = (tp.hours[tp.peak_hour] / max) * (plotH - 14);
          ctx.fillStyle = '#8b949e'; ctx.textAlign = 'center';
          ctx.fillText(tp.hours[tp.peak_hour], padL + tp.peak_hour * bw + bw / 2, plotH - pb - 3);
        }
        ctx.fillStyle = '#8b949e'; ctx.font = '10px monospace'; ctx.textAlign = 'center';
        for (const h of [0, 6, 12, 18, 23]) ctx.fillText(String(h), padL + h * bw + bw / 2, H - 1);
        // hover: full-height column per hour
        tipZones('time-histogram', Array.from({length: 24}, (_, h) => ({
          x: padL + h * bw, y: 0, w: bw, h: plotH,
          text: `${h}:00–${(h + 1) % 24}:00 — ${tp.hours[h] || 0} detections`,
        })));
      }
    }

    document.getElementById('d-tag').onclick = async () => {
      const mine = !d.is_mine;
      const label = document.getElementById('d-tag-label').value || (mine ? (d.last_label || 'my device') : null);
      await fetch(withToken('/api/device/' + encodeURIComponent(MAC) + '/tag'), {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ is_mine: mine, my_label: label }),
      });
      load();
    };
    // editing the name of an already-mine device saves on blur/Enter
    const tagInput = document.getElementById('d-tag-label');
    const saveLabel = async () => {
      if (!d.is_mine || tagInput.value === (d.my_label || '')) return;
      await fetch(withToken('/api/device/' + encodeURIComponent(MAC) + '/tag'), {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ is_mine: 1, my_label: tagInput.value }),
      });
      load();
    };
    tagInput.onchange = saveLabel;
    // rogue review actions (rendered only when an open rogue event exists)
    const post = (url, body) => fetch(withToken(url), {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body),
    });
    const btnKnown = document.getElementById('d-known');
    if (btnKnown) btnKnown.onclick = async () => {
      await post('/api/rogue/known', { mac: MAC, label: document.getElementById('d-tag-label').value || undefined });
      load();
    };
    const btnDismiss = document.getElementById('d-dismiss');
    if (btnDismiss) btnDismiss.onclick = async () => {
      await post('/api/rogue/' + encodeURIComponent(MAC) + '/resolve', {});
      load();
    };
  } catch (e) {
    document.getElementById('d-content').innerHTML = `<p>error: ${esc(e.message || e)}</p>`;
  } finally {
    btn.classList.remove('active');
  }
}

document.getElementById('btn-refresh').onclick = load;
load();
