// Auto analysis layer: the trendlines, flat levels, Fibonacci, patterns,
// swing labels and daily order blocks the screener finds (the Chart Patterns
// page), drawn read-only. The ⧉ legend button copies them into your own
// drawings, where you can edit them.

import { api } from '../api.js';
import { toast } from '../dom.js';
import { label, withAlpha } from '../drawings/geometry.js';
import { toolDefaults } from '../drawings/manager.js';

const REFRESH_MS = 5 * 60_000;
const C = { support: '#089981', resistance: '#f23645', fib: '#b2b5be', ob: '#9c27b0',
            bull: 'rgba(8,153,129,0.10)', bear: 'rgba(242,54,69,0.10)', neutral: 'rgba(120,123,134,0.10)' };

export class AutoAnalysis {
  constructor(app, slot, study) {
    this.app = app;
    this.slot = slot;
    this.view = slot.view;
    this.study = study;
    this.visible = !study.hidden;
    this.data = null;
    this.key = null;
    this.views = [{ zOrder: () => 'bottom', renderer: () => ({ draw: t => this._draw(t) }) }];
    this.view.onSeries(series => {
      if (this.series) { try { this.series.detachPrimitive(this); } catch { /* gone */ } }
      this.series = series;
      if (!this.dead) series.attachPrimitive(this);
    });
    this.timer = setInterval(() => this._load(true), REFRESH_MS);
  }

  attached({ requestUpdate }) { this.requestUpdate = requestUpdate; }
  detached() { this.requestUpdate = null; }
  paneViews() { return this.views; }
  setVisible(on) { this.visible = on; this.requestUpdate?.(); }
  setInputs() { this._load(true); }
  onTick() {}
  destroy() {
    this.dead = true;
    clearInterval(this.timer);
    try { this.series?.detachPrimitive(this); } catch { /* gone */ }
  }

  // New data: fetch again only when the symbol or timeframe changed.
  refresh() { this._load(false); }

  async _load(force) {
    const info = this.slot.info, tf = this.slot.tf;
    if (!info) return;
    const key = `${info.symbol}|${tf}|${this.study.inputs.n}`;
    if (!force && key === this.key) { this.requestUpdate?.(); return; }
    this.key = key;
    try {
      const data = await api.get('/api/chart/analysis', { symbol: info.symbol, tf, n: this.study.inputs.n,
                                                           order_blocks: this.study.inputs.obs });
      if (key !== this.key) return;
      this.data = data;
      this.requestUpdate?.();
    } catch (err) {
      toast(`Auto analysis: ${err.message}`, 'error');
    }
  }

  _draw(target) {
    const d = this.data;
    if (!d || !this.visible) return;
    const v = this.view, inp = this.study.inputs;
    const X = t => v.timeToX(t), Y = p => v.priceToY(p);
    const font = `11px ${getComputedStyle(document.documentElement).getPropertyValue('--font')}`;
    target.useMediaCoordinateSpace(({ context: ctx, mediaSize: size }) => {
      const W = size.width;
      const seg = (x0, y0, x1, y1, color, width = 1, dash = []) => {
        ctx.strokeStyle = color; ctx.lineWidth = width; ctx.setLineDash(dash);
        ctx.beginPath(); ctx.moveTo(x0, y0); ctx.lineTo(x1, y1); ctx.stroke();
      };
      // A line through two points, drawn to the right edge.
      const ray = (t0, p0, t1, p1, color, width, dash) => {
        const a = { x: X(t0), y: Y(p0) }, b = { x: X(t1), y: Y(p1) };
        if ([a.x, a.y, b.x, b.y].some(n => n === null) || a.x === b.x) return;
        const slope = (b.y - a.y) / (b.x - a.x);
        seg(a.x, a.y, W, a.y + slope * (W - a.x), color, width, dash);
      };

      if (inp.obs) {
        for (const ob of d.order_blocks) {
          const x0 = Math.max(0, X(ob.time) ?? 0);
          const y1 = Y(ob.top), y2 = Y(ob.bottom);
          if (y1 === null || y2 === null) continue;
          ctx.fillStyle = withAlpha(C.ob, ob.broken ? 0.08 : 0.16);
          ctx.fillRect(x0, y1, W - x0, y2 - y1);
          seg(x0, y1, W, y1, withAlpha(C.ob, 0.6)); seg(x0, y2, W, y2, withAlpha(C.ob, 0.6));
          label(ctx, ob.label, W - 6, (y1 + y2) / 2, { align: 'right', color: '#ce93d8', font });
        }
      }
      if (inp.patterns) {
        for (const p of d.patterns) {
          if (p.upper && p.lower) {
            const xs = X(p.upper.t0), xe = X(p.upper.t1);
            const u0 = Y(p.upper.p0), u1 = Y(p.upper.p1), l0 = Y(p.lower.p0), l1 = Y(p.lower.p1);
            if ([xs, xe, u0, u1, l0, l1].every(n => n !== null) && xe !== xs) {
              const su = (u1 - u0) / (xe - xs), sl = (l1 - l0) / (xe - xs);
              const end = Math.min(W, xe + (xe - xs) * 0.3);
              ctx.fillStyle = C[p.bias === 'bullish' ? 'bull' : p.bias === 'bearish' ? 'bear' : 'neutral'];
              ctx.beginPath();
              ctx.moveTo(xs, u0); ctx.lineTo(end, u0 + su * (end - xs));
              ctx.lineTo(end, l0 + sl * (end - xs)); ctx.lineTo(xs, l0); ctx.closePath(); ctx.fill();
              label(ctx, `${p.name} · ${p.status}`, xs + 2, u0 - 10, { color: '#d1d4dc', font });
            }
          }
          for (const pt of p.points) {
            const x = X(pt.time), y = Y(pt.price);
            if (x !== null && y !== null) label(ctx, p.bias === 'bearish' ? 'T' : 'B', x, y + (p.bias === 'bearish' ? -12 : 12), { align: 'center', color: '#fff', bg: '#555', font });
          }
          for (const [tgt, arrow] of [[p.target_up, '↑'], [p.target_down, '↓']]) {
            const y = tgt === null ? null : Y(tgt);
            const xl = X(this.view.bars[this.view.bars.length - 1]?.time);
            if (y === null || xl === null) continue;
            seg(xl, y, W, y, '#b2b5be', 1, [2, 3]);
            label(ctx, `target ${arrow} ${v.fmt(tgt)}`, W - 6, y - 9, { align: 'right', color: '#b2b5be', font });
          }
        }
      }
      if (inp.fib && d.fib) {
        const x0 = X(Math.min(d.fib.t0, d.fib.t1));
        for (const lv of d.fib.levels) {
          const y = Y(lv.price);
          if (x0 === null || y === null) continue;
          seg(x0, y, W, y, withAlpha(C.fib, 0.6), 1, [2, 3]);
          label(ctx, `${lv.ratio} · ${v.fmt(lv.price)}`, x0 + 4, y - 7, { color: C.fib, font });
        }
      }
      if (inp.levels) {
        for (const lv of d.levels) {
          const x0 = X(lv.t0), y = Y(lv.price);
          if (x0 === null || y === null) continue;
          const color = lv.kind === 'resistance' ? C.resistance : C.support;
          seg(x0, y, W, y, withAlpha(color, 0.8), 1, [5, 4]);
          label(ctx, `${lv.kind === 'resistance' ? 'R' : 'S'} ${v.fmt(lv.price)} ×${lv.touches}`, W - 6, y - 8,
                { align: 'right', color, font });
        }
      }
      if (inp.trendlines) {
        for (const ln of d.lines) {
          const color = ln.kind === 'resistance' ? C.resistance : C.support;
          ray(ln.t0, ln.p0, ln.t1, ln.p1, color, ln.rank === 0 ? 2 : 1,
              ln.broken ? [2, 3] : ln.rank === 0 ? [] : [6, 4]);
        }
      }
      if (inp.swings) {
        for (const s of d.swings) {
          const x = X(s.time), y = Y(s.price);
          if (x === null || y === null) continue;
          const high = s.label === 'HH' || s.label === 'LH';
          const good = s.label === 'HH' || s.label === 'HL';
          label(ctx, s.label, x, y + (high ? -12 : 12), { align: 'center', color: good ? C.support : C.resistance, font });
        }
      }
      ctx.setLineDash([]);
    });
  }

  // Copy what is shown into editable drawings.
  copyToDrawings() {
    const d = this.data, m = this.slot.drawings, inp = this.study.inputs;
    if (!d || !m) return;
    const out = [];
    const mk = (tool, points, style = {}, text = '') => out.push({ tool, points, style: { ...toolDefaults(tool), ...style }, text });
    if (inp.trendlines) {
      for (const ln of d.lines) {
        mk('trendline', [{ t: ln.t0, p: ln.p0 }, { t: ln.t1, p: ln.p1 }],
           { color: ln.kind === 'resistance' ? C.resistance : C.support, extendRight: true, width: ln.rank === 0 ? 2 : 1 });
      }
    }
    if (inp.levels) {
      for (const lv of d.levels) {
        mk('hray', [{ t: lv.t0, p: lv.price }], { color: lv.kind === 'resistance' ? C.resistance : C.support, dash: 'dashed' });
      }
    }
    if (inp.fib && d.fib) mk('fib', [{ t: d.fib.t0, p: d.fib.p0 }, { t: d.fib.t1, p: d.fib.p1 }]);
    if (inp.obs) {
      const last = this.view.bars[this.view.bars.length - 1]?.time ?? 0;
      for (const ob of d.order_blocks) {
        mk('rect', [{ t: ob.time, p: ob.top }, { t: last, p: ob.bottom }], { color: C.ob, extendRight: true }, ob.label);
      }
    }
    if (inp.patterns) {
      for (const p of d.patterns) {
        for (const side of ['upper', 'lower']) {
          const l = p[side];
          if (l) mk('trendline', [{ t: l.t0, p: l.p0 }, { t: l.t1, p: l.p1 }], { color: '#b2b5be', extendRight: true });
        }
      }
    }
    if (!out.length) { toast('Nothing to copy'); return; }
    m.addMany(out);
    toast(`${out.length} drawing(s) added — hide the auto layer to edit them`, 'ok');
  }
}
