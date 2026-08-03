/* Shared top nav. Add new tools to TOOLS only — every page picks them up.
   Each page provides <div id="nav"></div> as the mount point. */
(function () {
  var TOOLS = [
    { href: '/price-id', label: 'Price ID' },
    { href: '/sokoban', label: 'Sokoban' },
    { href: '/wish', label: 'Wish' },
    { href: '/monsters', label: 'Monsters' },
    { href: '/dungeon', label: 'Dungeon' },
    { href: '/checklist', label: 'Checklist' },
  ];

  function mount() {
    var el = document.getElementById('nav');
    if (!el) return;

    // '/price-id.html', '/price-id/', '/price-id' all normalize to '/price-id'
    var here = location.pathname.replace(/\.html$/, '').replace(/\/+$/, '') || '/';
    var atHome = here === '/' || here === '/index';

    var links = TOOLS.map(function (t) {
      var cur = here === t.href ? ' aria-current="page"' : '';
      return '<a href="' + t.href + '"' + cur + '>' + t.label + '</a>';
    }).join('');

    el.outerHTML =
      '<nav class="nav"><div class="nav-inner">' +
        '<a class="nav-brand" href="/"' + (atHome ? ' aria-current="page"' : '') + '>' +
          "<span class=\"tick\">&gt;</span> statico's nethack tools" +
        '</a>' +
        '<div class="nav-links">' + links + '</div>' +
        '<div class="nav-spacer"></div>' +
        '<div class="nav-links">' +
          '<a href="https://github.com/statico/nethack-tools" rel="noopener">Source</a>' +
          '<button type="button" class="theme-btn" id="theme-btn"></button>' +
        '</div>' +
      '</div></nav>';

    mountTheme();
  }

  /* Theme switcher. Cycles system -> light -> dark and shows where it is now;
     the label says what you are looking at, not what the click will do. */
  var GLYPH = { system: '◐', light: '○', dark: '●' };

  function mountTheme() {
    var btn = document.getElementById('theme-btn');
    if (!btn || !window.NHTheme) return;

    function label() {
      var m = NHTheme.get();
      btn.innerHTML = '<span class="theme-glyph" aria-hidden="true">' + GLYPH[m] + '</span>' +
        '<span class="theme-word">' + m + '</span>';
      btn.setAttribute('aria-label',
        'Theme: ' + m + (m === 'system' ? ' (following your device)' : '') +
        '. Switch to ' + NHTheme.next() + '.');
      btn.title = btn.getAttribute('aria-label');
    }

    btn.addEventListener('click', function () { NHTheme.cycle(); });
    NHTheme.onChange(label);
    label();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', mount);
  } else {
    mount();
  }
})();
