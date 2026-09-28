// Number and time formatting, and the time-zone shift of chart times.
//
// Lightweight Charts draws times as UTC. To show exchange-style local times
// (IST by default) intraday candle times are shifted by the zone's UTC offset
// before they go to the chart: chartTime = utc + offset. Daily and bigger
// candles are not shifted, so their dates stay exact.

let zone = 'Asia/Kolkata';
const offsetCache = new Map();

export function setTimeZone(tz) {
  zone = tz;
  offsetCache.clear();
}
export const timeZone = () => zone;

// Offset of the zone from UTC at a UTC time, in seconds (cached per hour).
export function zoneOffset(utcSec) {
  const hour = Math.floor(utcSec / 3600);
  let off = offsetCache.get(hour);
  if (off === undefined) {
    const parts = new Intl.DateTimeFormat('en-US', {
      timeZone: zone, hourCycle: 'h23', year: 'numeric', month: 'numeric',
      day: 'numeric', hour: 'numeric', minute: 'numeric', second: 'numeric',
    }).formatToParts(new Date(hour * 3600 * 1000));
    const p = Object.fromEntries(parts.map(x => [x.type, +x.value]));
    const local = Date.UTC(p.year, p.month - 1, p.day, p.hour, p.minute, p.second) / 1000;
    off = local - hour * 3600;
    offsetCache.set(hour, off);
  }
  return off;
}

export const toChartTime = (utc, intraday) => (intraday ? utc + zoneOffset(utc) : utc);
export const fromChartTime = (t, intraday) => (intraday ? t - zoneOffset(t - zoneOffset(t)) : t);

// Decimals to show for a series: the most any recent price uses (max 10).
export function precisionOf(bars) {
  let best = 2;
  for (const b of bars.slice(-100)) {
    for (const v of [b.open, b.close, b.high, b.low]) {
      const s = String(v);
      if (s.includes('e-')) return Math.min(10, +s.split('e-')[1] + 2);
      const i = s.indexOf('.');
      if (i >= 0) best = Math.max(best, s.length - i - 1);
    }
  }
  return Math.min(best, 10);
}

export function fmtPrice(v, precision = 2) {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  return v.toLocaleString('en-US', {
    minimumFractionDigits: precision, maximumFractionDigits: precision,
  });
}

// 17.12K, 8.36M ...
export function fmtVolume(v) {
  if (v === null || v === undefined) return '—';
  const a = Math.abs(v);
  if (a >= 1e9) return (v / 1e9).toFixed(2) + 'B';
  if (a >= 1e6) return (v / 1e6).toFixed(2) + 'M';
  if (a >= 1e3) return (v / 1e3).toFixed(2) + 'K';
  return v.toFixed(a < 10 ? 2 : 0);
}

export const fmtPct = v => (v > 0 ? '+' : '') + v.toFixed(2) + '%';

// "10:56", "1:02:03", "3d 4h" — time left to a candle close.
export function fmtCountdown(sec) {
  sec = Math.max(0, Math.floor(sec));
  const d = Math.floor(sec / 86400), h = Math.floor(sec % 86400 / 3600);
  const m = Math.floor(sec % 3600 / 60), s = sec % 60;
  const pad = n => String(n).padStart(2, '0');
  if (d > 0) return `${d}d ${h}h`;
  if (h > 0) return `${h}:${pad(m)}:${pad(s)}`;
  return `${pad(m)}:${pad(s)}`;
}

// The zone's offset as "UTC+5:30".
export function zoneLabel() {
  const off = zoneOffset(Date.now() / 1000) / 60;
  const sign = off >= 0 ? '+' : '-';
  const a = Math.abs(off);
  return `UTC${sign}${Math.floor(a / 60)}${a % 60 ? ':' + String(a % 60).padStart(2, '0') : ''}`;
}

// Chart times are already shifted, so they format as UTC.
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

export function fmtChartTime(t, intraday) {
  const d = new Date(t * 1000);
  const date = `${DAYS[d.getUTCDay()]} ${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]} '${String(d.getUTCFullYear()).slice(2)}`;
  if (!intraday) return date;
  return `${date}  ${String(d.getUTCHours()).padStart(2, '0')}:${String(d.getUTCMinutes()).padStart(2, '0')}`;
}

// Tick marks under the time axis. TickMarkType: 0 year, 1 month, 2 day, 3 time, 4 time+sec.
export function fmtTick(t, type) {
  const d = new Date(t * 1000);
  switch (type) {
    case 0: return String(d.getUTCFullYear());
    case 1: return MONTHS[d.getUTCMonth()];
    case 2: return String(d.getUTCDate());
    default: return `${String(d.getUTCHours()).padStart(2, '0')}:${String(d.getUTCMinutes()).padStart(2, '0')}`;
  }
}
