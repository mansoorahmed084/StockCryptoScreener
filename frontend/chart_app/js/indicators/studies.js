// The indicators on one chart: series, panes, recalculation on new data,
// legend rows (values under the cursor, hide / settings / remove).

import {
  BaselineSeries, HistogramSeries, LineSeries, createSeriesMarkers,
} from '../../vendor/lightweight-charts.standalone.production.mjs';
import { formDialog } from '../dialog.js';
import { esc, toast } from '../dom.js';
import { zoneOffset } from '../format.js';
import { AutoAnalysis } from './auto-analysis.js';
import { INDICATORS, defaultsOf, titleOf } from './registry.js';
import { VolumeProfile } from './volume-profile.js';

const LIVE_THROTTLE_MS = 400;
const SERVER_REFRESH_MS = 15_000;
let uidSeq = 0;

function fmtVal(v) {
  if (v === undefined || Number.isNaN(v)) return '—';
  const a = Math.abs(v);
  return v.toLocaleString('en-US', { maximumFractionDigits: a >= 1000 ? 2 : a >= 1 ? 3 : 6 });
}

function rgba(hex, a) {
  if (!/^#[0-9a-f]{6}$/i.test(hex)) return hex;
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${n >> 16}, ${(n >> 8) & 255}, ${n & 255}, ${a})`;
}

export class StudyManager {
  constructor(app, slot) {
    this.app = app;
    this.slot = slot;
    this.view = slot.view;
    this.chart = slot.view.chart;
    this.studies = [];
    this.legend = slot.el.querySelector('.legend-studies');
    this.listeners = { change: [] };
    this.view.on('data', bar => this._onData(bar));
    this.view.on('crosshair', p => this._legendValues(p));
    this.legend.addEventListener('click', e => this._legendClick(e));
  }

  on(ev, fn) { this.listeners[ev].push(fn); }
  _changed() { for (const f of this.listeners.change) f(); }

  // Saved form of the studies (for layouts / local storage).
  state() { return this.studies.map(s => ({ type: s.type, inputs: s.inputs, hidden: s.hidden })); }

  setState(list) {
    for (const s of [...this.studies]) this.remove(s.uid, { silent: true });
    for (const s of list || []) if (INDICATORS[s.type]) this.add(s.type, s.inputs, { hidden: s.hidden, silent: true });
    this._changed();
  }

  add(type, inputs, { hidden = false, silent = false } = {}) {
    const def = INDICATORS[type];
    const s = { uid: ++uidSeq, type, def, inputs: { ...defaultsOf(type), ...(inputs || {}) },
                hidden, series: {}, priceLines: [], result: null, pane: null };
    this.studies.push(s);
    if (def.custom === 'vprofile') s.custom = new VolumeProfile(this.view, s);
    if (def.custom === 'auto') s.custom = new AutoAnalysis(this.app, this.slot, s);
    this._compute(s);
    this._renderLegend();
    if (!silent) this._changed();
    return s;
  }

  remove(uid, { silent = false } = {}) {
    const s = this.studies.find(x => x.uid === uid);
    if (!s) return;
    this._dropSeries(s);
    s.custom?.destroy();
    this.studies = this.studies.filter(x => x !== s);
    this._renderLegend();
    if (!silent) this._changed();
  }

  _dropSeries(s) {
    const pane = s.pane;
    const paneIdx = s.paneIdx ? s.paneIdx() : 0;
    s.markers?.detach?.();
    s.markers = null;
    for (const series of Object.values(s.series)) this.chart.removeSeries(series);
    s.series = {};
    s.priceLines = [];
    if (pane !== null && pane !== 0) {
      // Drop the pane if nothing else lives in it.
      const panes = this.chart.panes();
      const p = panes.find(x => x.paneIndex() === paneIdx);
      if (p && !p.getSeries().length) this.chart.removePane(p.paneIndex());
    }
    s.pane = null;
  }

  async settings(s) {
    const out = await formDialog({ title: `${s.def.name} settings`, fields: s.def.inputs, values: s.inputs });
    if (!out) return;
    for (const inp of s.def.inputs) if (inp.type === 'select' && typeof inp.default === 'number') out[inp.key] = +out[inp.key];
    s.inputs = out;
    this._dropSeries(s);
    s.custom?.setInputs?.(out);
    this._compute(s);
    this._renderLegend();
    this._changed();
  }

  toggle(s) {
    s.hidden = !s.hidden;
    for (const series of Object.values(s.series)) series.applyOptions({ visible: !s.hidden });
    s.custom?.setVisible?.(!s.hidden);
    this._renderLegend();
    this._changed();
  }

  // ---- recalculation ----
  _onData(bar) {
    if (!bar) {                                  // new data or older candles
      for (const s of this.studies) this._compute(s);
      return;
    }
    // A live tick: recalculate at most every LIVE_THROTTLE_MS.
    if (!this.tickTimer) {
      this.tickTimer = setTimeout(() => {
        this.tickTimer = null;
        const n = this.view.bars.length;
        for (const s of this.studies) {
          if (s.def.custom) { s.custom?.onTick?.(); continue; }
          if (s.def.server) {
            const fresh = n !== s.barsAt || Date.now() - (s.at || 0) > SERVER_REFRESH_MS;
            if (fresh) this._compute(s);
          } else this._compute(s);
        }
      }, LIVE_THROTTLE_MS);
    }
  }

  async _compute(s) {
    if (s.def.custom) { s.custom.refresh(); return; }
    const bars = this.view.bars;
    if (!bars.length) return;
    s.barsAt = bars.length;
    s.at = Date.now();
    const seq = (s.seq = (s.seq || 0) + 1);
    let res;
    try {
      res = await s.def.compute(bars, s.inputs, { offset: zoneOffset(bars[bars.length - 1].time) });
    } catch (err) {
      if (seq === s.seq) toast(`${s.def.short}: ${err.message}`, 'error');
      return;
    }
    // A newer run started (new data, new settings) or the study was removed.
    if (seq !== s.seq || !this.studies.includes(s)) return;
    s.result = res;
    this._apply(s, bars);
  }

  _apply(s, bars) {
    const def = s.def, v = this.view;
    const times = bars.map(b => v.toChart(b.time));
    if (!Object.keys(s.series).length) this._makeSeries(s);
    for (const plot of def.plots) {
      const series = s.series[plot.key];
      const vals = s.result[plot.key];
      if (!series || !vals) continue;
      const data = [];
      for (let i = 0; i < vals.length; i++) {
        const val = vals[i];
        if (val === undefined || Number.isNaN(val) || val === null) continue;
        const pt = { time: times[i], value: val };
        if (plot.colorFn) pt.color = plot.colorFn(val, i ? vals[i - 1] : val);
        data.push(pt);
      }
      series.setData(data);
    }
    if (s.result.markers && def.plots.length) {
      const byPlot = {};
      for (const m of s.result.markers) {
        (byPlot[m.plot] ||= []).push({ time: v.toChart(m.time), position: m.position, shape: m.shape,
                                       color: m.color, text: m.text, size: m.size ?? 1 });
      }
      const target = s.series.wt2 || Object.values(s.series)[0];
      const list = (byPlot.wt2 || Object.values(byPlot).flat()).sort((a, b) => a.time - b.time);
      if (!s.markers) s.markers = createSeriesMarkers(target, list);
      else s.markers.setMarkers(list);
    }
    this._legendValues(v.lastCrosshair || {});
  }

  _makeSeries(s) {
    const def = s.def;
    const newPane = def.pane === 'new';
    const paneIndex = newPane ? this.chart.panes().length : 0;
    let first = null;
    for (const plot of def.plots) {
      const color = plot.colorKey ? s.inputs[plot.colorKey] : plot.color;
      const lineWidth = plot.width ?? (+s.inputs.width || 2);
      const common = { priceLineVisible: false, lastValueVisible: true, visible: !s.hidden,
                       crosshairMarkerVisible: false, title: '' };
      let series;
      if (plot.type === 'histogram') {
        series = this.chart.addSeries(HistogramSeries, { ...common, lastValueVisible: false }, paneIndex);
      } else if (plot.type === 'area') {
        const on = plot.hideKey ? s.inputs[plot.hideKey] !== false : true;
        series = this.chart.addSeries(BaselineSeries, {
          ...common, visible: !s.hidden && on, lastValueVisible: false, baseValue: { type: 'price', price: 0 },
          topLineColor: 'rgba(0,0,0,0)', bottomLineColor: 'rgba(0,0,0,0)',
          topFillColor1: rgba(plot.color, 0.35), topFillColor2: rgba(plot.color, 0.35),
          bottomFillColor1: rgba(plot.negColor, 0.35), bottomFillColor2: rgba(plot.negColor, 0.35),
        }, paneIndex);
      } else if (plot.area) {
        series = this.chart.addSeries(BaselineSeries, {
          ...common, lineWidth, baseValue: { type: 'price', price: 0 },
          topLineColor: color, bottomLineColor: color,
          topFillColor1: rgba(color, 0.5), topFillColor2: rgba(color, 0.15),
          bottomFillColor1: rgba(color, 0.15), bottomFillColor2: rgba(color, 0.5),
        }, paneIndex);
      } else {
        series = this.chart.addSeries(LineSeries, { ...common, color, lineWidth }, paneIndex);
      }
      s.series[plot.key] = series;
      first ||= series;
    }
    if (first && def.levels) {
      for (const lv of def.levels(s.inputs)) {
        s.priceLines.push(first.createPriceLine({ price: lv.value, color: lv.color, lineWidth: 1,
                                                  lineStyle: 2, axisLabelVisible: false }));
      }
    }
    if (first && newPane) {
      const pane = first.getPane();
      pane.setStretchFactor(0.3);
      s.pane = pane;
      s.paneIdx = () => first.getPane().paneIndex();
    } else {
      s.pane = 0;
      s.paneIdx = () => 0;
    }
  }

  // ---- legend ----
  _renderLegend() {
    this.legend.innerHTML = this.studies.map(s => `
      <div class="study${s.hidden ? ' hidden-study' : ''}" data-uid="${s.uid}">
        <span class="st-name">${esc(titleOf(s))}</span>
        <span class="st-vals"></span>
        <span class="st-btns">
          ${s.def.custom === 'auto' ? '<button data-a="copy" title="Copy to my drawings">⧉</button>' : ''}
          <button data-a="hide" title="${s.hidden ? 'Show' : 'Hide'}">${s.hidden ? '◌' : '👁'}</button>
          <button data-a="settings" title="Settings">⚙</button>
          <button data-a="remove" title="Remove">✕</button>
        </span>
      </div>`).join('');
    this._legendValues(this.view.lastCrosshair || {});
  }

  _legendClick(e) {
    const b = e.target.closest('button[data-a]');
    const row = e.target.closest('.study');
    if (!row) return;
    const s = this.studies.find(x => x.uid === +row.dataset.uid);
    if (!s) return;
    if (!b) { this.settings(s); return; }
    if (b.dataset.a === 'hide') this.toggle(s);
    else if (b.dataset.a === 'settings') this.settings(s);
    else if (b.dataset.a === 'remove') this.remove(s.uid);
    else if (b.dataset.a === 'copy') s.custom?.copyToDrawings();
  }

  _legendValues(p) {
    const n = this.view.bars.length;
    const i = p && p.logical !== undefined && p.time !== undefined
      ? Math.max(0, Math.min(n - 1, Math.round(p.logical))) : n - 1;
    for (const s of this.studies) {
      const el = this.legend.querySelector(`.study[data-uid="${s.uid}"] .st-vals`);
      if (!el || !s.result) continue;
      el.innerHTML = s.def.plots.filter(pl => s.result[pl.key]).map(pl => {
        const val = s.result[pl.key][i];
        const color = pl.colorFn ? pl.colorFn(val, s.result[pl.key][i - 1] ?? val)
          : pl.colorKey ? s.inputs[pl.colorKey] : pl.color;
        return `<b style="color:${esc(color)}">${fmtVal(val)}</b>`;
      }).join(' ');
    }
  }
}
