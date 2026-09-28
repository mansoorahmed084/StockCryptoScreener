// Live last / change / change% for a set of symbols.
//
// Crypto: Binance combined miniTicker streams (24h change, like TradingView's
// crypto watchlist). Stocks: /api/chart/quotes every 30 s (delayed).

import { api } from './api.js';

const FUTURES_STREAM = 'wss://fstream.binance.com/market/stream?streams=';
const SPOT_STREAM = 'wss://stream.binance.com:9443/stream?streams=';
const STOCK_POLL_MS = 30_000;
const MAX_STREAMS = 180;          // per connection

// Binance symbol (lower case) of a chart symbol, and which stream has it.
function binanceOf(symbol) {
  const [exch, ticker] = symbol.split(':');
  if (exch === 'CRYPTOCAP') return ticker === 'BTC.D' ? ['btcdomusdt', 'fut'] : null;
  if (exch !== 'BINANCE') return null;
  return ticker.endsWith('.P') ? [ticker.slice(0, -2).toLowerCase(), 'fut'] : [ticker.toLowerCase(), 'spot'];
}

export class QuoteStream {
  constructor(onQuote) {
    this.onQuote = onQuote;          // (symbol, {last, change, change_pct, high, low, volume})
    this.symbols = [];
    this.sockets = [];
    this.timer = null;
  }

  setSymbols(symbols) {
    const next = [...new Set(symbols)].sort();
    if (next.join() === this.symbols.join()) return;
    this.stop();
    this.symbols = next;
    if (!next.length) return;
    this.closed = false;
    this.gen = (this.gen || 0) + 1;
    this._snapshot(next);
    const fut = new Map(), spot = new Map(), stocks = [];
    for (const s of next) {
      const b = binanceOf(s);
      if (!b) stocks.push(s);
      else (b[1] === 'fut' ? fut : spot).set(b[0], [...((b[1] === 'fut' ? fut : spot).get(b[0]) || []), s]);
    }
    this._streams(FUTURES_STREAM, fut);
    this._streams(SPOT_STREAM, spot);
    if (stocks.length) this._poll(stocks);
  }

  async _snapshot(symbols) {
    const gen = this.gen;
    try {
      const { quotes } = await api.get('/api/chart/quotes', { symbols: symbols.join(',') });
      if (this.closed || gen !== this.gen) return;
      for (const [s, q] of Object.entries(quotes)) this.onQuote(s, q);
    } catch { /* live streams fill in */ }
  }

  _streams(base, map) {
    const keys = [...map.keys()];
    for (let i = 0; i < keys.length; i += MAX_STREAMS) {
      const chunk = keys.slice(i, i + MAX_STREAMS);
      this._open(base + chunk.map(k => `${k}@miniTicker`).join('/'), map, 1000, this.gen);
    }
  }

  _open(url, map, delay, gen) {
    if (this.closed || gen !== this.gen) return;
    const ws = new WebSocket(url);
    this.sockets.push(ws);
    ws.onopen = () => { delay = 1000; };
    let lastMsg = Date.now();
    const dog = setInterval(() => { if (Date.now() - lastMsg > 90_000) ws.close(); }, 20_000);
    ws.onmessage = ev => {
      lastMsg = Date.now();
      const d = JSON.parse(ev.data).data;
      if (!d || !d.s) return;
      const last = +d.c, open = +d.o;
      const q = { last, change: last - open, change_pct: open ? (last - open) / open * 100 : 0,
                  high: +d.h, low: +d.l, volume: +d.q };
      for (const s of map.get(d.s.toLowerCase()) || []) this.onQuote(s, q);
    };
    ws.onclose = () => {
      clearInterval(dog);
      this.sockets = this.sockets.filter(x => x !== ws);
      if (!this.closed && gen === this.gen) {
        setTimeout(() => this._open(url, map, Math.min(delay * 2, 30_000), gen), delay);
      }
    };
    ws.onerror = () => ws.close();
  }

  _poll(stocks) {
    const gen = this.gen;
    const tick = async () => {
      await this._snapshot(stocks);
      if (!this.closed && gen === this.gen) this.timer = setTimeout(tick, STOCK_POLL_MS);
    };
    this.timer = setTimeout(tick, STOCK_POLL_MS);
  }

  stop() {
    this.closed = true;
    clearTimeout(this.timer);
    for (const ws of this.sockets) ws.close();
    this.sockets = [];
    this.symbols = [];
  }
}
