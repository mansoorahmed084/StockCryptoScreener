// Run signals_overlays_own.pine in Trade Station's Pine engine with many settings and write every
// plot to csv files, so compare_signals_overlays.py can check the Python twin against them.
// Usage: node dump_signals_overlays.ts <bars.csv> <timeframe in minutes> <out dir>
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';

const { ScriptHost } = await import(pathToFileURL('C:/temp/myTradingview/packages/script-engine/src/index.ts').href);

const [csvPath, tf, outDir] = process.argv.slice(2);
const lines = readFileSync(csvPath, 'utf8').trim().split(/\r?\n/);
const head = lines[0].split(',');
const rows = lines.slice(1).map((l) => l.split(','));
const col = (name: string) => rows.map((r) => Number(r[head.indexOf(name)]));
const t = col('time');
const series = { length: t.length, time: t, open: col('open'), high: col('high'), low: col('low'), close: col('close'), volume: col('volume') };
const host = new ScriptHost({
    getBars: async () => series,
    describe: async () => ({ ticker: 'TEST', symbol: 'CSV:TEST', provider: 'CSV', tickSize: 0.01, description: 'csv', type: 'crypto', currency: 'USDT', timezone: 'Etc/UTC', session: '24x7', minQty: 0 }),
    clock: () => t[t.length - 1] + 10 * 86_400_000,
} as any);
const source = readFileSync('C:/temp/AI/StockCryptoScreener/tradestation-pine/signals_overlays_own.pine', 'utf8');

const overlays = { 'Reversal Zones': true, 'Trend Catcher': true, 'Trend Tracer': true, 'Neo Cloud': true };
const cont = { 'Signal Mode': 'Contrarian + Exits' };
const configs: Record<string, Record<string, unknown>> = {
    conf: { ...overlays, 'TP/SL Levels': 'Signals' },
    cont: { ...cont, ...overlays, 'TP/SL Levels': 'Smart Trail' },
    conf_auto_short: { 'Autopilot Sensitivity': 'Short-Term' },
    conf_auto_medium: { 'Autopilot Sensitivity': 'Medium-Term' },
    conf_auto_long: { 'Autopilot Sensitivity': 'Long-Term' },
    cont_auto_short: { ...cont, 'Autopilot Sensitivity': 'Short-Term' },
    cont_auto_medium: { ...cont, 'Autopilot Sensitivity': 'Medium-Term' },
    cont_auto_long: { ...cont, 'Autopilot Sensitivity': 'Long-Term' },
    conf_ml34: { 'ML Signal Classifier': true, 'ML Classifier Filter': 34 },
    conf_ml12: { 'ML Signal Classifier': true, 'ML Classifier Filter': 12 },
    cont_ml34: { ...cont, 'ML Signal Classifier': true, 'ML Classifier Filter': 34 },
    cont_ml12: { ...cont, 'ML Signal Classifier': true, 'ML Classifier Filter': 12 },
    conf_filt_trail: { 'Presets / Filters': 'Smart Trail' },
    conf_filt_tracer: { 'Presets / Filters': 'Trend Tracer' },
    conf_filt_catcher: { 'Presets / Filters': 'Trend Catcher' },
    conf_filt_neo: { 'Presets / Filters': 'Neo Cloud' },
    conf_filt_strength: { 'Presets / Filters': 'Trend Strength' },
    conf_sens8: { 'Signals Sensitivity': 8 },
    conf_sens20: { 'Signals Sensitivity': 20 },
    cont_sens8: { ...cont, 'Signals Sensitivity': 8 },
    cont_sens20: { ...cont, 'Signals Sensitivity': 20 },
    // the second signal style
    lux: { 'Signal Style': 'LuxAlgo-like', ...overlays, 'TP/SL Levels': 'Signals' },
    lux_sens5: { 'Signal Style': 'LuxAlgo-like', 'Signals Sensitivity': 5 },
    lux_sens25: { 'Signal Style': 'LuxAlgo-like', 'Signals Sensitivity': 25 },
    lux_auto_medium: { 'Signal Style': 'LuxAlgo-like', 'Autopilot Sensitivity': 'Medium-Term' },
    lux_filt_trail: { 'Signal Style': 'LuxAlgo-like', 'Presets / Filters': 'Smart Trail' },
    lux_cont: { 'Signal Style': 'LuxAlgo-like', ...cont },
};

mkdirSync(outDir, { recursive: true });
for (const [name, inputs] of Object.entries(configs)) {
    const run = await host.run(source, 'CSV:TEST', tf, { from: t[0], inputs });
    const names = Object.keys(run.plots);
    const out = [names.join(',')];
    for (let i = 0; i < t.length; i++) out.push(names.map((n) => run.plots[n][i] ?? '').join(','));
    writeFileSync(`${outDir}/${name}.csv`, out.join('\n'));
    console.log(`${name}: ${names.length} plots`);
}
