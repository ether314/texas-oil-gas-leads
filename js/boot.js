// Runs before first paint: marks the page as scripted (reveal-on-scroll only hides content while JS runs) and applies a saved
// Light or Dark choice so it does not flash the other theme.
(function () {
  var root = document.documentElement;
  root.classList.add('js');
  if (/[?&]still\b/.test(location.search)) root.classList.add('still'); // QA only: no motion, no reveal
  try {
    var t = localStorage.getItem('theme');
    if (t === 'light' || t === 'dark') root.setAttribute('data-theme', t);
  } catch (e) { /* storage blocked */ }
})();
