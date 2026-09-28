// Alerts from the chart: the 🔔 button (Alt+A), "Add alert" on drawings,
// alert lines on the chart, and a check every minute while the page is open.
// Alerts live in the screener's alert store, so the Alerts page, the watcher
// and Telegram see them too.

import { api } from './api.js';
import { formDialog } from './dialog.js';
import { $, esc, popupMenu, toast } from './dom.js';
import { label } from './drawings/geometry.js';
import { ICONS } from './icons.js';

const CHECK_MS = 60_000;
const ACTIVE_COLOR = '#ff9800';
const FIRED_COLOR = '#787b86';
const CLOSE_TFS = [['1m', '1m'], ['5m', '5m'], ['15m', '15m'], ['1h', '1h'], ['4h', '4h'], ['1d', '1D']];
const PRICE_CONDS = [['above', 'Goes above'], ['below', 'Goes below'], ['touch', 'Touches'],
                     ['close_above', 'Closes above'], ['close_below', 'Closes below']];
const LINE_CONDS = [['touch', 'Touches the line'], ['break_up', 'Closes above the line'],
                    ['break_down', 'Closes below the line']];
const LINE_TOOLS = ['trendline', 'ray', 'extline'];

// Paints the alerts of one chart.
class AlertLayer {
  constructor(slot) {
    this.slot = slot;
    this.view = slot.view;
    this.alerts = [];
    this.supported = false;
    this.views = [{ zOrder: () => 'top', renderer: () => ({ draw: t => this._draw(t) }) }];
    this.axis = [];
    this.view.onSeries(series => {
      if (this.series) { try { this.series.detachPrimitive(this); } catch { /* gone */ } }
      this.series = series;
      series.attachPrimitive(this);
    });
  }

  attached({ requestUpdate }) { this.requestUpdate = requestUpdate; }
  detached() { this.requestUpdate = null; }
  paneViews() { return this.views; }
  priceAxisViews() { return this.axis; }

  updateAllViews() {
    const v = this.view;
    this.axis = this.alerts.filter(a => a.status === 'active').map(a => {
      const p = target(a);
      const y = v.priceToY(p);
      return { coordinate: () => y ?? -100, text: () => `🔔 ${v.fmt(p)}`, textColor: () => '#000',
               backColor: () => ACTIVE_COLOR, visible: () => y !== null, tickVisible: () => true };
    });
  }

  set(list, supported) {
    this.alerts = list;
    this.supported = supported;
    this.requestUpdate?.();
  }

  _draw(t) {
    const v = this.view;
    const font = `11px ${getComputedStyle(document.documentElement).getPropertyValue('--font')}`;
    t.useMediaCoordinateSpace(({ context: ctx, mediaSize: size }) => {
      ctx.setLineDash([4, 4]);
      ctx.lineWidth = 1;
      for (const a of this.alerts) {
        const color = a.status === 'active' ? ACTIVE_COLOR : FIRED_COLOR;
        ctx.strokeStyle = color;
        const text = `🔔 ${condText(a)}${a.status === 'active' ? '' : ' · fired'}`;
        if (a.kind === 'price') {
          const y = v.priceToY(a.level);
          if (y === null) continue;
          line(ctx, 0, y, size.width, y);
          label(ctx, text, 6, y - 8, { color, font });
        } else if (a.kind === 'zone') {
          for (const p of [a.low, a.high]) {
            const y = v.priceToY(p);
            if (y !== null) line(ctx, 0, y, size.width, y);
          }
          const y = v.priceToY(a.high);
          if (y !== null) label(ctx, text, 6, y - 8, { color, font });
        } else if (a.kind === 'line') {
          const x1 = v.timeToX(a.t1 / 1000), x2 = v.timeToX(a.t2 / 1000);
          const y1 = v.priceToY(a.p1), y2 = v.priceToY(a.p2);
          if ([x1, x2, y1, y2].some(n => n === null) || x1 === x2) continue;
          const slope = (y2 - y1) / (x2 - x1);
          const x0 = Math.min(x1, x2);
          line(ctx, x0, y1 + slope * (x0 - x1), size.width, y1 + slope * (size.width - x1));
          label(ctx, text, x0 + 4, y1 + slope * (x0 - x1) - 10, { color, font });
        }
      }
      ctx.setLineDash([]);
    });
  }
}

function line(ctx, x0, y0, x1, y1) {
  ctx.beginPath(); ctx.moveTo(x0, y0); ctx.lineTo(x1, y1); ctx.stroke();
}

function target(a) {
  if (a.kind === 'price') return a.level;
  if (a.kind === 'zone') return (a.low + a.high) / 2;
  const now = Date.now();
  return a.p1 + (a.p2 - a.p1) * (now - a.t1) / (a.t2 - a.t1);
}

function condText(a) {
  const all = Object.fromEntries([...PRICE_CONDS, ...LINE_CONDS, ['enter', 'Enters the zone']]);
  const tf = a.condition.startsWith('close') || a.condition.startsWith('break') ? ` (${a.timeframe} close)` : '';
  return `${all[a.condition] || a.condition}${tf}`;
}

export function initAlerts(app) {
  const layers = new Map();

  async function refresh(slot) {
    const layer = layers.get(slot);
    if (!layer || !slot.info) return;
    try {
      const res = await api.get('/api/chart/alerts', { symbol: slot.info.symbol });
      layer.set(res.alerts, res.supported);
    } catch { layer.set([], false); }
  }
  const refreshAll = () => { for (const s of app.slots) refresh(s); };

  app.on('slot', slot => {
    const layer = new AlertLayer(slot);
    layers.set(slot, layer);
    slot.on('loaded', () => refresh(slot));
    // "Add alert" on drawings: context menu and floating toolbar.
    const run = d => fromDrawing(slot, d);
    slot.drawings.menuExtras.push(d => (canAlert(d) ? [{ label: '🔔 Add alert…', value: 'alert', run }] : []));
    slot.drawToolbar.extras.push(d => (canAlert(d) ? [{ id: 'alert', icon: ICONS.alert, title: 'Add alert', run }] : []));
  });

  const canAlert = d => ['hline', 'hray', 'rect', 'long', 'short', ...LINE_TOOLS].includes(d.tool);

  async function create(slot, body) {
    try {
      await api.post('/api/chart/alerts', { symbol: slot.info.symbol, ...body });
      toast('Alert set — the Alerts page, watcher and Telegram see it too', 'ok');
      refreshAll();
    } catch (err) { toast(`Alert not set: ${err.message}`, 'error'); }
  }

  const lastPrice = slot => slot.view.bars[slot.view.bars.length - 1]?.close;

  async function priceDialog(slot, level, title = 'Price alert') {
    const now = lastPrice(slot);
    const out = await formDialog({
      title: `${title} · ${slot.info.ticker}`, ok: 'Create',
      values: { condition: level >= now ? 'above' : 'below', level: +slot.view.fmt(level).replace(/,/g, ''),
                timeframe: '15m', note: '' },
      fields: [
        { key: 'condition', label: 'When price', type: 'select', options: PRICE_CONDS },
        { key: 'level', label: `Price (now ${slot.view.fmt(now)})`, type: 'number' },
        { key: 'timeframe', label: 'Candle for "closes" alerts', type: 'select', options: CLOSE_TFS },
        { key: 'note', label: 'Note (optional)', type: 'text' },
      ],
    });
    if (out) await create(slot, { kind: 'price', condition: out.condition, level: +out.level, timeframe: out.timeframe, note: out.note });
  }

  async function fromDrawing(slot, d) {
    const layer = layers.get(slot);
    if (layer && !layer.supported) { toast('Alerts work on Binance perpetuals, BTC.D and USDT spot pairs for now', 'error'); return; }
    const pts = d.points;
    if (d.tool === 'hline' || d.tool === 'hray') return priceDialog(slot, pts[0].p, 'Alert on the line');
    if (LINE_TOOLS.includes(d.tool)) {
      const out = await formDialog({
        title: `Trendline alert · ${slot.info.ticker}`, ok: 'Create',
        values: { condition: 'break_up', timeframe: '15m', note: d.text || '' },
        fields: [
          { key: 'condition', label: 'When price', type: 'select', options: LINE_CONDS },
          { key: 'timeframe', label: 'Candle for "closes" alerts', type: 'select', options: CLOSE_TFS },
          { key: 'note', label: 'Note (optional)', type: 'text' },
        ],
      });
      if (out) {
        await create(slot, { kind: 'line', condition: out.condition, timeframe: out.timeframe, note: out.note,
                             t1: pts[0].t, p1: pts[0].p, t2: pts[1].t, p2: pts[1].p });
      }
      return;
    }
    if (d.tool === 'rect') {
      const out = await formDialog({
        title: `Zone alert · ${slot.info.ticker}`, ok: 'Create', values: { note: d.text || '' },
        fields: [{ key: 'note', label: 'Fires when price trades inside the zone. Note (optional)', type: 'text' }],
      });
      if (out) {
        await create(slot, { kind: 'zone', condition: 'enter', note: out.note,
                             low: Math.min(pts[0].p, pts[1].p), high: Math.max(pts[0].p, pts[1].p) });
      }
      return;
    }
    if (d.tool === 'long' || d.tool === 'short') {
      const long = d.tool === 'long';
      const [, tp, sl] = pts;
      await create(slot, { kind: 'price', condition: long ? 'above' : 'below', level: tp.p, note: 'target' });
      await create(slot, { kind: 'price', condition: long ? 'below' : 'above', level: sl.p, note: 'stop' });
    }
  }

  // ---- top bar button ----
  const btn = document.createElement('button');
  btn.className = 'tb-btn';
  btn.title = 'Alerts (Alt+A)';
  btn.innerHTML = `${ICONS.alert}<span>Alert</span>`;
  $('#tb-extra').appendChild(btn);
  btn.onclick = () => {
    const slot = app.slot, layer = layers.get(slot);
    if (!slot?.info) return;
    if (!layer?.supported) { toast('Alerts work on Binance perpetuals, BTC.D and USDT spot pairs for now', 'error'); return; }
    const items = [{ label: `Create alert at ${slot.view.fmt(lastPrice(slot))}…`, value: ['new'] }];
    const mine = layer.alerts;
    if (mine.length) items.push('-', { header: `${slot.info.ticker} alerts` });
    for (const a of mine) {
      items.push({ html: `<span style="color:${a.status === 'active' ? ACTIVE_COLOR : FIRED_COLOR}">●</span> ${esc(a.text)}<span class="kbd">✕ remove</span>`,
                   value: ['del', a.id] });
    }
    items.push('-', { label: 'All alerts (Alerts page in the screener)…', value: ['page'] });
    popupMenu(btn, items, async ([act, id]) => {
      if (act === 'new') priceDialog(slot, lastPrice(slot));
      else if (act === 'del') {
        try { await api.del(`/api/chart/alerts/${id}`); toast('Alert removed'); refreshAll(); } catch (err) { toast(err.message, 'error'); }
      } else if (act === 'page') {
        window.open(`${location.protocol}//${location.hostname}:8501/Alerts`, '_blank');
      }
    });
  };

  app.on('keydown', e => {
    if (e.altKey && e.key.toLowerCase() === 'a') { btn.click(); return true; }
    return false;
  });

  // ---- check alerts while the page is open ----
  setInterval(async () => {
    if (document.hidden) return;
    try {
      const { fired } = await api.post('/api/chart/alerts/check', {});
      for (const a of fired) toast(`🔔 ${a.text} — hit ${a.trigger_price}`, 'ok');
      if (fired.length) refreshAll();
    } catch { /* the watcher still checks */ }
  }, CHECK_MS);
  setInterval(refreshAll, CHECK_MS * 2);
}
