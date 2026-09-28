// Chart timeframes. Ids match the server (backend/chart/market_data.py).

export const TIMEFRAMES = [
  { id: '1m', label: '1m', sec: 60, group: 'Minutes' },
  { id: '3m', label: '3m', sec: 180, group: 'Minutes' },
  { id: '5m', label: '5m', sec: 300, group: 'Minutes' },
  { id: '15m', label: '15m', sec: 900, group: 'Minutes' },
  { id: '30m', label: '30m', sec: 1800, group: 'Minutes' },
  { id: '1h', label: '1h', sec: 3600, group: 'Hours' },
  { id: '2h', label: '2h', sec: 7200, group: 'Hours' },
  { id: '4h', label: '4h', sec: 14400, group: 'Hours' },
  { id: '6h', label: '6h', sec: 21600, group: 'Hours' },
  { id: '12h', label: '12h', sec: 43200, group: 'Hours' },
  { id: '1d', label: 'D', sec: 86400, group: 'Days' },
  { id: '1w', label: 'W', sec: 604800, group: 'Days' },
  { id: '1M', label: 'M', sec: 2592000, group: 'Days' },
];

// Shown as buttons in the top bar; the rest are in the dropdown.
export const FAVOURITES = ['1m', '3m', '15m', '1h', '2h', '4h', '1d', '1w'];

// Timeframes a stock chart can show (Yahoo has no 3m, 6h or 12h).
export const STOCK_TIMEFRAMES = ['1m', '5m', '15m', '30m', '1h', '2h', '4h', '1d', '1w', '1M'];

const BY_ID = Object.fromEntries(TIMEFRAMES.map(t => [t.id, t]));

// A timeframe the symbol can show: stocks swap 3m/6h/12h for the nearest one.
const STOCK_SWAP = { '3m': '5m', '6h': '4h', '12h': '1d' };
export const fitTf = (info, tf) =>
  (info.market === 'stock' && !STOCK_TIMEFRAMES.includes(tf) ? STOCK_SWAP[tf] || '1d' : tf);

export const tfSeconds = id => BY_ID[id]?.sec ?? 3600;
export const tfLabel = id => BY_ID[id]?.label ?? id;
export const isIntraday = id => tfSeconds(id) < 86400;
export const isValidTf = id => id in BY_ID;

// Candle open time (UTC seconds) of the candle after the one opening at t.
export function nextBarTime(t, id) {
  if (id === '1M') {
    const d = new Date(t * 1000);
    return Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 1) / 1000;
  }
  return t + tfSeconds(id);
}

// Bottom-bar ranges: like TradingView, each range picks a timeframe too.
const DAY = 86400;
export const RANGES = [
  { id: '1D', tf: '1m', span: DAY },
  { id: '5D', tf: '5m', span: 5 * DAY },
  { id: '1M', tf: '30m', span: 30 * DAY },
  { id: '3M', tf: '1h', span: 91 * DAY },
  { id: '6M', tf: '2h', span: 182 * DAY },
  { id: 'YTD', tf: '1d', span: 'ytd' },
  { id: '1Y', tf: '1d', span: 365 * DAY },
  { id: '5Y', tf: '1w', span: 5 * 365 * DAY },
  { id: 'All', tf: '1w', span: 'all' },
];
