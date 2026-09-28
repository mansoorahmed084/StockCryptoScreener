// Small line icons (28x28, currentColor) for the left toolbar and menus.

const svg = body => `<svg viewBox="0 0 28 28" width="28" height="28" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">${body}</svg>`;
const dot = (x, y) => `<circle cx="${x}" cy="${y}" r="2" fill="currentColor" stroke="none"/>`;

export const ICONS = {
  cursor: svg('<path d="M14 5v18M5 14h18"/>'),
  trendline: svg(`<path d="M6 22L22 6"/>${dot(6, 22)}${dot(22, 6)}`),
  ray: svg(`<path d="M6 20L25 8"/>${dot(6, 20)}${dot(14, 15)}`),
  extline: svg(`<path d="M3 22L25 6"/>${dot(10, 17)}${dot(18, 11)}`),
  hline: svg(`<path d="M3 14h22"/>${dot(14, 14)}`),
  hray: svg(`<path d="M9 14h17"/>${dot(9, 14)}`),
  vline: svg(`<path d="M14 3v22"/>${dot(14, 14)}`),
  channel: svg(`<path d="M4 17L20 5M8 23L24 11"/>${dot(4, 17)}${dot(20, 5)}${dot(16, 17)}`),
  rect: svg(`<rect x="5" y="8" width="18" height="12" rx="1"/>${dot(5, 8)}${dot(23, 20)}`),
  fib: svg('<path d="M4 6h20M4 11h20M4 16h20M4 22h20" stroke-dasharray="0"/><path d="M6 22L22 6" stroke-dasharray="2 2"/>'),
  text: svg('<path d="M7 7h14M14 7v15M11 22h6"/>'),
  long: svg('<rect x="5" y="5" width="18" height="9" fill="rgba(8,153,129,.35)" stroke="#089981"/><rect x="5" y="14" width="18" height="7" fill="rgba(242,54,69,.3)" stroke="#f23645"/>'),
  short: svg('<rect x="5" y="7" width="18" height="7" fill="rgba(242,54,69,.3)" stroke="#f23645"/><rect x="5" y="14" width="18" height="9" fill="rgba(8,153,129,.35)" stroke="#089981"/>'),
  measure: svg('<path d="M4 20L20 4l4 4L8 24z"/><path d="M8 16l2 2M11 13l2 2M14 10l2 2M17 7l2 2"/>'),
  magnet: svg('<path d="M8 5v9a6 6 0 0 0 12 0V5"/><path d="M8 9h4M16 9h4"/>'),
  stay: svg('<path d="M9 13V9a5 5 0 0 1 10 0v4"/><rect x="7" y="13" width="14" height="10" rx="2"/><path d="M11 18h6"/>'),
  lock: svg('<rect x="7" y="13" width="14" height="10" rx="2"/><path d="M10 13V9a4 4 0 0 1 8 0v4"/>'),
  eye: svg('<path d="M3 14s4-7 11-7 11 7 11 7-4 7-11 7S3 14 3 14z"/><circle cx="14" cy="14" r="3"/>'),
  trash: svg('<path d="M6 8h16M11 8V5h6v3M8 8l1 15h10l1-15"/>'),
  alert: svg('<path d="M8 19V13a6 6 0 0 1 12 0v6l2 2H6z"/><path d="M12 23a2 2 0 0 0 4 0"/>'),
  gear: svg('<circle cx="14" cy="14" r="3"/><path d="M14 4v3M14 21v3M4 14h3M21 14h3M7 7l2 2M19 19l2 2M7 21l2-2M19 9l2-2"/>'),
  clone: svg('<rect x="9" y="9" width="13" height="13" rx="2"/><path d="M6 18V7a1 1 0 0 1 1-1h11"/>'),
  indicators: svg('<path d="M4 20c4 0 4-10 8-10s4 8 8 8 4-12 4-12"/>'),
};
