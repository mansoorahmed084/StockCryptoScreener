// Indicator definitions. compute(bars, inputs, ctx) returns arrays aligned
// to the bars, one per plot key. Async ones (server) return a Promise.

import { api } from '../api.js';
import { SOURCES, atr, bollinger, ema, macd, rsi, sma, source, stoch, vwap, wma } from './calc.js';

const len = (d, label = 'Length') => ({ key: 'length', label, type: 'number', default: d, min: 1, step: 1 });
const src = { key: 'source', label: 'Source', type: 'select', default: 'close', options: SOURCES };
const col = (key, label, d) => ({ key, label, type: 'color', default: d });
const width = { key: 'width', label: 'Line width', type: 'select', default: 2, options: [[1, '1 px'], [2, '2 px'], [3, '3 px']] };

const num = (key, label, d, extra = {}) => ({ key, label, type: 'number', default: d, min: 1, ...extra });
const check = (key, label, d = true) => ({ key, label, type: 'check', default: d });

// A study the screener's Python code computes on the chart's candles. Series
// come back by name and are lined up with the bars.
async function serverStudy(path, bars, params) {
  const res = await api.post(path, {
    bars: bars.map(b => ({ time: b.time, open: b.open, high: b.high, low: b.low, close: b.close, volume: b.volume })),
    params,
  });
  const at = new Map(bars.map((b, k) => [b.time, k]));
  const series = {};
  for (const [name, points] of Object.entries(res.series || {})) {
    const out = new Array(bars.length).fill(NaN);
    for (const p of points) { const k = at.get(p.time); if (k !== undefined) out[k] = p.value; }
    series[name] = out;
  }
  return { series, markers: res.markers || [] };
}

const UP = '#089981', DOWN = '#f23645', FLAT = '#9598a1';

// Technical Sentiment Composite: 0–100, the same bands as backend/indicators/sentiment.py.
const sentimentColor = v => (v >= 75 ? UP : v >= 60 ? '#5fbf9f' : v > 40 ? FLAT : v > 25 ? '#f28b94' : DOWN);
const sentimentRating = v => (v >= 75 ? 'Strong bullish' : v >= 60 ? 'Bullish' : v > 40 ? 'Neutral'
  : v > 25 ? 'Bearish' : 'Strong bearish');
const SENTIMENT_PARTS = [['rsi', 'RSI'], ['stoch', 'Stoch'], ['stoch_rsi', 'StochRSI'], ['cci', 'CCI'],
  ['bbp', 'BBP'], ['ma', 'MA'], ['bb', 'BB'], ['supertrend', 'ST'], ['vwap', 'VWAP'], ['linreg', 'LinReg'],
  ['structure', 'Struct']];

const MATRIX_MARKS = {
  turn_up: { position: 'belowBar', shape: 'circle', color: '#08998199', size: 0.4 },
  turn_down: { position: 'aboveBar', shape: 'circle', color: '#f2364599', size: 0.4 },
  turn_up_strong: { position: 'belowBar', shape: 'circle', color: UP, size: 0.9 },
  turn_down_strong: { position: 'aboveBar', shape: 'circle', color: DOWN, size: 0.9 },
  rev_up: { position: 'belowBar', shape: 'square', color: UP, size: 0.7 },
  rev_down: { position: 'aboveBar', shape: 'square', color: DOWN, size: 0.7 },
  rev_up_major: { position: 'belowBar', shape: 'arrowUp', color: UP, text: 'Rev' },
  rev_down_major: { position: 'aboveBar', shape: 'arrowDown', color: DOWN, text: 'Rev' },
  bull_div: { position: 'belowBar', shape: 'arrowUp', color: '#2962ff', text: 'Bull div' },
  bear_div: { position: 'aboveBar', shape: 'arrowDown', color: '#ff6d00', text: 'Bear div' },
};

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
  sentiment: {
    name: 'Technical Sentiment Composite (screener)', short: 'Sentiment', pane: 'new', server: true,
    markerPlot: 'sentiment',
    inputs: [num('rsi_len', 'RSI length', 14), num('stoch_len', 'Stochastic length', 14),
      num('stoch_smooth', 'Stochastic smoothing', 3), num('stoch_rsi_len', 'Stochastic RSI length', 14),
      num('cci_len', 'CCI length', 20), num('bbp_len', 'Bull Bear Power length', 13),
      num('ma_len', 'Moving average length', 20), num('bb_len', 'Bollinger length', 20),
      num('bb_mult', 'Bollinger StdDev', 2, { min: 0.1, step: 0.1 }),
      num('st_len', 'Supertrend ATR length', 10), num('st_mult', 'Supertrend factor', 3, { min: 0.1, step: 0.1 }),
      num('linreg_len', 'Linear regression length', 25, { min: 2 }),
      num('structure_len', 'Market structure swing length', 5),
      num('norm_smooth', 'Trend score smoothing', 3),
      check('showGroups', 'Momentum and trend lines'),
      check('showParts', 'Every component in the legend'),
      check('showDivs', 'Divergences')],
    plots: [
      { key: 'momentum', color: '#5b9cf6', width: 1, hideKey: 'showGroups', lastValue: false },
      { key: 'trend', color: '#f7a600', width: 1, hideKey: 'showGroups', lastValue: false },
      { key: 'sentiment', color: FLAT, width: 2, colorFn: sentimentColor }],
    levels: () => [{ value: 75, color: '#08998180' }, { value: 60, color: '#08998140' }, { value: 50, color: '#787b8680' },
      { value: 40, color: '#f2364540' }, { value: 25, color: '#f2364580' }],
    legendText(res, k, i) {
      const v = res.sentiment?.[k];
      if (v === undefined || Number.isNaN(v)) return [];
      const tags = [{ text: sentimentRating(v), color: sentimentColor(v) }];
      if (i.showParts !== false) {
        for (const [key, label] of SENTIMENT_PARTS) {
          const p = res[key]?.[k];
          if (p !== undefined && !Number.isNaN(p)) tags.push({ text: `${label} ${Math.round(p)}`, color: sentimentColor(p) });
        }
      }
      return tags;
    },
    async compute(bars, i) {
      const { showGroups, showParts, showDivs, ...params } = i;
      const res = await serverStudy('/api/chart/studies/sentiment', bars, params);
      const markers = showDivs === false ? [] : res.markers.map(m => ({
        time: m.time, plot: 'sentiment',
        ...(m.kind === 'bull_div'
          ? { position: 'belowBar', shape: 'arrowUp', color: UP, text: 'Bull div' }
          : { position: 'aboveBar', shape: 'arrowDown', color: DOWN, text: 'Bear div' }),
      }));
      return { ...res.series, markers };
    },
  },
  matrix: {
    name: 'Wave & Flow Matrix (screener)', short: 'Wave/Flow', pane: 'new', server: true,
    markerPlot: 'wave',
    inputs: [num('wave_len', 'Wave length', 7),
      { key: 'signal_type', label: 'Signal line', type: 'select', default: 'sma',
        options: [['sma', 'Average'], ['trail', 'Trailing stop']] },
      num('signal_len', 'Signal length / stop distance', 3),
      num('flow_len', 'Money flow length', 35), num('flow_smooth', 'Money flow smoothing', 6),
      num('reversal_factor', 'Reversal factor (higher = fewer)', 5, { min: 0.5, step: 0.5 }),
      num('div_min_gap', 'Divergence: least wave difference', 10, { min: 0, step: 1 }),
      check('showFlow', 'Money flow and overflow'), check('showThresholds', 'Money flow thresholds'),
      check('showConfluence', 'Confluence strips'), check('showMeter', 'Confluence meter line', false),
      check('showTurns', 'Turning points'), check('showReversals', 'Reversals'),
      check('showDivs', 'Divergences')],
    plots: [
      { key: 'flow', type: 'area', base: 50, color: '#26a69a', negColor: '#ef5350', hideKey: 'showFlow' },
      { key: 'overflowAt', type: 'area', base: 50, opacity: 0.75, color: '#26a69a', negColor: '#ef5350',
        hideKey: 'showFlow', legend: false },
      { key: 'flow_upper', color: '#26a69a', width: 1, lineStyle: 1, hideKey: 'showThresholds', legend: false, lastValue: false },
      { key: 'flow_lower', color: '#ef5350', width: 1, lineStyle: 1, hideKey: 'showThresholds', legend: false, lastValue: false },
      { key: 'confUp', type: 'histogram', base: 100, hideKey: 'showConfluence', legend: false,
        colorFn: v => (v > 104 ? '#089981' : '#08998155') },
      { key: 'confDown', type: 'histogram', base: 0, hideKey: 'showConfluence', legend: false,
        colorFn: v => (v < -4 ? '#f23645' : '#f2364555') },
      { key: 'meter', color: '#ab47bc', width: 1, hideKey: 'showMeter', lastValue: false },
      { key: 'signal', color: '#f7a600', width: 1, lastValue: false },
      { key: 'wave', color: '#2962ff', width: 2 }],
    levels: () => [{ value: 80, color: '#f2364580' }, { value: 50, color: '#787b8680' }, { value: 20, color: '#08998180' }],
    legendText(res, k) {
      const up = res.confluence_up?.[k], down = res.confluence_down?.[k], over = res.overflow?.[k];
      const tags = [];
      if (up === 2) tags.push({ text: 'Bullish confluence', color: UP });
      else if (down === 2) tags.push({ text: 'Bearish confluence', color: DOWN });
      else if (up !== undefined && !Number.isNaN(up)) tags.push({ text: 'Mixed' });
      if (over > 0) tags.push({ text: 'Overflow ▲', color: UP });
      if (over < 0) tags.push({ text: 'Overflow ▼', color: DOWN });
      return tags;
    },
    async compute(bars, i) {
      const { showFlow, showThresholds, showConfluence, showMeter, showTurns, showReversals, showDivs, ...params } = i;
      const res = await serverStudy('/api/chart/studies/matrix', bars, params);
      const s = res.series;
      const wanted = m => (m.kind.startsWith('turn_') ? showTurns !== false
        : m.kind.startsWith('rev_') ? showReversals !== false : showDivs !== false);
      const kept = res.markers.filter(wanted);
      // a reversal is a turning point with a climax behind it: draw it once
      const reversed = new Set(kept.filter(m => m.kind.startsWith('rev_')).map(m => m.time));
      const markers = kept.filter(m => !(m.kind.startsWith('turn_') && reversed.has(m.time)))
        .map(m => ({ time: m.time, plot: 'wave', ...MATRIX_MARKS[m.kind] }));
      return {
        ...s,
        overflowAt: (s.overflow || []).map(v => 50 + v),
        // strips outside the 0–100 scale: 4 high for one of wave / flow, 8 for both
        confUp: (s.confluence_up || []).map(v => (v > 0 ? 100 + 4 * v : NaN)),
        confDown: (s.confluence_down || []).map(v => (v > 0 ? -4 * v : NaN)),
        markers,
      };
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
  atr: ['length'], vumanchu: [], sentiment: [], matrix: ['wave_len', 'flow_len'], vprofile: ['rows'], auto: [],
};

export function titleOf(study) {
  const def = INDICATORS[study.type];
  const shown = (TITLE_KEYS[study.type] || []).map(k => study.inputs[k]);
  return `${def.short} ${shown.join(' ')}`.trim();
}
