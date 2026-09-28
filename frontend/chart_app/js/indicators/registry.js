// Indicator definitions. compute(bars, inputs, ctx) returns arrays aligned
// to the bars, one per plot key. Async ones (server) return a Promise.

import { api } from '../api.js';
import { SOURCES, atr, bollinger, ema, macd, rsi, sma, source, stoch, vwap, wma } from './calc.js';

const len = (d, label = 'Length') => ({ key: 'length', label, type: 'number', default: d, min: 1, step: 1 });
const src = { key: 'source', label: 'Source', type: 'select', default: 'close', options: SOURCES };
const col = (key, label, d) => ({ key, label, type: 'color', default: d });
const width = { key: 'width', label: 'Line width', type: 'select', default: 2, options: [[1, '1 px'], [2, '2 px'], [3, '3 px']] };

export const INDICATORS = {
  ema: {
    name: 'Exponential Moving Average', short: 'EMA', pane: 'overlay',
    inputs: [len(20), src, col('color', 'Colour', '#f7a600'), width],
    plots: [{ key: 'value', colorKey: 'color' }],
    compute: (bars, i) => ({ value: ema(source(bars, i.source), i.length) }),
  },
  sma: {
    name: 'Simple Moving Average', short: 'SMA', pane: 'overlay',
    inputs: [len(50), src, col('color', 'Colour', '#2962ff'), width],
    plots: [{ key: 'value', colorKey: 'color' }],
    compute: (bars, i) => ({ value: sma(source(bars, i.source), i.length) }),
  },
  wma: {
    name: 'Weighted Moving Average', short: 'WMA', pane: 'overlay',
    inputs: [len(20), src, col('color', 'Colour', '#e91e63'), width],
    plots: [{ key: 'value', colorKey: 'color' }],
    compute: (bars, i) => ({ value: wma(source(bars, i.source), i.length) }),
  },
  vwap: {
    name: 'VWAP', short: 'VWAP', pane: 'overlay',
    inputs: [{ key: 'anchor', label: 'Anchor', type: 'select', default: 'day', options: [['day', 'Session (day)'], ['week', 'Week'], ['month', 'Month']] },
      col('color', 'Colour', '#2962ff'), width],
    plots: [{ key: 'value', colorKey: 'color' }],
    compute: (bars, i, ctx) => ({ value: vwap(bars, i.anchor, ctx.offset) }),
  },
  bb: {
    name: 'Bollinger Bands', short: 'BB', pane: 'overlay',
    inputs: [len(20), { key: 'mult', label: 'StdDev', type: 'number', default: 2, min: 0.1, step: 0.1 }, src,
      col('color', 'Basis colour', '#ff6d00'), col('band', 'Band colour', '#2962ff')],
    plots: [{ key: 'basis', colorKey: 'color', width: 1 },
      { key: 'upper', colorKey: 'band', width: 1 }, { key: 'lower', colorKey: 'band', width: 1 }],
    compute: (bars, i) => bollinger(source(bars, i.source), i.length, i.mult),
  },
  rsi: {
    name: 'Relative Strength Index', short: 'RSI', pane: 'new',
    inputs: [len(14), src, col('color', 'Colour', '#7e57c2'),
      { key: 'upper', label: 'Upper band', type: 'number', default: 70 },
      { key: 'lower', label: 'Lower band', type: 'number', default: 30 }],
    plots: [{ key: 'value', colorKey: 'color', width: 2 }],
    levels: i => [{ value: i.upper, color: '#787b86' }, { value: 50, color: '#787b8680' }, { value: i.lower, color: '#787b86' }],
    compute: (bars, i) => ({ value: rsi(source(bars, i.source), i.length) }),
  },
  macd: {
    name: 'MACD', short: 'MACD', pane: 'new',
    inputs: [{ key: 'fast', label: 'Fast length', type: 'number', default: 12, min: 1 },
      { key: 'slow', label: 'Slow length', type: 'number', default: 26, min: 1 },
      { key: 'signal', label: 'Signal length', type: 'number', default: 9, min: 1 }, src,
      col('color', 'MACD colour', '#2962ff'), col('sigColor', 'Signal colour', '#ff6d00')],
    plots: [
      { key: 'hist', type: 'histogram',
        colorFn: (v, prev) => (v >= 0 ? (v >= prev ? '#26a69a' : '#b2dfdb') : (v <= prev ? '#ff5252' : '#ffcdd2')) },
      { key: 'macd', colorKey: 'color', width: 2 }, { key: 'signal', colorKey: 'sigColor', width: 2 }],
    compute: (bars, i) => macd(source(bars, i.source), i.fast, i.slow, i.signal),
  },
  stoch: {
    name: 'Stochastic', short: 'Stoch', pane: 'new',
    inputs: [{ key: 'k', label: '%K length', type: 'number', default: 14, min: 1 },
      { key: 'smooth', label: '%K smoothing', type: 'number', default: 1, min: 1 },
      { key: 'd', label: '%D smoothing', type: 'number', default: 3, min: 1 },
      col('color', '%K colour', '#2962ff'), col('dColor', '%D colour', '#ff6d00')],
    plots: [{ key: 'k', colorKey: 'color', width: 2 }, { key: 'd', colorKey: 'dColor', width: 2 }],
    levels: () => [{ value: 80, color: '#787b86' }, { value: 20, color: '#787b86' }],
    compute: (bars, i) => stoch(bars, i.k, i.smooth, i.d),
  },
  atr: {
    name: 'Average True Range', short: 'ATR', pane: 'new',
    inputs: [len(14), col('color', 'Colour', '#b71c1c')],
    plots: [{ key: 'value', colorKey: 'color', width: 2 }],
    compute: (bars, i) => ({ value: atr(bars, i.length) }),
  },
  vumanchu: {
    name: 'VuManChu Cipher B (screener)', short: 'VMC Cipher B', pane: 'new', server: true,
    inputs: [{ key: 'channel_len', label: 'Channel length', type: 'number', default: 9, min: 1 },
      { key: 'average_len', label: 'Average length', type: 'number', default: 12, min: 1 },
      { key: 'ma_len', label: 'MA length', type: 'number', default: 3, min: 1 },
      { key: 'overbought', label: 'Overbought', type: 'number', default: 53 },
      { key: 'oversold', label: 'Oversold', type: 'number', default: -53 },
      { key: 'mfi_period', label: 'Money-flow period', type: 'number', default: 60, min: 1 },
      { key: 'mfi_mult', label: 'Money-flow multiplier', type: 'number', default: 150 },
      { key: 'showMfi', label: 'Money flow area', type: 'check', default: true },
      { key: 'showDots', label: 'Buy / sell dots and divergences', type: 'check', default: true }],
    plots: [
      { key: 'mfi', type: 'area', hideKey: 'showMfi', color: '#3ee145', negColor: '#ff3d2e' },
      { key: 'wt1', color: '#90caf9', width: 1, area: true },
      { key: 'wt2', color: '#1e3a8a', width: 1 }],
    levels: i => [{ value: i.overbought, color: '#f2364580' }, { value: 0, color: '#787b8680' }, { value: i.oversold, color: '#08998180' }],
    async compute(bars, i) {
      const { showMfi, showDots, ...params } = i;
      const res = await api.post('/api/chart/studies/vumanchu', {
        bars: bars.map(b => ({ time: b.time, open: b.open, high: b.high, low: b.low, close: b.close, volume: b.volume })),
        params,
      });
      const at = new Map(bars.map((b, k) => [b.time, k]));
      const align = s => {
        const out = new Array(bars.length).fill(NaN);
        for (const p of s) { const k = at.get(p.time); if (k !== undefined) out[k] = p.value; }
        return out;
      };
      const markers = !showDots ? [] : res.markers.map(m => ({
        time: m.time, plot: 'wt2',
        ...{ buy: { position: 'belowBar', shape: 'circle', color: '#089981', size: 0.6 },
             sell: { position: 'aboveBar', shape: 'circle', color: '#f23645', size: 0.6 },
             bull_div: { position: 'belowBar', shape: 'arrowUp', color: '#089981', text: 'Bull div' },
             bear_div: { position: 'aboveBar', shape: 'arrowDown', color: '#f23645', text: 'Bear div' } }[m.kind],
      }));
      return { wt1: align(res.wt1), wt2: align(res.wt2), mfi: align(res.mfi), markers };
    },
  },
  vprofile: {
    name: 'Volume Profile (visible range)', short: 'VRVP', pane: 'overlay', custom: 'vprofile',
    inputs: [{ key: 'rows', label: 'Rows', type: 'number', default: 40, min: 5, max: 200 },
      { key: 'width', label: 'Width (% of chart)', type: 'number', default: 28, min: 5, max: 80 },
      { key: 'placement', label: 'Placement', type: 'select', default: 'right', options: [['right', 'Right'], ['left', 'Left']] },
      { key: 'valueArea', label: 'Value area %', type: 'number', default: 70, min: 10, max: 100 },
      col('upColor', 'Up volume', '#26a69a'), col('downColor', 'Down volume', '#ef5350'),
      col('pocColor', 'POC line', '#ffeb3b')],
    plots: [],
  },
  auto: {
    name: 'Auto analysis (screener)', short: 'Auto', pane: 'overlay', custom: 'auto',
    inputs: [{ key: 'n', label: 'Candles analysed', type: 'number', default: 300, min: 60, max: 1000 },
      { key: 'trendlines', label: 'Trendlines', type: 'check', default: true },
      { key: 'levels', label: 'Flat levels', type: 'check', default: true },
      { key: 'fib', label: 'Fibonacci', type: 'check', default: false },
      { key: 'patterns', label: 'Patterns + targets', type: 'check', default: true },
      { key: 'swings', label: 'Swing labels (HH / HL / LH / LL)', type: 'check', default: true },
      { key: 'obs', label: 'Daily order blocks', type: 'check', default: true }],
    plots: [],
  },
};

export const defaultsOf = type =>
  Object.fromEntries(INDICATORS[type].inputs.map(inp => [inp.key, inp.default]));

// Inputs shown after the name in the legend, like TradingView ("EMA 20 close").
const TITLE_KEYS = {
  ema: ['length', 'source'], sma: ['length', 'source'], wma: ['length', 'source'], vwap: ['anchor'],
  bb: ['length', 'mult'], rsi: ['length'], macd: ['fast', 'slow', 'signal'], stoch: ['k', 'smooth', 'd'],
  atr: ['length'], vumanchu: [], vprofile: ['rows'], auto: [],
};

export function titleOf(study) {
  const def = INDICATORS[study.type];
  const shown = (TITLE_KEYS[study.type] || []).map(k => study.inputs[k]);
  return `${def.short} ${shown.join(' ')}`.trim();
}
