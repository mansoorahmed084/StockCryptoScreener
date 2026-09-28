// Tiny DOM helpers.

const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
export const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ESC[c]);

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

// True when keys typed now belong to a text box, not to the chart.
export function typingInField(e) {
  const t = e.target;
  return t && (t.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(t.tagName));
}

// localStorage that never throws (private windows, blocked storage).
export const store = {
  get(key, fallback = null) {
    try {
      const v = localStorage.getItem(key);
      return v === null ? fallback : JSON.parse(v);
    } catch { return fallback; }
  },
  set(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* ignore */ }
  },
};

// A small popup menu under an anchor element. items: [{label, value, active}] or '-'.
export function popupMenu(anchor, items, onPick, { className = '' } = {}) {
  closeMenus();
  const menu = document.createElement('div');
  menu.className = `popup-menu ${className}`;
  for (const it of items) {
    if (it === '-') { menu.appendChild(Object.assign(document.createElement('hr'), {})); continue; }
    if (it.header) {
      const h = document.createElement('div');
      h.className = 'menu-header';
      h.textContent = it.header;
      menu.appendChild(h);
      continue;
    }
    const b = document.createElement('button');
    b.className = 'menu-item' + (it.active ? ' active' : '') + (it.danger ? ' danger' : '');
    b.innerHTML = it.html ?? esc(it.label);
    b.onclick = e => { e.stopPropagation(); closeMenus(); onPick(it.value, it); };
    menu.appendChild(b);
  }
  document.body.appendChild(menu);
  const r = anchor.getBoundingClientRect();
  const w = menu.offsetWidth, h = menu.offsetHeight;
  menu.style.left = Math.max(4, Math.min(r.left, innerWidth - w - 4)) + 'px';
  menu.style.top = (r.bottom + h + 4 > innerHeight ? Math.max(4, r.top - h - 4) : r.bottom + 4) + 'px';
  setTimeout(() => document.addEventListener('mousedown', outside), 0);
  function outside(e) { if (!menu.contains(e.target)) closeMenus(); }
  menu._cleanup = () => document.removeEventListener('mousedown', outside);
  return menu;
}

// Same, at a screen point (context menus).
export function contextMenu(x, y, items, onPick) {
  const anchor = { getBoundingClientRect: () => ({ left: x, right: x, top: y, bottom: y }) };
  return popupMenu(anchor, items, onPick, { className: 'context' });
}

export function closeMenus() {
  for (const m of document.querySelectorAll('.popup-menu')) { m._cleanup?.(); m.remove(); }
}

// Short message at the bottom of the screen.
export function toast(text, kind = 'info') {
  const el = document.createElement('div');
  el.className = `toast ${kind}`;
  el.textContent = text;
  document.body.appendChild(el);
  setTimeout(() => el.classList.add('show'), 10);
  setTimeout(() => { el.classList.remove('show'); setTimeout(() => el.remove(), 300); }, 3500);
}
