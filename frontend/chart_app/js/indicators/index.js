// Indicators feature: the "Indicators" button and picker, one StudyManager
// per chart, and remembering each chart's indicators.

import { $, esc, store } from '../dom.js';
import { ICONS } from '../icons.js';
import { INDICATORS } from './registry.js';
import { StudyManager } from './studies.js';

const GROUPS = [
  ['Screener', ['vumanchu', 'auto']],
  ['Trend', ['ema', 'sma', 'wma', 'vwap', 'bb']],
  ['Oscillators', ['rsi', 'macd', 'stoch', 'atr']],
  ['Volume', ['vprofile']],
];

export function initIndicators(app) {
  const saved = store.get('cw.studies', null);

  app.on('slot', slot => {
    const sm = new StudyManager(app, slot);
    slot.studies = sm;
    const idx = app.slots.indexOf(slot);
    const first = saved === null && idx === 0
      ? [{ type: 'vumanchu', inputs: {} }]   // a first-time user gets the screener's oscillator
      : (saved || {})[idx] || [];
    sm.setState(first);
    sm.on('change', () => {
      const all = store.get('cw.studies', {}) || {};
      all[app.slots.indexOf(slot)] = sm.state();
      store.set('cw.studies', all);
    });
  });

  const btn = document.createElement('button');
  btn.className = 'tb-btn';
  btn.title = 'Indicators';
  btn.innerHTML = `${ICONS.indicators}<span>Indicators</span>`;
  $('#tb-extra').appendChild(btn);
  btn.onclick = () => openPicker(app);
  app.on('keydown', e => {
    if (e.key === '/' && !e.ctrlKey && !e.altKey) { openPicker(app); return true; }
    return false;
  });
}

function openPicker(app) {
  const root = $('#dialog');
  root.innerHTML = `
    <div class="modal-card" role="dialog" aria-label="Indicators">
      <div class="modal-head"><span>Indicators</span><button class="icon-btn" data-close>✕</button></div>
      <div class="search-input"><span class="search-icon">⌕</span>
        <input type="text" placeholder="Search" spellcheck="false" style="text-transform:none"></div>
      <div class="ind-list"></div>
      <div class="search-foot">Click to add to the ${app.slots.length > 1 ? 'selected ' : ''}chart · Esc to close</div>
    </div>`;
  root.hidden = false;
  const input = root.querySelector('input');
  const list = root.querySelector('.ind-list');
  const close = () => { root.hidden = true; root.innerHTML = ''; document.removeEventListener('keydown', key, true); };
  const key = e => { if (e.key === 'Escape') { e.stopPropagation(); close(); } };
  document.addEventListener('keydown', key, true);
  root.onmousedown = e => { if (e.target === root) close(); };
  root.querySelector('[data-close]').onclick = close;
  const draw = () => {
    const q = input.value.trim().toLowerCase();
    list.innerHTML = GROUPS.map(([g, ids]) => {
      const rows = ids.filter(id => !q || INDICATORS[id].name.toLowerCase().includes(q)
                                         || INDICATORS[id].short.toLowerCase().includes(q));
      if (!rows.length) return '';
      return `<div class="menu-header">${esc(g)}</div>` + rows.map(id =>
        `<button class="ind-row" data-id="${id}"><b>${esc(INDICATORS[id].short)}</b><span>${esc(INDICATORS[id].name)}</span></button>`).join('');
    }).join('') || '<div class="wl-empty">No indicator matches</div>';
    list.querySelectorAll('[data-id]').forEach(b => {
      b.onclick = () => {
        app.slot.studies.add(b.dataset.id);
        b.classList.add('added');
        b.querySelector('span').textContent = 'Added ✓';
      };
    });
  };
  input.addEventListener('input', draw);
  draw();
  input.focus();
}
