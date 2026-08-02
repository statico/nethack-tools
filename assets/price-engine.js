/* ==========================================================================
   price-engine.js — NetHack shop pricing math.

   Pure integer arithmetic, zero DOM access. Faithful port of get_cost() and
   set_cost() from NetHack src/shk.c (verified against NetHack-5.0 @ a8a13be;
   the code is unchanged in 3.6 and 3.7 apart from cosmetics).

   The two things other calculators get wrong and this one does not:
     1. the round-half-up tweak  tmp = (((tmp*10)/divisor)+5)/10  with C
        integer (truncating) division at BOTH divisions;
     2. the artifact ×4 and the angry-shopkeeper surcharge being applied
        AFTER that rounding, not folded into the multiplier.

   Loadable as a plain <script> (defines window.PriceEngine) or via
   require() in node (module.exports).
   ========================================================================== */

var PriceEngine = (function () {
  'use strict';

  /* Highest base cost in the object tables (Amulet of Yendor). The reverse
     lookup brute-forces every base cost up to this; ~30k iterations per
     surcharge branch is instantaneous. */
  var MAX_BASE = 30000;

  /* ---------------------------------------------------------------------- *
   * Core arithmetic                                                        *
   * ---------------------------------------------------------------------- */

  /* The shared rounding tweak used by both get_cost() and set_cost():
       tmp *= multiplier;
       if (divisor > 1) { tmp *= 10; tmp /= divisor; tmp += 5; tmp /= 10; }
     C integer division truncates; all values here are non-negative, so
     Math.floor is equivalent. */
  function applyTweak(tmp, multiplier, divisor) {
    tmp = tmp * multiplier;
    if (divisor > 1) {
      tmp = Math.floor((Math.floor((tmp * 10) / divisor) + 5) / 10);
    }
    return tmp;
  }

  /* Charisma ladder from get_cost(). Exactly one rung applies. */
  function chaFactor(cha) {
    if (cha > 18) return { m: 1, d: 2, why: 'Cha ' + cha + ' (>18): ÷2' };
    if (cha === 18) return { m: 2, d: 3, why: 'Cha 18: ×2/3' };
    if (cha >= 16) return { m: 3, d: 4, why: 'Cha ' + cha + ' (16-17): ×3/4' };
    if (cha >= 11) return { m: 1, d: 1, why: 'Cha ' + cha + ' (11-15): no change' };
    if (cha >= 8) return { m: 4, d: 3, why: 'Cha ' + cha + ' (8-10): ×4/3' };
    if (cha >= 6) return { m: 3, d: 2, why: 'Cha ' + cha + ' (6-7): ×3/2' };
    return { m: 2, d: 1, why: 'Cha ' + cha + ' (≤5): ×2' };
  }

  /* True when one of the mutually exclusive "you look like a rube" modifiers
     is in play. In C these are if / else-if, so they never stack. */
  function rubeModifier(o) {
    if (o.dunce) return 'dunce cap worn: ×4/3';
    if (o.touristy) return 'Tourist below XL14 / visible tourist shirt: ×4/3';
    return null;
  }

  /* ---------------------------------------------------------------------- *
   * get_cost — what the shopkeeper charges YOU (buy price)                 *
   * ---------------------------------------------------------------------- */
  /* opts: { cha, surcharge, dunce, touristy, artifact, angry }
     `surcharge` is the unknowable 1-in-4 unidentified markup
     (oid_price_adjustment(): (o_id % 4) == 0).
     `trace` is an optional array that receives human-readable steps. */
  function getCost(base, opts, trace) {
    opts = opts || {};
    var tmp = base | 0;
    var m = 1, d = 1;

    if (!tmp) {
      tmp = 5;
      if (trace) trace.push('base cost 0 → shk quotes it as 5');
    } else if (trace) {
      trace.push('base cost ' + tmp);
    }

    if (opts.surcharge) {
      m *= 4; d *= 3;
      if (trace) trace.push('unidentified surcharge (shk rolled it): ×4/3');
    }

    var rube = rubeModifier(opts);
    if (rube) {
      m *= 4; d *= 3;
      if (trace) trace.push(rube);
    }

    var cha = chaFactor(normCha(opts.cha));
    m *= cha.m; d *= cha.d;
    if (trace) trace.push(cha.why);

    var pre = tmp * m;
    tmp = applyTweak(tmp, m, d);
    if (trace) {
      trace.push(
        d > 1
          ? 'round: floor((floor(' + pre + '×10 / ' + d + ') + 5) / 10) = ' + tmp
          : 'no division, price = ' + tmp
      );
    }

    if (tmp <= 0) {
      tmp = 1;
      if (trace) trace.push('clamped up to 1');
    }

    if (opts.artifact) {
      tmp *= 4;
      if (trace) trace.push('artifact ×4 (applied AFTER rounding) = ' + tmp);
    }

    if (opts.angry) {
      tmp += Math.floor((tmp + 2) / 3);
      if (trace) trace.push('angry shk surcharge +(x+2)/3 (AFTER rounding) = ' + tmp);
    }

    return tmp;
  }

  /* ---------------------------------------------------------------------- *
   * set_cost — what the shopkeeper pays YOU (sell price), quantity 1       *
   * ---------------------------------------------------------------------- */
  /* opts: { surcharge, dunce, touristy, gem }
     No charisma effect and no anger surcharge when selling.
     `gem` short-circuits: an unidentified gemstone/glass is bought for
     3-8 zorkmids flat, so its price carries no information at all. */
  function setCost(base, opts, trace) {
    opts = opts || {};
    var tmp = base | 0;
    var m = 1, d = 2;

    if (trace) trace.push('base cost ' + tmp);

    var rube = rubeModifier(opts);
    if (rube) {
      d = 3;
      if (trace) trace.push(rube.replace('×4/3', '÷3 instead of ÷2'));
    } else if (trace) {
      trace.push('shk keeps half: ÷2');
    }

    /* C also requires tmp > 1 before applying the sell-side markdown. */
    if (opts.surcharge && tmp > 1) {
      m *= 3; d *= 4;
      if (trace) trace.push('unidentified markdown (shk m_id % 4 == 0): ×3/4');
    }

    if (tmp >= 1) {
      var pre = tmp * m;
      tmp = applyTweak(tmp, m, d);
      if (trace) {
        trace.push('round: floor((floor(' + pre + '×10 / ' + d + ') + 5) / 10) = ' + tmp);
      }
      if (tmp < 1) {
        tmp = 1;
        /* never adjust a nonzero price down to zero */
        if (trace) trace.push('clamped up to 1 (never round a nonzero price to 0)');
      }
    } else if (trace) {
      trace.push('base cost 0 → shk offers nothing');
    }

    return tmp;
  }

  function normCha(cha) {
    cha = parseInt(cha, 10);
    if (isNaN(cha)) cha = 11;
    return Math.max(3, Math.min(25, cha));
  }

  /* Price for one observation's settings, given a base cost and a choice of
     the unknowable surcharge branch. */
  function priceFor(base, obs, surcharge, trace) {
    var o = {
      cha: obs.cha,
      dunce: !!obs.dunce,
      touristy: !!obs.touristy,
      artifact: !!obs.artifact,
      angry: !!obs.angry,
      surcharge: !!surcharge
    };
    return obs.direction === 'sell' ? setCost(base, o, trace) : getCost(base, o, trace);
  }

  /* ---------------------------------------------------------------------- *
   * Reverse lookup                                                         *
   * ---------------------------------------------------------------------- */
  /* Brute force every base cost forward through the algorithm, across both
     branches of the unknown surcharge, and keep exact matches. The
     round-half-up tweak makes analytic inversion wrong, so we do not try.

     obs: { price, direction, cha, dunce, touristy, angry, artifact }
     returns [ { base, branches: [ {surcharge:boolean} ] } ] ascending by base. */
  function reverse(obs) {
    var target = obs.price | 0;
    var out = [];
    var maxBase = obs.maxBase || MAX_BASE;
    if (!(target >= 0)) return out;

    for (var b = 1; b <= maxBase; b++) {
      var branches = null;
      if (priceFor(b, obs, false) === target) branches = [{ surcharge: false }];
      if (priceFor(b, obs, true) === target) {
        (branches = branches || []).push({ surcharge: true });
      }
      if (branches) out.push({ base: b, branches: branches });
    }
    return out;
  }

  /* Full derivation for one (base, branch) pair — used by the <details> UI. */
  function explain(base, obs, surcharge) {
    var trace = [];
    var price = priceFor(base, obs, surcharge, trace);
    return { price: price, surcharge: !!surcharge, steps: trace };
  }

  /* Intersect several reverse() results. Returns the sorted list of base
     costs that satisfy every observation, plus per-observation branch info. */
  function intersect(results) {
    if (!results.length) return [];
    var acc = null;
    results.forEach(function (list) {
      var here = Object.create(null);
      list.forEach(function (r) { here[r.base] = r.branches; });
      if (acc === null) {
        acc = here;
      } else {
        var next = Object.create(null);
        Object.keys(acc).forEach(function (k) {
          if (here[k]) next[k] = acc[k];
        });
        acc = next;
      }
    });
    return Object.keys(acc)
      .map(Number)
      .sort(function (a, b) { return a - b; });
  }

  /* ---------------------------------------------------------------------- *
   * Object-table helpers                                                   *
   * ---------------------------------------------------------------------- */

  /* Only weapons and armor get the +N price bump, and only for spe > 0. */
  var ENCHANTABLE = { weapon: 1, armor: 1 };

  /* The effective base cost the shk prices from, for an item with spe = n. */
  function effectiveBase(item, ench) {
    var e = ench > 0 ? ench | 0 : 0;
    return item.cost + (e && ENCHANTABLE[item.class] ? 10 * e : 0);
  }

  /* Items from `objects` whose effective base cost equals `base`.
     cost === 0 items are excluded from candidate output (they are only in the
     data so the probability denominators come out right). */
  function itemsForBase(objects, base, ench) {
    var out = [];
    for (var i = 0; i < objects.length; i++) {
      var it = objects[i];
      if (it.cost <= 0) continue;
      if (effectiveBase(it, ench) === base) out.push(it);
    }
    return out;
  }

  /* ---------------------------------------------------------------------- *
   * Probability                                                            *
   * ---------------------------------------------------------------------- */
  /* Generation probability of an item within its own class.

     Caveats baked in:
       - `other` lumps several C object classes together, so its 4000 total is
         not a meaningful denominator -> suppressed.
       - In 3.6 every ring has prob 0 (that is literally what objects.c says;
         the ring class is filled uniformly at random instead) -> reported as
         uniform 1/N rather than 0%.
       - Denominators always come from class_prob_totals, never a hardcoded
         1000: 5.0 weapons sum to 1002 because silver mace was added without
         rebalancing.

     returns { known, uniform, pct, denom } */
  function classProbability(item, totals, classCounts) {
    var cls = item.class;
    if (cls === 'other') return { known: false, uniform: false, pct: 0, denom: 0 };

    var denom = totals && totals[cls];
    if (!denom) {
      /* whole class has zero total: 3.6 rings. Uniform over the class. */
      var n = (classCounts && classCounts[cls]) || 0;
      return n
        ? { known: true, uniform: true, pct: 100 / n, denom: n }
        : { known: false, uniform: false, pct: 0, denom: 0 };
    }
    return {
      known: true,
      uniform: false,
      pct: (item.prob * 100) / denom,
      denom: denom
    };
  }

  /* ---------------------------------------------------------------------- *
   * Special cases worth warning about                                      *
   * ---------------------------------------------------------------------- */

  /* An unidentified glass gem is priced as one of two valuable lookalikes of
     the same color, chosen once per game from ubirthday. So a gem's buy price
     is drawn from the valuable gem's cost, and any gem price is deeply
     ambiguous. Table from get_cost() in shk.c. */
  var GLASS_LOOKALIKES = [
    { color: 'white', gems: ['diamond', 'opal'] },
    { color: 'blue', gems: ['sapphire', 'aquamarine'] },
    { color: 'red', gems: ['ruby', 'jasper'] },
    { color: 'yellowish brown', gems: ['amber', 'topaz'] },
    { color: 'orange', gems: ['jacinth', 'agate'] },
    { color: 'yellow', gems: ['citrine', 'chrysoberyl'] },
    { color: 'black', gems: ['black opal', 'jet'] },
    { color: 'green', gems: ['emerald', 'jade'] },
    { color: 'violet', gems: ['amethyst', 'fluorite'] }
  ];

  /* Gray stones are GEM_CLASS but neither GEMSTONE nor GLASS material, so the
     flat 3-8 zorkmid sell price does not apply to them. */
  var GRAY_STONES = {
    luckstone: 1, loadstone: 1, touchstone: 1, flint: 1, rock: 1
  };

  function isGemOrGlass(item) {
    return item.class === 'gem' && !GRAY_STONES[item.name];
  }

  /* ---------------------------------------------------------------------- */

  var API = {
    MAX_BASE: MAX_BASE,
    applyTweak: applyTweak,
    chaFactor: chaFactor,
    getCost: getCost,
    setCost: setCost,
    priceFor: priceFor,
    reverse: reverse,
    explain: explain,
    intersect: intersect,
    effectiveBase: effectiveBase,
    itemsForBase: itemsForBase,
    classProbability: classProbability,
    isGemOrGlass: isGemOrGlass,
    GLASS_LOOKALIKES: GLASS_LOOKALIKES,
    GRAY_STONES: GRAY_STONES
  };
  return API;
})();

if (typeof module !== 'undefined' && module.exports) module.exports = PriceEngine;
if (typeof window !== 'undefined') window.PriceEngine = PriceEngine;
