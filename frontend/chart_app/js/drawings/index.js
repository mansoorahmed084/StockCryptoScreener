// Drawing tools feature: the left toolbar, tool state, shortcuts, and one
// DrawingManager (+ floating toolbar) per chart.

import { confirmDialog } from '../dialog.js';
import { $, esc, popupMenu, store, toast } from '../dom.js';
import { ICONS } from '../icons.js';
import { DrawingManager } from './manager.js';
import { DrawingToolbar } from './toolbar.js';
import { TOOLS } from './tools.js';

// Left bar groups. The group button shows the last tool used from it.
const GROUPS = [
  { id: 'cursor', tools: ['cursor'] },
  { id: 'lines', tools: ['trendline', 'ray', 'extline', 'hline', 'hray', 'vline', 'channel'] },
  { id: 'fib', tools: ['fib'] },
  { id: 'shapes', tools: ['rect'] },
  { id: 'text', tools: ['text'] },
  { id: 'position', tools: ['long', 'short'] },
  { id: 'measure', tools: ['measure'] },
];

const SHORTCUTS = {        // Alt + key, like TradingView
  t: 'trendline', h: 'hline', j: 'hray', v: 'vline', f: 'fib', c: 'channel',
};

const LABELS = { cursor: 'Cross', measure: 'Measure (or Shift + drag)' };
const labelOf = id => LABELS[id] || TOOLS[id]?.label || id;
const KEYS = { trendline: 'Alt+T', hline: 'Alt+H', hray: 'Alt+J', vline: 'Alt+V', fib: 'Alt+F',
               channel: 'Alt+C', rect: 'Alt+Shift+R' };

export function initDrawings(app) {
  const saved = store.get('cw.draw', {});
  app.tool = 'cursor';
  app.magnet = saved.magnet || 'off';
  app.stayInDrawMode = !!saved.stay;
  app.drawLocked = !!saved.locked;
  app.drawHidden = false;
  const lastInGroup = saved.last || {};

  const persist = () => store.set('cw.draw', {
    magnet: app.magnet, stay: app.stayInDrawMode, locked: app.drawLocked, last: lastInGroup,
  });

  app.setTool = id => {
    for (const s of app.slots) s.drawings?.cancelCreate();
    app.tool = id;
    const g = GROUPS.find(x => x.tools.includes(id));
    if (g && g.tools.length > 1) lastInGroup[g.id] = id;
    persist();
    render();
    for (const s of app.slots) s.el.classList.toggle('drawing-mode', id !== 'cursor');
  };

  // ---- one manager per chart ----
  app.on('slot', slot => {
    const m = new DrawingManager(app, slot);
    slot.drawings = m;
    slot.drawToolbar = new DrawingToolbar(m, slot.el);
    slot.on('loaded', info => m.load(info.drawing_key));
  });
  app.on('drawings', src => { for (const s of app.slots) s.drawings?.syncFrom(src); });

  // ---- left bar ----
  const bar = $('#leftbar');
  bar.hidden = false;

  function render() {
    const groupBtn = g => {
      const current = g.tools.length > 1 ? (lastInGroup[g.id] || g.tools[0]) : g.tools[0];
      const on = g.tools.includes(app.tool);
      return `<div class="lb-group">
        <button class="lb-btn${on ? ' on' : ''}" data-tool="${current}" title="${esc(labelOf(current))}${KEYS[current] ? ` (${KEYS[current]})` : ''}">${ICONS[current]}</button>
        ${g.tools.length > 1 ? `<button class="lb-more" data-group="${g.id}" title="More">›</button>` : ''}
      </div>`;
    };
    bar.innerHTML = GROUPS.map(groupBtn).join('') + `
      <span class="lb-sep"></span>
      <button class="lb-btn${app.magnet !== 'off' ? ' on' : ''}" data-act="magnet" title="Magnet: ${app.magnet} (hold Ctrl to switch while drawing)">${ICONS.magnet}${app.magnet === 'strong' ? '<b class="lb-badge">S</b>' : ''}</button>
      <button class="lb-btn${app.stayInDrawMode ? ' on' : ''}" data-act="stay" title="Stay in drawing mode">${ICONS.stay}</button>
      <button class="lb-btn${app.drawLocked ? ' on' : ''}" data-act="lock" title="Lock all drawings">${ICONS.lock}</button>
      <button class="lb-btn${app.drawHidden ? ' on' : ''}" data-act="hide" title="Hide all drawings">${ICONS.eye}</button>
      <button class="lb-btn" data-act="trash" title="Remove drawings">${ICONS.trash}</button>`;
    bar.querySelectorAll('[data-tool]').forEach(b => {
      b.onclick = () => app.setTool(app.tool === b.dataset.tool && b.dataset.tool !== 'cursor' ? 'cursor' : b.dataset.tool);
    });
    bar.querySelectorAll('[data-group]').forEach(b => {
      b.onclick = () => {
        const g = GROUPS.find(x => x.id === b.dataset.group);
        popupMenu(b, g.tools.map(id => ({
          html: `<span class="mi-icon">${ICONS[id]}</span>${esc(labelOf(id))}${KEYS[id] ? `<span class="kbd">${KEYS[id]}</span>` : ''}`,
          value: id, active: app.tool === id,
        })), id => app.setTool(id), { className: 'side' });
      };
    });
    bar.querySelectorAll('[data-act]').forEach(b => { b.onclick = () => act(b.dataset.act, b); });
  }

  async function act(a, anchor) {
    const m = app.slot?.drawings;
    if (a === 'magnet') {
      popupMenu(anchor, [['off', 'Magnet off'], ['weak', 'Weak magnet (near OHLC)'], ['strong', 'Strong magnet (always OHLC)']]
        .map(([v, l]) => ({ label: l, value: v, active: app.magnet === v })), v => { app.magnet = v; persist(); render(); },
      { className: 'side' });
      return;
    }
    if (a === 'stay') app.stayInDrawMode = !app.stayInDrawMode;
    else if (a === 'lock') app.drawLocked = !app.drawLocked;
    else if (a === 'hide') {
      app.drawHidden = !app.drawHidden;
      for (const s of app.slots) { s.drawings.select(null); s.drawings.update(); }
    } else if (a === 'trash' && m) {
      popupMenu(anchor, [
        { label: `Remove all drawings on ${app.info?.ticker || 'this symbol'}`, value: 'all', danger: true },
        { label: 'Show hidden drawings', value: 'show' },
      ], async v => {
        if (v === 'show') { const n = m.showAll(); toast(n ? `${n} drawing(s) shown` : 'No hidden drawings'); return; }
        const n = m.drawings.length;
        if (!n) { toast('No drawings on this symbol'); return; }
        if (await confirmDialog({ title: 'Remove drawings', text: `Remove all ${n} drawing(s) on ${app.info?.ticker}? Ctrl+Z brings them back.`, ok: 'Remove', danger: true })) {
          await m.removeAll();
        }
      }, { className: 'side' });
      return;
    }
    persist();
    render();
  }

  // ---- keys ----
  app.on('keydown', e => {
    const m = app.slot?.drawings;
    if (e.altKey && !e.ctrlKey) {
      const k = e.key.toLowerCase();
      if (e.shiftKey && k === 'r') { app.setTool('rect'); return true; }
      if (!e.shiftKey && SHORTCUTS[k]) { app.setTool(SHORTCUTS[k]); return true; }
    }
    return m ? m.onKey(e) : false;
  });

  render();
}
