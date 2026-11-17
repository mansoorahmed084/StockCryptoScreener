// Run the three Pine ports in Trade Station's Pine engine on exported bars and compare every value
// with the Python rebuilds. Usage: node compare.ts <csv> [timeframe]
import { readFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';

const { ScriptHost } = await import(pathToFileURL('C:/temp/myTradingview/packages/script-engine/src/index.ts').href);

const [csvPath, tf = '240'] = process.argv.slice(2);
const lines = readFileSync(csvPath, 'utf8').trim().split(/\r?\n/);
const head = lines[0].split(',');
const rows = lines.slice(1).map((l) => l.split(','));
const col = (name: string) => {
    const i = head.indexOf(name);
    if (i < 0) throw new Error(`no column ${name}`);
    return rows.map((r) => (r[i] === '' ? Number.NaN : Number(r[i])));
};
const t = col('time');
const series = {
    length: t.length,
    time: t,
    open: col('open'),
    high: col('high'),
    low: col('low'),
    close: col('close'),
    volume: col('volume'),
};
const data = {
    getBars: async () => series,
    describe: async () => ({ ticker: 'TEST', symbol: 'CSV:TEST', provider: 'CSV', tickSize: 0.01, description: 'csv', type: 'crypto', currency: 'USDT', timezone: 'Etc/UTC', session: '24x7', minQty: 0 }),
    clock: () => t[t.length - 1] + 10 * 86_400_000,
};
const host = new ScriptHost(data as any);
const dir = 'C:/temp/AI/StockCryptoScreener/tradestation-pine/';

const checks: [string, [string, string][]][] = [
    ['supertrend_ai.pine', [['ts', 'st_ts'], ['os', 'st_os'], ['factor', 'st_factor'], ['score', 'st_score']]],
    ['sr_breaks.pine', [['Resistance', 'sr_res'], ['Support', 'sr_sup'], ['osc', 'sr_osc'], ['x_up', 'sr_x_up'], ['x_dn', 'sr_x_dn'], ['b_up', 'sr_b_up'], ['b_dn', 'sr_b_dn']]],
    ['liquidity_swings.pine', [['lo_any', 'ls_lo_any'], ['hi_any', 'ls_hi_any'], ['lo_last', 'ls_lo_last'], ['hi_last', 'ls_hi_last'], ['lz_btm', 'ls_lz_btm'], ['lz_top', 'ls_lz_top'], ['hz_btm', 'ls_hz_btm'], ['hz_top', 'ls_hz_top']]],
];

let bad = 0;
for (const [file, pairs] of checks) {
    const source = readFileSync(dir + file, 'utf8');
    let run: any;
    try {
        run = await host.run(source, 'CSV:TEST', tf, { from: t[0] });
    } catch (err: any) {
        console.log(`${file}: ERROR ${err.stage} line ${err.line}: ${err.message}`);
        bad++;
        continue;
    }
    if (run.times.length !== t.length) console.log(`${file}: ${run.times.length} bars, expected ${t.length}`);
    const warn = [...new Set(run.warnings.map((w: any) => w.message))];
    if (warn.length) console.log(`${file}: warnings ${warn.join(' | ')}`);
    console.log(`${file}: ran in ${Math.round(run.ms)} ms`);
    for (const [plot, pyCol] of pairs) {
        const got = run.plots[plot];
        if (!got) {
            console.log(`  ${plot}: missing plot (have ${Object.keys(run.plots).join(', ')})`);
            bad++;
            continue;
        }
        const want = col(pyCol);
        let miss = 0;
        const first: string[] = [];
        for (let i = 0; i < want.length; i++) {
            const w = want[i];
            const g = got[i];
            const ok = Number.isNaN(w) ? g === null : g !== null && Math.abs(g - w) <= 1e-7 * Math.max(1, Math.abs(w));
            if (!ok) {
                miss++;
                if (first.length < 4) first.push(`#${i} pine=${g} py=${w}`);
            }
        }
        if (miss) bad++;
        console.log(`  ${plot.padEnd(10)} ${miss ? `${miss} mismatches: ${first.join('; ')}` : 'all match'}`);
    }
}
process.exit(bad ? 1 : 0);
