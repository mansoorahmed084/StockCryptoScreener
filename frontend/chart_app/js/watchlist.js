// Right panel: watchlists with sections, flags, live quotes, drag to reorder,
// and the selected symbol's details underneath.

import { api } from './api.js';
import { confirmDialog, promptDialog, textDialog } from './dialog.js';
import { $, $$, contextMenu, esc, popupMenu, store, toast } from './dom.js';
import { fmtPct, fmtVolume } from './format.js';
import { QuoteStream } from './quotes.js';

export const FLAG_COLORS = {
  red: '#f23645', orange: '#ff9800', green: '#089981', blue: '#2962ff',
  purple: '#9c27b0', cyan: '#00bcd4', pink: '#e91e63',
};
const SECTION = '###';

// Price with sensible decimals for a quote (no series precision here).
export function fmtQuote(v) {
  if (v === undefined || v === null || Number.isNaN(v)) return '—';
  const a = Math.abs(v);
  const d = a >= 1000 ? 2 : a >= 10 ? 3 : a >= 1 ? 4 : a >= 0.01 ? 5 : 8;
  return v.toLocaleString('en-US', { minimumFractionDigits: Math.min(d, 2), maximumFractionDigits: d });
}

const tickerOf = s => s.split(':').pop();

export async function initWatchlist(app) {
  const panel = new WatchlistPanel(app, $('#rightpanel'));
  app.watchlist = panel;
  await panel.init();
}

class WatchlistPanel {
  constructor(app, el) {
    this.app = app;
    this.el = el;
    this.lists = [];
    this.list = null;
    this.quotes = new Map();
    this.dirty = new Set();
    this.collapsed = store.get('cw.wl.collapsed', {});
    this.flagFilter = null;
    this.stream = new QuoteStream((s, q) => this._quote(s, q));
  }

  async init() {
    this.el.innerHTML = `
      <div class="wl-head">
        <button class="wl-name tb-btn" title="Watchlists"><span></span> ▾</button>
        <span class="spacer"></span>
        <button class="icon-btn wl-add" title="Add symbol (Alt+W adds the chart's symbol)">＋</button>
        <button class="icon-btn wl-flagf" title="Show flagged only">⚑</button>
      </div>
      <div class="wl-cols"><span>Symbol</span><span>Last</span><span>Chg</span><span>Chg%</span></div>
      <div class="wl-body"></div>
      <div class="wl-details"></div>`;
    this.body = $('.wl-body', this.el);
    $('.wl-name', this.el).onclick = e => this._listMenu(e.currentTarget);
    $('.wl-add', this.el).onclick = () => this.addViaSearch();
    $('.wl-flagf', this.el).onclick = e => this._flagFilterMenu(e.currentTarget);
    this.body.addEventListener('contextmenu', e => this._rowMenu(e));
    this._dragAndDrop();

    this._setupToggle();
    this.app.on('symbol', () => { this._markActive(); this._details(); });
    this.app.on('keydown', e => this._key(e));
    try {
      await this.loadLists();
    } catch (err) {
      this.body.innerHTML = `<div class="wl-empty">Watchlists could not load: ${esc(err.message)}</div>`;
    }
  }

  // ---- panel open / close / width ----
  _setupToggle() {
    const btn = document.createElement('button');
    btn.className = 'tb-btn';
    btn.id = 'wl-toggle';
    btn.title = 'Watchlist';
    btn.innerHTML = '☰ <span>Watchlist</span>';
    $('#tb-right').appendChild(btn);
    const resizer = $('#right-resizer');
    const apply = () => {
      const open = store.get('cw.wl.open', innerWidth > 800);
      this.el.hidden = resizer.hidden = !open;
      btn.classList.toggle('on', open);
      this.el.style.width = store.get('cw.wl.width', 320) + 'px';
      if (open) this.stream.setSymbols(this._symbols()); else this.stream.stop();
    };
    btn.onclick = () => { store.set('cw.wl.open', this.el.hidden); apply(); };
    resizer.onmousedown = e => {
      e.preventDefault();
      resizer.classList.add('drag');
      const move = ev => {
        const w = Math.max(220, Math.min(640, innerWidth - ev.clientX));
        this.el.style.width = w + 'px';
        store.set('cw.wl.width', w);
      };
      const up = () => {
        resizer.classList.remove('drag');
        removeEventListener('mousemove', move);
        removeEventListener('mouseup', up);
      };
      addEventListener('mousemove', move);
      addEventListener('mouseup', up);
    };
    this.applyOpen = apply;
    apply();
  }

  // ---- data ----
  async loadLists(selectId) {
    const { lists, active } = await api.get('/api/chart/watchlists');
    this.lists = lists;
    const id = selectId ?? active ?? lists[0]?.id;
    if (id) await this.open(id);
    else { this.list = null; this.render(); }
  }

  async open(id) {
    this.list = await api.get(`/api/chart/watchlists/${id}`);
    api.put(`/api/chart/watchlists/${id}/active`).catch(() => {});
    this.render();
  }

  async saveItems(items) {
    const prev = this.list;
    this.list = { ...this.list, items };
    this.render();
    try {
      this.list = await api.put(`/api/chart/watchlists/${prev.id}/items`, { items });
      const meta = this.lists.find(l => l.id === prev.id);
      if (meta) meta.count = items.filter(i => !i.symbol.startsWith(SECTION)).length;
    } catch (err) {
      toast(`Could not save the watchlist: ${err.message}`, 'error');
      this.list = prev;
    }
    this.render();
  }

  get items() { return this.list?.items || []; }
  _symbols() { return this.items.filter(i => !i.symbol.startsWith(SECTION)).map(i => i.symbol); }

  // ---- rendering ----
  render() {
    $('.wl-name span', this.el).textContent = this.list?.name || 'No watchlist';
    $('.wl-flagf', this.el).style.color = this.flagFilter ? FLAG_COLORS[this.flagFilter] : '';
    if (!this.list) {
      this.body.innerHTML = '<div class="wl-empty">No watchlist yet. Use ▾ to create one.</div>';
      return;
    }
    const closed = new Set(this.collapsed[this.list.id] || []);
    let section = null;
    const rows = [];
    this.items.forEach((it, i) => {
      if (it.symbol.startsWith(SECTION)) {
        section = it.symbol.slice(3);
        if (this.flagFilter) return;
        rows.push(`<div class="wl-section" data-i="${i}" draggable="true">
          <span class="caret">${closed.has(section) ? '▸' : '▾'}</span>${esc(section)}</div>`);
        return;
      }
      if (this.flagFilter ? it.flag !== this.flagFilter : closed.has(section)) return;
      const q = this.quotes.get(it.symbol) || {};
      const cls = q.change > 0 ? 'up' : q.change < 0 ? 'down' : '';
      const tk = tickerOf(it.symbol);
      rows.push(`<div class="wl-row" data-i="${i}" data-symbol="${esc(it.symbol)}" draggable="true" title="${esc(it.symbol)}">
        <span class="wl-flag" style="${it.flag ? `background:${FLAG_COLORS[it.flag]}` : ''}"></span>
        <span class="wl-sym"><span class="wl-icon">${esc(tk[0])}</span><span class="wl-tk">${esc(tk)}</span></span>
        <span class="wl-last">${fmtQuote(q.last)}</span>
        <span class="wl-chg ${cls}">${q.change === undefined ? '' : fmtQuote(q.change)}</span>
        <span class="wl-pct ${cls}">${q.change_pct === undefined ? '' : fmtPct(q.change_pct)}</span>
        <button class="wl-x" title="Remove">✕</button>
      </div>`);
    });
    this.body.innerHTML = rows.join('') || `<div class="wl-empty">${this.flagFilter
      ? 'No symbols with this flag.' : 'Empty list. Click ＋ to add symbols.'}</div>`;
    $$('.wl-row', this.body).forEach(r => {
      r.onclick = e => {
        if (e.target.closest('.wl-x')) { this.remove(+r.dataset.i); return; }
        if (e.target.closest('.wl-flag')) { this._cycleFlag(+r.dataset.i); return; }
        this.app.setSymbol(r.dataset.symbol);
      };
    });
    $$('.wl-section', this.body).forEach(r => {
      r.onclick = () => this._toggleSection(this.items[+r.dataset.i].symbol.slice(3));
    });
    this._markActive();
    this._details();
    if (!this.el.hidden) this.stream.setSymbols(this._symbols());
  }

  _markActive() {
    const cur = this.app.symbol;
    $$('.wl-row', this.body).forEach(r => r.classList.toggle('active', r.dataset.symbol === cur));
  }

  _quote(symbol, q) {
    const prev = this.quotes.get(symbol);
    this.quotes.set(symbol, { ...prev, ...q, dir: prev?.last === undefined ? 0 : Math.sign(q.last - prev.last) });
    this.dirty.add(symbol);
    if (!this.raf) this.raf = requestAnimationFrame(() => this._flush());
  }

  // Update only the cells whose quote changed (once per frame).
  _flush() {
    this.raf = null;
    for (const symbol of this.dirty) {
      const q = this.quotes.get(symbol);
      for (const r of this.body.querySelectorAll(`.wl-row[data-symbol="${CSS.escape(symbol)}"]`)) {
        const cls = q.change > 0 ? 'up' : q.change < 0 ? 'down' : '';
        const last = r.querySelector('.wl-last');
        last.textContent = fmtQuote(q.last);
        if (q.dir) {
          last.classList.remove('flash-up', 'flash-down');
          void last.offsetWidth;
          last.classList.add(q.dir > 0 ? 'flash-up' : 'flash-down');
        }
        const chg = r.querySelector('.wl-chg'), pct = r.querySelector('.wl-pct');
        chg.textContent = fmtQuote(q.change);
        pct.textContent = fmtPct(q.change_pct);
        chg.className = `wl-chg ${cls}`;
        pct.className = `wl-pct ${cls}`;
      }
      if (symbol === this.app.symbol) this._details();
    }
    this.dirty.clear();
  }

  _details() {
    const box = $('.wl-details', this.el);
    const info = this.app.info;
    if (!info) { box.innerHTML = ''; return; }
    const q = this.quotes.get(info.symbol) || {};
    const bars = this.app.slot?.view.bars || [];
    const last = q.last ?? bars[bars.length - 1]?.close;
    const cls = q.change > 0 ? 'up' : q.change < 0 ? 'down' : '';
    const inList = this._symbols().includes(info.symbol);
    box.innerHTML = `
      <div class="wd-top">
        <span class="wl-icon big">${esc(info.ticker[0])}</span>
        <div><div class="wd-tk">${esc(info.ticker)}</div>
        <div class="wd-desc">${esc(info.description)} · ${esc(info.exchange)}</div></div>
        <button class="icon-btn wd-add" title="${inList ? 'In this list' : 'Add to this list'}">${inList ? '✓' : '＋'}</button>
      </div>
      <div class="wd-price">${fmtQuote(last)} <small>${info.market === 'stock' ? '' : info.symbol.includes('USDT') ? 'USDT' : ''}</small></div>
      <div class="wd-chg ${cls}">${q.change === undefined ? '' : `${fmtQuote(q.change)} (${fmtPct(q.change_pct)})`}
        <span class="wd-when">${info.market === 'stock' ? 'today · delayed' : '24h'}</span></div>
      ${q.high !== undefined ? `<div class="wd-stats">
        <div><span>24h high</span>${fmtQuote(q.high)}</div>
        <div><span>24h low</span>${fmtQuote(q.low)}</div>
        <div><span>24h volume</span>${fmtVolume(q.volume)}</div></div>` : ''}
      <div class="wd-status ${info.delayed ? 'delayed' : 'live'}">${info.delayed ? 'Delayed ~15 min (Yahoo)' : 'Real-time (Binance)'}</div>`;
    const add = $('.wd-add', box);
    if (add) add.onclick = () => { if (!inList) this.addSymbol(info.symbol); };
  }

  // ---- actions ----
  async addSymbol(symbol) {
    if (!this.list) { toast('Create a watchlist first', 'error'); return; }
    if (this._symbols().includes(symbol)) { toast(`${tickerOf(symbol)} is already in ${this.list.name}`); return; }
    await this.saveItems([...this.items, { symbol }]);
    toast(`${tickerOf(symbol)} added to ${this.list.name}`, 'ok');
  }

  async addViaSearch() {
    if (!this.list) { toast('Create a watchlist first', 'error'); return; }
    const pick = await this.app.search.open('', { title: `Add to ${this.list.name}` });
    if (pick) {
      try {
        const info = await api.get('/api/chart/resolve', { symbol: pick });
        await this.addSymbol(info.symbol);
      } catch (err) { toast(`Cannot add ${pick}: ${err.message}`, 'error'); }
    }
  }

  remove(i) {
    const items = this.items.slice();
    items.splice(i, 1);
    this.saveItems(items);
  }

  _cycleFlag(i) {
    const order = [null, ...Object.keys(FLAG_COLORS)];
    const it = this.items[i];
    const next = order[(order.indexOf(it.flag ?? null) + 1) % order.length];
    this._setFlag(i, next);
  }

  _setFlag(i, flag) {
    const items = this.items.map((it, j) => (j === i ? { ...it, flag } : it));
    this.saveItems(items);
  }

  _toggleSection(name) {
    const set = new Set(this.collapsed[this.list.id] || []);
    set.has(name) ? set.delete(name) : set.add(name);
    this.collapsed[this.list.id] = [...set];
    store.set('cw.wl.collapsed', this.collapsed);
    this.render();
  }

  async addSection(at) {
    const name = await promptDialog({ title: 'Add section', label: 'Section name', placeholder: 'e.g. ALTS' });
    if (!name) return;
    const items = this.items.slice();
    items.splice(at, 0, { symbol: SECTION + name.toUpperCase() });
    this.saveItems(items);
  }

  // ---- menus ----
  _listMenu(anchor) {
    const items = [{ header: 'Watchlists' },
      ...this.lists.map(l => ({ label: `${l.name}  (${l.count})`, value: ['open', l.id], active: l.id === this.list?.id })),
      '-',
      { label: 'Create new list…', value: ['new'] }];
    if (this.list) {
      items.push({ label: 'Rename…', value: ['rename'] },
        { label: 'Add section…', value: ['section'] },
        { label: 'Import symbols…', value: ['import'] },
        { label: 'Export list', value: ['export'] },
        { label: 'Clear list', value: ['clear'] },
        '-', { label: 'Delete list', value: ['delete'], danger: true });
    }
    popupMenu(anchor, items, ([action, id]) => this._listAction(action, id));
  }

  async _listAction(action, id) {
    try {
      if (action === 'open') await this.open(id);
      else if (action === 'new') {
        const name = await promptDialog({ title: 'New watchlist', label: 'Name' });
        if (name) { const l = await api.post('/api/chart/watchlists', { name }); await this.loadLists(l.id); }
      } else if (action === 'rename') {
        const name = await promptDialog({ title: 'Rename watchlist', label: 'Name', value: this.list.name });
        if (name) { await api.put(`/api/chart/watchlists/${this.list.id}`, { name }); await this.loadLists(this.list.id); }
      } else if (action === 'section') {
        await this.addSection(this.items.length);
      } else if (action === 'import') {
        const text = await promptDialog({
          title: `Import into ${this.list.name}`, multiline: true, ok: 'Import',
          label: 'Symbols separated by commas, spaces or lines. ###NAME starts a section. Ctrl+Enter imports.',
          placeholder: 'BINANCE:SOLUSDT.P, ETHUSDT.P, NSE:TCS, AAPL, ###MEMES, PEPE' });
        if (!text) return;
        const res = await api.post(`/api/chart/watchlists/${this.list.id}/import`, { text });
        this.list = res;
        await this.loadLists(res.id);
        toast(res.skipped.length ? `Imported. Not found: ${res.skipped.join(', ')}` : 'Imported',
              res.skipped.length ? 'error' : 'ok');
      } else if (action === 'export') {
        await textDialog({ title: `Export ${this.list.name}`,
                           text: this.items.map(i => i.symbol).join(',') });
      } else if (action === 'clear') {
        if (await confirmDialog({ title: 'Clear list', text: `Remove every symbol from ${this.list.name}?`, ok: 'Clear', danger: true })) {
          await this.saveItems([]);
        }
      } else if (action === 'delete') {
        if (await confirmDialog({ title: 'Delete list', text: `Delete the watchlist ${this.list.name}?`, ok: 'Delete', danger: true })) {
          await api.del(`/api/chart/watchlists/${this.list.id}`);
          await this.loadLists();
        }
      }
    } catch (err) {
      toast(err.message, 'error');
    }
  }

  _flagFilterMenu(anchor) {
    popupMenu(anchor, [
      { label: 'All symbols', value: null, active: !this.flagFilter },
      ...Object.entries(FLAG_COLORS).map(([k, c]) => ({
        html: `<span class="dot" style="background:${c}"></span>${k[0].toUpperCase() + k.slice(1)} flag`,
        value: k, active: this.flagFilter === k })),
    ], v => { this.flagFilter = v; this.render(); });
  }

  _rowMenu(e) {
    const row = e.target.closest('.wl-row, .wl-section');
    if (!row) return;
    e.preventDefault();
    const i = +row.dataset.i;
    const it = this.items[i];
    if (row.classList.contains('wl-section')) {
      contextMenu(e.clientX, e.clientY, [
        { label: 'Rename section…', value: 'rename' },
        { label: 'Add section above…', value: 'add' },
        '-', { label: 'Remove section', value: 'remove', danger: true },
      ], async v => {
        if (v === 'remove') this.remove(i);
        else if (v === 'add') this.addSection(i);
        else {
          const name = await promptDialog({ title: 'Rename section', value: it.symbol.slice(3) });
          if (name) this.saveItems(this.items.map((x, j) => (j === i ? { symbol: SECTION + name.toUpperCase() } : x)));
        }
      });
      return;
    }
    contextMenu(e.clientX, e.clientY, [
      { header: tickerOf(it.symbol) },
      ...Object.entries(FLAG_COLORS).map(([k, c]) => ({
        html: `<span class="dot" style="background:${c}"></span>Flag ${k}`, value: ['flag', k], active: it.flag === k })),
      ...(it.flag ? [{ label: 'Unflag', value: ['flag', null] }] : []),
      '-',
      { label: 'Add section above…', value: ['section'] },
      { label: 'Copy symbol', value: ['copy'] },
      '-', { label: 'Remove from list', value: ['remove'], danger: true },
    ], ([v, arg]) => {
      if (v === 'flag') this._setFlag(i, arg);
      else if (v === 'section') this.addSection(i);
      else if (v === 'copy') navigator.clipboard?.writeText(it.symbol).then(() => toast('Copied'));
      else if (v === 'remove') this.remove(i);
    });
  }

  // ---- drag to reorder ----
  _dragAndDrop() {
    let from = null;
    this.body.addEventListener('dragstart', e => {
      const row = e.target.closest('[data-i]');
      if (!row) return;
      from = +row.dataset.i;
      e.dataTransfer.effectAllowed = 'move';
      row.classList.add('dragging');
    });
    this.body.addEventListener('dragover', e => {
      if (from === null) return;
      e.preventDefault();
      const row = e.target.closest('[data-i]');
      $$('.drop-above, .drop-below', this.body).forEach(r => r.classList.remove('drop-above', 'drop-below'));
      if (!row) return;
      const r = row.getBoundingClientRect();
      row.classList.add(e.clientY < r.top + r.height / 2 ? 'drop-above' : 'drop-below');
    });
    this.body.addEventListener('dragend', () => {
      from = null;
      $$('.dragging, .drop-above, .drop-below', this.body)
        .forEach(r => r.classList.remove('dragging', 'drop-above', 'drop-below'));
    });
    this.body.addEventListener('drop', e => {
      e.preventDefault();
      const row = e.target.closest('[data-i]');
      if (from === null || !row) return;
      const r = row.getBoundingClientRect();
      let to = +row.dataset.i + (e.clientY < r.top + r.height / 2 ? 0 : 1);
      const items = this.items.slice();
      const [moved] = items.splice(from, 1);
      if (to > from) to -= 1;
      items.splice(to, 0, moved);
      from = null;
      this.saveItems(items);
    });
  }

  // ---- keyboard ----
  _key(e) {
    if (e.altKey && e.key.toLowerCase() === 'w') {
      if (this.app.info) this.addSymbol(this.app.info.symbol);
      return true;
    }
    if ((e.key === 'ArrowDown' || e.key === 'ArrowUp') && !this.el.hidden && !e.ctrlKey && !e.altKey) {
      const rows = $$('.wl-row', this.body);
      if (!rows.length) return false;
      const i = rows.findIndex(r => r.dataset.symbol === this.app.symbol);
      const next = rows[i < 0 ? 0 : (i + (e.key === 'ArrowDown' ? 1 : -1) + rows.length) % rows.length];
      next.scrollIntoView({ block: 'nearest' });
      this.app.setSymbol(next.dataset.symbol);
      return true;
    }
    return false;
  }
}
