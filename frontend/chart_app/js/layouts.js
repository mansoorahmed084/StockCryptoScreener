// Multi-chart layouts (1, 2 side by side, 2 stacked, 4), linked symbol and
// crosshair, and named layouts saved on the server.

import { api } from './api.js';
import { confirmDialog, promptDialog } from './dialog.js';
import { $, esc, popupMenu, store, toast } from './dom.js';

const GRIDS = { 1: 'One chart', 2: 'Two, side by side', '2v': 'Two, stacked', 4: 'Four' };
const COUNT = { 1: 1, 2: 2, '2v': 2, 4: 4 };
const ICON = {
  1: '<svg viewBox="0 0 20 20" width="18" height="18"><rect x="2" y="3" width="16" height="14" rx="1" fill="none" stroke="currentColor"/></svg>',
  2: '<svg viewBox="0 0 20 20" width="18" height="18"><rect x="2" y="3" width="16" height="14" rx="1" fill="none" stroke="currentColor"/><path d="M10 3v14" stroke="currentColor"/></svg>',
  '2v': '<svg viewBox="0 0 20 20" width="18" height="18"><rect x="2" y="3" width="16" height="14" rx="1" fill="none" stroke="currentColor"/><path d="M2 10h16" stroke="currentColor"/></svg>',
  4: '<svg viewBox="0 0 20 20" width="18" height="18"><rect x="2" y="3" width="16" height="14" rx="1" fill="none" stroke="currentColor"/><path d="M10 3v14M2 10h16" stroke="currentColor"/></svg>',
};

export function initLayouts(app) {
  const saved = store.get('cw.workspace', {});
  app.layout = COUNT[saved.layout] ? saved.layout : '1';
  app.link = { symbol: false, crosshair: true, ...(saved.link || {}) };
  let restoring = false;

  const save = () => {
    if (restoring) return;
    store.set('cw.workspace', { layout: app.layout, link: app.link,
      slots: app.slots.map(s => ({ symbol: s.info?.symbol, tf: s.tf })) });
  };

  // The whole workspace, for named layouts.
  app.workspaceState = () => ({
    layout: app.layout, link: app.link, style: app.style,
    slots: app.slots.map(s => ({ symbol: s.info?.symbol, tf: s.tf, studies: s.studies?.state() || [] })),
  });

  app.setLayout = async (id, specs = []) => {
    app.layout = id;
    const want = COUNT[id];
    $('#charts').className = `layout-${id}`;
    while (app.slots.length > want) {
      const s = app.slots.pop();
      s.studies?.setState([]);
      s.destroy();
    }
    if (app.active >= app.slots.length) app.active = 0;
    const base = app.slot;
    while (app.slots.length < want) {
      const i = app.slots.length;
      const slot = app.addSlot();
      const spec = specs[i] || {};
      await app.setSymbol(spec.symbol || base.info?.symbol || app.symbol, slot, spec.tf || base.tf);
    }
    for (const s of app.slots) s.el.classList.toggle('focused', s === app.slot && app.slots.length > 1);
    renderButton();
    save();
  };

  app.applyWorkspace = async state => {
    restoring = true;
    try {
      if (state.style) app.setStyle(state.style);
      app.link = { ...app.link, ...(state.link || {}) };
      await app.setLayout(COUNT[state.layout] ? state.layout : '1', state.slots || []);
      for (const [i, spec] of (state.slots || []).entries()) {
        const slot = app.slots[i];
        if (!slot) continue;
        if (spec.symbol && (spec.symbol !== slot.info?.symbol || spec.tf !== slot.tf)) {
          await app.setSymbol(spec.symbol, slot, spec.tf);
        }
        if (spec.studies) slot.studies?.setState(spec.studies);
      }
    } finally {
      restoring = false;
      save();
    }
  };

  // ---- linking ----
  app.on('symbol', slot => {
    save();
    if (!app.link.symbol || restoring || app.linking) return;
    app.linking = true;
    Promise.all(app.slots.filter(s => s !== slot && s.info?.symbol !== slot.info.symbol)
      .map(s => app.setSymbol(slot.info.symbol, s))).finally(() => { app.linking = false; });
  });

  app.on('slot', slot => {
    slot.view.on('crosshair', p => {
      if (!app.link.crosshair || app.syncingCrosshair || app.slots.length < 2) return;
      app.syncingCrosshair = true;
      try {
        for (const other of app.slots) {
          if (other === slot || !other.view.bars.length) continue;
          if (p.time === undefined) { other.view.chart.clearCrosshairPosition(); continue; }
          const utc = slot.view.fromChart(p.time);
          const i = other.view.barIndexAt(utc);
          const bar = other.view.bars[Math.max(0, i)];
          other.view.chart.setCrosshairPosition(bar.close, other.view.toChart(bar.time), other.view.series);
        }
      } finally { app.syncingCrosshair = false; }
    });
    slot.on('loaded', save);
  });

  // ---- top bar button ----
  const btn = document.createElement('button');
  btn.className = 'tb-btn';
  btn.id = 'layout-btn';
  $('#tb-right').prepend(btn);
  function renderButton() {
    btn.innerHTML = `${ICON[app.layout]}<span>Layout</span>`;
    btn.title = `Chart layout: ${GRIDS[app.layout]}`;
  }
  renderButton();

  btn.onclick = async () => {
    let named = [];
    try { named = (await api.get('/api/chart/layouts')).layouts; } catch { /* offline */ }
    const items = [{ header: 'Grid' },
      ...Object.entries(GRIDS).map(([id, label]) => ({ html: `${ICON[id]} ${esc(label)}`, value: ['grid', id], active: app.layout === id })),
      '-', { header: 'Link charts' },
      { label: `${app.link.symbol ? '☑' : '☐'} Same symbol on every chart`, value: ['link', 'symbol'] },
      { label: `${app.link.crosshair ? '☑' : '☐'} Crosshair follows across charts`, value: ['link', 'crosshair'] },
      '-', { header: 'Saved layouts' },
      ...named.map(l => ({ html: `${esc(l.name)}<span class="kbd">load</span>`, value: ['load', l.name] })),
      { label: 'Save layout as…', value: ['save'] },
      ...(named.length ? [{ label: 'Delete a saved layout…', value: ['delete'] }] : [])];
    popupMenu(btn, items, async ([act, arg]) => {
      if (act === 'grid') await app.setLayout(arg);
      else if (act === 'link') { app.link[arg] = !app.link[arg]; save(); }
      else if (act === 'save') {
        const name = await promptDialog({ title: 'Save layout', label: 'Name', placeholder: 'e.g. Swing: BTC + ETH + NIFTY' });
        if (!name) return;
        try { await api.put(`/api/chart/layouts/${encodeURIComponent(name)}`, { state: app.workspaceState() }); toast(`Layout "${name}" saved`, 'ok'); }
        catch (err) { toast(err.message, 'error'); }
      } else if (act === 'load') {
        try { const l = await api.get(`/api/chart/layouts/${encodeURIComponent(arg)}`); await app.applyWorkspace(l.state); toast(`Layout "${arg}" loaded`, 'ok'); }
        catch (err) { toast(err.message, 'error'); }
      } else if (act === 'delete') {
        popupMenu(btn, named.map(l => ({ label: `Delete "${l.name}"`, value: l.name, danger: true })), async name => {
          if (!(await confirmDialog({ title: 'Delete layout', text: `Delete the saved layout "${name}"?`, ok: 'Delete', danger: true }))) return;
          try { await api.del(`/api/chart/layouts/${encodeURIComponent(name)}`); toast('Deleted'); } catch (err) { toast(err.message, 'error'); }
        });
      }
    });
  };

  // After the first chart loads, bring back the other charts of last time.
  app.on('ready', async () => {
    if (COUNT[app.layout] > 1) {
      restoring = true;
      try { await app.setLayout(app.layout, saved.slots || []); } finally { restoring = false; save(); }
    }
  });
}
