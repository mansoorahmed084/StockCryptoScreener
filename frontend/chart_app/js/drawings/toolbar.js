// The floating toolbar over the chart when a drawing is selected:
// colour, width, line style, extend, text, settings, lock, clone, delete.

import { esc, popupMenu } from '../dom.js';
import { ICONS } from '../icons.js';
import { PALETTE, TOOLS } from './tools.js';

const LINE_TOOLS = ['trendline', 'ray', 'extline', 'hline', 'hray', 'vline', 'channel', 'rect', 'fib'];
const EXTEND_TOOLS = ['trendline', 'ray', 'extline', 'channel'];

export class DrawingToolbar {
  constructor(manager, parent) {
    this.m = manager;
    this.el = document.createElement('div');
    this.el.className = 'draw-toolbar';
    this.el.hidden = true;
    parent.appendChild(this.el);
    this.el.addEventListener('mousedown', e => e.stopPropagation());
    manager.on('select', d => this.show(d));
    this.extras = [];                // (drawing) => [{icon, title, run}]
  }

  show(d) {
    if (!d) { this.el.hidden = true; return; }
    const tool = TOOLS[d.tool];
    const s = d.style;
    const btn = (act, html, title, on = false) =>
      `<button class="dt-btn${on ? ' on' : ''}" data-act="${act}" title="${esc(title)}">${html}</button>`;
    const parts = [];
    if (s.color !== undefined && d.tool !== 'long' && d.tool !== 'short') {
      parts.push(btn('color', `<span class="swatch" style="background:${esc(s.color)}"></span>`, 'Colour'));
    }
    if (LINE_TOOLS.includes(d.tool)) {
      parts.push(btn('width', `<span class="wbar" style="height:${s.width}px"></span>${s.width}px`, 'Line width'));
      if (d.tool !== 'fib') parts.push(btn('dash', { solid: '━', dashed: '╍', dotted: '┅' }[s.dash] || '━', 'Line style'));
    }
    if (EXTEND_TOOLS.includes(d.tool)) {
      parts.push(btn('extL', '⇤', 'Extend left', s.extendLeft), btn('extR', '⇥', 'Extend right', s.extendRight));
    }
    if (d.tool === 'rect') parts.push(btn('extR', '⇥', 'Extend right', s.extendRight));
    if (['text', 'hline', 'rect'].includes(d.tool)) parts.push(btn('text', '✎', 'Edit text'));
    for (const x of this.extras.flatMap(f => f(d) || [])) parts.push(btn(`x:${x.id}`, x.icon, x.title));
    parts.push(btn('settings', ICONS.gear, `${tool.label} settings`),
               btn('lock', ICONS.lock, d.locked ? 'Unlock' : 'Lock', d.locked),
               btn('clone', ICONS.clone, 'Clone'),
               btn('remove', ICONS.trash, 'Remove (Delete)'));
    this.el.innerHTML = parts.join('');
    this.el.hidden = false;
    for (const b of this.el.querySelectorAll('[data-act]')) b.onclick = e => this._act(b.dataset.act, d, e.currentTarget);
  }

  _act(act, d, anchor) {
    const m = this.m;
    const style = patch => m.patch(d, patch, { styleOnly: true });
    if (act === 'color') {
      popupMenu(anchor, PALETTE.map(c => ({
        html: `<span class="swatch" style="background:${c}"></span>${c}`, value: c, active: c === d.style.color })),
      c => style({ color: c }), { className: 'palette' });
    } else if (act === 'width') {
      popupMenu(anchor, [1, 2, 3, 4].map(w => ({
        html: `<span class="wbar" style="height:${w}px;width:40px"></span>${w}px`, value: w, active: w === d.style.width })),
      w => style({ width: w }));
    } else if (act === 'dash') {
      popupMenu(anchor, [['solid', '━━━ Solid'], ['dashed', '╍╍╍ Dashed'], ['dotted', '┅┅┅ Dotted']]
        .map(([v, l]) => ({ label: l, value: v, active: v === d.style.dash })), v => style({ dash: v }));
    } else if (act === 'extL') style({ extendLeft: !d.style.extendLeft });
    else if (act === 'extR') style({ extendRight: !d.style.extendRight });
    else if (act === 'lock') m.patch(d, { locked: !d.locked });
    else if (act === 'clone') m.cloneDrawing(d);
    else if (act === 'remove') m.remove(d);
    else if (act === 'text') m.editText(d);
    else if (act === 'settings') m.settings(d);
    else if (act.startsWith('x:')) {
      const x = this.extras.flatMap(f => f(d) || []).find(e => `x:${e.id}` === act);
      x?.run(d);
    }
  }
}
