// Auto / Light / Dark. CSS colors resolve through color-scheme (light-dark()); canvas code listens for "themechange".
import { $$ } from './util.js';

const THEMES = ['auto', 'light', 'dark'];
const sysDark = matchMedia('(prefers-color-scheme: dark)');
let current = 'auto';
const fire = () => window.dispatchEvent(new Event('themechange'));

export function applyTheme(t, persist = true) {
  current = THEMES.includes(t) ? t : 'auto';
  if (current === 'auto') document.documentElement.removeAttribute('data-theme');
  else document.documentElement.dataset.theme = current;
  $$('[data-theme-set]').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.themeSet === current)));
  if (persist) {
    try { localStorage.setItem('theme', current); } catch (e) { /* storage blocked */ }
  }
  fire();
}

export function initTheme() {
  let t = 'auto';
  try { t = localStorage.getItem('theme') || 'auto'; } catch (e) { /* storage blocked */ }
  $$('[data-theme-set]').forEach((b) => b.addEventListener('click', () => applyTheme(b.dataset.themeSet)));
  sysDark.addEventListener('change', () => { if (current === 'auto') fire(); });
  applyTheme(t, false);
}

export const isDark = () => current === 'dark' || (current === 'auto' && sysDark.matches);
export const onTheme = (fn) => window.addEventListener('themechange', fn);
