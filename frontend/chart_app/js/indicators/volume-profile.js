// Visible-range volume profile: volume traded at each price over the candles
// on screen, split into up and down volume, with the point of control (POC)
// and the value area. Recomputed as you scroll and zoom.

function rgba(hex, a) {
  if (!/^#[0-9a-f]{6}$/i.test(hex)) return hex;
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${n >> 16}, ${(n >> 8) & 255}, ${n & 255}, ${a})`;
}

// Rows of {lo, hi, up, down} for bars[from..to].
export function profile(bars, from, to, rows) {
  let lo = Infinity, hi = -Infinity;
  for (let i = from; i <= to; i++) { lo = Math.min(lo, bars[i].low); hi = Math.max(hi, bars[i].high); }
  if (!(hi > lo)) return null;
  const step = (hi - lo) / rows;
  const out = Array.from({ length: rows }, (_, k) => ({ lo: lo + k * step, hi: lo + (k + 1) * step, up: 0, down: 0 }));
  for (let i = from; i <= to; i++) {
    const b = bars[i];
    const range = b.high - b.low;
    const a = Math.max(0, Math.floor((b.low - lo) / step));
    const z = Math.min(rows - 1, Math.floor((b.high - lo) / step));
    const side = b.close >= b.open ? 'up' : 'down';
    for (let k = a; k <= z; k++) {
      // Share of the candle's range inside this row (all of it for a doji).
      const part = range > 0 ? (Math.min(b.high, out[k].hi) - Math.max(b.low, out[k].lo)) / range : 1 / (z - a + 1);
      out[k][side] += b.volume * Math.max(0, part);
    }
  }
  const tot = out.map(r => r.up + r.down);
  let poc = 0;
  tot.forEach((v, k) => { if (v > tot[poc]) poc = k; });
  return { rows: out, poc, total: tot.reduce((x, y) => x + y, 0), tot };
}

export function valueArea(p, pct) {
  let lo = p.poc, hi = p.poc, sum = p.tot[p.poc];
  const want = p.total * pct / 100;
  while (sum < want && (lo > 0 || hi < p.tot.length - 1)) {
    const below = lo > 0 ? p.tot[lo - 1] : -1, above = hi < p.tot.length - 1 ? p.tot[hi + 1] : -1;
    if (above >= below) sum += p.tot[++hi]; else sum += p.tot[--lo];
  }
  return [lo, hi];
}

export class VolumeProfile {
  constructor(view, study) {
    this.view = view;
    this.study = study;
    this.visible = !study.hidden;
    this.views = [{ zOrder: () => 'bottom', renderer: () => ({ draw: t => this._draw(t) }) }];
    view.onSeries(series => {
      if (this.series) { try { this.series.detachPrimitive(this); } catch { /* gone */ } }
      this.series = series;
      if (!this.dead) series.attachPrimitive(this);
    });
  }

  attached({ requestUpdate }) { this.requestUpdate = requestUpdate; }
  detached() { this.requestUpdate = null; }
  paneViews() { return this.views; }
  refresh() { this.requestUpdate?.(); }
  onTick() { this.refresh(); }
  setInputs() { this.refresh(); }
  setVisible(on) { this.visible = on; this.refresh(); }
  destroy() { this.dead = true; try { this.series?.detachPrimitive(this); } catch { /* gone */ } }

  _draw(target) {
    if (!this.visible) return;
    const v = this.view, bars = v.bars;
    const r = v.chart.timeScale().getVisibleLogicalRange();
    if (!r || !bars.length) return;
    const from = Math.max(0, Math.floor(r.from)), to = Math.min(bars.length - 1, Math.ceil(r.to));
    if (to - from < 2) return;
    const inp = this.study.inputs;
    const p = profile(bars, from, to, Math.max(5, Math.min(200, inp.rows | 0)));
    if (!p) return;
    const [vaLo, vaHi] = valueArea(p, inp.valueArea);
    const max = Math.max(...p.tot);
    target.useMediaCoordinateSpace(({ context: ctx, mediaSize }) => {
      const full = mediaSize.width * inp.width / 100;
      const right = inp.placement !== 'left';
      p.rows.forEach((row, k) => {
        const y1 = v.priceToY(row.hi), y2 = v.priceToY(row.lo);
        if (y1 === null || y2 === null) return;
        const h = Math.max(1, Math.abs(y2 - y1) - 1);
        const inVa = k >= vaLo && k <= vaHi;
        const wUp = full * row.up / max, wDn = full * row.down / max;
        const x0 = right ? mediaSize.width : 0;
        ctx.fillStyle = rgba(inp.upColor, inVa ? 0.55 : 0.25);
        ctx.fillRect(right ? x0 - wUp : x0, Math.min(y1, y2), wUp, h);
        ctx.fillStyle = rgba(inp.downColor, inVa ? 0.55 : 0.25);
        ctx.fillRect(right ? x0 - wUp - wDn : x0 + wUp, Math.min(y1, y2), wDn, h);
      });
      const pr = p.rows[p.poc];
      const y = v.priceToY((pr.lo + pr.hi) / 2);
      if (y !== null) {
        ctx.strokeStyle = inp.pocColor;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(mediaSize.width, y);
        ctx.stroke();
      }
    });
  }
}
