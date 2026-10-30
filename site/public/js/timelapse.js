// "Watch Texas drill": replays the located permits by issue date over the last 24 months in about 12 seconds.
// The engine does the drawing (settled dots in a cached layer, the newest days glowing); this module owns the clock and the controls.
// With reduced motion there is no autoplay and no play button: the scrubber alone moves through time.
import { el, fmt, dayLabel, reduced } from './util.js';
import { icon } from './icons.js';

export function createTimelapse({ engine, t0, coverage }) {
  const [tMin, tMax] = engine.tlRange;
  const DUR = 12000; const calm = reduced();
  let cur = tMax; let playing = false; let raf = 0; let last = 0; let open = false;
  const playBtn = calm ? null : el('button', { type: 'button', class: 'ibtn tl-play', 'aria-label': 'Play' }, icon('play', 18));
  const range = el('input', { type: 'range', class: 'tl-range', min: tMin, max: tMax, step: 1, value: tMax, 'aria-label': 'Replay date' });
  const dateEl = el('span', { class: 'tl-date' }); const countEl = el('span', { class: 'tl-count' });
  const bar = el('div', { class: 'tl-bar' + (calm ? ' calm' : ''), hidden: true, role: 'group', 'aria-label': 'Watch Texas drill: replay of located permits by issue date' },
    playBtn,
    el('div', { class: 'tl-mid' }, range, el('div', { class: 'tl-ends' }, el('span', { text: dayLabel(t0 + tMin * 864e5) }), el('span', { text: dayLabel(t0 + tMax * 864e5) }))),
    el('div', { class: 'tl-read', 'aria-hidden': 'true' }, dateEl, countEl),
    el('p', { class: 'tl-note' }, el('strong', { text: 'Located permits only. ' }),
      'Dots are the ' + Math.round(coverage.share24 * 100) + '% of the last 24 months of permits (' + Math.round(coverage.share12 * 100)
      + '% of the last 12) with a recorded surface location, so the busiest counties look quiet. Read the shading for the full counts.'));

  function paint() {
    const day = Math.floor(cur);
    range.style.setProperty('--p', (((cur - tMin) / (tMax - tMin)) * 100).toFixed(2) + '%');
    if (+range.value !== day) range.value = day;
    const n = engine.tlCount(cur); const d = dayLabel(t0 + day * 864e5);
    if (dateEl.textContent !== d) dateEl.textContent = d;
    const c = fmt.format(n) + ' located permit' + (n === 1 ? '' : 's') + ' so far';
    if (countEl.textContent !== c) countEl.textContent = c;
    range.setAttribute('aria-valuetext', d + ', ' + c);
  }
  const push = () => { engine.setTimelapse(true, cur); paint(); };
  function tick(now) {
    raf = 0;
    if (!playing) return;
    const dt = last ? Math.min(80, now - last) : 16; last = now;
    cur = Math.min(tMax, cur + dt * ((tMax - tMin) / DUR));
    push();
    if (cur >= tMax) setPlaying(false); else raf = requestAnimationFrame(tick);
  }
  function setPlaying(p) {
    playing = p; last = 0;
    if (playBtn) {
      const label = p ? 'Pause' : cur >= tMax ? 'Replay' : 'Play';
      playBtn.replaceChildren(icon(p ? 'pause' : cur >= tMax ? 'replay' : 'play', 18)); playBtn.setAttribute('aria-label', label); playBtn.title = label;
    }
    if (p && !raf) raf = requestAnimationFrame(tick);
  }
  if (playBtn) playBtn.addEventListener('click', () => { if (playing) setPlaying(false); else { if (cur >= tMax) cur = tMin; setPlaying(true); } });
  range.addEventListener('input', () => { cur = +range.value; setPlaying(false); push(); });
  document.addEventListener('visibilitychange', () => { if (document.hidden) setPlaying(false); });

  return {
    bar,
    get open() { return open; },
    show() { open = true; bar.hidden = false; cur = calm ? tMax : tMin; push(); setPlaying(!calm); },
    hide() { open = false; bar.hidden = true; setPlaying(false); engine.setTimelapse(false); },
    pause() { setPlaying(false); },
    refresh() { if (open) push(); },
    // QA: jump to a fraction of the replay without waiting for the clock
    seek(f) { cur = tMin + (tMax - tMin) * f; setPlaying(false); push(); },
    get playing() { return playing; },
  };
}
