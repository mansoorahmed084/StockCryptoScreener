// Candle history (with paging) and the live candle for one symbol+timeframe.
//
// Crypto: the browser listens to Binance's kline WebSocket directly.
// Stocks: Yahoo has no free stream, so the newest candles are polled.
// All times here are UTC seconds; the chart does the time-zone shift.

import { api } from './api.js';

// Binance serves USD-M futures market streams under /market (the old paths
// still accept connections but send nothing).
const FUTURES_WS = 'wss://fstream.binance.com/market/ws';
const SPOT_WS = 'wss://stream.binance.com:9443/ws';
const STOCK_POLL_MS = 30_000;

export class Datafeed {
  constructor(info, tf, { onBar, onStatus } = {}) {
    this.info = info;          // from /api/chart/resolve
    this.tf = tf;
    this.bars = [];
    this.more = true;
    this.loading = null;
    this.onBar = onBar || (() => {});
    this.onStatus = onStatus || (() => {});
    this.closed = false;
  }

  async loadInitial(limit = 1000) {
    const page = await api.get('/api/chart/candles', {
      symbol: this.info.symbol, tf: this.tf, limit,
    });
    this.bars = page.candles;
    this.more = page.more;
    return this.bars;
  }

  // Older candles before the first loaded one. Returns how many were added.
  loadMore(limit = 1000) {
    if (!this.more || !this.bars.length) return Promise.resolve(0);
    if (this.loading) return this.loading;
    const end = this.bars[0].time;
    this.loading = api.get('/api/chart/candles', {
      symbol: this.info.symbol, tf: this.tf, end, limit,
    }).then(page => {
      const older = page.candles.filter(b => b.time < end);
      this.bars = older.concat(this.bars);
      this.more = page.more && older.length > 0;
      return older.length;
    }).finally(() => { this.loading = null; });
    return this.loading;
  }

  // Load pages until the history reaches back to `fromUtc` (or runs out).
  async ensureHistory(fromUtc, maxPages = 10) {
    for (let i = 0; i < maxPages && this.more && this.bars.length
         && this.bars[0].time > fromUtc; i++) {
      if (!(await this.loadMore())) break;
    }
  }

  // Put a live candle in: replace the last one or add a new one.
  _merge(bar) {
    const last = this.bars[this.bars.length - 1];
    if (!last || bar.time > last.time) this.bars.push(bar);
    else if (bar.time === last.time) this.bars[this.bars.length - 1] = bar;
    else return;                       // an old candle; ignore
    this.onBar(bar);
  }

  start() {
    if (this.info.market === 'stock') this._poll();
    else this._connect();
  }

  _connect(delay = 1000) {
    if (this.closed) return;
    const base = this.info.market === 'spot' ? SPOT_WS : FUTURES_WS;
    const ws = new WebSocket(`${base}/${this.info.binance.toLowerCase()}@kline_${this.tf}`);
    this.ws = ws;
    ws.onopen = () => {
      this.onStatus('connecting');
      delay = 1000;
      this._catchUp();
    };
    // "Live" only once data flows; a silent socket is dropped and reopened.
    let lastMsg = Date.now();
    clearInterval(this.watchdog);
    this.watchdog = setInterval(() => {
      if (Date.now() - lastMsg > 60_000) ws.close();
    }, 15_000);
    ws.onmessage = ev => {
      if (Date.now() - lastMsg > 5000 || !this.flowing) { this.flowing = true; this.onStatus('live'); }
      lastMsg = Date.now();
      const k = JSON.parse(ev.data).k;
      if (!k) return;
      this._merge({ time: k.t / 1000, open: +k.o, high: +k.h, low: +k.l,
                    close: +k.c, volume: +k.v });
    };
    ws.onclose = () => {
      clearInterval(this.watchdog);
      this.flowing = false;
      if (this.closed) return;
      this.onStatus('reconnecting');
      this.retry = setTimeout(() => this._connect(Math.min(delay * 2, 30_000)), delay);
    };
    ws.onerror = () => ws.close();
  }

  // After a (re)connect, fetch the newest candles so no gap is left.
  async _catchUp() {
    try {
      const page = await api.get('/api/chart/candles', {
        symbol: this.info.symbol, tf: this.tf, limit: 5,
      });
      if (this.closed) return;
      for (const b of page.candles) this._merge(b);
    } catch { /* the stream still works */ }
  }

  _poll() {
    this.onStatus('delayed');
    const tick = async () => {
      await this._catchUp();
      if (!this.closed) this.timer = setTimeout(tick, STOCK_POLL_MS);
    };
    this.timer = setTimeout(tick, STOCK_POLL_MS);
  }

  stop() {
    this.closed = true;
    clearTimeout(this.retry);
    clearTimeout(this.timer);
    clearInterval(this.watchdog);
    if (this.ws) this.ws.close();
  }
}
