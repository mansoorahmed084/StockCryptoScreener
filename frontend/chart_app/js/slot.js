// One chart on the screen: its DOM, ChartView and Datafeed.
// The workspace has one slot, or 2 / 4 in a multi-chart layout.

import { api } from './api.js';
import { ChartView } from './chart.js';
import { Datafeed } from './datafeed.js';

const infoCache = new Map();

export async function resolveSymbol(symbol) {
  const key = symbol.toUpperCase();
  if (!infoCache.has(key)) {
    const p = api.get('/api/chart/resolve', { symbol: key });
    infoCache.set(key, p);
    p.catch(() => infoCache.delete(key));
  }
  return infoCache.get(key);
}

export class ChartSlot {
  constructor(parent, index) {
    this.index = index;
    this.el = document.createElement('div');
    this.el.className = 'chart-slot';
    this.el.innerHTML = `
      <div class="chart-host"></div>
      <div class="legend">
        <div class="lg-row"><span class="lg-title"></span><span class="lg-ohlc"></span></div>
        <div class="lg-row"><span class="lg-vol"></span></div>
        <div class="legend-studies"></div>
      </div>
      <button class="go-live" title="Scroll to the newest candle" hidden>»</button>
      <div class="chart-msg" hidden></div>`;
    parent.appendChild(this.el);
    this.host = this.el.querySelector('.chart-host');
    this.host.style.cssText = 'position:absolute;inset:0';
    this.view = new ChartView(this.host, this.el.querySelector('.legend'));
    this.msg = this.el.querySelector('.chart-msg');
    this.goLive = this.el.querySelector('.go-live');
    this.goLive.onclick = () => this.view.chart.timeScale().scrollToRealTime();
    this.feed = null;
    this.info = null;
    this.tf = null;
    this.listeners = { loaded: [], status: [] };
    this.loadSeq = 0;

    this.view.on('range', r => this._onRange(r));
  }

  on(event, fn) { this.listeners[event].push(fn); }
  _emit(event, ...args) { for (const f of this.listeners[event]) f(...args); }

  message(text) {
    this.msg.textContent = text || '';
    this.msg.hidden = !text;
  }

  async load(symbol, tf) {
    const seq = ++this.loadSeq;
    this.message('Loading…');
    if (this.feed) { this.feed.stop(); this.feed = null; }
    let info;
    try {
      info = await resolveSymbol(symbol);
    } catch (err) {
      if (seq === this.loadSeq) this.message(`Unknown symbol ${symbol}: ${err.message}`);
      throw err;
    }
    const feed = new Datafeed(info, tf, {
      onBar: bar => { if (this.feed === feed) this.view.update(bar); },
      onStatus: s => { if (this.feed === feed) this._emit('status', s); },
    });
    let bars;
    try {
      bars = await feed.loadInitial();
    } catch (err) {
      if (seq === this.loadSeq) this.message(`No data: ${err.message}`);
      throw err;
    }
    if (seq !== this.loadSeq) return;         // a newer load started
    this.feed = feed;
    this.info = info;
    this.tf = tf;
    this.view.setData(info, tf, bars);
    this.view.chart.timeScale().scrollToRealTime();
    this.message(bars.length ? '' : 'No candles for this timeframe');
    feed.start();
    this._emit('loaded', info, tf);
  }

  // Scrolled near the oldest candle: fetch older ones.
  async _onRange(r) {
    if (!r || !this.feed) return;
    this.goLive.hidden = r.to > this.view.bars.length - 2;
    if (r.from < 40 && this.feed.more && !this.feed.loading) {
      const feed = this.feed;
      const added = await feed.loadMore();
      if (added && feed === this.feed) this.view.prepend(feed.bars);
    }
  }

  // Load history back to utcFrom (range buttons), then show it.
  async showRange(utcFrom) {
    if (!this.feed) return;
    const feed = this.feed;
    const target = utcFrom === null ? 0 : utcFrom;
    const before = feed.bars.length;
    await feed.ensureHistory(target, utcFrom === null ? 4 : 10);
    if (feed !== this.feed) return;
    if (feed.bars.length !== before) this.view.prepend(feed.bars);
    this.view.showRange(utcFrom);
  }

  destroy() {
    if (this.feed) this.feed.stop();
    clearInterval(this.view.clock);
    this.view.chart.remove();
    this.el.remove();
  }
}
