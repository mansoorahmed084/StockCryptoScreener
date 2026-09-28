// Chart workspace start-up: top bar, bottom bar, keyboard, and the app
// object every feature module hooks into.

import { $, $$, esc, popupMenu, store, toast, typingInField } from './dom.js';
import { setTimeZone, timeZone, zoneLabel } from './format.js';
import { ChartSlot, resolveSymbol } from './slot.js';
import { SymbolSearch } from './symbol-search.js';
import { initWatchlist } from './watchlist.js';
import { initDrawings } from './drawings/index.js';
import { initIndicators } from './indicators/index.js';
import { initAlerts } from './alerts.js';
import { initExtras } from './extras.js';
import { initLayouts } from './layouts.js';
import { initReplay } from './replay.js';
import {
  FAVOURITES, RANGES, STOCK_TIMEFRAMES, TIMEFRAMES, fitTf, isValidTf, tfLabel,
} from './timeframes.js';

const STYLES = [
  ['candles', 'Candles', '▮'], ['heikin', 'Heikin Ashi', '▯'], ['bars', 'Bars', '┤'],
  ['line', 'Line', '╱'], ['area', 'Area', '◢'],
];

const saved = store.get('cw.state', {});
const params = new URLSearchParams(location.search);

export const app = {
  symbol: (params.get('symbol') || saved.symbol || 'BINANCE:BTCUSDT.P').toUpperCase(),
  tf: isValidTf(params.get('tf')) ? params.get('tf') : (isValidTf(saved.tf) ? saved.tf : '2h'),
  style: saved.style || 'candles',
  slots: [],
  active: 0,
  search: new SymbolSearch($('#search-modal')),
  hooks: { symbol: [], slot: [], keydown: [] },

  get slot() { return this.slots[this.active]; },
  get info() { return this.slot?.info; },

  on(event, fn) { (this.hooks[event] ||= []).push(fn); },
  // One feature failing must not stop the others.
  emit(event, ...args) {
    for (const f of this.hooks[event] || []) {
      try {
        const r = f(...args);
        if (r && r.catch) r.catch(err => console.error(`${event} hook failed`, err));
      } catch (err) { console.error(`${event} hook failed`, err); }
    }
  },

  save() {
    store.set('cw.state', { ...store.get('cw.state', {}), symbol: this.symbol, tf: this.tf, style: this.style });
    const url = new URL(location.href);
    url.searchParams.set('symbol', this.symbol);
    url.searchParams.set('tf', this.tf);
    history.replaceState(null, '', url);
  },

  async setSymbol(symbol, slot = this.slot, tf = null) {
    symbol = symbol.toUpperCase();
    try {
      const info = await resolveSymbol(symbol);
      await slot.load(info.symbol, fitTf(info, tf || slot.tf || this.tf));
    } catch (err) {
      toast(`Cannot open ${symbol}: ${err.message}`, 'error');
      return false;
    }
    if (slot === this.slot) {
      this.symbol = slot.info.symbol;
      this.tf = slot.tf;
      this._afterChange();
    }
    return true;
  },

  async setTf(tf, slot = this.slot) {
    if (!slot.info) return;
    if (slot.info.market === 'stock' && !STOCK_TIMEFRAMES.includes(tf)) {
      toast(`${tfLabel(tf)} is not available for stocks`, 'error');
      return;
    }
    try {
      await slot.load(slot.info.symbol, tf);
    } catch (err) {
      toast(`Cannot load ${tfLabel(tf)}: ${err.message}`, 'error');
      return;
    }
    if (slot === this.slot) {
      this.tf = tf;
      this._afterChange();
    }
  },

  _afterChange() {
    this.save();
    renderTopbar();
    document.title = `${this.slot.info.ticker} · ${tfLabel(this.tf)} — Chart Workspace`;
    this.emit('symbol', this.slot);
  },

  async openSearch(prefill = '') {
    const pick = await this.search.open(prefill);
    if (pick) await this.setSymbol(pick);
  },

  setStyle(style) {
    this.style = style;
    for (const s of this.slots) s.view.setStyle(style);
    this.save();
    renderTopbar();
  },

  addSlot() {
    const slot = new ChartSlot($('#charts'), this.slots.length);
    slot.view.setStyle(this.style);
    slot.on('status', s => { if (slot === this.slot) setStatus(s); });
    slot.el.addEventListener('mousedown', () => this.focusSlot(slot), true);
    this.slots.push(slot);
    this.emit('slot', slot);
    if (this.slots.length > 1) applyScale();
    return slot;
  },

  focusSlot(slot) {
    const i = this.slots.indexOf(slot);
    if (i < 0 || i === this.active) return;
    this.active = i;
    for (const s of this.slots) s.el.classList.toggle('focused', s === slot && this.slots.length > 1);
    if (slot.info) {
      this.symbol = slot.info.symbol;
      this.tf = slot.tf;
      this._afterChange();
    }
  },
};
window.app = app;   // handy in the browser console

// ---- top bar ----
function renderTopbar() {
  const info = app.info;
  $('#symbol-btn .symbol-text').textContent = info ? info.ticker : app.symbol.split(':').pop();
  $('#symbol-btn').title = info ? `${info.symbol} — ${info.description}` : 'Symbol search';
  const stock = info?.market === 'stock';
  $('#tf-buttons').innerHTML = FAVOURITES.map(id => {
    const off = stock && !STOCK_TIMEFRAMES.includes(id);
    return `<button class="tb-btn${id === app.tf ? ' active' : ''}" data-tf="${id}"${off ? ' disabled style="opacity:.35"' : ''}>${tfLabel(id)}</button>`;
  }).join('');
  if (!FAVOURITES.includes(app.tf)) {
    $('#tf-buttons').insertAdjacentHTML('beforeend',
      `<button class="tb-btn active" data-tf="${app.tf}">${tfLabel(app.tf)}</button>`);
  }
  $$('#tf-buttons [data-tf]').forEach(b => { b.onclick = () => app.setTf(b.dataset.tf); });
  const st = STYLES.find(s => s[0] === app.style) || STYLES[0];
  $('#style-btn').innerHTML = `<span>${st[2]}</span><span>${st[1]}</span>`;
}

$('#symbol-btn').onclick = () => app.openSearch();
$('#tf-more').onclick = e => {
  const stock = app.info?.market === 'stock';
  const items = [];
  let group = '';
  for (const t of TIMEFRAMES) {
    if (t.group !== group) { items.push({ header: t.group }); group = t.group; }
    if (stock && !STOCK_TIMEFRAMES.includes(t.id)) continue;
    items.push({ label: t.id === '1d' ? '1 day' : t.id === '1w' ? '1 week' : t.id === '1M' ? '1 month' : t.id,
                 value: t.id, active: t.id === app.tf });
  }
  popupMenu(e.currentTarget, items, tf => app.setTf(tf));
};
$('#style-btn').onclick = e => popupMenu(e.currentTarget,
  STYLES.map(([id, label, icon]) => ({ html: `<span>${icon}</span>${esc(label)}`, value: id, active: id === app.style })),
  style => app.setStyle(style));

function setStatus(s) {
  const el = $('#feed-status');
  el.className = `feed-status ${s}`;
  el.textContent = { live: 'Live', delayed: 'Delayed ~15 min', connecting: 'Connecting…', reconnecting: 'Reconnecting…' }[s] || s;
}

// ---- bottom bar ----
$('#ranges').innerHTML = RANGES.map(r =>
  `<button class="bb-btn" data-range="${r.id}" title="Last ${r.id} (${tfLabel(r.tf)} candles)">${r.id}</button>`).join('');
$$('#ranges [data-range]').forEach(b => {
  b.onclick = async () => {
    const r = RANGES.find(x => x.id === b.dataset.range);
    let tf = r.tf;
    if (app.info?.market === 'stock' && r.span === 5 * 86400) tf = '15m';
    if (tf !== app.tf) await app.setTf(tf);
    const now = Date.now() / 1000;
    let from;
    if (r.span === 'all') from = null;
    else if (r.span === 'ytd') from = Date.UTC(new Date().getUTCFullYear(), 0, 1) / 1000;
    else from = now - r.span;
    await app.slot.showRange(from);
  };
});

const scale = { percent: false, log: false, auto: true, ...(store.get('cw.state', {}).scale || {}) };
function applyScale() {
  for (const s of app.slots) {
    s.view.setScaleMode(scale.percent ? 'percent' : scale.log ? 'log' : 'normal');
    s.view.setAutoScale(scale.auto);
  }
  $$('#bottombar [data-scale]').forEach(b => b.classList.toggle('active', scale[b.dataset.scale]));
  store.set('cw.state', { ...store.get('cw.state', {}), scale });
}
$$('#bottombar [data-scale]').forEach(b => {
  b.onclick = () => {
    const k = b.dataset.scale;
    scale[k] = !scale[k];
    if (k === 'percent' && scale.percent) scale.log = false;
    if (k === 'log' && scale.log) scale.percent = false;
    applyScale();
  };
});

setTimeZone(store.get('cw.state', {}).tz || 'Asia/Kolkata');
function tickClock() {
  const now = new Date();
  $('#clock').textContent = now.toLocaleTimeString('en-GB', { timeZone: timeZone(), hour12: false })
    + ' ' + zoneLabel();
}
setInterval(tickClock, 1000);
tickClock();
$('#clock').title = 'Time zone (click to change)';
$('#clock').style.cursor = 'pointer';
$('#clock').onclick = e => {
  const zones = ['Asia/Kolkata', 'UTC', 'Europe/London', 'America/New_York', 'Asia/Singapore', 'Asia/Tokyo'];
  popupMenu(e.currentTarget, zones.map(z => ({ label: z, value: z, active: z === timeZone() })), async z => {
    setTimeZone(z);
    store.set('cw.state', { ...store.get('cw.state', {}), tz: z });
    tickClock();
    for (const s of app.slots) if (s.info) await s.load(s.info.symbol, s.tf);
  });
};

// ---- keyboard: typing a letter opens symbol search, like TradingView ----
document.addEventListener('keydown', e => {
  if (typingInField(e) || app.search.isOpen || !$('#dialog').hidden) return;
  for (const f of app.hooks.keydown) if (f(e) === true) { e.preventDefault(); return; }
  if (e.ctrlKey || e.metaKey || e.altKey) return;
  if (/^[a-zA-Z0-9]$/.test(e.key)) {
    e.preventDefault();
    app.openSearch(e.key);
  }
});

// Feature modules (watchlist, drawings, indicators, alerts, layouts). Each
// exports init(app) and runs before the first symbol loads.
const FEATURES = [initWatchlist, initDrawings, initIndicators, initAlerts, initLayouts, initReplay, initExtras];

async function start() {
  for (const init of FEATURES) await init(app);
  app.addSlot();
  app.slot.el.classList.add('focused');
  renderTopbar();
  applyScale();
  const ok = await app.setSymbol(app.symbol);
  if (!ok && app.symbol !== 'BINANCE:BTCUSDT.P') await app.setSymbol('BINANCE:BTCUSDT.P');
  applyScale();
  app.emit('ready');
  applyScale();
}

start();
