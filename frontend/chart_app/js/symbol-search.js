// Symbol search dialog: type, pick a market tab, arrow keys + Enter.

import { api } from './api.js';
import { esc } from './dom.js';

const MARKETS = [['all', 'All'], ['crypto', 'Crypto'], ['india', 'India'], ['us', 'US']];

export class SymbolSearch {
  constructor(root) {
    this.root = root;
    this.market = 'all';
    this.results = [];
    this.active = 0;
    this.seq = 0;
    root.innerHTML = `
      <div class="modal-card search-card" role="dialog" aria-label="Symbol search">
        <div class="modal-head">
          <span>Symbol search</span>
          <button class="icon-btn" data-close aria-label="Close">✕</button>
        </div>
        <div class="search-input">
          <span class="search-icon">⌕</span>
          <input type="text" placeholder="Symbol, e.g. BTCUSDT.P, RELIANCE, AAPL" spellcheck="false" autocomplete="off">
        </div>
        <div class="tabs">${MARKETS.map(([id, label]) =>
          `<button class="tab" data-market="${id}">${label}</button>`).join('')}</div>
        <ul class="search-results"></ul>
        <div class="search-foot">↑ ↓ to move · Enter to open · Esc to close</div>
      </div>`;
    this.input = root.querySelector('input');
    this.list = root.querySelector('.search-results');
    root.addEventListener('mousedown', e => { if (e.target === root) this.close(); });
    root.querySelector('[data-close]').onclick = () => this.close();
    root.querySelectorAll('[data-market]').forEach(b => {
      b.onclick = () => { this.market = b.dataset.market; this._tabs(); this._query(); this.input.focus(); };
    });
    this.input.addEventListener('input', () => {
      clearTimeout(this.debounce);
      this.debounce = setTimeout(() => this._query(), 150);
    });
    this.input.addEventListener('keydown', e => this._key(e));
    this._tabs();
  }

  // Resolves with the picked symbol (or null when closed).
  open(prefill = '', { title = 'Symbol search' } = {}) {
    this.root.querySelector('.modal-head span').textContent = title;
    this.root.hidden = false;
    this.input.value = prefill;
    this.input.focus();
    this._query();
    return new Promise(resolve => { this.resolve = resolve; });
  }

  close(value = null) {
    this.root.hidden = true;
    if (this.resolve) { this.resolve(value); this.resolve = null; }
  }

  get isOpen() { return !this.root.hidden; }

  _tabs() {
    this.root.querySelectorAll('[data-market]').forEach(b =>
      b.classList.toggle('active', b.dataset.market === this.market));
  }

  async _query() {
    const q = this.input.value.trim();
    const seq = ++this.seq;
    if (!q) { this.results = []; this._draw(); return; }
    try {
      const { symbols } = await api.get('/api/chart/symbols', { q, market: this.market });
      if (seq !== this.seq) return;
      this.results = symbols;
    } catch (err) {
      if (seq !== this.seq) return;
      this.results = [];
      this.list.innerHTML = `<li class="empty">Search failed: ${esc(err.message)}</li>`;
      return;
    }
    this.active = 0;
    this._draw();
  }

  _draw() {
    if (!this.results.length) {
      this.list.innerHTML = this.input.value.trim()
        ? '<li class="empty">No symbols match</li>' : '<li class="empty">Start typing a symbol</li>';
      return;
    }
    this.list.innerHTML = this.results.map((r, i) => `
      <li class="${i === this.active ? 'active' : ''}" data-i="${i}">
        <span class="sr-ticker">${esc(r.ticker)}</span>
        <span class="sr-desc">${esc(r.description)}</span>
        <span class="sr-type">${esc(r.market)}</span>
        <span class="sr-exch">${esc(r.exchange)}</span>
      </li>`).join('');
    this.list.querySelectorAll('li[data-i]').forEach(li => {
      li.onclick = () => this.close(this.results[+li.dataset.i].symbol);
    });
  }

  _key(e) {
    if (e.key === 'Escape') { this.close(); return; }
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      if (!this.results.length) return;
      this.active = (this.active + (e.key === 'ArrowDown' ? 1 : -1) + this.results.length) % this.results.length;
      this._draw();
      this.list.querySelector('li.active')?.scrollIntoView({ block: 'nearest' });
    } else if (e.key === 'Enter') {
      e.preventDefault();
      const pick = this.results[this.active];
      // Nothing listed yet: try the typed text as a symbol.
      this.close(pick ? pick.symbol : this.input.value.trim().toUpperCase() || null);
    }
  }
}
