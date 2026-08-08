/* Candidate-table presentation helpers for price-id.html.
   Plain script in browsers; CommonJS export for the dependency-free tests. */

var PriceUI = (function () {
  'use strict';

  var CLASS_ORDER = ['weapon', 'armor', 'ring', 'amulet', 'tool', 'food', 'potion',
    'scroll', 'spellbook', 'wand', 'gem', 'rock', 'other'];

  var CLASS_BADGES = {
    weapon: 'b-red',
    armor: 'b-frost',
    ring: 'b-purple',
    amulet: 'b-yellow',
    tool: 'b-orange',
    food: 'b-green',
    potion: 'b-purple',
    scroll: 'b-yellow',
    spellbook: 'b-frost',
    wand: 'b-orange',
    gem: 'b-green',
    rock: 'b-dim',
    other: 'b-dim'
  };

  var CLASS_INDEX = {};
  CLASS_ORDER.forEach(function (cls, i) { CLASS_INDEX[cls] = i; });

  function classBadgeClass(cls) {
    return CLASS_BADGES[cls] || 'b-dim';
  }

  function itemName(row) {
    return String(row.item.name || '').toLowerCase();
  }

  function sortCandidates(candidates, key, direction) {
    var dir = direction < 0 ? -1 : 1;
    return candidates.slice().sort(function (a, b) {
      var cmp = 0;

      if (key === 'class') {
        var ac = Object.prototype.hasOwnProperty.call(CLASS_INDEX, a.item.class)
          ? CLASS_INDEX[a.item.class] : CLASS_ORDER.length;
        var bc = Object.prototype.hasOwnProperty.call(CLASS_INDEX, b.item.class)
          ? CLASS_INDEX[b.item.class] : CLASS_ORDER.length;
        cmp = ac - bc;
      } else if (key === 'chance') {
        if (!!a.p.known !== !!b.p.known) return a.p.known ? -1 : 1;
        if (a.p.known) cmp = a.p.pct - b.p.pct;
      } else {
        var ai = itemName(a), bi = itemName(b);
        cmp = ai < bi ? -1 : ai > bi ? 1 : 0;
      }

      if (cmp) return cmp * dir;
      var an = itemName(a), bn = itemName(b);
      return an < bn ? -1 : an > bn ? 1 : 0;
    });
  }

  function nextSort(currentKey, currentDirection, selectedKey) {
    if (currentKey === selectedKey) {
      return { key: currentKey, direction: currentDirection < 0 ? 1 : -1 };
    }
    return { key: selectedKey, direction: selectedKey === 'chance' ? -1 : 1 };
  }

  return {
    CLASS_ORDER: CLASS_ORDER,
    classBadgeClass: classBadgeClass,
    sortCandidates: sortCandidates,
    nextSort: nextSort
  };
})();

if (typeof module !== 'undefined' && module.exports) module.exports = PriceUI;
if (typeof window !== 'undefined') window.PriceUI = PriceUI;
