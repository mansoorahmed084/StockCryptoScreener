// Indicator maths on arrays aligned to the candles. NaN = no value yet.
// Formulas follow TradingView's built-ins (ta.ema, ta.rma, ta.rsi, ...).

export const SOURCES = ['close', 'open', 'high', 'low', 'hl2', 'hlc3', 'ohlc4'];

export function source(bars, src) {
  switch (src) {
    case 'open': return bars.map(b => b.open);
    case 'high': return bars.map(b => b.high);
    case 'low': return bars.map(b => b.low);
    case 'hl2': return bars.map(b => (b.high + b.low) / 2);
    case 'hlc3': return bars.map(b => (b.high + b.low + b.close) / 3);
    case 'ohlc4': return bars.map(b => (b.open + b.high + b.low + b.close) / 4);
    default: return bars.map(b => b.close);
  }
}

export function sma(x, n) {
  const out = new Array(x.length).fill(NaN);
  let sum = 0, count = 0;
  for (let i = 0; i < x.length; i++) {
    const v = x[i];
    if (!Number.isNaN(v)) { sum += v; count++; }
    if (i >= n) { const old = x[i - n]; if (!Number.isNaN(old)) { sum -= old; count--; } }
    if (i >= n - 1 && count === n) out[i] = sum / n;
  }
  return out;
}

// EMA seeded with the SMA of the first n values (like ta.ema).
export function ema(x, n, alpha = 2 / (n + 1)) {
  const out = new Array(x.length).fill(NaN);
  let prev = NaN, seed = 0, seen = 0;
  for (let i = 0; i < x.length; i++) {
    const v = x[i];
    if (Number.isNaN(v)) continue;
    if (Number.isNaN(prev)) {
      seed += v;
      seen++;
      if (seen === n) { prev = seed / n; out[i] = prev; }
      continue;
    }
    prev = alpha * v + (1 - alpha) * prev;
    out[i] = prev;
  }
  return out;
}

export const rma = (x, n) => ema(x, n, 1 / n);

export function wma(x, n) {
  const out = new Array(x.length).fill(NaN);
  const denom = n * (n + 1) / 2;
  for (let i = n - 1; i < x.length; i++) {
    let s = 0;
    for (let k = 0; k < n; k++) s += x[i - k] * (n - k);
    out[i] = s / denom;
  }
  return out;
}

export function stdev(x, n) {
  const m = sma(x, n);
  const out = new Array(x.length).fill(NaN);
  for (let i = n - 1; i < x.length; i++) {
    if (Number.isNaN(m[i])) continue;
    let s = 0;
    for (let k = 0; k < n; k++) s += (x[i - k] - m[i]) ** 2;
    out[i] = Math.sqrt(s / n);
  }
  return out;
}

export function rsi(x, n) {
  const up = [NaN], down = [NaN];
  for (let i = 1; i < x.length; i++) {
    const d = x[i] - x[i - 1];
    up.push(Math.max(d, 0));
    down.push(Math.max(-d, 0));
  }
  const ru = rma(up.map((v, i) => (i === 0 ? NaN : v)), n);
  const rd = rma(down.map((v, i) => (i === 0 ? NaN : v)), n);
  return ru.map((u, i) => (Number.isNaN(u) ? NaN : rd[i] === 0 ? 100 : u === 0 ? 0 : 100 - 100 / (1 + u / rd[i])));
}

export function macd(x, fast, slow, signal) {
  const f = ema(x, fast), s = ema(x, slow);
  const line = f.map((v, i) => v - s[i]);
  const sig = ema(line, signal);
  return { macd: line, signal: sig, hist: line.map((v, i) => v - sig[i]) };
}

export function bollinger(x, n, mult) {
  const mid = sma(x, n), sd = stdev(x, n);
  return { basis: mid, upper: mid.map((m, i) => m + mult * sd[i]), lower: mid.map((m, i) => m - mult * sd[i]) };
}

export function atr(bars, n) {
  const tr = bars.map((b, i) => (i === 0 ? b.high - b.low
    : Math.max(b.high - b.low, Math.abs(b.high - bars[i - 1].close), Math.abs(b.low - bars[i - 1].close))));
  return rma(tr, n);
}

// VWAP that restarts each session (day, week or month, in the given UTC offset).
export function vwap(bars, anchor = 'day', offsetSec = 0) {
  const out = new Array(bars.length).fill(NaN);
  let key = null, pv = 0, vol = 0;
  for (let i = 0; i < bars.length; i++) {
    const b = bars[i];
    const d = new Date((b.time + offsetSec) * 1000);
    const k = anchor === 'month' ? `${d.getUTCFullYear()}-${d.getUTCMonth()}`
      : anchor === 'week' ? Math.floor((b.time + offsetSec - 4 * 86400) / (7 * 86400))
      : Math.floor((b.time + offsetSec) / 86400);
    if (k !== key) { key = k; pv = 0; vol = 0; }
    const tp = (b.high + b.low + b.close) / 3;
    pv += tp * b.volume;
    vol += b.volume;
    out[i] = vol ? pv / vol : tp;
  }
  return out;
}

export function stoch(bars, kLen, kSmooth, dLen) {
  const raw = bars.map((b, i) => {
    if (i < kLen - 1) return NaN;
    let hi = -Infinity, lo = Infinity;
    for (let k = 0; k < kLen; k++) { hi = Math.max(hi, bars[i - k].high); lo = Math.min(lo, bars[i - k].low); }
    return hi === lo ? 50 : (b.close - lo) / (hi - lo) * 100;
  });
  const k = sma(raw, kSmooth);
  return { k, d: sma(k, dLen) };
}
