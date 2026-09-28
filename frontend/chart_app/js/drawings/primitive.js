// The Lightweight Charts primitive that paints every drawing of one chart,
// their handles, and their labels on the price and time axes.

import { fmtChartTime } from '../format.js';
import { HANDLE_R, label } from './geometry.js';
import { TOOLS, handlesOf } from './tools.js';

const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();

class Renderer {
  constructor(prim) { this.prim = prim; }
  draw(target) {
    target.useMediaCoordinateSpace(({ context: ctx, mediaSize }) => {
      this.prim.paint(ctx, mediaSize);
    });
  }
}

export class DrawingsPrimitive {
  constructor(manager) {
    this.m = manager;
    this.views = [{ zOrder: () => 'top', renderer: () => this.renderer }];
    this.renderer = new Renderer(this);
    this.priceViews = [];
    this.timeViews = [];
  }

  attached({ requestUpdate }) { this.requestUpdate = requestUpdate; }
  detached() { this.requestUpdate = null; }
  update() { if (this.requestUpdate) this.requestUpdate(); }
  paneViews() { return this.views; }
  priceAxisViews() { return this.priceViews; }
  timeAxisViews() { return this.timeViews; }

  // Axis labels: price of every horizontal line, and the points of the
  // selected drawing on both axes.
  updateAllViews() {
    const m = this.m, v = m.view;
    const price = [], time = [];
    const accent = css('--accent');
    const add = (p, color) => {
      const y = v.priceToY(p);
      if (y === null) return;
      price.push({ coordinate: () => y, text: () => v.fmt(p), textColor: () => '#fff',
                   backColor: () => color, visible: () => true, tickVisible: () => true });
    };
    for (const d of m.visible()) {
      const tool = TOOLS[d.tool];
      if (tool?.axisLabel && d.style.showPrice !== false) add(d.points[0].p, d.style.color);
    }
    const sel = m.selectedDrawing();
    if (sel) {
      const tool = TOOLS[sel.tool];
      const prices = tool.axisPrices ? tool.axisPrices(sel) : sel.points.map(p => p.p);
      if (!tool.axisLabel) for (const p of prices) add(p, accent);
      if (sel.tool !== 'hline' && sel.tool !== 'hray') {
        for (const pt of sel.points) {
          const x = v.timeToX(pt.t);
          if (x === null) continue;
          time.push({ coordinate: () => x, text: () => fmtChartTime(v.toChart(pt.t), v.intraday),
                      textColor: () => '#fff', backColor: () => accent,
                      visible: () => true, tickVisible: () => true });
        }
      }
    }
    this.priceViews = price;
    this.timeViews = time;
  }

  // Cursor and hover for the chart's own hit test.
  hitTest(x, y) {
    const hit = this.m.hitTest(x, y);
    if (!hit) return null;
    return { cursorStyle: hit.handle !== null ? 'pointer' : (hit.d.locked ? 'default' : 'move'),
             externalId: hit.d.id, zOrder: 'top' };
  }

  paint(ctx, size) {
    const m = this.m;
    const env = m.env(size);
    ctx.save();
    ctx.lineCap = 'round';
    for (const d of [...m.visible(), ...(m.creating ? [m.creating] : [])]) {
      const tool = TOOLS[d.tool];
      if (!tool) continue;
      const P = m.pixels(d);
      if (!P) continue;
      ctx.save();
      try { tool.draw(ctx, d, P, env); } catch (err) { console.warn('drawing failed', d, err); }
      ctx.restore();
      const selected = d === m.creating || d.id === m.selected;
      if (selected || d.id === m.hovered) this._handles(ctx, handlesOf(tool, d, P), d, selected);
    }
    if (m.measure) this._measure(ctx, m.measure, env);
    ctx.restore();
  }

  _handles(ctx, hs, d, selected) {
    ctx.setLineDash([]);
    for (const h of hs) {
      ctx.beginPath();
      ctx.arc(h.x, h.y, HANDLE_R, 0, Math.PI * 2);
      ctx.fillStyle = selected ? css('--chart-bg') || '#000' : 'rgba(0,0,0,0)';
      ctx.fill();
      ctx.lineWidth = 1.5;
      ctx.strokeStyle = d.locked ? '#787b86' : css('--accent');
      if (selected || !d.locked) ctx.stroke();
    }
  }

  // Date and price range box (the measure tool).
  _measure(ctx, ms, env) {
    const v = this.m.view;
    const [a, b] = ms.points;
    const A = { x: v.timeToX(a.t), y: v.priceToY(a.p) }, B = { x: v.timeToX(b.t), y: v.priceToY(b.p) };
    if ([A.x, A.y, B.x, B.y].some(n => n === null)) return;
    const up = b.p >= a.p;
    const color = up ? '#2962ff' : '#f23645';
    ctx.fillStyle = up ? 'rgba(41, 98, 255, 0.18)' : 'rgba(242, 54, 69, 0.18)';
    ctx.fillRect(Math.min(A.x, B.x), Math.min(A.y, B.y), Math.abs(B.x - A.x), Math.abs(B.y - A.y));
    ctx.strokeStyle = color;
    ctx.lineWidth = 1;
    ctx.setLineDash([]);
    const midX = (A.x + B.x) / 2, midY = (A.y + B.y) / 2;
    ctx.beginPath(); ctx.moveTo(midX, A.y); ctx.lineTo(midX, B.y); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(A.x, midY); ctx.lineTo(B.x, midY); ctx.stroke();
    const dp = b.p - a.p;
    const bars = Math.round(v.logicalOf(b.t) - v.logicalOf(a.t));
    const secs = Math.abs(b.t - a.t);
    const dur = secs >= 86400 ? `${Math.round(secs / 86400)}d` : secs >= 3600
      ? `${Math.floor(secs / 3600)}h ${Math.round(secs % 3600 / 60)}m` : `${Math.round(secs / 60)}m`;
    const lines = [`${dp >= 0 ? '+' : ''}${v.fmt(dp)} (${(a.p ? dp / a.p * 100 : 0).toFixed(2)}%)`,
                   `${bars} bars, ${dur}`];
    let y = (up ? Math.min(A.y, B.y) - 8 : Math.max(A.y, B.y) + 8) + (up ? -18 * (lines.length - 1) : 0);
    for (const t of lines) {
      label(ctx, t, midX, y, { align: 'center', base: up ? 'bottom' : 'top', color: '#fff', bg: color, font: env.font });
      y += 18;
    }
  }
}
