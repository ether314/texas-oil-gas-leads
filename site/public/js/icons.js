// A small inline-SVG icon set: 24px grid, 1.5px stroke, round caps. Paths are constants, never data.
import { svg } from './util.js';

const PATHS = {
  drop: 'M12 3.5C15.2 7.4 18 10.4 18 13.5a6 6 0 0 1-12 0C6 10.4 8.8 7.4 12 3.5Z|M9 14.2a3 3 0 0 0 2.3 2.7',
  flame: 'M12 3c.6 3.3 5 5.4 5 9.7a5 5 0 0 1-10 0c0-2.2 1-3.7 2.2-4.8.1 1.5.8 2.4 1.9 2.8C10.6 8.7 10.8 5.8 12 3Z',
  rig: 'M12 3 7.5 20.5|M12 3l4.5 17.5|M8.6 16h6.8|M9.9 11.2h4.2|M11 6.9h2|M5.5 20.5h13',
  factory: 'M3 20.5v-11l6 4v-4l6 4v-9h4.5v16Z|M7 17h2|M12 17h2',
  pipe: 'M2.5 9.5h19|M2.5 14.5h19|M7 6.5v11|M17 6.5v11',
  jobs: 'M5 15.5a7 7 0 0 1 14 0|M3 15.5h18v3H3Z|M10.5 8.8h3v6.7h-3Z',
  dollar: 'M12 3.5v17|M16 7.5c-.7-1.3-2.2-2-4-2-2.3 0-4 1.2-4 3 0 4.3 8 2.2 8 6.5 0 1.8-1.7 3-4 3-1.9 0-3.5-.8-4.2-2.2',
  pin: 'M12 21s-6.5-5.7-6.5-11a6.5 6.5 0 0 1 13 0c0 5.3-6.5 11-6.5 11Z|M12 12.3a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5Z',
  calendar: 'M4 6.5h16V20H4Z|M4 10.5h16|M8 4v4|M16 4v4',
  chart: 'M4 19.5h16|M5.5 15l4-5 3.5 3 5.5-7',
  trend: 'M4 17l5-5 3.5 3.5L20 8|M14.5 8H20v5.5',
  layers: 'M12 3.5 21 8l-9 4.5L3 8Z|M3 12l9 4.5L21 12|M3 16l9 4.5 9-4.5',
  gem: 'M6.5 4h11L21 9l-9 11.5L3 9Z|M3 9h18|M9.5 4 8 9l4 11.5L16 9l-1.5-5',
  share: 'M12 15V4|M8 7.5 12 3.5l4 4|M5 11.5v8h14v-8',
  arrow: 'M5 12h14|M13 6l6 6-6 6',
  check: 'M5 12.5 9.5 17 19 7.5',
  building: 'M5.5 20.5V4.5h9v16|M14.5 9.5h4v11|M3.5 20.5h17|M8.5 8h3|M8.5 11.5h3|M8.5 15h3',
  replay: 'M4 12a8 8 0 1 0 2.5-5.8|M4 4.5V9h4.5',
  bulb: 'M9 18.5h6|M10 21h4|M12 3.5a6 6 0 0 0-3.5 10.9c.6.5 1 1.2 1 2.1h5c0-.9.4-1.6 1-2.1A6 6 0 0 0 12 3.5Z',
  clock: 'M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Z|M12 7.5V12l3 2',
  close: 'M6.5 6.5l11 11|M17.5 6.5l-11 11',
  play: 'M8 5.5v13l10.5-6.5Z',
  pause: 'M7 5h3.5v14H7Z|M13.5 5H17v14h-3.5Z',
};
const FILLED = new Set(['play', 'pause']);

export function icon(name, size = 18, cls = '') {
  const d = PATHS[name];
  if (!d) return null;
  const filled = FILLED.has(name);
  return svg('svg', {
    class: 'ico' + (cls ? ' ' + cls : ''), width: size, height: size, viewBox: '0 0 24 24', fill: filled ? 'currentColor' : 'none',
    stroke: filled ? 'none' : 'currentColor', 'stroke-width': 1.5, 'stroke-linecap': 'round', 'stroke-linejoin': 'round', 'aria-hidden': 'true', focusable: 'false',
  }, d.split('|').map((p) => svg('path', { d: p })));
}
