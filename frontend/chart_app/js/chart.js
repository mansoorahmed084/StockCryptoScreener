// The main chart: candles, volume, legend, countdown label and the helpers
// other parts (drawings, indicators) use to map (time, price) <-> pixels.

import {
  createChart, CandlestickSeries, BarSeries, LineSeries, AreaSeries, HistogramSeries,
  CrosshairMode, PriceScaleMode,
} from '../vendor/lightweight-charts.standalone.production.mjs';
import {
  toChartTime, fromChartTime, precisionOf, fmtPrice, fmtVolume, fmtPct,
  fmtCountdown, fmtChartTime, fmtTick,
} from './format.js';
import { isIntraday, nextBarTime, tfLabel, tfSeconds } from './timeframes.js';

const css = name => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

// Heikin Ashi candles from normal ones.
function heikinAshi(bars) {
  const out = [];
  for (const b of bars) {
    const close = (b.open + b.high + b.low + b.close) / 4;
    const prev = out[out.length - 1];
    const open = prev ? (prev.open + prev.close) / 2 : (b.open + b.close) / 2;
    out.push({ ...b, open, close, high: Math.max(b.high, open, close), low: Math.min(b.low, open, close) });
  }
  return out;
}

// Time left to the candle close, drawn on the price axis under the price label.
class CountdownLabel {
  constructor(view) {
    this.view = view;
    this.axis = {
      coordinate: () => this.y,
      text: () => this.text,
      textColor: () => '#ffffff',
      backColor: () => this.color,
      visible: () => this.text !== '',
      tickVisible: () => false,
    };
    this.views = [this.axis];
    this.y = -100; this.text = ''; this.color = '#000';
  }
  attached({ requestUpdate }) { this.requestUpdate = requestUpdate; }
  detached() { this.requestUpdate = null; }
  priceAxisViews() { return this.views; }
  updateAllViews() {
    const v = this.view, last = v.bars[v.bars.length - 1];
    if (!last || !v.showCountdown) { this.text = ''; return; }
    const left = nextBarTime(last.time, v.tf) - Date.now() / 1000;
    const y = v.series.priceToCoordinate(last.close);
    this.text = left > 0 && left <= tfSeconds(v.tf) * 1.05 ? fmtCountdown(left) : '';
    this.y = y === null ? -100 : y + 17;
    this.color = last.close >= last.open ? css('--up') : css('--down');
  }
  tick() { if (this.requestUpdate) this.requestUpdate(); }
}

export class ChartView {
  constructor(container, legendEl) {
    this.container = container;
    this.legendEl = legendEl;
    this.bars = [];
    this.tf = '1h';
    this.info = null;
    this.style = 'candles';
    this.showCountdown = true;
    this.listeners = { crosshair: [], range: [], data: [] };

    this.chart = createChart(container, {
      autoSize: true,
      crosshair: { mode: CrosshairMode.Normal },
      timeScale: { timeVisible: true, secondsVisible: false, rightOffset: 12, barSpacing: 7,
                   tickMarkFormatter: (t, type) => fmtTick(t, type) },
      localization: { timeFormatter: t => fmtChartTime(t, isIntraday(this.tf)) },
      rightPriceScale: { scaleMargins: { top: 0.08, bottom: 0.2 } },
    });
    this._makeSeries();
    this.volume = this.chart.addSeries(HistogramSeries, {
      priceScaleId: 'vol', priceFormat: { type: 'volume' },
      lastValueVisible: false, priceLineVisible: false,
    });
    this.chart.priceScale('vol').applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    this.applyTheme();

    this.chart.subscribeCrosshairMove(p => {
      this._legend(p);
      for (const f of this.listeners.crosshair) f(p);
    });
    this.chart.timeScale().subscribeVisibleLogicalRangeChange(r => {
      for (const f of this.listeners.range) f(r);
    });
    this.clock = setInterval(() => this.countdown.tick(), 1000);
  }

  on(event, fn) { this.listeners[event].push(fn); }

  _makeSeries() {
    if (this.series) {
      this.series.detachPrimitive(this.countdown);
      this.chart.removeSeries(this.series);
    }
    const up = css('--up'), down = css('--down');
    const def = { candles: CandlestickSeries, heikin: CandlestickSeries, bars: BarSeries,
                  line: LineSeries, area: AreaSeries }[this.style];
    const opts = {
      candles: { upColor: up, downColor: down, borderUpColor: up, borderDownColor: down,
                 wickUpColor: up, wickDownColor: down },
      heikin: { upColor: up, downColor: down, borderUpColor: up, borderDownColor: down,
                wickUpColor: up, wickDownColor: down },
      bars: { upColor: up, downColor: down, thinBars: false },
      line: { color: css('--accent'), lineWidth: 2 },
      area: { lineColor: css('--accent'), topColor: css('--accent-soft'),
              bottomColor: 'rgba(0,0,0,0)', lineWidth: 2 },
    }[this.style];
    this.series = this.chart.addSeries(def, opts, 0);
    this.countdown = this.countdown || new CountdownLabel(this);
    this.series.attachPrimitive(this.countdown);
    for (const f of this.seriesHooks || []) f(this.series);
  }

  // Code that attaches primitives to the main series (drawings, alerts)
  // registers here so it is re-attached when the chart style changes.
  onSeries(fn) {
    (this.seriesHooks ||= []).push(fn);
    fn(this.series);
  }

  setStyle(style) {
    if (style === this.style) return;
    const range = this.chart.timeScale().getVisibleLogicalRange();
    this.style = style;
    this._makeSeries();
    this._render();
    if (range) this.chart.timeScale().setVisibleLogicalRange(range);
  }

  applyTheme() {
    this.chart.applyOptions({
      layout: { background: { color: css('--chart-bg') }, textColor: css('--text-muted'),
                fontFamily: css('--font'), fontSize: 12, panes: { separatorColor: css('--border') } },
      grid: { vertLines: { color: css('--grid') }, horzLines: { color: css('--grid') } },
      rightPriceScale: { borderColor: css('--border') },
      timeScale: { borderColor: css('--border') },
      crosshair: { vertLine: { labelBackgroundColor: css('--crosshair-label') },
                   horzLine: { labelBackgroundColor: css('--crosshair-label') } },
    });
    if (this.series) { this._makeSeries(); this._render(); }
  }

  get intraday() { return isIntraday(this.tf); }
  fmt(p) { return fmtPrice(p, this.precision ?? 2); }
  toChart(utc) { return toChartTime(utc, this.intraday); }
  fromChart(t) { return fromChartTime(t, this.intraday); }

  // New symbol or timeframe: replace all data.
  setData(info, tf, bars) {
    this.info = info;
    this.tf = tf;
    this.bars = bars;
    // Stock candles are delayed and sessions end early: no countdown.
    this.showCountdown = info.market !== 'stock';
    this.precision = precisionOf(bars);
    const minMove = Math.pow(10, -this.precision);
    this.series.applyOptions({ priceFormat: { type: 'price', precision: this.precision, minMove } });
    this._render();
    this.chart.timeScale().applyOptions({ timeVisible: this.intraday });
    this._legend({});
    for (const f of this.listeners.data) f();
  }

  // Older candles were added in front; keep the view where it is.
  prepend(bars) {
    this.bars = bars;
    this._render();
    for (const f of this.listeners.data) f();
  }

  _render() {
    const src = this.style === 'heikin' ? heikinAshi(this.bars) : this.bars;
    const single = this.style === 'line' || this.style === 'area';
    this.series.setData(src.map(b => single
      ? { time: this.toChart(b.time), value: b.close }
      : { time: this.toChart(b.time), open: b.open, high: b.high, low: b.low, close: b.close }));
    const up = css('--up-soft'), down = css('--down-soft');
    this.volume.setData(this.bars.map(b => ({
      time: this.toChart(b.time), value: b.volume, color: b.close >= b.open ? up : down,
    })));
  }

  // A live candle update (the datafeed already merged it into this.bars).
  update(bar) {
    const t = this.toChart(bar.time);
    if (this.style === 'heikin') {
      this._render();
    } else if (this.style === 'line' || this.style === 'area') {
      this.series.update({ time: t, value: bar.close });
    } else {
      this.series.update({ time: t, open: bar.open, high: bar.high, low: bar.low, close: bar.close });
    }
    this.volume.update({ time: t, value: bar.volume,
                         color: bar.close >= bar.open ? css('--up-soft') : css('--down-soft') });
    this.countdown.tick();
    this._legend(this.lastCrosshair || {});
    for (const f of this.listeners.data) f(bar);
  }

  setScaleMode(mode) {
    const m = { normal: PriceScaleMode.Normal, log: PriceScaleMode.Logarithmic,
                percent: PriceScaleMode.Percentage }[mode];
    this.chart.priceScale('right').applyOptions({ mode: m });
  }

  setAutoScale(on) { this.chart.priceScale('right').applyOptions({ autoScale: on }); }

  // Show the candles from utcFrom to now.
  showRange(utcFrom) {
    const ts = this.chart.timeScale();
    if (utcFrom === null) { ts.fitContent(); return; }
    const from = this.logicalOf(utcFrom);
    ts.setVisibleLogicalRange({ from, to: this.bars.length - 1 + 5 });
  }

  // ---- time <-> position helpers (UTC seconds, any time, even between
  // candles, before the first or after the last one) ----

  // Index of the last bar that opens at or before utc (-1 if none).
  barIndexAt(utc) {
    let lo = 0, hi = this.bars.length - 1, ans = -1;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      if (this.bars[mid].time <= utc) { ans = mid; lo = mid + 1; } else hi = mid - 1;
    }
    return ans;
  }

  logicalOf(utc) {
    const n = this.bars.length;
    if (!n) return 0;
    const step = tfSeconds(this.tf);
    if (utc <= this.bars[0].time) return (utc - this.bars[0].time) / step;
    if (utc >= this.bars[n - 1].time) return n - 1 + (utc - this.bars[n - 1].time) / step;
    const i = this.barIndexAt(utc);
    const a = this.bars[i].time, b = this.bars[i + 1].time;
    return i + (utc - a) / (b - a);
  }

  utcOfLogical(l) {
    const n = this.bars.length;
    if (!n) return 0;
    const step = tfSeconds(this.tf);
    if (l <= 0) return this.bars[0].time + l * step;
    if (l >= n - 1) return this.bars[n - 1].time + (l - (n - 1)) * step;
    const i = Math.floor(l), f = l - i;
    return this.bars[i].time + f * (this.bars[i + 1].time - this.bars[i].time);
  }

  timeToX(utc) { return this.chart.timeScale().logicalToCoordinate(this.logicalOf(utc)); }
  xToTime(x) {
    const l = this.chart.timeScale().coordinateToLogical(x);
    return l === null ? null : this.utcOfLogical(l);
  }
  priceToY(p) { return this.series.priceToCoordinate(p); }
  yToPrice(y) { return this.series.coordinateToPrice(y); }

  // ---- legend ----
  _legend(p) {
    this.lastCrosshair = p;
    const el = this.legendEl;
    if (!this.info) { el.innerHTML = ''; return; }
    let i = this.bars.length - 1;
    if (p.time !== undefined && p.logical !== undefined) {
      i = Math.max(0, Math.min(this.bars.length - 1, Math.round(p.logical)));
    }
    const b = this.bars[i], prev = this.bars[i - 1];
    if (!b) return;
    const pr = this.precision;
    const chg = prev ? b.close - prev.close : b.close - b.open;
    const base = prev ? prev.close : b.open;
    const cls = chg >= 0 ? 'up' : 'down';
    el.querySelector('.lg-title').textContent =
      `${this.info.description} · ${tfLabel(this.tf)} · ${this.info.exchangeName}`;
    el.querySelector('.lg-ohlc').innerHTML =
      `O<b class="${cls}">${fmtPrice(b.open, pr)}</b> H<b class="${cls}">${fmtPrice(b.high, pr)}</b> ` +
      `L<b class="${cls}">${fmtPrice(b.low, pr)}</b> C<b class="${cls}">${fmtPrice(b.close, pr)}</b> ` +
      `<b class="${cls}">${chg >= 0 ? '+' : ''}${fmtPrice(chg, pr)} (${fmtPct(base ? chg / base * 100 : 0)})</b>`;
    el.querySelector('.lg-vol').innerHTML = `Vol <b class="${cls}">${fmtVolume(b.volume)}</b>`;
  }
}
