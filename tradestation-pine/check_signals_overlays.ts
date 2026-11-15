// Run signals_overlays_own.pine in Trade Station's Pine engine on exported bars and check its rules.
// Usage: node check_signals_overlays.ts <csv> [timeframe in minutes]
// The csv needs the columns time (ms), open, high, low, close, volume.
import { readFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';

const engine = 'C:/temp/myTradingview/packages/script-engine/src/';
const { ScriptHost } = await import(pathToFileURL(engine + 'index.ts').href);
const { findUnsupported } = await import(pathToFileURL(engine + 'compat.ts').href);

const [csvPath, tf = '240'] = process.argv.slice(2);
const lines = readFileSync(csvPath, 'utf8').trim().split(/\r?\n/);
const head = lines[0].split(',');
const rows = lines.slice(1).map((l) => l.split(','));
const col = (name: string) => {
    const i = head.indexOf(name);
    if (i < 0) throw new Error(`no column ${name}`);
    return rows.map((r) => Number(r[i]));
};
const all = { time: col('time'), open: col('open'), high: col('high'), low: col('low'), close: col('close'), volume: col('volume') };
const N = all.time.length;

/** A host that serves only the first `n` bars. */
function hostFor(n: number) {
    const cut = (a: number[]) => a.slice(0, n);
    const series = { length: n, time: cut(all.time), open: cut(all.open), high: cut(all.high), low: cut(all.low), close: cut(all.close), volume: cut(all.volume) };
    return new ScriptHost({
        getBars: async () => series,
        describe: async () => ({ ticker: 'TEST', symbol: 'CSV:TEST', provider: 'CSV', tickSize: 0.01, description: 'csv', type: 'crypto', currency: 'USDT', timezone: 'Etc/UTC', session: '24x7', minQty: 0 }),
        clock: () => all.time[n - 1] + 10 * 86_400_000,
    } as any);
}

const source = readFileSync('C:/temp/AI/StockCryptoScreener/tradestation-pine/signals_overlays_own.pine', 'utf8');
let bad = 0;
const fail = (msg: string) => {
    bad++;
    console.log(`  FAIL ${msg}`);
};

const missing = await findUnsupported(source);
if (missing.length) fail(`built-ins the engine lacks: ${missing.map((m: any) => m.name).join(', ')}`);

type Plots = Record<string, (number | null)[]>;
async function run(inputs: Record<string, unknown>, n = N): Promise<Plots | null> {
    try {
        const r = await hostFor(n).run(source, 'CSV:TEST', tf, { from: all.time[0], inputs });
        const warn = [...new Set(r.warnings.map((w: any) => w.message))];
        if (warn.length) console.log(`  warnings: ${warn.join(' | ')}`);
        if (r.times.length !== n) fail(`${r.times.length} bars, expected ${n}`);
        return r.plots;
    } catch (err: any) {
        fail(`ERROR ${err.stage} line ${err.line}: ${err.message}`);
        return null;
    }
}

const count = (a: (number | null)[], v: number) => a.filter((x) => x === v).length;
const filled = (a?: (number | null)[]) => (a ? a.filter((x) => x !== null).length : 0);
const summary = (p: Plots) =>
    `bull ${count(p.sig, 1)}  bull+ ${count(p.sig, 2)}  bear ${count(p.sig, -1)}  bear+ ${count(p.sig, -2)}  exits ${count(p.exit, 1)}/${count(p.exit, -1)}`;

/** Exits must follow a signal of their side, and must be in profit against that signal's close. */
function checkExits(p: Plots, oneExitOnly: boolean) {
    let pos = 0;
    let entry = Number.NaN;
    let exits = 0;
    for (let i = 0; i < N; i++) {
        const s = p.sig[i] ?? 0;
        const x = p.exit[i] ?? 0;
        if (s !== 0) {
            pos = Math.sign(s);
            entry = all.close[i];
            exits = 0;
            if (x !== 0) return fail(`bar ${i}: exit on a signal bar`);
            continue;
        }
        if (x === 0) continue;
        exits++;
        if (x !== pos) return fail(`bar ${i}: exit ${x} while position is ${pos}`);
        if (pos * (all.close[i] - entry) <= 0) return fail(`bar ${i}: exit is not in profit`);
        if (oneExitOnly && exits > 1) return fail(`bar ${i}: second exit for one signal`);
    }
}

function checkSignalsWhere(p: Plots, name: string, okBull: (i: number) => boolean, okBear: (i: number) => boolean) {
    for (let i = 0; i < N; i++) {
        const s = p.sig[i] ?? 0;
        if (s > 0 && !okBull(i)) return fail(`${name}: bullish signal at bar ${i} breaks the filter`);
        if (s < 0 && !okBear(i)) return fail(`${name}: bearish signal at bar ${i} breaks the filter`);
    }
}

// 1. Default settings: Confirmation + Exits
console.log('Default (Confirmation + Exits)');
const base = await run({});
if (base) {
    console.log(`  ${summary(base)}`);
    let last = 0;
    for (let i = 0; i < N; i++) {
        const s = Math.sign(base.sig[i] ?? 0);
        if (s !== 0 && s === last) {
            fail(`bar ${i}: two ${s > 0 ? 'bullish' : 'bearish'} signals in a row`);
            break;
        }
        if (s !== 0) last = s;
    }
    checkExits(base, false);
    for (let i = 1; i < N; i++) {
        const t = base.trail[i];
        const d = base.trail_dir[i];
        if (t === null || d === null) continue;
        if (d === base.trail_dir[i - 1] && d * (all.close[i] - t) < 0) {
            fail(`bar ${i}: close is on the wrong side of the Smart Trail`);
            break;
        }
    }
    const opt = base['Optimal Sensitivity'];
    const vals = opt.filter((x): x is number => x !== null);
    if (opt.slice(0, 250).some((x) => x !== null)) fail('Optimal Sensitivity shows before 250 bars');
    if (vals.some((x) => x < 10 || x > 20)) fail('Optimal Sensitivity is outside 10..20');
    console.log(`  Optimal Sensitivity: last ${opt[N - 1]}, ${new Set(vals).size} different values`);
    const ts = base['Trend Strength'].filter((x): x is number => x !== null);
    console.log(`  Trend Strength: above 50% on ${Math.round((100 * ts.filter((x) => x > 50).length) / ts.length)}% of bars`);

    // 2. No look-ahead: the first 2/3 of the bars must give the same values with or without the rest.
    const n2 = Math.floor((N * 2) / 3);
    const part = await run({}, n2);
    if (part) {
        for (const name of Object.keys(part)) {
            let diff = 0;
            for (let i = 0; i < n2; i++) {
                const a = part[name][i];
                const b = base[name]?.[i];
                if (a === null || b === null || b === undefined ? a !== b : Math.abs(a - b) > 1e-6 * Math.max(1, Math.abs(b))) diff++;
            }
            if (diff) fail(`look-ahead: plot "${name}" changes on ${diff} old bars when new bars come in`);
        }
        console.log(`  no look-ahead: ${Object.keys(part).length} plots checked on ${n2} bars`);
    }
}

// 3. Contrarian + Exits
console.log('Contrarian + Exits');
const cont = await run({ 'Signal Mode': 'Contrarian + Exits' });
if (cont) {
    console.log(`  ${summary(cont)}`);
    checkExits(cont, true);
}

// 4. Signal Mode None
console.log('Signal Mode None');
const none = await run({ 'Signal Mode': 'None' });
if (none && (none.sig.some((x) => x) || none.exit.some((x) => x))) fail('signals show with Signal Mode None');

// 5. Autopilot
for (const [term, lo, hi] of [['Short-Term', 5, 10], ['Medium-Term', 10, 20], ['Long-Term', 20, 30]] as const) {
    console.log(`Autopilot ${term}`);
    const p = await run({ 'Autopilot Sensitivity': term });
    if (!p) continue;
    console.log(`  ${summary(p)}`);
    const vals = p['Optimal Sensitivity'].filter((x): x is number => x !== null);
    if (vals.some((x) => x < lo || x > hi)) fail(`sensitivity is outside ${lo}..${hi}`);
    checkExits(p, false);
}
console.log('Autopilot Medium-Term, Contrarian');
const autoCont = await run({ 'Autopilot Sensitivity': 'Medium-Term', 'Signal Mode': 'Contrarian + Exits' });
if (autoCont) {
    console.log(`  ${summary(autoCont)}`);
    checkExits(autoCont, true);
}

// 6. Classifier
console.log('ML Signal Classifier');
const ml = await run({ 'ML Signal Classifier': true });
if (ml) {
    const at = ml.ml_class.filter((_, i) => (ml.sig[i] ?? 0) !== 0) as number[];
    if (at.some((c) => c < 1 || c > 4)) fail('class is outside 1..4');
    console.log(`  classes at signals: ${[1, 2, 3, 4].map((c) => `${c}:${at.filter((x) => x === c).length}`).join('  ')}`);
}
const ml12 = await run({ 'ML Signal Classifier': true, 'ML Classifier Filter': 12 });
if (ml12) {
    const at = ml12.ml_class.filter((_, i) => (ml12.sig[i] ?? 0) !== 0) as number[];
    if (at.some((c) => c !== 1 && c !== 2)) fail('filter 12 lets class 3 or 4 through');
    console.log(`  filter 12: ${at.length} signals left`);
}

// 7. Filters
console.log('Filters');
const fTrail = await run({ 'Presets / Filters': 'Smart Trail' });
if (fTrail) checkSignalsWhere(fTrail, 'Smart Trail', (i) => all.close[i] > fTrail.trail[i]!, (i) => all.close[i] < fTrail.trail[i]!);
for (const [name, plot] of [['Trend Tracer', 'tracer_dir'], ['Trend Catcher', 'catcher_dir']] as const) {
    const p = await run({ 'Presets / Filters': name });
    if (p) checkSignalsWhere(p, name, (i) => p[plot][i] === 1, (i) => p[plot][i] === -1);
}
const fNeo = await run({ 'Presets / Filters': 'Neo Cloud', 'Neo Cloud': true });
if (fNeo) {
    const top = (i: number) => Math.max(fNeo['Neo Cloud Lead'][i]!, fNeo['Neo Cloud Lag'][i]!);
    const btm = (i: number) => Math.min(fNeo['Neo Cloud Lead'][i]!, fNeo['Neo Cloud Lag'][i]!);
    checkSignalsWhere(fNeo, 'Neo Cloud', (i) => all.close[i] > top(i), (i) => all.close[i] < btm(i));
    console.log(`  Neo Cloud filter: ${summary(fNeo)}`);
}
const fStr = await run({ 'Presets / Filters': 'Trend Strength' });
if (fStr) {
    checkSignalsWhere(fStr, 'Trend Strength', (i) => fStr['Trend Strength'][i]! > 50, (i) => fStr['Trend Strength'][i]! > 50);
    console.log(`  Trend Strength filter: ${summary(fStr)}`);
}

// 8. Presets: each one must draw its own set of features
console.log('Presets');
const want: Record<string, { on: string[]; off: string[] }> = {
    'Trend Trader': { on: ['Smart Trail', 'Trend Catcher'], off: ['R1', 'Neo Cloud Lead', 'Trend Tracer', 'TP 1'] },
    Scalper: { on: ['R1', 'S3', 'TP 1', 'SL 2'], off: ['Smart Trail', 'Trend Catcher', 'Neo Cloud Lead'] },
    'Swing Trader': { on: ['Neo Cloud Lead', 'Neo Cloud Lag'], off: ['Smart Trail', 'R1', 'TP 1'] },
    'Contrarian Trader': { on: ['R1', 'S1'], off: ['Smart Trail', 'Neo Cloud Lead', 'TP 1'] },
};
for (const [name, w] of Object.entries(want)) {
    const p = await run({ 'Presets / Filters': name });
    if (!p) continue;
    for (const k of w.on) if (!filled(p[k])) fail(`${name}: "${k}" is not drawn`);
    for (const k of w.off) if (filled(p[k])) fail(`${name}: "${k}" is drawn`);
    console.log(`  ${name.padEnd(18)} ${summary(p)}`);
}

// 9. TP/SL triggers and all overlays
console.log('TP/SL Levels');
for (const trig of ['Signals', 'Smart Trail', 'Reversal Zones', 'Trend Catcher', 'Trend Tracer', 'Neo Cloud']) {
    const p = await run({ 'TP/SL Levels': trig, 'Reversal Zones': true, 'Trend Catcher': true, 'Trend Tracer': true, 'Neo Cloud': true });
    if (!p) continue;
    const n = filled(p['TP 1']);
    if (!n) fail(`${trig}: no levels drawn`);
    let order = 0;
    for (let i = 0; i < N; i++) {
        const [t1, t2, s1, s2] = [p['TP 1'][i], p['TP 2'][i], p['SL 1'][i], p['SL 2'][i]];
        if (t1 === null || t2 === null || s1 === null || s2 === null) continue;
        const up = t1 > s1;
        if (up ? !(t2 > t1 && s1 > s2) : !(t2 < t1 && s1 < s2)) order++;
    }
    if (order) fail(`${trig}: levels are in the wrong order on ${order} bars`);
    console.log(`  ${trig.padEnd(15)} levels on ${n} bars`);
}

console.log(bad ? `\n${bad} check(s) FAILED` : '\nAll checks passed');
process.exit(bad ? 1 : 0);
