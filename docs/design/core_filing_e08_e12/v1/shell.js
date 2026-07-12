/* Prototype chrome wiring — theme toggle persists to localStorage 'ls-theme'
   exactly like the shipped app (App.tsx). No app logic; presentation only. */
(function () {
  var root = document.documentElement;
  var btn = document.getElementById('themeBtn');
  function label() {
    if (!btn) return;
    var dark = root.getAttribute('data-theme') === 'dark';
    btn.textContent = dark ? 'Light' : 'Dark';
    btn.setAttribute('aria-label', 'Switch to ' + (dark ? 'light' : 'dark') + ' theme');
  }
  label();
  if (btn) {
    btn.addEventListener('click', function () {
      var next = root.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
      root.setAttribute('data-theme', next);
      try { localStorage.setItem('ls-theme', next); } catch (e) {}
      label();
    });
  }
  // Allow the gallery (index.html) to drive theme across embedded iframes.
  window.addEventListener('message', function (ev) {
    if (ev && ev.data && ev.data.lsTheme) {
      root.setAttribute('data-theme', ev.data.lsTheme);
      try { localStorage.setItem('ls-theme', ev.data.lsTheme); } catch (e) {}
      label();
    }
  });
})();
