// Small modal dialogs: prompt, confirm, and a form builder used by settings.

import { $, esc } from './dom.js';

const root = () => $('#dialog');

function show(html, { onOpen, onKey } = {}) {
  const el = root();
  el.innerHTML = `<div class="modal-card small" role="dialog">${html}</div>`;
  el.hidden = false;
  return new Promise(resolve => {
    const done = value => {
      el.hidden = true;
      el.innerHTML = '';
      document.removeEventListener('keydown', key, true);
      resolve(value);
    };
    const key = e => {
      if (e.key === 'Escape') { e.stopPropagation(); done(null); }
      else if (onKey) onKey(e, done);
    };
    document.addEventListener('keydown', key, true);
    el.onmousedown = e => { if (e.target === el) done(null); };
    el.querySelectorAll('[data-close]').forEach(b => { b.onclick = () => done(null); });
    onOpen?.(el, done);
  });
}

export function promptDialog({ title, label = '', value = '', ok = 'OK', multiline = false, placeholder = '' }) {
  const field = multiline
    ? `<textarea class="inp" placeholder="${esc(placeholder)}">${esc(value)}</textarea>`
    : `<input class="inp" value="${esc(value)}" placeholder="${esc(placeholder)}" spellcheck="false">`;
  return show(`
    <div class="modal-head"><span>${esc(title)}</span><button class="icon-btn" data-close>✕</button></div>
    <div class="modal-body"><div class="field">${label ? `<label>${esc(label)}</label>` : ''}${field}</div></div>
    <div class="modal-foot"><button class="btn" data-close>Cancel</button><button class="btn primary" data-ok>${esc(ok)}</button></div>`, {
    onOpen: (el, done) => {
      const inp = el.querySelector('.inp');
      inp.focus();
      if (!multiline) inp.select();
      el.querySelector('[data-ok]').onclick = () => done(inp.value.trim() || null);
    },
    onKey: (e, done) => {
      if (e.key === 'Enter' && (!multiline || e.ctrlKey)) {
        e.preventDefault();
        done(root().querySelector('.inp').value.trim() || null);
      }
    },
  });
}

export function confirmDialog({ title, text, ok = 'OK', danger = false }) {
  return show(`
    <div class="modal-head"><span>${esc(title)}</span><button class="icon-btn" data-close>✕</button></div>
    <div class="modal-body">${esc(text)}</div>
    <div class="modal-foot"><button class="btn" data-close>Cancel</button><button class="btn ${danger ? 'danger' : 'primary'}" data-ok>${esc(ok)}</button></div>`, {
    onOpen: (el, done) => { el.querySelector('[data-ok]').onclick = () => done(true); el.querySelector('[data-ok]').focus(); },
  }).then(v => v === true);
}

// Read-only text with a Copy button (exports).
export function textDialog({ title, text }) {
  return show(`
    <div class="modal-head"><span>${esc(title)}</span><button class="icon-btn" data-close>✕</button></div>
    <div class="modal-body"><textarea class="inp" readonly style="height:160px">${esc(text)}</textarea></div>
    <div class="modal-foot"><button class="btn" data-close>Close</button><button class="btn primary" data-copy>Copy</button></div>`, {
    onOpen: el => {
      const ta = el.querySelector('textarea');
      ta.select();
      el.querySelector('[data-copy]').onclick = async e => {
        try { await navigator.clipboard.writeText(text); } catch { ta.select(); document.execCommand('copy'); }
        e.target.textContent = 'Copied';
      };
    },
  });
}

// A settings form. fields: [{key, label, type: number|color|select|check|text, options, min, max, step}]
// Resolves with the new values object, or null.
export function formDialog({ title, fields, values, ok = 'Apply' }) {
  const input = f => {
    const v = values[f.key];
    switch (f.type) {
      case 'check':
        return `<label class="check"><input type="checkbox" data-key="${f.key}"${v ? ' checked' : ''}> ${esc(f.label)}</label>`;
      case 'select':
        return `<select class="inp" data-key="${f.key}">${f.options.map(o =>
          `<option value="${esc(o[0] ?? o)}"${String(o[0] ?? o) === String(v) ? ' selected' : ''}>${esc(o[1] ?? o)}</option>`).join('')}</select>`;
      case 'color':
        return `<input class="inp" type="color" data-key="${f.key}" value="${esc(toHex(v))}" style="padding:2px;height:32px">`;
      case 'number':
        return `<input class="inp" type="number" data-key="${f.key}" value="${esc(v)}"${f.min !== undefined ? ` min="${f.min}"` : ''}${f.max !== undefined ? ` max="${f.max}"` : ''} step="${f.step ?? 'any'}">`;
      case 'textarea':
        return `<textarea class="inp" data-key="${f.key}">${esc(v)}</textarea>`;
      default:
        return `<input class="inp" data-key="${f.key}" value="${esc(v)}">`;
    }
  };
  const rows = fields.map(f => f.type === 'check'
    ? `<div class="field">${input(f)}</div>`
    : `<div class="field"><label>${esc(f.label)}</label>${input(f)}</div>`).join('');
  return show(`
    <div class="modal-head"><span>${esc(title)}</span><button class="icon-btn" data-close>✕</button></div>
    <div class="modal-body">${rows}</div>
    <div class="modal-foot"><button class="btn" data-close>Cancel</button><button class="btn primary" data-ok>${esc(ok)}</button></div>`, {
    onOpen: (el, done) => {
      el.querySelector('[data-ok]').onclick = () => {
        const out = { ...values };
        for (const f of fields) {
          const inp = el.querySelector(`[data-key="${f.key}"]`);
          out[f.key] = f.type === 'check' ? inp.checked
            : f.type === 'number' ? (inp.value === '' ? values[f.key] : +inp.value)
            : inp.value;
        }
        done(out);
      };
    },
  });
}

// "#rrggbb" for any CSS colour (the colour input needs hex).
export function toHex(color) {
  if (/^#[0-9a-f]{6}$/i.test(color || '')) return color;
  const c = document.createElement('canvas').getContext('2d');
  c.fillStyle = color || '#000';
  const v = c.fillStyle;
  return /^#/.test(v) ? v : '#2962ff';
}
