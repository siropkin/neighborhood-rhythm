// Hover/tap tooltips for the hand-rolled canvas charts.
// Draw functions record bar geometry via tipZones(id, zones) after each
// redraw; one shared div shows the zone's text on hover (or tap, for touch).
// zones: [{x, y, w, h, text}] in CSS-pixel canvas coords.
const _tipZones = {};
function tipZones(id, zones) {
  _tipZones[id] = zones;
  const c = document.getElementById(id);
  if (!c || c._tipAttached) return;
  c._tipAttached = true;
  const show = (cx, cy) => {
    const r = c.getBoundingClientRect();
    const x = cx - r.left, y = cy - r.top;
    const z = (_tipZones[id] || []).find(z => x >= z.x && x <= z.x + z.w && y >= z.y && y <= z.y + z.h);
    const tip = _tipEl();
    if (!z) { tip.hidden = true; return; }
    tip.textContent = z.text;
    tip.hidden = false;
    tip.style.left = Math.min(cx + 12, innerWidth - tip.offsetWidth - 8) + 'px';
    tip.style.top = (cy + 14) + 'px';
  };
  c.addEventListener('mousemove', e => show(e.clientX, e.clientY));
  c.addEventListener('click', e => show(e.clientX, e.clientY));  // touch: tap = hover
  c.addEventListener('mouseleave', () => { _tipEl().hidden = true; });
}
function _tipEl() {
  let el = document.getElementById('chart-tooltip');
  if (!el) {
    el = document.createElement('div');
    el.id = 'chart-tooltip';
    el.hidden = true;
    document.body.appendChild(el);
  }
  return el;
}
