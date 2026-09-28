// Drawing tools. Each tool says how many clicks make it, how to draw it from
// pixel points, how to hit-test it, and which settings it has.
//
// A drawing: { id, key, tool, points: [{t, p}], style, text, locked, hidden }
// P below is its points in pixels: [{x, y}] (same order).

import {
  HIT, dashFor, distToSegment, extendSegment, inRect, label, nearRectBorder, withAlpha,
} from './geometry.js';

export const PALETTE = ['#f23645', '#ff9800', '#ffeb3b', '#4caf50', '#089981', '#00bcd4',
  '#2962ff', '#673ab7', '#9c27b0', '#e91e63', '#ffffff', '#b2b5be', '#787b86', '#131722'];

export const FIB_LEVELS = [
  { v: 0, color: '#787b86', on: true }, { v: 0.236, color: '#f23645', on: true },
  { v: 0.382, color: '#ff9800', on: true }, { v: 0.5, color: '#4caf50', on: true },
  { v: 0.618, color: '#089981', on: true }, { v: 0.786, color: '#00bcd4', on: true },
  { v: 1, color: '#787b86', on: true }, { v: 1.272, color: '#2962ff', on: false },
  { v: 1.618, color: '#2962ff', on: true }, { v: 2.618, color: '#f23645', on: false },
];

const LINE_FIELDS = [
  { key: 'color', label: 'Colour', type: 'color' },
  { key: 'width', label: 'Width', type: 'select', options: [[1, '1 px'], [2, '2 px'], [3, '3 px'], [4, '4 px']] },
  { key: 'dash', label: 'Style', type: 'select', options: [['solid', 'Solid'], ['dashed', 'Dashed'], ['dotted', 'Dotted']] },
];

function stroke(ctx, s) {
  ctx.strokeStyle = s.color;
  ctx.lineWidth = s.width || 1;
  ctx.setLineDash(dashFor(s.dash, s.width || 1));
}

function line(ctx, a, b) {
  ctx.beginPath();
  ctx.moveTo(a.x, a.y);
  ctx.lineTo(b.x, b.y);
  ctx.stroke();
}

// Price and % change between two points, for line labels.
function moveText(env, p0, p1) {
  const d = p1 - p0;
  return `${d >= 0 ? '+' : ''}${env.fmt(d)} (${d >= 0 ? '+' : ''}${(p0 ? d / p0 * 100 : 0).toFixed(2)}%)`;
}

// ---- lines ------------------------------------------------------------------
function lineTool(id, label_, left, right) {
  return {
    id, label: label_, clicks: 2, group: 'lines',
    defaults: { color: '#2962ff', width: 2, dash: 'solid', extendLeft: left, extendRight: right, showMove: false },
    fields: [...LINE_FIELDS,
      { key: 'extendLeft', label: 'Extend left', type: 'check' },
      { key: 'extendRight', label: 'Extend right', type: 'check' },
      { key: 'showMove', label: 'Show price change', type: 'check' }],
    draw(ctx, d, P, env) {
      const s = d.style;
      const [a, b] = extendSegment(P[0], P[1], s.extendLeft, s.extendRight, env.width);
      stroke(ctx, s);
      line(ctx, a, b);
      if (s.showMove) {
        const mid = { x: (P[0].x + P[1].x) / 2, y: (P[0].y + P[1].y) / 2 };
        label(ctx, moveText(env, d.points[0].p, d.points[1].p), mid.x, mid.y - 12,
              { align: 'center', color: '#fff', bg: withAlpha(s.color, 0.85), font: env.font });
      }
    },
    hit(d, P, x, y, env) {
      const s = d.style;
      const [a, b] = extendSegment(P[0], P[1], s.extendLeft, s.extendRight, env.width);
      return distToSegment(x, y, a, b) <= HIT;
    },
  };
}

const hline = {
  id: 'hline', label: 'Horizontal line', clicks: 1, group: 'lines', axisLabel: true,
  defaults: { color: '#2962ff', width: 1, dash: 'solid', showPrice: true },
  fields: [...LINE_FIELDS, { key: 'showPrice', label: 'Price label on the line', type: 'check' }],
  draw(ctx, d, P, env) {
    stroke(ctx, d.style);
    line(ctx, { x: 0, y: P[0].y }, { x: env.width, y: P[0].y });
    if (d.text) label(ctx, d.text, 8, P[0].y - 10, { color: d.style.color, font: env.font });
  },
  hit: (d, P, x, y) => Math.abs(y - P[0].y) <= HIT,
  moveBody: 'price',
};

const hray = {
  id: 'hray', label: 'Horizontal ray', clicks: 1, group: 'lines', axisLabel: true,
  defaults: { color: '#2962ff', width: 1, dash: 'solid' },
  fields: LINE_FIELDS,
  draw(ctx, d, P, env) {
    stroke(ctx, d.style);
    line(ctx, P[0], { x: env.width, y: P[0].y });
  },
  hit: (d, P, x, y) => x >= P[0].x - HIT && Math.abs(y - P[0].y) <= HIT,
};

const vline = {
  id: 'vline', label: 'Vertical line', clicks: 1, group: 'lines',
  defaults: { color: '#2962ff', width: 1, dash: 'solid' },
  fields: LINE_FIELDS,
  draw(ctx, d, P, env) {
    stroke(ctx, d.style);
    line(ctx, { x: P[0].x, y: 0 }, { x: P[0].x, y: env.height });
  },
  hit: (d, P, x) => Math.abs(x - P[0].x) <= HIT,
  moveBody: 'time',
  axisPrices: () => [],
};

// ---- channel ----------------------------------------------------------------
// Points: A, B (the base line) and C (any point on the parallel line).
function channelLines(P) {
  const [a, b, c] = P;
  const yAt = x => (b.x === a.x ? a.y : a.y + (b.y - a.y) * (x - a.x) / (b.x - a.x));
  const off = c ? c.y - yAt(c.x) : 0;
  return [[a, b], [{ x: a.x, y: a.y + off }, { x: b.x, y: b.y + off }],
          [{ x: a.x, y: a.y + off / 2 }, { x: b.x, y: b.y + off / 2 }]];
}

const channel = {
  id: 'channel', label: 'Parallel channel', clicks: 3, group: 'lines',
  defaults: { color: '#2962ff', width: 2, dash: 'solid', fillOpacity: 0.12, middle: true,
              extendLeft: false, extendRight: false },
  fields: [...LINE_FIELDS,
    { key: 'fillOpacity', label: 'Fill opacity (0–1)', type: 'number', min: 0, max: 1, step: 0.05 },
    { key: 'middle', label: 'Middle line', type: 'check' },
    { key: 'extendLeft', label: 'Extend left', type: 'check' },
    { key: 'extendRight', label: 'Extend right', type: 'check' }],
  init: pt => [pt, pt, pt],
  draw(ctx, d, P, env) {
    const s = d.style;
    const [base, par, mid] = channelLines(P.length > 2 ? P : [P[0], P[1], P[1]])
      .map(([a, b]) => extendSegment(a, b, s.extendLeft, s.extendRight, env.width));
    if (s.fillOpacity > 0) {
      ctx.fillStyle = withAlpha(s.color, s.fillOpacity);
      ctx.beginPath();
      ctx.moveTo(base[0].x, base[0].y); ctx.lineTo(base[1].x, base[1].y);
      ctx.lineTo(par[1].x, par[1].y); ctx.lineTo(par[0].x, par[0].y);
      ctx.closePath();
      ctx.fill();
    }
    stroke(ctx, s);
    line(ctx, ...base);
    line(ctx, ...par);
    if (s.middle) {
      ctx.setLineDash([4, 4]);
      ctx.lineWidth = 1;
      line(ctx, ...mid);
    }
  },
  hit(d, P, x, y, env) {
    const s = d.style;
    const [base, par] = channelLines(P).map(([a, b]) => extendSegment(a, b, s.extendLeft, s.extendRight, env.width));
    if (distToSegment(x, y, ...base) <= HIT || distToSegment(x, y, ...par) <= HIT) return true;
    // inside the band
    const minX = Math.min(P[0].x, P[1].x), maxX = Math.max(P[0].x, P[1].x);
    if (x < minX || x > maxX) return false;
    const [l0, l1] = channelLines(P);
    const yA = l0[0].y + (l0[1].y - l0[0].y) * (x - l0[0].x) / ((l0[1].x - l0[0].x) || 1);
    const yB = l1[0].y + (l1[1].y - l1[0].y) * (x - l1[0].x) / ((l1[1].x - l1[0].x) || 1);
    return y >= Math.min(yA, yB) && y <= Math.max(yA, yB);
  },
  handles(d, P) {
    const [, par] = channelLines(P);
    return [P[0], P[1], { x: (par[0].x + par[1].x) / 2, y: (par[0].y + par[1].y) / 2, i: 2 }];
  },
};

// ---- rectangle (zones, order blocks) ------------------------------------------
const rect = {
  id: 'rect', label: 'Rectangle', clicks: 2, group: 'shapes',
  defaults: { color: '#9c27b0', width: 1, dash: 'solid', fillOpacity: 0.2, extendRight: false, showRange: false },
  fields: [...LINE_FIELDS,
    { key: 'fillOpacity', label: 'Fill opacity (0–1)', type: 'number', min: 0, max: 1, step: 0.05 },
    { key: 'extendRight', label: 'Extend right', type: 'check' },
    { key: 'showRange', label: 'Show price range', type: 'check' }],
  draw(ctx, d, P, env) {
    const s = d.style;
    const l = Math.min(P[0].x, P[1].x), t = Math.min(P[0].y, P[1].y);
    const r = s.extendRight ? env.width + 10 : Math.max(P[0].x, P[1].x);
    const h = Math.abs(P[1].y - P[0].y);
    if (s.fillOpacity > 0) {
      ctx.fillStyle = withAlpha(s.color, s.fillOpacity);
      ctx.fillRect(l, t, r - l, h);
    }
    stroke(ctx, s);
    ctx.strokeRect(l, t, r - l, h);
    if (d.text) label(ctx, d.text, l + 6, t + 10, { color: s.color, font: env.font });
    if (s.showRange) {
      const [hi, lo] = [Math.max(d.points[0].p, d.points[1].p), Math.min(d.points[0].p, d.points[1].p)];
      label(ctx, `${env.fmt(hi - lo)} (${(lo ? (hi - lo) / lo * 100 : 0).toFixed(2)}%)`,
            (l + Math.min(r, env.width)) / 2, t - 10, { align: 'center', color: s.color, font: env.font });
    }
  },
  hit(d, P, x, y, env) {
    const b = { x: d.style.extendRight ? env.width + 10 : P[1].x, y: P[1].y };
    const a = d.style.extendRight ? { x: Math.min(P[0].x, P[1].x), y: P[0].y } : P[0];
    return inRect(x, y, a, b) || nearRectBorder(x, y, a, b);
  },
  // Corner handles: the two points plus the other two corners.
  handles: (d, P) => [P[0], P[1], { x: P[0].x, y: P[1].y, i: 'c01' }, { x: P[1].x, y: P[0].y, i: 'c10' }],
  moveHandle(d, h, pt) {
    if (h === 'c01') { d.points[0].t = pt.t; d.points[1].p = pt.p; }
    else if (h === 'c10') { d.points[1].t = pt.t; d.points[0].p = pt.p; }
    else d.points[h] = pt;
  },
};

// ---- fib retracement -----------------------------------------------------------
const fib = {
  id: 'fib', label: 'Fib retracement', clicks: 2, group: 'fib',
  defaults: { color: '#787b86', width: 1, dash: 'dashed', extendRight: false, fillOpacity: 0.06,
              showPrices: true, levels: FIB_LEVELS },
  fields: [
    { key: 'width', label: 'Line width', type: 'select', options: [[1, '1 px'], [2, '2 px']] },
    { key: 'fillOpacity', label: 'Band fill opacity (0–1)', type: 'number', min: 0, max: 1, step: 0.02 },
    { key: 'extendRight', label: 'Extend lines right', type: 'check' },
    { key: 'showPrices', label: 'Show prices', type: 'check' },
    ...FIB_LEVELS.map((l, i) => ({ key: `lv${i}`, label: `Level ${l.v}`, type: 'check' })),
  ],
  // Level v sits at end + (start - end) * v: 0 on the second point, 1 on the first.
  prices(d) {
    const [a, b] = d.points;
    return (d.style.levels || FIB_LEVELS).filter(l => l.on).map(l => ({ ...l, p: b.p + (a.p - b.p) * l.v }));
  },
  draw(ctx, d, P, env) {
    const s = d.style;
    const l = Math.min(P[0].x, P[1].x);
    const r = s.extendRight ? env.width : Math.max(P[0].x, P[1].x);
    const levels = fib.prices(d).map(lv => ({ ...lv, y: env.y(lv.p) })).sort((a, b) => a.v - b.v);
    for (let i = 0; i + 1 < levels.length && s.fillOpacity > 0; i++) {
      ctx.fillStyle = withAlpha(levels[i + 1].color, s.fillOpacity);
      ctx.fillRect(l, Math.min(levels[i].y, levels[i + 1].y), r - l, Math.abs(levels[i + 1].y - levels[i].y));
    }
    ctx.setLineDash(dashFor(s.dash, s.width));
    ctx.strokeStyle = s.color;
    ctx.lineWidth = 1;
    line(ctx, P[0], P[1]);
    ctx.setLineDash([]);
    for (const lv of levels) {
      ctx.strokeStyle = lv.color;
      ctx.lineWidth = s.width;
      line(ctx, { x: l, y: lv.y }, { x: r, y: lv.y });
      const txt = s.showPrices ? `${lv.v} (${env.fmt(lv.p)})` : `${lv.v}`;
      label(ctx, txt, l - 6, lv.y, { align: 'right', color: lv.color, font: env.font });
    }
  },
  hit(d, P, x, y, env) {
    const l = Math.min(P[0].x, P[1].x) - HIT;
    const r = d.style.extendRight ? env.width : Math.max(P[0].x, P[1].x) + HIT;
    if (x < l || x > r) return distToSegment(x, y, P[0], P[1]) <= HIT;
    return fib.prices(d).some(lv => Math.abs(env.y(lv.p) - y) <= HIT)
      || distToSegment(x, y, P[0], P[1]) <= HIT;
  },
  axisPrices: d => fib.prices(d).map(l => l.p),
};

// ---- text ---------------------------------------------------------------------
const text = {
  id: 'text', label: 'Text', clicks: 1, group: 'text', needsText: true,
  defaults: { color: '#d1d4dc', fontSize: 14, bg: false, bold: false },
  fields: [
    { key: 'color', label: 'Colour', type: 'color' },
    { key: 'fontSize', label: 'Size', type: 'select', options: [10, 12, 14, 16, 20, 24, 28, 32].map(v => [v, `${v} px`]) },
    { key: 'bold', label: 'Bold', type: 'check' },
    { key: 'bg', label: 'Background', type: 'check' },
  ],
  draw(ctx, d, P, env) {
    const s = d.style;
    const font = `${s.bold ? '600 ' : ''}${s.fontSize}px ${env.fontFamily}`;
    const lines = (d.text || 'Text').split('\n');
    let y = P[0].y;
    const boxes = lines.map(t => {
      const b = label(ctx, t, P[0].x, y, { color: s.color, font, base: 'top', pad: 3,
                                           bg: s.bg ? withAlpha(s.color, 0.18) : null });
      y += b.h;
      return b;
    });
    d._box = { x: P[0].x - 3, y: P[0].y, w: Math.max(...boxes.map(b => b.w)), h: y - P[0].y };
  },
  hit: (d, P, x, y) => d._box && inRect(x, y, { x: d._box.x, y: d._box.y },
                                       { x: d._box.x + d._box.w, y: d._box.y + d._box.h }, 2),
};

// ---- long / short position ------------------------------------------------------
// Points: 0 = entry (start time, entry price), 1 = target (end time, target),
// 2 = stop (end time, stop price).
function position(id, long) {
  return {
    id, label: long ? 'Long position' : 'Short position', clicks: 1, group: 'position',
    defaults: { qty: 0, showStats: true },
    fields: [{ key: 'showStats', label: 'Show target / stop / R:R', type: 'check' }],
    init(pt, env) {
      const y = env.y(pt.p);
      const step = env.bar;
      const t1 = env.timeAt(env.x(pt.t) + step * 25);
      const stop = env.price(y + (long ? 45 : -45));
      const target = env.price(y + (long ? -90 : 90));
      return [pt, { t: t1, p: target }, { t: t1, p: stop }];
    },
    draw(ctx, d, P, env) {
      const [e, tg, st] = P;
      const l = Math.min(e.x, tg.x), r = Math.max(e.x, tg.x);
      ctx.setLineDash([]);
      ctx.fillStyle = 'rgba(8, 153, 129, 0.22)';
      ctx.fillRect(l, Math.min(e.y, tg.y), r - l, Math.abs(tg.y - e.y));
      ctx.fillStyle = 'rgba(242, 54, 69, 0.22)';
      ctx.fillRect(l, Math.min(e.y, st.y), r - l, Math.abs(st.y - e.y));
      ctx.strokeStyle = '#787b86';
      ctx.lineWidth = 1;
      line(ctx, { x: l, y: e.y }, { x: r, y: e.y });
      if (!d.style.showStats) return;
      const [pe, pt, ps] = d.points.map(p => p.p);
      const reward = Math.abs(pt - pe), risk = Math.abs(pe - ps);
      const cx = (l + r) / 2;
      const f = env.font;
      label(ctx, `Target: ${env.fmt(pt)} (${(reward / pe * 100).toFixed(2)}%)`, cx, tg.y + (long ? -11 : 11),
            { align: 'center', color: '#fff', bg: '#089981', font: f });
      label(ctx, `Stop: ${env.fmt(ps)} (${(risk / pe * 100).toFixed(2)}%)`, cx, st.y + (long ? 11 : -11),
            { align: 'center', color: '#fff', bg: '#f23645', font: f });
      label(ctx, `${long ? 'Long' : 'Short'} ${env.fmt(pe)} · R:R ${risk ? (reward / risk).toFixed(2) : '—'}`,
            cx, e.y, { align: 'center', color: '#fff', bg: 'rgba(60, 64, 76, 0.9)', font: f });
    },
    hit(d, P, x, y) {
      const [e, tg, st] = P;
      return inRect(x, y, { x: e.x, y: tg.y }, { x: tg.x, y: st.y });
    },
    handles: (d, P) => [P[0], P[1], P[2], { x: P[1].x, y: P[0].y, i: 'end' }],
    moveHandle(d, h, pt) {
      const [e, tg, st] = d.points;
      if (h === 0) { e.t = pt.t; e.p = pt.p; }
      else if (h === 1) { tg.p = long ? Math.max(pt.p, e.p) : Math.min(pt.p, e.p); tg.t = st.t = pt.t; }
      else if (h === 2) { st.p = long ? Math.min(pt.p, e.p) : Math.max(pt.p, e.p); tg.t = st.t = pt.t; }
      else if (h === 'end') { tg.t = st.t = pt.t; }
    },
  };
}

export const TOOLS = Object.fromEntries([
  lineTool('trendline', 'Trend line', false, false),
  lineTool('ray', 'Ray', false, true),
  lineTool('extline', 'Extended line', true, true),
  hline, hray, vline, channel, rect, fib, text,
  position('long', true), position('short', false),
].map(t => [t.id, t]));

// Default handles and handle moves for tools that do not set their own.
export const handlesOf = (tool, d, P) => (tool.handles ? tool.handles(d, P) : P);
export function moveHandle(tool, d, h, pt) {
  if (tool.moveHandle) tool.moveHandle(d, h, pt);
  else d.points[h] = pt;
}
