/* Theme preference. Loaded synchronously from <head> — before any painting —
   so a stored choice is applied without a flash of the wrong theme.

   Three states: 'system' (no attribute, smui.css's prefers-color-scheme rule
   decides), 'light', and 'dark'. The switcher lives in assets/nav.js. */
(function () {
  var KEY = 'nht-theme';
  var MODES = ['system', 'light', 'dark'];
  var listeners = [];

  function stored() {
    try {
      var v = localStorage.getItem(KEY);
      return MODES.indexOf(v) > 0 ? v : 'system';
    } catch (e) {
      return 'system';           // private mode, or storage disabled
    }
  }

  function apply(mode) {
    if (mode === 'system') document.documentElement.removeAttribute('data-theme');
    else document.documentElement.setAttribute('data-theme', mode);
  }

  function set(mode) {
    if (MODES.indexOf(mode) < 0) mode = 'system';
    try {
      if (mode === 'system') localStorage.removeItem(KEY);
      else localStorage.setItem(KEY, mode);
    } catch (e) { /* preference just won't persist */ }
    apply(mode);
    listeners.forEach(function (fn) { fn(mode); });
  }

  window.NHTheme = {
    MODES: MODES,
    get: stored,
    set: set,
    next: function () { return MODES[(MODES.indexOf(stored()) + 1) % MODES.length]; },
    cycle: function () { set(window.NHTheme.next()); return stored(); },
    /* true when the page is currently rendering dark, whichever mode is set */
    isDark: function () {
      var m = stored();
      if (m !== 'system') return m === 'dark';
      return !!(window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches);
    },
    onChange: function (fn) { listeners.push(fn); }
  };

  apply(stored());

  // In 'system' mode, follow the OS if it changes while the page is open.
  if (window.matchMedia) {
    var mq = window.matchMedia('(prefers-color-scheme: dark)');
    var relay = function () {
      if (stored() === 'system') listeners.forEach(function (fn) { fn('system'); });
    };
    if (mq.addEventListener) mq.addEventListener('change', relay);
    else if (mq.addListener) mq.addListener(relay);
  }
})();
