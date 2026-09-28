// Small extras: light / dark theme, chart screenshot, and "copy trade plan"
// on long / short position drawings.

import { $, store, toast } from './dom.js';
import { tfLabel } from './timeframes.js';

export function initExtras(app) {
  // ---- theme ----
  const setTheme = theme => {
    document.documentElement.dataset.theme = theme;
    store.set('cw.theme', theme);
    themeBtn.textContent = theme === 'dark' ? '☾' : '☀';
    themeBtn.title = theme === 'dark' ? 'Light theme' : 'Dark theme';
    for (const s of app.slots) s.view.applyTheme();
  };
  const themeBtn = document.createElement('button');
  themeBtn.className = 'tb-btn';
  themeBtn.onclick = () => setTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark');
  $('#tb-right').appendChild(themeBtn);
  const theme = store.get('cw.theme', 'dark');
  document.documentElement.dataset.theme = theme;
  themeBtn.textContent = theme === 'dark' ? '☾' : '☀';
  themeBtn.title = theme === 'dark' ? 'Light theme' : 'Dark theme';

  // ---- screenshot ----
  const shot = document.createElement('button');
  shot.className = 'tb-btn';
  shot.title = 'Save a picture of the chart (PNG)';
  shot.textContent = '📷';
  $('#tb-right').appendChild(shot);
  shot.onclick = () => {
    const slot = app.slot;
    if (!slot?.info) return;
    const chartCanvas = slot.view.chart.takeScreenshot(true, false);
    const head = 28;
    const c = document.createElement('canvas');
    c.width = chartCanvas.width;
    c.height = chartCanvas.height + head * devicePixelRatio;
    const ctx = c.getContext('2d');
    const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
    ctx.fillStyle = css('--chart-bg');
    ctx.fillRect(0, 0, c.width, c.height);
    ctx.drawImage(chartCanvas, 0, head * devicePixelRatio);
    ctx.fillStyle = css('--text');
    ctx.font = `${14 * devicePixelRatio}px ${css('--font')}`;
    ctx.textBaseline = 'middle';
    const when = new Date().toISOString().slice(0, 16).replace('T', ' ');
    ctx.fillText(`${slot.info.symbol} · ${tfLabel(slot.tf)} · ${slot.info.description} · ${when} UTC`,
                 10 * devicePixelRatio, head * devicePixelRatio / 2);
    c.toBlob(blob => {
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = `${slot.info.ticker}-${slot.tf}-${when.replace(/[: ]/g, '')}.png`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 5000);
    }, 'image/png');
  };

  // ---- copy trade plan ----
  app.on('slot', slot => {
    slot.drawings.menuExtras.push(d => (d.tool === 'long' || d.tool === 'short' ? [{
      label: 'Copy trade plan', value: 'plan',
      run: dd => {
        const [e, t, s] = dd.points.map(p => p.p);
        const f = v => slot.view.fmt(v);
        const rr = Math.abs(t - e) / Math.abs(e - s);
        const text = `${dd.tool.toUpperCase()} ${slot.info.ticker} (${tfLabel(slot.tf)}) entry ${f(e)} `
          + `stop ${f(s)} (${(Math.abs(e - s) / e * 100).toFixed(2)}%) target ${f(t)} `
          + `(${(Math.abs(t - e) / e * 100).toFixed(2)}%) R:R ${rr.toFixed(2)}`;
        navigator.clipboard?.writeText(text).then(() => toast('Trade plan copied', 'ok'), () => toast(text));
      },
    }] : []));
  });
}
