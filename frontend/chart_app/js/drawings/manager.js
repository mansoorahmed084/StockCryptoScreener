// Drawings of one chart slot: load/save, mouse (create, select, move),
// magnet, undo/redo, context menu. Painting is in primitive.js.

import { api } from '../api.js';
import { formDialog, promptDialog } from '../dialog.js';
import { contextMenu, store, toast } from '../dom.js';
import { DrawingsPrimitive } from './primitive.js';
import { nearPoint } from './geometry.js';
import { FIB_LEVELS, TOOLS, handlesOf, moveHandle } from './tools.js';

const DRAG_START = 4;          // px of movement before a press becomes a drag
const MAGNET_PX = 18;          // weak magnet reach

const clone = o => JSON.parse(JSON.stringify(o, (k, v) => (k.startsWith('_') ? undefined : v)));
const newId = () => (crypto.randomUUID ? crypto.randomUUID()
  : Date.now().toString(36) + Math.random().toString(36).slice(2));

export function toolDefaults(toolId) {
  const saved = store.get('cw.draw.defaults', {})[toolId] || {};
  return { ...clone(TOOLS[toolId].defaults), ...saved };
}

export function rememberDefaults(toolId, style) {
  const all = store.get('cw.draw.defaults', {});
  const { levels, ...rest } = style;          // fib levels stay per drawing
  all[toolId] = rest;
  store.set('cw.draw.defaults', all);
}

export class DrawingManager {
  constructor(app, slot) {
    this.app = app;
    this.slot = slot;
    this.view = slot.view;
    this.host = slot.host;
    this.key = null;
    this.drawings = [];
    this.selected = null;
    this.hovered = null;
    this.creating = null;
    this.measure = null;
    this.undoStack = [];
    this.redoStack = [];
    this.saveTimers = new Map();
    this.listeners = { select: [], change: [] };
    this.menuExtras = [];            // (drawing) => [menu items] (alerts add theirs)

    this.prim = new DrawingsPrimitive(this);
    this.view.onSeries(series => {
      if (this.series) { try { this.series.detachPrimitive(this.prim); } catch { /* removed */ } }
      this.series = series;
      series.attachPrimitive(this.prim);
    });
    this.view.on('data', () => this.update());

    this.host.addEventListener('mousedown', e => this._down(e), true);
    this.host.addEventListener('dblclick', e => this._dbl(e), true);
    this.host.addEventListener('contextmenu', e => this._context(e), true);
    this.host.addEventListener('mousemove', e => this._hover(e));
    window.addEventListener('mousemove', e => this._move(e));
    window.addEventListener('mouseup', e => this._up(e));
  }

  on(ev, fn) { this.listeners[ev].push(fn); }
  _emit(ev, ...a) { for (const f of this.listeners[ev]) f(...a); }

  update() { this.prim.update(); }

  // ---- loading and saving ----
  async load(key) {
    if (key === this.key) return;
    this.key = key;
    this.drawings = [];
    this.undoStack = [];
    this.redoStack = [];
    this.creating = null;
    this.measure = null;
    this.select(null);
    try {
      const { drawings } = await api.get('/api/chart/drawings', { key });
      if (key !== this.key) return;
      this.drawings = drawings;
    } catch (err) {
      toast(`Drawings could not load: ${err.message}`, 'error');
    }
    this.update();
    this._emit('change');
  }

  _save(d) {
    clearTimeout(this.saveTimers.get(d.id));
    this.saveTimers.set(d.id, setTimeout(async () => {
      this.saveTimers.delete(d.id);
      try {
        await api.put(`/api/chart/drawings/${encodeURIComponent(d.id)}`, clone(d));
        this.app.emit('drawings', this);
      } catch (err) {
        toast(`Drawing not saved: ${err.message}`, 'error');
      }
    }, 250));
  }

  async _delete(id) {
    clearTimeout(this.saveTimers.get(id));
    try {
      await api.del(`/api/chart/drawings/${encodeURIComponent(id)}`);
      this.app.emit('drawings', this);
    } catch (err) {
      toast(`Drawing not deleted: ${err.message}`, 'error');
    }
  }

  // Another chart with the same symbol changed its drawings.
  syncFrom(other) {
    if (other === this || other.key !== this.key) return;
    this.drawings = clone(other.drawings);
    if (!this.drawings.some(d => d.id === this.selected)) this.select(null);
    this.update();
  }

  // ---- undo / redo ----
  checkpoint() {
    this.undoStack.push(clone(this.drawings));
    if (this.undoStack.length > 100) this.undoStack.shift();
    this.redoStack = [];
  }

  undo() { this._restore(this.undoStack, this.redoStack); }
  redo() { this._restore(this.redoStack, this.undoStack); }

  _restore(from, to) {
    if (!from.length) return;
    to.push(clone(this.drawings));
    const target = from.pop();
    const now = new Map(this.drawings.map(d => [d.id, JSON.stringify(clone(d))]));
    const next = new Set(target.map(d => d.id));
    for (const id of now.keys()) if (!next.has(id)) this._delete(id);
    for (const d of target) if (now.get(d.id) !== JSON.stringify(d)) this._save(d);
    this.drawings = target;
    if (!next.has(this.selected)) this.select(null);
    this.update();
    this._emit('change');
  }

  // ---- queries ----
  visible() {
    return this.app.drawHidden ? [] : this.drawings.filter(d => !d.hidden);
  }

  selectedDrawing() { return this.drawings.find(d => d.id === this.selected) || null; }

  select(id) {
    if (id === this.selected) return;
    this.selected = id;
    this.update();
    this._emit('select', this.selectedDrawing());
  }

  env(size) {
    const v = this.view;
    const ff = getComputedStyle(document.documentElement).getPropertyValue('--font').trim() || 'sans-serif';
    const s = size || this.paneSize();
    return {
      width: s.width, height: s.height, fontFamily: ff, font: `12px ${ff}`,
      fmt: p => v.fmt(p), y: p => v.priceToY(p), x: t => v.timeToX(t),
      price: y => v.yToPrice(y), timeAt: x => this.snapTime(x),
      bar: v.chart.timeScale().options().barSpacing,
    };
  }

  paneSize() {
    const s = this.view.chart.paneSize(0);
    return { width: s.width, height: s.height };
  }

  pixels(d) {
    const v = this.view;
    const P = [];
    for (const pt of d.points) {
      const x = v.timeToX(pt.t), y = v.priceToY(pt.p);
      if (x === null || y === null) return null;
      P.push({ x, y });
    }
    return P;
  }

  // The drawing (and handle) under a pane point, top-most first.
  hitTest(x, y) {
    if (this.app.drawHidden || !this.view.bars.length) return null;
    const env = this.env();
    const list = this.visible();
    const sel = this.selectedDrawing();
    if (sel && !sel.hidden) {
      const P = this.pixels(sel);
      if (P) {
        const hs = handlesOf(TOOLS[sel.tool], sel, P);
        const i = hs.findIndex(h => nearPoint(x, y, h));
        if (i >= 0) return { d: sel, handle: hs[i].i ?? i };
      }
    }
    for (let k = list.length - 1; k >= 0; k--) {
      const d = list[k];
      const tool = TOOLS[d.tool];
      const P = tool && this.pixels(d);
      if (P && tool.hit(d, P, x, y, env)) return { d, handle: null };
    }
    return null;
  }

  // ---- mouse -> (time, price) ----
  _local(e) {
    const r = this.host.getBoundingClientRect();
    return { x: e.clientX - r.left, y: e.clientY - r.top };
  }

  _inPane(pos) {
    const s = this.paneSize();
    return pos.x >= 0 && pos.y >= 0 && pos.x <= s.width && pos.y <= s.height;
  }

  // Time at x, on a candle (or where one would be, past the last candle).
  snapTime(x) {
    const l = this.view.chart.timeScale().coordinateToLogical(x);
    return this.view.utcOfLogical(Math.round(l ?? 0));
  }

  point(pos, e) {
    const v = this.view;
    const l = Math.round(v.chart.timeScale().coordinateToLogical(pos.x) ?? 0);
    const t = v.utcOfLogical(l);
    let p = v.yToPrice(pos.y);
    let mode = this.app.magnet;
    if (e?.ctrlKey || e?.metaKey) mode = mode === 'off' ? 'weak' : 'off';
    const bar = v.bars[l];
    if (bar && mode !== 'off') {
      let best = null, dist = Infinity;
      for (const val of [bar.open, bar.high, bar.low, bar.close]) {
        const dy = Math.abs(v.priceToY(val) - pos.y);
        if (dy < dist) { dist = dy; best = val; }
      }
      if (mode === 'strong' || dist <= MAGNET_PX) p = best;
    }
    return { t, p };
  }

  // ---- create ----
  _startCreate(toolId, pt, pos) {
    const tool = TOOLS[toolId];
    const d = {
      id: newId(), key: this.key, tool: toolId, text: '', locked: false, hidden: false,
      style: toolDefaults(toolId),
      points: tool.init ? tool.init(pt, this.env()) : Array.from({ length: tool.clicks }, () => ({ ...pt })),
    };
    if (tool.clicks <= 1) { this._finish(d); return; }
    this.creating = d;
    this.step = 1;
    this.downPos = pos;
    this.update();
  }

  async _finish(d) {
    this.creating = null;
    const tool = TOOLS[d.tool];
    if (tool.needsText) {
      const text = await promptDialog({ title: 'Text', label: 'Text (Ctrl+Enter for OK)', multiline: true });
      if (!text) { this.update(); this._doneTool(); return; }
      d.text = text;
    }
    d.created_ms = Date.now();
    this.checkpoint();
    this.drawings.push(d);
    this._save(d);
    this.select(d.id);
    this._emit('change');
    this._doneTool();
  }

  _doneTool() {
    if (!this.app.stayInDrawMode) this.app.setTool('cursor');
  }

  cancelCreate() {
    if (!this.creating) return false;
    this.creating = null;
    this.update();
    return true;
  }

  cancel() {
    if (this.cancelCreate()) return true;
    if (this.measure) { this.measure = null; this.update(); return true; }
    return false;
  }

  // ---- mouse handlers ----
  _down(e) {
    if (e.button !== 0) return;
    const pos = this._local(e);
    if (!this._inPane(pos) || !this.view.bars.length) return;
    const tool = this.app.tool;
    const pt = this.point(pos, e);

    if (this.measure?.active) {               // second click ends a measure
      e.stopPropagation();
      this.measure.active = false;
      this.update();
      return;
    }
    if (this.measure) { this.measure = null; this.update(); }

    if (tool === 'measure' || (tool === 'cursor' && e.shiftKey)) {
      e.stopPropagation();
      this.measure = { points: [pt, { ...pt }], active: true };
      this.downPos = pos;
      if (tool === 'measure') this._doneTool();
      return;
    }

    if (tool !== 'cursor' && TOOLS[tool]) {
      e.stopPropagation();
      e.preventDefault();
      if (this.creating) { this._advance(pt); return; }
      this._startCreate(tool, pt, pos);
      return;
    }

    const hit = this.hitTest(pos.x, pos.y);
    if (hit) {
      e.stopPropagation();
      e.preventDefault();
      this.select(hit.d.id);
      if (!hit.d.locked && !this.app.drawLocked) {
        this.drag = { d: hit.d, handle: hit.handle, pos, orig: clone(hit.d.points), moved: false,
                      logical: this.view.chart.timeScale().coordinateToLogical(pos.x) };
      }
    } else if (this.selected) {
      this.select(null);
    }
  }

  _advance(pt) {
    const d = this.creating;
    const tool = TOOLS[d.tool];
    this.step += 1;
    if (this.step >= tool.clicks) { this._finish(d); return; }
    for (let i = this.step; i < d.points.length; i++) d.points[i] = { ...pt };
    this.update();
  }

  _move(e) {
    if (this.creating) {
      const pt = this.point(this._local(e), e);
      for (let i = this.step; i < this.creating.points.length; i++) this.creating.points[i] = { ...pt };
      this.update();
    } else if (this.measure?.active) {
      this.measure.points[1] = this.point(this._local(e), null);
      this.update();
    } else if (this.drag) {
      const pos = this._local(e);
      const dg = this.drag;
      if (!dg.moved) {
        if (Math.hypot(pos.x - dg.pos.x, pos.y - dg.pos.y) < DRAG_START) return;
        dg.moved = true;
        this.checkpoint();
      }
      const d = dg.d;
      const tool = TOOLS[d.tool];
      if (dg.handle !== null) {
        moveHandle(tool, d, dg.handle, this.point(pos, e));
      } else {
        const v = this.view;
        const l = v.chart.timeScale().coordinateToLogical(pos.x) ?? dg.logical;
        const dl = tool.moveBody === 'price' ? 0 : Math.round(l - dg.logical);
        const dy = tool.moveBody === 'time' ? 0 : pos.y - dg.pos.y;
        d.points = dg.orig.map(o => {
          const y = v.priceToY(o.p);
          return { t: dl ? v.utcOfLogical(v.logicalOf(o.t) + dl) : o.t,
                   p: dy && y !== null ? v.yToPrice(y + dy) : o.p };
        });
      }
      this.update();
    }
  }

  _up(e) {
    if (this.creating && this.downPos) {
      const pos = this._local(e);
      // Pressed, dragged and let go: that places the next point.
      if (Math.hypot(pos.x - this.downPos.x, pos.y - this.downPos.y) > DRAG_START) {
        this.downPos = null;
        this._advance(this.point(pos, e));
      } else {
        this.downPos = null;
      }
    } else if (this.measure?.active && this.downPos) {
      const pos = this._local(e);
      if (Math.hypot(pos.x - this.downPos.x, pos.y - this.downPos.y) > DRAG_START) this.measure.active = false;
      this.downPos = null;
      this.update();
    } else if (this.drag) {
      const dg = this.drag;
      this.drag = null;
      if (dg.moved) { this._save(dg.d); this._emit('change'); this.update(); }
    }
  }

  _hover(e) {
    if (this.drag || this.creating) return;
    const pos = this._local(e);
    const hit = this._inPane(pos) ? this.hitTest(pos.x, pos.y) : null;
    const id = hit ? hit.d.id : null;
    if (id !== this.hovered) { this.hovered = id; this.update(); }
  }

  _dbl(e) {
    const pos = this._local(e);
    const hit = this._inPane(pos) ? this.hitTest(pos.x, pos.y) : null;
    if (!hit) return;
    e.stopPropagation();
    if (hit.d.tool === 'text') this.editText(hit.d);
    else this.settings(hit.d);
  }

  _context(e) {
    const pos = this._local(e);
    const hit = this._inPane(pos) ? this.hitTest(pos.x, pos.y) : null;
    if (!hit) return;
    e.preventDefault();
    e.stopPropagation();
    const d = hit.d;
    this.select(d.id);
    const extras = this.menuExtras.flatMap(f => f(d) || []);
    contextMenu(e.clientX, e.clientY, [
      { header: TOOLS[d.tool].label },
      ...extras, ...(extras.length ? ['-'] : []),
      { label: 'Settings…', value: 'settings' },
      ...(['text', 'hline', 'rect'].includes(d.tool) ? [{ label: 'Edit text…', value: 'text' }] : []),
      { label: 'Clone', value: 'clone' },
      { label: d.locked ? 'Unlock' : 'Lock', value: 'lock' },
      { label: 'Hide', value: 'hide' },
      { label: 'Bring to front', value: 'front' },
      { label: 'Send to back', value: 'back' },
      '-', { label: 'Remove', value: 'remove', danger: true },
    ], (v, item) => (item.run ? item.run(d) : this.action(v, d)));
  }

  // ---- actions (menu, floating toolbar, keys) ----
  action(v, d = this.selectedDrawing()) {
    if (!d) return;
    if (v === 'settings') this.settings(d);
    else if (v === 'text') this.editText(d);
    else if (v === 'clone') this.cloneDrawing(d);
    else if (v === 'lock') this.patch(d, { locked: !d.locked });
    else if (v === 'hide') { this.patch(d, { hidden: true }); this.select(null); }
    else if (v === 'front' || v === 'back') {
      this.checkpoint();
      this.drawings = this.drawings.filter(x => x !== d);
      if (v === 'front') this.drawings.push(d); else this.drawings.unshift(d);
      d.created_ms = v === 'front' ? Date.now() : Math.min(...this.drawings.map(x => x.created_ms || 0)) - 1;
      this._save(d);
      this.update();
    } else if (v === 'remove') this.remove(d);
  }

  patch(d, fields, { styleOnly = false } = {}) {
    this.checkpoint();
    if (styleOnly) d.style = { ...d.style, ...fields };
    else Object.assign(d, fields);
    if (styleOnly) rememberDefaults(d.tool, d.style);
    this._save(d);
    this.update();
    this._emit('select', this.selectedDrawing());
  }

  remove(d = this.selectedDrawing()) {
    if (!d) return;
    this.checkpoint();
    this.drawings = this.drawings.filter(x => x !== d);
    if (this.selected === d.id) this.select(null);
    this._delete(d.id);
    this.update();
    this._emit('change');
  }

  async removeAll() {
    if (!this.drawings.length) return;
    this.checkpoint();
    this.drawings = [];
    this.select(null);
    try {
      await api.del('/api/chart/drawings', { key: this.key });
      this.app.emit('drawings', this);
    } catch (err) { toast(err.message, 'error'); }
    this.update();
    this._emit('change');
  }

  showAll() {
    const hidden = this.drawings.filter(d => d.hidden);
    if (!hidden.length) return 0;
    this.checkpoint();
    for (const d of hidden) { d.hidden = false; this._save(d); }
    this.update();
    return hidden.length;
  }

  cloneDrawing(d) {
    const v = this.view;
    const c = { ...clone(d), id: newId(), created_ms: Date.now(), locked: false };
    // A little to the right and down, so the copy is visible.
    c.points = c.points.map(p => {
      const y = v.priceToY(p.p);
      return { t: v.utcOfLogical(v.logicalOf(p.t) + 3), p: y === null ? p.p : v.yToPrice(y + 12) };
    });
    this.checkpoint();
    this.drawings.push(c);
    this._save(c);
    this.select(c.id);
    this.update();
  }

  async editText(d) {
    const text = await promptDialog({ title: 'Text', label: 'Text (Ctrl+Enter for OK)', value: d.text, multiline: true });
    if (text !== null) this.patch(d, { text });
  }

  async settings(d) {
    const tool = TOOLS[d.tool];
    const values = { ...d.style, text: d.text };
    const fields = [...tool.fields];
    if (d.tool === 'fib') (d.style.levels || FIB_LEVELS).forEach((l, i) => { values[`lv${i}`] = l.on; });
    if (['hline', 'rect', 'text'].includes(d.tool)) fields.push({ key: 'text', label: 'Text', type: d.tool === 'text' ? 'textarea' : 'text' });
    const out = await formDialog({ title: `${tool.label} settings`, fields, values });
    if (!out) return;
    const { text, ...style } = out;
    for (const k of Object.keys(style)) if (/^lv\d+$/.test(k)) delete style[k];
    if (d.tool === 'fib') {
      style.levels = (d.style.levels || FIB_LEVELS).map((l, i) => ({ ...l, on: !!out[`lv${i}`] }));
    }
    for (const f of tool.fields) if (f.type === 'select' && typeof tool.defaults[f.key] === 'number') style[f.key] = +style[f.key];
    this.checkpoint();
    d.style = { ...d.style, ...style };
    if (text !== undefined) d.text = text;
    rememberDefaults(d.tool, d.style);
    this._save(d);
    this.update();
    this._emit('select', d);
  }

  // Keys while this chart is the active one. True = handled.
  onKey(e) {
    const k = e.key;
    if (k === 'Escape') {
      const did = this.cancel();
      if (this.app.tool !== 'cursor') { this.app.setTool('cursor'); return true; }
      if (!did && this.selected) this.select(null);
      return did || true;
    }
    if ((k === 'Delete' || k === 'Backspace') && this.selected) { this.remove(); return true; }
    if ((e.ctrlKey || e.metaKey) && k.toLowerCase() === 'z' && !e.shiftKey) { this.undo(); return true; }
    if ((e.ctrlKey || e.metaKey) && (k.toLowerCase() === 'y' || (k.toLowerCase() === 'z' && e.shiftKey))) {
      this.redo();
      return true;
    }
    return false;
  }
}
