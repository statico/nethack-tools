/* ==========================================================================
   monster-engine.js — NetHack random-monster-generation rules.

   Pure logic, zero DOM access. A port of the eligibility and weighting rules
   in rndmonst()/rndmonst_adj(), src/makemon.c, together with the difficulty
   gates monmin_difficulty()/monmax_difficulty() and the too-weak/too-strong
   tests from include/monst.h. Verified against NetHack-5.0 @ a8a13be; 3.6
   uses the same arithmetic written inline in rndmonst().

   The rule, in full:

     minmlev = level_difficulty / 6                  monmin_difficulty()
     maxmlev = (level_difficulty + u.ulevel) / 2     monmax_difficulty()

     for each mons[i] with LOW_PM <= i < SPECIAL_PM:
       skip if difficulty < minmlev        montooweak()
       skip if difficulty > maxmlev        montoostrong()
       skip if geno & (G_NOGEN | G_UNIQ)   uncommon()
       in Gehennom: skip if maligntyp > A_NEUTRAL   uncommon()
                    skip if geno & G_NOHELL         rndmonst()
       elsewhere:   skip if geno & G_HELL           uncommon()
       weight = (geno & G_FREQ) + align_shift() [+ temperature_shift()]
       skip if weight <= 0

     one of the survivors is then chosen with probability
     weight / sum(weights). 3.6 walks a cumulative total; 3.7 and 5.0 use
     weighted reservoir sampling, which yields the same distribution.

   Note the pieces this deliberately does NOT model, because they depend on
   game state a static page cannot know: mvitals[] (genocided / extinct
   monsters are removed from the pool), the quest branch's qt_montype()
   override, the Rogue level's uppercase-only filter, the elemental planes'
   wrong_elem_type() filter, and goodpos() rejecting a monster that cannot
   survive at the chosen square.

   Loadable as a plain <script> (defines window.MonsterEngine) or via
   require() in node (module.exports).
   ========================================================================== */

var MonsterEngine = (function () {
  'use strict';

  /* include/global.h:411 */
  var ALIGNWEIGHT = 4;
  /* include/align.h */
  var A_NEUTRAL = 0;

  /* Geno bits. Values are asserted against data/monsters.json's legend by
     scripts/test-monsters.mjs, so a change upstream shows up as a failure
     rather than as silently wrong filtering. */
  var G_UNIQ = 0x1000,
    G_NOHELL = 0x0800,
    G_HELL = 0x0400,
    G_NOGEN = 0x0200,
    G_SGROUP = 0x0080,
    G_LGROUP = 0x0040,
    G_FREQ = 0x0007;

  /* C integer division truncates toward zero. Every operand here is an
     int; align_shift() can see negative numerators (maligntyp is signed),
     so plain Math.floor would be wrong. */
  function idiv(a, b) {
    var q = a / b;
    return q < 0 ? Math.ceil(q) : Math.floor(q);
  }

  function minDifficulty(levelDifficulty) {
    return idiv(levelDifficulty, 6);
  }
  function maxDifficulty(levelDifficulty, ulevel) {
    return idiv(levelDifficulty + ulevel, 2);
  }

  /* align_shift(), src/makemon.c. `align` is the *level's* alignment:
     'none', 'lawful', 'neutral' or 'chaotic'. */
  function alignShift(mon, align) {
    var a = mon.al;
    switch (align) {
      case 'lawful':
        return idiv(a + 20, 2 * ALIGNWEIGHT);
      case 'neutral':
        return idiv(20 - Math.abs(a), ALIGNWEIGHT);
      case 'chaotic':
        return idiv(-(a - 20), 2 * ALIGNWEIGHT);
      default:
        return 0;
    }
  }

  function frequency(mon) {
    return mon.g & G_FREQ;
  }

  /* uncommon(), src/makemon.c — minus the mvitals[] (genocide/extinct) test,
     which is per-game state. */
  function uncommon(mon, inHell) {
    if (mon.g & (G_NOGEN | G_UNIQ)) return true;
    if (inHell) return mon.al > A_NEUTRAL;
    return (mon.g & G_HELL) !== 0;
  }

  /* The full per-monster weight rndmonst() would compute. Returns 0 for any
     monster that cannot be generated at all under these conditions. */
  function weight(mon, opts) {
    var w = frequency(mon) + alignShift(mon, opts.align || 'none');
    if (opts.temperature) w += 3; /* temperature_shift(), 3.7/5.0 only */
    return w;
  }

  /* Everything rndmonst() checks, as a list of reasons. An empty list means
     the monster is a legal candidate. */
  function rejections(mon, index, opts) {
    var out = [];
    if (index >= opts.specialPm) out.push('past SPECIAL_PM (never generated randomly)');
    if (mon.g & G_NOGEN) out.push('G_NOGEN');
    if (mon.g & G_UNIQ) out.push('G_UNIQ');
    if (opts.inHell) {
      if (mon.al > A_NEUTRAL) out.push('lawful, and Gehennom admits only maligntyp <= 0');
      if (mon.g & G_NOHELL) out.push('G_NOHELL');
    } else if (mon.g & G_HELL) {
      out.push('G_HELL');
    }
    if (mon.d < opts.minmlev) out.push('too weak (difficulty ' + mon.d + ' < ' + opts.minmlev + ')');
    if (mon.d > opts.maxmlev) out.push('too strong (difficulty ' + mon.d + ' > ' + opts.maxmlev + ')');
    if (!out.length && weight(mon, opts) <= 0) out.push('generation weight 0');
    return out;
  }

  function eligible(mon, index, opts) {
    return rejections(mon, index, opts).length === 0;
  }

  /* Resolve a user-facing query into the exact gate values rndmonst() uses. */
  function conditions(q) {
    var ld = Math.max(0, q.levelDifficulty | 0);
    var xl = Math.max(1, q.ulevel | 0);
    return {
      levelDifficulty: ld,
      ulevel: xl,
      minmlev: minDifficulty(ld),
      maxmlev: maxDifficulty(ld, xl),
      inHell: !!q.inHell,
      align: q.align || 'none',
      temperature: !!q.temperature,
      specialPm: q.specialPm
    };
  }

  /* The candidate pool for a set of conditions, with each monster's exact
     selection probability. */
  function pool(mons, q) {
    var opts = conditions(q);
    var hits = [];
    var total = 0;
    for (var i = 0; i < mons.length && i < opts.specialPm; i++) {
      var m = mons[i];
      if (!eligible(m, i, opts)) continue;
      var w = weight(m, opts);
      total += w;
      hits.push({ mon: m, index: i, weight: w });
    }
    for (var j = 0; j < hits.length; j++) {
      hits[j].chance = total > 0 ? hits[j].weight / total : 0;
    }
    return { conditions: opts, total: total, list: hits };
  }

  /* ---------------------------------------------------------------------- *
   * Decoding helpers for the compact JSON records                          *
   * ---------------------------------------------------------------------- */

  /* legend entries are [bitvalue, SYMBOL, "readable label"] */
  function bits(value, legend) {
    var out = [];
    for (var i = 0; i < legend.length; i++) {
      var b = legend[i][0];
      /* M1_NOLIMBS and M1_OMNIVORE are unions of two bits; only report them
         when *every* bit is present, exactly as the C tests do. */
      if (b !== 0 && (value & b) === b) out.push({ bit: b, sym: legend[i][1], label: legend[i][2] });
    }
    return out;
  }

  function attackText(a, legend) {
    var at = legend.at[String(a[0])];
    var ad = legend.ad[String(a[1])];
    var dice = a[2] > 0 && a[3] > 0 ? a[2] + 'd' + a[3] : a[3] > 0 ? '0d' + a[3] : '';
    return {
      atSym: at ? at[0] : 'AT_?',
      at: at ? at[1] : '?',
      adSym: ad ? ad[0] : 'AD_?',
      ad: ad ? ad[1] : '?',
      severity: ad && ad.length > 2 ? ad[2] : null,
      dice: dice
    };
  }

  /* Highest-severity damage type on the monster, or null. */
  var SEV_RANK = { red: 3, orange: 2, yellow: 1 };
  function worstSeverity(mon, legend) {
    var worst = null;
    for (var i = 0; i < mon.a.length; i++) {
      var ad = legend.ad[String(mon.a[i][1])];
      var s = ad && ad.length > 2 ? ad[2] : null;
      if (s && (!worst || SEV_RANK[s] > SEV_RANK[worst])) worst = s;
    }
    return worst;
  }

  function groupSize(mon) {
    if (mon.g & G_LGROUP) return 'large group';
    if (mon.g & G_SGROUP) return 'small group';
    return null;
  }

  var API = {
    ALIGNWEIGHT: ALIGNWEIGHT,
    G_UNIQ: G_UNIQ,
    G_NOHELL: G_NOHELL,
    G_HELL: G_HELL,
    G_NOGEN: G_NOGEN,
    G_SGROUP: G_SGROUP,
    G_LGROUP: G_LGROUP,
    G_FREQ: G_FREQ,
    idiv: idiv,
    minDifficulty: minDifficulty,
    maxDifficulty: maxDifficulty,
    alignShift: alignShift,
    frequency: frequency,
    uncommon: uncommon,
    weight: weight,
    rejections: rejections,
    eligible: eligible,
    conditions: conditions,
    pool: pool,
    bits: bits,
    attackText: attackText,
    worstSeverity: worstSeverity,
    groupSize: groupSize
  };
  return API;
})();

if (typeof module !== 'undefined' && module.exports) module.exports = MonsterEngine;
if (typeof window !== 'undefined') window.MonsterEngine = MonsterEngine;
