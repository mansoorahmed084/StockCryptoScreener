// Bar replay: hide the candles after a point you click, then step or play
// them back one by one. Drawings and indicators follow along.

import { $, toast } from './dom.js';

const SPEEDS = [[1000, '1×'], [400, '3×'], [150, '10×']];

export function initReplay(app) {
  const btn = document.createElement('button');
  btn.className = 'tb-btn';
  btn.title = 'Bar replay';
  btn.innerHTML = '<span>⏮</span><span>Replay</span>';
  $('#tb-extra').appendChild(btn);

  btn.onclick = () => {
    const slot = app.slot;
    if (!slot?.info) return;
    if (slot.replay) { exit(slot); return; }
    if (app.replayPick) { stopPick(); return; }
    app.replayPick = slot;
    btn.classList.add('on');
    slot.el.classList.add('replay-pick');
    toast('Click the candle to start the replay from (Esc to cancel)');
  };

  function stopPick() {
    if (app.replayPick) app.replayPick.el.classList.remove('replay-pick');
    app.replayPick = null;
    btn.classList.toggle('on', !!app.slot?.replay);
  }

  app.on('slot', slot => {
    // Picking the start candle.
    slot.host.addEventListener('mousedown', e => {
      if (app.replayPick !== slot || e.button !== 0) return;
      e.stopPropagation();
      e.preventDefault();
      const r = slot.host.getBoundingClientRect();
      const l = slot.view.chart.timeScale().coordinateToLogical(e.clientX - r.left);
      stopPick();
      if (l === null) return;
      start(slot, Math.max(10, Math.min(slot.view.bars.length - 2, Math.round(l))));
    }, true);
    // A new symbol or timeframe ends the replay.
    slot.on('loaded', () => { if (slot.replay && !slot.replay.exiting) cleanup(slot); });
  });

  app.on('keydown', e => {
    if (e.key === 'Escape' && app.replayPick) { stopPick(); return true; }
    const r = app.slot?.replay;
    if (!r) return false;
    if (e.key === 'ArrowRight' && e.shiftKey) { step(app.slot); return true; }
    return false;
  });

  function start(slot, i) {
    const all = slot.view.bars.slice();
    if (slot.feed) { slot.feed.stop(); slot.feed = null; }   // no live candles while replaying
    const bars = all.slice(0, i + 1);
    slot.replay = { all, i, bars, timer: null, speed: SPEEDS[0][0] };
    slot.view.setData(slot.info, slot.tf, bars);
    slot.view.showCountdown = false;
    slot.view.chart.timeScale().scrollToRealTime();
    controls(slot);
    btn.classList.add('on');
  }

  function step(slot) {
    const r = slot.replay;
    if (!r || r.i + 1 >= r.all.length) { pause(slot); return; }
    r.i += 1;
    const bar = r.all[r.i];
    r.bars.push(bar);
    slot.view.update(bar);
    label(slot);
  }

  function play(slot) {
    const r = slot.replay;
    pause(slot);
    r.timer = setInterval(() => step(slot), r.speed);
    label(slot);
  }

  function pause(slot) {
    const r = slot.replay;
    if (r?.timer) { clearInterval(r.timer); r.timer = null; }
    if (r) label(slot);
  }

  function label(slot) {
    const r = slot.replay, el = slot.replayEl;
    if (!r || !el) return;
    el.querySelector('[data-a=play]').textContent = r.timer ? '⏸' : '▶';
    const b = r.all[r.i];
    el.querySelector('.rp-when').textContent =
      `${new Date(b.time * 1000).toISOString().slice(0, 16).replace('T', ' ')} UTC · ${r.all.length - 1 - r.i} left`;
  }

  function controls(slot) {
    const el = document.createElement('div');
    el.className = 'replay-bar';
    el.innerHTML = `
      <span class="rp-title">Replay</span>
      <button data-a="play" title="Play / pause">▶</button>
      <button data-a="step" title="Next candle (Shift+→)">⏭</button>
      <select data-a="speed" title="Speed">${SPEEDS.map(([ms, l]) => `<option value="${ms}">${l}</option>`).join('')}</select>
      <span class="rp-when"></span>
      <button data-a="exit" title="Back to live">✕ Exit</button>`;
    el.addEventListener('mousedown', e => e.stopPropagation());
    el.querySelector('[data-a=play]').onclick = () => (slot.replay.timer ? pause(slot) : play(slot));
    el.querySelector('[data-a=step]').onclick = () => { pause(slot); step(slot); };
    el.querySelector('[data-a=speed]').onchange = e => {
      slot.replay.speed = +e.target.value;
      if (slot.replay.timer) play(slot);
    };
    el.querySelector('[data-a=exit]').onclick = () => exit(slot);
    slot.el.appendChild(el);
    slot.replayEl = el;
    label(slot);
  }

  function cleanup(slot) {
    pause(slot);
    slot.replayEl?.remove();
    slot.replayEl = null;
    slot.replay = null;
    btn.classList.remove('on');
  }

  async function exit(slot) {
    if (!slot.replay) return;
    slot.replay.exiting = true;
    cleanup(slot);
    await slot.load(slot.info.symbol, slot.tf);   // back to live data
  }
}
