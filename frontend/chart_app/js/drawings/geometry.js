// Pixel geometry for drawing and hit-testing drawings.

export const HIT = 6;            // px: how close the mouse must be to a line
export const HANDLE_R = 5;       // px: handle circle radius

export function distToSegment(x, y, a, b) {
  const dx = b.x - a.x, dy = b.y - a.y;
  const len2 = dx * dx + dy * dy;
  let t = len2 ? ((x - a.x) * dx + (y - a.y) * dy) / len2 : 0;
  t = Math.max(0, Math.min(1, t));
  return Math.hypot(x - (a.x + t * dx), y - (a.y + t * dy));
}

// The part of the line a->b to draw, extended left and/or right to the
// pane edges (a far-away point is enough; the canvas clips it).
export function extendSegment(a, b, left, right, width) {
  const dx = b.x - a.x, dy = b.y - a.y;
  if (!dx && !dy) return [a, b];
  const far = Math.max(width, 1000) * 4 / Math.max(Math.hypot(dx, dy), 1e-9);
  // "Left" means toward smaller x, whichever point comes first.
  const aIsLeft = a.x <= b.x;
  const [l, r] = aIsLeft ? [a, b] : [b, a];
  const ux = (r.x - l.x), uy = (r.y - l.y);
  const p1 = left ? { x: l.x - ux * far, y: l.y - uy * far } : l;
  const p2 = right ? { x: r.x + ux * far, y: r.y + uy * far } : r;
  return [p1, p2];
}

export function nearPoint(x, y, p, r = HANDLE_R + 3) {
  return Math.hypot(x - p.x, y - p.y) <= r;
}

export function inRect(x, y, a, b, pad = 0) {
  return x >= Math.min(a.x, b.x) - pad && x <= Math.max(a.x, b.x) + pad
      && y >= Math.min(a.y, b.y) - pad && y <= Math.max(a.y, b.y) + pad;
}

export function nearRectBorder(x, y, a, b) {
  const l = Math.min(a.x, b.x), r = Math.max(a.x, b.x);
  const t = Math.min(a.y, b.y), bt = Math.max(a.y, b.y);
  const edges = [[{ x: l, y: t }, { x: r, y: t }], [{ x: r, y: t }, { x: r, y: bt }],
                 [{ x: r, y: bt }, { x: l, y: bt }], [{ x: l, y: bt }, { x: l, y: t }]];
  return edges.some(([p, q]) => distToSegment(x, y, p, q) <= HIT);
}

export function dashFor(dash, width) {
  if (dash === 'dashed') return [6 * Math.max(1, width / 1.5), 4 * Math.max(1, width / 1.5)];
  if (dash === 'dotted') return [Math.max(1, width), 2 * Math.max(1, width)];
  return [];
}

export function withAlpha(color, alpha) {
  if (/^#[0-9a-f]{6}$/i.test(color)) {
    const n = parseInt(color.slice(1), 16);
    return `rgba(${n >> 16}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`;
  }
  return color;
}

// A text label with a rounded background box.
export function label(ctx, text, x, y, { color = '#fff', bg = null, align = 'left',
  base = 'middle', font = '12px sans-serif', pad = 4 } = {}) {
  ctx.font = font;
  const w = ctx.measureText(text).width;
  const h = parseInt(font, 10) + pad;
  let left = align === 'center' ? x - w / 2 : align === 'right' ? x - w : x;
  let top = base === 'middle' ? y - h / 2 : base === 'bottom' ? y - h : y;
  if (bg) {
    ctx.fillStyle = bg;
    roundRect(ctx, left - pad, top, w + pad * 2, h, 3);
    ctx.fill();
  }
  ctx.fillStyle = color;
  ctx.textAlign = 'left';
  ctx.textBaseline = 'middle';
  ctx.fillText(text, left, top + h / 2 + 0.5);
  return { x: left - pad, y: top, w: w + pad * 2, h };
}

export function roundRect(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}
