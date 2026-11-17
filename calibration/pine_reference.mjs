// Run a Pine script over a candles CSV with PineTS and write every plot to a CSV.
//
//   node calibration/pine_reference.mjs <candles.csv> <script.pine> <out.csv>
//
// The candles CSV has time (Unix seconds), open, high, low, close, volume. The output has the same
// columns plus one per plot, named by the plot's title, so it reads like a TradingView export.
// PineTS comes from the myTradingView project (PINETS_DIR overrides where it is looked for).
import { readFileSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { homedir } from 'node:os';
import { pathToFileURL } from 'node:url';

const [candlesPath, scriptPath, outPath] = process.argv.slice(2);
if (!outPath) {
    console.error('usage: node calibration/pine_reference.mjs <candles.csv> <script.pine> <out.csv>');
    process.exit(2);
}

const pinetsDir = process.env.PINETS_DIR ?? `${homedir()}/myTradingView/node_modules/pinets`;
const req = createRequire(`${pinetsDir}/`);
const { PineTS } = await import(pathToFileURL(req.resolve(pinetsDir)).href);

const lines = readFileSync(candlesPath, 'utf8').trim().split(/\r?\n/); // Python's csv writes \r\n
const head = lines[0].split(',').map((h) => h.trim());
const col = (n) => {
    const i = head.indexOf(n);
    if (i < 0) throw new Error(`the candles CSV has no "${n}" column (found ${head.join(', ')})`);
    return i;
};
const rows = lines.slice(1).map((l) => l.split(','));
const times = rows.map((r) => Number(r[col('time')]) * 1000);
const step = times[1] - times[0];
const klines = rows.map((r, i) => ({
    openTime: times[i],
    closeTime: times[i] + step - 1,
    open: Number(r[col('open')]),
    high: Number(r[col('high')]),
    low: Number(r[col('low')]),
    close: Number(r[col('close')]),
    volume: Number(r[col('volume')]),
}));

const t0 = Date.now();
// Pine timeframe strings: minutes for intraday, "D" / "W" for daily and weekly
const minutes = Math.round(step / 60000);
const timeframe = minutes === 1440 ? 'D' : minutes === 10080 ? 'W' : String(minutes);
const ctx = await new PineTS(klines, 'SYMBOL', timeframe).run(readFileSync(scriptPath, 'utf8'));
const titles = Object.keys(ctx.plots ?? {}).filter((t) => !t.startsWith('__')); // PineTS's own drawing buckets
if (titles.length === 0) {
    console.error('the script produced no plots');
    process.exit(1);
}
const out = [['time', 'open', 'high', 'low', 'close', 'volume', ...titles].join(',')];
for (let i = 0; i < rows.length; i++) {
    const vals = titles.map((t) => {
        const v = ctx.plots[t]?.data?.[i]?.value;
        return typeof v === 'number' && Number.isFinite(v) ? String(v) : '';
    });
    out.push([times[i] / 1000, ...['open', 'high', 'low', 'close', 'volume'].map((k) => rows[i][col(k)]), ...vals].join(','));
}
writeFileSync(outPath, out.join('\n') + '\n');
console.log(`${rows.length} bars, ${titles.length} plots (${titles.join(', ')}) in ${((Date.now() - t0) / 1000).toFixed(1)}s -> ${outPath}`);
