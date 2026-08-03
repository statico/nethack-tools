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
        '</div>' +
      '</div></nav>';
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', mount);
  } else {
    mount();
  }
})();
