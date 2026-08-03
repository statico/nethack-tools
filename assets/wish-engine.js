/* ==========================================================================
   wish-engine.js — what NetHack actually gives you for a wish.

   Pure logic, zero DOM access: it builds the canonical wish string and
   evaluates readobjnam()'s rules against it.  All object/artifact facts
   arrive as the data argument (data/wish.json + data/objects.json); nothing
   about the game is hardcoded here except the shape of the rules, and each
   rule carries the file:line it was read from.

   Line numbers below are NetHack-5.0 @ a8a13be.  3.7's readobjnam() is
   byte-identical to 5.0's (scripts/gen-wish.py proves that on every run);
   3.6's differs and its own line numbers ride along in wish.json's `cites`,
   which is what the page displays.

   The rules implemented, and where they live:

     src/zap.c:6328        makewish() — reads a line, calls readobjnam()
     src/zap.c:6174        MAXWISHTRY 5 — bad wishes are re-prompted
     src/objnam.c:3995     readobjnam_preparse() — the adjective loop
     src/objnam.c:4207     readobjnam_parse_charges() — the "(n:m)" suffix
     src/objnam.c:4262     requested spe capped at SPE_LIM (include/obj.h:49)
     src/objnam.c:4264     recharge count capped at 7
     src/objnam.c:4566     gold quantity capped at 5000
     src/objnam.c:5033     wizard-mode-only objects substituted
     src/objnam.c:5050     oc_nowish objects rejected outright
     src/objnam.c:5100     quantity honored only sometimes
     src/objnam.c:5123     the enchantment / charge rules
     src/objnam.c:5211     wished wand of wishing gets (0:-1) or (0:0)
     src/objnam.c:5287     blessed / uncursed / cursed and Luck
     src/objnam.c:5316     erodeproof and Luck
     src/objnam.c:5330     poisoned and Luck
     src/objnam.c:5366     greased, unconditionally
     src/objnam.c:5402     artifact wishes that fail
     src/do_name.c:392     oname() refuses to duplicate an existing artifact
     src/artifact.c:462    nartifact_exist()
     src/mkobj.c:869       mksobj_init() — the spe/quantity the item starts with
     src/mkobj.c:1841      blessorcurse()
     src/rnd.c:192         rne()

   Loadable as a plain <script> (defines window.WishEngine) or via require()
   in node (module.exports).
   ========================================================================== */

var WishEngine = (function () {
  'use strict';

  /* ---------------------------------------------------------------------- *
   * Probability primitives                                                 *
   * ---------------------------------------------------------------------- */

  /* rne(x) — src/rnd.c:192.  tmp starts at 1 and increments while
     rn2(x) == 0, stopping at utmp = (u.ulevel < 15) ? 5 : u.ulevel / 3.
     So P(rne(x) >= n) = (1/x)^(n-1) for n <= utmp, and 0 above utmp.
     Everything this engine reports uses the XL < 15 cap of 5; above XL 17
     the cap rises and the tail probabilities stop being zero. */
  var RNE_CAP = 5;

  function pRneAtLeast(x, n, cap) {
    cap = cap || RNE_CAP;
    if (n <= 1) return 1;
    if (n > cap) return 0;
    return Math.pow(1 / x, n - 1);
  }

  /* P(rnd(die) >= n): rnd(die) is uniform on 1..die. */
  function pRndAtLeast(die, n) {
    if (n <= 1) return 1;
    if (n > die) return 0;
    return (die - n + 1) / die;
  }

  /* P(uniform integer on [lo,hi] >= n) */
  function pRangeAtLeast(lo, hi, n) {
    if (n <= lo) return 1;
    if (n > hi) return 0;
    return (hi - n + 1) / (hi - lo + 1);
  }

  /* P(rn2(4) - rn2(3) >= n) — the "make useless +0 rings much less common"
     reroll, src/mkobj.c:1138.  Values run -2..3 over 12 equally likely
     (a,b) pairs. */
  function pRingReroll(n) {
    var hits = 0, a, b;
    for (a = 0; a < 4; a++) for (b = 0; b < 3; b++) if (a - b >= n) hits++;
    return hits / 12;
  }

  /* ---------------------------------------------------------------------- *
   * What mksobj() hands the wish before readobjnam() adjusts it            *
   * ---------------------------------------------------------------------- */

  /* P(the freshly created object's spe is already >= n).  readobjnam()
     compares the request against this value twice (objnam.c:5131 and
     :5144), so it is the difference between "you asked for +7 and got +0"
     and "you asked for +7 and got +7". */
  function pRandomSpeAtLeast(item, V, n) {
    if (n <= 0) return 1;
    var cls = item.cls;

    /* wands: src/mkobj.c:1114 */
    if (cls === 'wand') {
      var wr = V.wand_spe[item.f.dir === 'nodir' ? 'nodir' : 'beam'];
      var sp = V.tool_spe[item.name];       /* wand of wishing / stasis */
      if (sp) return pRangeAtLeast(sp[0], sp[1], n);
      return pRangeAtLeast(wr[0], wr[1], n);
    }

    /* charged tools: src/mkobj.c:983-1046 */
    if (V.tool_spe[item.name]) {
      var t = V.tool_spe[item.name];
      return pRangeAtLeast(t[0], t[1], n);
    }

    /* weapons: src/mkobj.c:876 — 1/11 blessed +rne(3), else 1/10 cursed
       -rne(3), else +0 */
    if (cls === 'weapon' || (cls === 'tool' && item.f.wpt)) {
      return (1 / 11) * pRneAtLeast(3, n);
    }

    /* armor: src/mkobj.c:1085 */
    if (cls === 'armor') {
      var special = V.cursed_armor.indexOf(item.name) >= 0;
      var pCursed = (9 / 10) * (special ? 1 : 1 / 11);
      var pPos = (1 - pCursed) * (1 / 10);
      return pPos * pRneAtLeast(3, n);
    }

    /* charged rings: src/mkobj.c:1128 */
    if (cls === 'ring' && item.f.chg) {
      return (9 / 20) * pRneAtLeast(3, n) + (1 / 10) * pRingReroll(n);
    }

    return 0; /* everything else starts at spe 0 */
  }

  /* Human-readable version of the same thing, for the "capped at" note. */
  function randomSpeRange(item, V) {
    if (V.tool_spe[item.name]) return V.tool_spe[item.name];
    if (item.cls === 'wand') {
      return V.wand_spe[item.f.dir === 'nodir' ? 'nodir' : 'beam'];
    }
    return null;
  }

  /* Which arm of readobjnam()'s spe switch (objnam.c:5123-5146) applies. */
  function speBranch(item, V) {
    if (!item) return 'none';
    /* ARMOR_CLASS || WEAPON_CLASS || is_weptool() || charged RING_CLASS */
    if (item.cls === 'armor' || item.cls === 'weapon' || item.f.wpt
        || (item.cls === 'ring' && item.f.chg)) {
      return 'enchant';
    }
    /* WAND_CLASS, plus CRYSTAL_BALL in 3.7/5.0 only (objnam.c:5137) */
    if (item.cls === 'wand') return 'wandlike';
    if (item.name === 'crystal ball' && V.features.crystal_ball_cancels) {
      return 'wandlike';
    }
    return 'other';
  }

  /* ---------------------------------------------------------------------- *
   * Canonical wish string                                                  *
   * ---------------------------------------------------------------------- */

  /* readobjnam_preparse() (objnam.c:3995) loops over the adjectives, so
     their order does not matter to the parser.  The order used here is the
     order the game itself prints them in doname_base() (objnam.c:1224) and
     add_erosion_words() (objnam.c:1143):

       <count> <B/U/C> greased poisoned <erodeproof> <+N> <name> (n:m)

     which is what a player sees in inventory and therefore the least
     surprising thing to paste back into the wish prompt. */
  function buildString(spec, data) {
    var V = data.versions[spec.version];
    var item = resolveItem(spec, data);
    var parts = [];

    function push(text, kind, why) {
      parts.push({ text: text, kind: kind, why: why });
    }

    if (item && spec.quantity != null && spec.quantity > 1) {
      push(String(spec.quantity), 'count', 'quantity');
    }
    if (spec.bcu) push(spec.bcu, 'bcu', 'blessed/uncursed/cursed');
    if (spec.greased) push('greased', 'greased', 'greased');
    if (spec.poisoned) push('poisoned', 'poisoned', 'poisoned');
    if (spec.erodeproof) push('fixed', 'erodeproof', 'erodeproof');

    var chargeSuffix = null;
    if (spec.speGiven && item) {
      /* wands and charged tools are conventionally written with the
         parenthesised charge count that doname() prints; both forms parse
         (objnam.c:4207 handles "(n:m)", the prefix loop handles "+N") */
      if (usesChargeSyntax(item)) {
        chargeSuffix = '(' + (spec.recharged || 0) + ':' + spec.spe + ')';
      } else {
        push((spec.spe >= 0 ? '+' : '') + spec.spe, 'spe', 'enchantment');
      }
    }

    var name = item ? item.name : (spec.artifact || '');
    if (spec.artifact) name = spec.artifact;
    if (name) push(name, 'name', 'object');
    if (chargeSuffix) push(chargeSuffix, 'spe', 'charges');

    return {
      text: parts.map(function (p) { return p.text; }).join(' '),
      parts: parts,
      item: item,
      version: V
    };
  }

  function usesChargeSyntax(item) {
    return item.cls === 'wand'
      || (item.cls === 'tool' && item.f.chg && !item.f.wpt);
  }

  /* ---------------------------------------------------------------------- *
   * Item lookup                                                            *
   * ---------------------------------------------------------------------- */

  /* wish.json deliberately does not repeat the object class, name, cost or
     probability that data/objects.json already carries (gen-wish.py asserts
     the two name lists are identical).  Call this once after loading both to
     stamp each flag record with its class; it returns the names that failed
     to join, which should always be empty. */
  function attachClasses(wishData, objectsJson) {
    var orphans = [];
    Object.keys(wishData.versions).forEach(function (key) {
      var V = wishData.versions[key];
      var src = objectsJson.versions[key];
      if (!src) { orphans.push('missing version ' + key); return; }
      var cls = {};
      src.objects.forEach(function (o) { cls[o.name] = o['class']; });
      Object.keys(V.objects).forEach(function (name) {
        if (cls[name] === undefined) orphans.push(key + ':' + name);
        V.objects[name].cls = cls[name];
      });
    });
    return orphans;
  }

  /* Returns { name, cls, f } where f is the wish.json flag record.
     An artifact selection forces the base object type: readobjnam() looks
     the name up in artilist[] (artifact.c:329) and takes a->otyp. */
  function resolveItem(spec, data) {
    var V = data.versions[spec.version];
    var name = spec.item;
    if (spec.artifact) {
      var a = findArtifact(spec.artifact, V);
      if (a) name = a.base;
    }
    if (!name) return null;
    var f = V.objects[name];
    if (!f) return null;
    return { name: name, cls: f.cls, f: f };
  }

  function findArtifact(name, V) {
    for (var i = 0; i < V.artifacts.length; i++) {
      if (V.artifacts[i].name === name) return V.artifacts[i];
    }
    return null;
  }

  /* ---------------------------------------------------------------------- *
   * The validator                                                          *
   * ---------------------------------------------------------------------- */

  /* Each finding is
       { key, label, status, text, cite }
     with status one of:
       'honored'  — the game does exactly what you asked
       'chance'   — honored with a stated probability
       'clamped'  — honored but reduced
       'dropped'  — silently ignored
       'blocked'  — you do not get the item at all
       'note'     — context, not a verdict                                  */
  function evaluate(spec, data) {
    var V = data.versions[spec.version];
    var item = resolveItem(spec, data);
    var out = [];
    var C = V.cites;

    function add(key, label, status, text, citeKey) {
      out.push({
        key: key, label: label, status: status, text: text,
        cite: citeKey ? C[citeKey] : null
      });
    }

    if (!item && !spec.artifact) {
      return { findings: [], item: null };
    }

    /* --- things that are not wishable at all (objnam.c:5033-5054) ------ */
    var subbed = substitutionFor(item, V);
    if (subbed) {
      add('substitute', 'Object type', 'blocked',
          'Outside wizard mode readobjnam() rewrites this wish before the '
          + 'object is even created: you get ' + subbed.to + ' instead.',
          'wizonly_subs');
    }
    if (item && V.nowish_rejected.indexOf(item.name) >= 0) {
      add('nowish', 'Object type', 'blocked',
          'This object carries oc_nowish, so readobjnam() returns nothing '
          + 'and the game says "Nothing fitting that description exists in '
          + 'the game." The wish is not consumed — makewish() re-prompts, up '
          + 'to MAXWISHTRY (5) times (src/zap.c:6174).',
          'nowish');
    }

    /* --- artifacts (objnam.c:5402, do_name.c:392) ---------------------- */
    if (spec.artifact) {
      var a = findArtifact(spec.artifact, V);
      if (a) {
        add('arti_base', 'Artifact', 'note',
            'readobjnam() only recognises an artifact by name, and takes its '
            + 'base object type from artilist[]: you are really wishing for a '
            + a.base + '.', 'arti_name');

        if (a.questrole) {
          add('arti_quest', 'Artifact', 'blocked',
              'If you are playing a ' + a.questrole + ' this is your own quest '
              + 'artifact: is_quest_artifact() is true, the object is freed, '
              + 'and you get "For a moment, you feel something in your hands, '
              + 'but it disappears!" — nothing at all, and the wish is spent. '
              + 'Every other role can wish for it normally.', 'arti_quest');
        }
        add('arti_exists', 'Artifact', 'note',
            'If ' + a.name + ' already exists — generated, gifted, named or '
            + 'left in a bones file — oname() returns the object untouched, '
            + 'so you get a plain ' + a.base + ' with no name and no powers. '
            + 'The artifact-wish conduct is broken either way.', 'arti_exists');

        var n = spec.nArtifacts != null ? spec.nArtifacts : 1;
        var pFail = artifactFailChance(n);
        add('arti_roll', 'Artifact', pFail > 0 ? 'chance' : 'honored',
            artifactRollText(n, pFail), 'arti_fail');

        if (a.nogen) {
          add('arti_nogen', 'Artifact', 'note',
              a.name + ' is SPFX_NOGEN: it is never randomly generated, so '
              + 'wishing (or the special path that creates it) is the only '
              + 'way it can come to exist. SPFX_NOGEN does not itself block '
              + 'a wish.', 'arti_name');
        }
        add('arti_align', 'Artifact', 'note',
            'Alignment and crowning do not enter into it. readobjnam() checks '
            + 'only is_quest_artifact() and the rn2(nartifact_exist()) roll; '
            + 'a->alignment is consulted by mk_artifact() for sacrifice gifts, '
            + 'never for wishes.', 'arti_fail');
      }
    }

    if (!item) return { findings: out, item: null };

    /* --- quantity (objnam.c:5100-5113) --------------------------------- */
    if (spec.quantity != null && spec.quantity > 1) {
      out.push(quantityFinding(spec, item, V, C));
    }

    /* --- blessed / uncursed / cursed (objnam.c:5287-5297) -------------- */
    out.push(bucFinding(spec, V, C));

    /* --- enchantment / charges (objnam.c:5123-5146) -------------------- */
    if (spec.speGiven) {
      var e = enchantFinding(spec, item, V, C);
      for (var i = 0; i < e.length; i++) out.push(e[i]);
    } else {
      add('spe_default', 'Enchantment', 'note',
          'No +N given, so d.spesgn stays 0 and the item keeps whatever spe '
          + 'mksobj() rolled for it' + speDefaultText(item, V) + '.',
          'spe_unspecified');
    }

    /* --- erodeproof (objnam.c:5300-5320) ------------------------------- */
    if (spec.erodeproof) {
      if (!item.f.ero) {
        add('erodeproof', 'Erodeproof', 'dropped',
            'is_damageable() is false for a ' + item.name + ', so the '
            + 'erodeproof flag is parsed and then never applied.',
            'erodeproof');
      } else if (spec.luckNeg) {
        add('erodeproof', 'Erodeproof', 'dropped',
            'oerodeproof is set to (Luck >= 0), and your Luck is negative, so '
            + 'the item comes out erodible. Fix your Luck first.',
            'erodeproof');
      } else {
        add('erodeproof', 'Erodeproof', 'honored',
            'Honored. The game will describe it as "' + (item.f.epw || 'fixed')
            + '"; "fixed", "rustproof", "corrodeproof", "fireproof", '
            + '"rotproof", "tempered" and "crackproof" are all accepted as '
            + 'input and mean the same thing.', 'erodeproof');
      }
    }

    /* --- poisoned (objnam.c:5326-5334) --------------------------------- */
    if (spec.poisoned) {
      if (item.f.psn && !spec.luckNeg) {
        add('poisoned', 'Poisoned', 'honored',
            'Honored: is_poisonable() covers arrows, bolts, darts, shuriken '
            + 'and spears, and opoisoned is set to (Luck >= 0).', 'poisoned');
      } else if (item.f.psn) {
        add('poisoned', 'Poisoned', 'dropped',
            'opoisoned is set to (Luck >= 0) and your Luck is negative, so '
            + 'the poison is dropped.', 'poisoned');
      } else if (item.cls === 'food') {
        add('poisoned', 'Poisoned', 'clamped',
            'Food cannot be poisoned as such; readobjnam() instead sets '
            + 'age = 1, making it as old (and as likely to be tainted) as '
            + 'possible.', 'poisoned');
      } else {
        add('poisoned', 'Poisoned', 'dropped',
            'is_poisonable() is false for a ' + item.name + ', so "poisoned" '
            + 'is parsed and discarded.', 'poisoned');
      }
    }

    /* --- greased (objnam.c:5366) --------------------------------------- */
    if (spec.greased) {
      add('greased', 'Greased', 'honored',
          'Always honored. It is an unconditional assignment — no material '
          + 'test, no Luck test.', 'greased');
    }

    return { findings: out, item: item };
  }

  /* --- helpers used by evaluate() ------------------------------------- */

  function substitutionFor(item, V) {
    if (!item) return null;
    for (var i = 0; i < V.substitutions.length; i++) {
      if (V.substitutions[i].from === item.name) return V.substitutions[i];
    }
    return null;
  }

  /* objnam.c:5403 — rn2(nartifact_exist()) > 1, evaluated AFTER the new
     artifact has been registered, so n counts the one you just asked for.
     rn2(n) is 0..n-1, so the wish only fails when n >= 3. */
  function artifactFailChance(n) {
    if (n < 3) return 0;
    return (n - 2) / n;
  }

  function artifactRollText(n, pFail) {
    var pct = (pFail * 100).toFixed(1).replace(/\.0$/, '');
    if (pFail === 0) {
      return 'With ' + n + ' artifact' + (n === 1 ? '' : 's') + ' in existence '
        + '(counting this one), rn2(' + n + ') can never exceed 1, so the wish '
        + 'always succeeds. The first two artifacts of a game are free.';
    }
    return 'With ' + n + ' artifacts in existence (counting this one), the '
      + 'wish fails with probability (n − 2)/n = ' + pct + '%. On failure the '
      + 'artifact is un-created, the object is freed, and you get "For a '
      + 'moment, you feel something in your hands, but it disappears!" — '
      + 'nothing, and the wish is spent.';
  }

  function quantityFinding(spec, item, V, C) {
    var cnt = spec.quantity;
    var K = V.consts;
    var base = { key: 'quantity', label: 'Quantity', cite: C.quan_rnd6 };

    if (!item.f.mrg) {
      base.status = 'dropped';
      base.text = 'A ' + item.name + ' has oc_merge clear, so the count is '
        + 'parsed and then ignored entirely — the whole quantity test is '
        + 'inside `if (objects[typ].oc_merge)`.';
      base.cite = C.quan_merge;
      return base;
    }
    if (item.f.cnd && cnt <= K.candle_count_cap) {
      base.status = 'honored';
      base.text = 'Candles are special-cased: up to ' + K.candle_count_cap
        + ' are granted unconditionally.';
      base.cite = C.quan_candle;
      return base;
    }
    var bulk = item.f.mis || (item.cls === 'weapon' && item.f.amo)
      || item.name === 'rock'
      || (item.name === 'flint' && V.features.flint_stacks);
    if (bulk && cnt <= K.bulk_count_cap) {
      base.status = 'honored';
      base.text = 'Ammunition, thrown missiles and rocks are granted in bulk: '
        + 'up to ' + K.bulk_count_cap + ' are honored unconditionally.';
      base.cite = C.quan_bulk;
      return base;
    }
    var p = pRndAtLeast(K.quan_die, cnt + 1);   /* P(cnt < rnd(die)) */
    if (p <= 0) {
      base.status = 'dropped';
      base.text = 'The only remaining test is `cnt < rnd(' + K.quan_die + ')`, '
        + 'and rnd(' + K.quan_die + ') never exceeds ' + K.quan_die + ', so a '
        + 'count of ' + cnt + ' is always refused. You get whatever stack '
        + 'mksobj() rolled' + quantityFallback(item) + '.';
      return base;
    }
    base.status = 'chance';
    base.text = 'Granted only if `cnt < rnd(' + K.quan_die + ')` — '
      + (p * 100).toFixed(0) + '% for a count of ' + cnt + '. Otherwise you '
      + 'get whatever stack mksobj() rolled' + quantityFallback(item) + '.';
    return base;
  }

  function quantityFallback(item) {
    /* src/mkobj.c:877 (is_multigen), :972 (food), :1000 (gems) */
    if (item.f.mgn) return ' — 6 to 11 for stacking ammo, via rn1(6, 6)';
    if (item.name === 'rock') return ' — 6 to 11, via rn1(6, 6)';
    if (item.cls === 'food') return ' — 2 one time in 6, otherwise 1';
    if (item.cls === 'gem') return ' — 2 one time in 6, otherwise 1';
    return ', usually 1';
  }

  function bucFinding(spec, V, C) {
    if (!spec.bcu) {
      return {
        key: 'buc', label: 'Beatitude', status: 'note', cite: C.blessorcurse,
        text: 'Unspecified, so the item keeps whatever blessorcurse() rolled '
          + 'in mksobj(): usually uncursed, with a small class-dependent '
          + 'chance of blessed or cursed. If it matters, say so explicitly.'
      };
    }
    if (spec.bcu === 'cursed') {
      return {
        key: 'buc', label: 'Beatitude', status: 'honored', cite: C.bcu,
        text: '"cursed" calls curse() unconditionally — the one beatitude '
          + 'request that Luck cannot spoil.'
      };
    }
    if (!spec.luckNeg) {
      return {
        key: 'buc', label: 'Beatitude', status: 'honored', cite: C.bcu,
        text: 'Honored: blessed is set to (Luck >= 0) and cursed to '
          + '(Luck < 0), and your Luck is not negative.'
      };
    }
    return {
      key: 'buc', label: 'Beatitude', status: 'blocked', cite: C.bcu,
      text: 'With negative Luck this backfires: blessed = (Luck >= 0) is 0 '
        + 'and cursed = (Luck < 0) is 1, so asking for "' + spec.bcu + '" '
        + 'hands you a cursed item.'
    };
  }

  function speDefaultText(item, V) {
    var r = randomSpeRange(item, V);
    if (r) {
      return r[0] === r[1] ? ' — always ' + r[0]
        : ' — ' + r[0] + ' to ' + r[1] + ', uniformly';
    }
    if (item.cls === 'weapon' || item.f.wpt) {
      return ' — +0 nine times in eleven, otherwise ±rne(3)';
    }
    if (item.cls === 'armor') return ' — +0 about 82% of the time';
    if (item.cls === 'ring' && item.f.chg) return ' — rarely +0';
    return '';
  }

  /* The heart of it: objnam.c:5123-5146. */
  function enchantFinding(spec, item, V, C) {
    var out = [];
    var K = V.consts;
    var mag = Math.abs(spec.spe);
    var neg = spec.spe < 0;
    var branch = speBranch(item, V);
    var label = usesChargeSyntax(item) ? 'Charges' : 'Enchantment';

    if (mag > K.spe_cap) {
      out.push({
        key: 'spe_cap', label: label, status: 'clamped', cite: C.spe_cap,
        text: 'Capped at ' + K.spe_cap_name + ' = ' + K.spe_cap
          + ' the moment it is parsed, long before any of the rules below.'
      });
      mag = K.spe_cap;
    }

    if (branch === 'enchant') {
      var pRnd = 1 - pRndAtLeast(K.ench_die, mag);          /* P(mag > rnd(5)) */
      var pRandLower = 1 - pRandomSpeAtLeast(item, V, mag); /* P(mag > obj spe) */
      var pZero = pRnd * pRandLower;
      var pKeep = 1 - pZero;

      out.push({
        key: 'spe_clamp', label: label,
        status: pZero === 0 ? 'honored' : (pKeep === 0 ? 'blocked' : 'chance'),
        cite: C.spe_clamp,
        prob: pKeep,
        text: enchantText(mag, neg, pRnd, pRandLower, pZero, K, item, V)
      });

      if (spec.luckNeg && mag > K.luck_ench_floor && !neg) {
        out.push({
          key: 'spe_luck', label: label, status: 'blocked', cite: C.spe_luck,
          text: 'And with negative Luck, anything above +' + K.luck_ench_floor
            + ' that survives the roll above has its sign flipped: you get −'
            + mag + ', and the negative sign then curses the item. At negative '
            + 'Luck the best safe request is +' + K.luck_ench_floor + '.'
        });
      }
      if (neg) {
        out.push({
          key: 'spe_neg', label: label, status: 'note', cite: C.bcu,
          text: 'A negative request falls through to `else if (d.spesgn < 0) '
            + 'curse(d.otmp)`, so the item is cursed even if you did not say '
            + '"cursed". Note the zeroing rule above works on the magnitude, '
            + 'so a failed −' + mag + ' request yields a cursed +0, not a '
            + 'smaller negative.'
        });
      }
      return out;
    }

    if (branch === 'wandlike') {
      var r = randomSpeRange(item, V)
        || V.wand_spe[item.f.dir === 'nodir' ? 'nodir' : 'beam'];
      if (item.name === 'wand of wishing') {
        out.push({
          key: 'wan_wishing', label: label, status: 'blocked',
          cite: C.wan_wishing,
          text: 'A wished-for wand of wishing has its charges overwritten '
            + 'outright: spe = rn2(10) ? -1 : 0, so it is cancelled 9 times '
            + 'in 10 and empty the tenth. It also arrives with recharged = 1 '
            + '(objnam.c:' + C.wan_wishing_rechrg.line + '), so a scroll of '
            + 'charging will not help — only wresting.'
        });
        return out;
      }
      if (neg) {
        out.push({
          key: 'spe_wand_neg', label: label, status: 'clamped',
          cite: C.spe_wand_neg,
          text: 'Wands (and, in 3.7/5.0, the crystal ball) clamp a negative '
            + 'request to exactly −1: a cancelled wand. Asking for −'
            + mag + ' gives (0:-1).'
        });
        return out;
      }
      var p = pRangeAtLeast(r[0], r[1], mag);
      out.push({
        key: 'spe_cap_random', label: label,
        status: mag <= r[0] ? 'honored' : (p === 0 ? 'clamped' : 'chance'),
        cite: C.spe_cap_random,
        prob: p,
        text: 'This class is not enchantable, so the only rule is '
          + '`if (d.spe > d.otmp->spe) d.spe = d.otmp->spe` — your request is '
          + 'capped at whatever mksobj() rolled, which for a ' + item.name
          + ' is ' + (r[0] === r[1] ? 'always ' + r[0]
                      : r[0] + ' to ' + r[1] + ' uniformly')
          + '. Asking for ' + mag + ' therefore succeeds '
          + (p * 100).toFixed(0) + '% of the time; the rest of the time you '
          + 'get the roll, which averages ' + ((r[0] + r[1]) / 2).toFixed(1)
          + '. You cannot wish a wand above its natural maximum, and asking '
          + 'for fewer charges than it rolled works every time.'
      });
      return out;
    }

    /* branch === 'other' */
    var rr = randomSpeRange(item, V);
    if (neg) {
      out.push({
        key: 'spe_other_neg', label: label, status: 'clamped',
        cite: C.spe_other_neg,
        text: 'Outside the enchantable classes a negative request is zeroed '
          + '(`if (d.spe > 0 && d.spesgn == -1) d.spe = 0`), and the negative '
          + 'sign still curses the item. You get a cursed +0.'
      });
      return out;
    }
    if (rr) {
      var pp = pRangeAtLeast(rr[0], rr[1], mag);
      out.push({
        key: 'spe_cap_random', label: label,
        status: mag <= rr[0] ? 'honored' : (pp === 0 ? 'clamped' : 'chance'),
        cite: C.spe_cap_random,
        prob: pp,
        text: 'Capped at what mksobj() rolled — ' + rr[0] + ' to ' + rr[1]
          + ' for a ' + item.name + '. A request of ' + mag + ' survives '
          + (pp * 100).toFixed(0) + '% of the time; otherwise you get the '
          + 'roll. Asking for more than ' + rr[1] + ' can never work.'
      });
      return out;
    }
    out.push({
      key: 'spe_cap_random', label: label,
      status: mag > 0 ? 'dropped' : 'honored', cite: C.spe_cap_random,
      text: mag > 0
        ? 'A ' + item.name + ' starts at spe 0 and is not in an enchantable '
          + 'class, so `if (d.spe > d.otmp->spe) d.spe = d.otmp->spe` clamps '
          + 'the request straight back to 0.'
        : 'No change.'
    });
    return out;
  }

  function enchantText(mag, neg, pRnd, pRandLower, pZero, K, item, V) {
    var pKeep = 1 - pZero;
    var s = 'The rule is `if (d.spe > rnd(' + K.ench_die + ') && d.spe > '
      + 'd.otmp->spe) d.spe = 0` — note that it zeroes the request rather '
      + 'than reducing it. ';
    if (mag <= 1) {
      s += 'rnd(' + K.ench_die + ') is at least 1, so ' + (neg ? '−' : '+')
        + mag + ' always survives.';
      return s;
    }
    s += 'The request survives only when rnd(' + K.ench_die + ') comes up at '
      + 'least ' + mag + ', which happens '
      + ((1 - pRnd) * 100).toFixed(0) + '% of the time';
    if (pRandLower < 1) {
      s += ', and even when it does not, the freshly created ' + item.name
        + ' may already have rolled a spe of ' + mag + ' or better ('
        + ((1 - pRandLower) * 100).toFixed(1) + '%)';
    }
    s += '. Net: you keep ' + (neg ? '−' : '+') + mag + ' about '
      + (pKeep * 100).toFixed(pKeep < 0.1 ? 1 : 0) + '% of the time, and get '
      + (neg ? 'a cursed +0' : '+0') + ' otherwise.';
    if (mag > K.ench_die) {
      s += ' Above +' + K.ench_die + ' the rnd(' + K.ench_die + ') test can '
        + 'never save the request; only an mksobj() roll of ' + mag + ' or '
        + 'better can, and at XL under 15 rne(3) caps at ' + RNE_CAP
        + ', so it cannot.';
    }
    return s;
  }

  /* ---------------------------------------------------------------------- *
   * Version differences, for the notes panel                               *
   * ---------------------------------------------------------------------- */
  function versionDiffs(data) {
    var a = data.versions['3.6'], b = data.versions['3.7-5.0'];
    var d = [];
    if (a.consts.spe_cap !== b.consts.spe_cap) {
      d.push({
        what: 'Cap on a requested +N or charge count',
        v36: a.consts.spe_cap_name + ' = ' + a.consts.spe_cap,
        v37: b.consts.spe_cap_name + ' = ' + b.consts.spe_cap,
        cite: b.cites.spe_cap
      });
    }
    var keys = {};
    Object.keys(a.tool_spe).forEach(function (k) { keys[k] = 1; });
    Object.keys(b.tool_spe).forEach(function (k) { keys[k] = 1; });
    Object.keys(keys).forEach(function (k) {
      var x = a.tool_spe[k], y = b.tool_spe[k];
      /* readobjnam() overwrites a wished wand of wishing's charges outright
         (objnam.c:5211), so mksobj()'s roll for it is not a wish rule */
      if (k === 'wand of wishing') return;
      if (JSON.stringify(x) !== JSON.stringify(y)) {
        d.push({
          what: 'Charges mksobj() rolls for a ' + k
            + ' (the ceiling on wishing for charges)',
          v36: x ? x[0] + '–' + x[1] : 'does not exist in 3.6',
          v37: y ? y[0] + '–' + y[1] : 'removed',
          cite: b.cites.spe_cap_random
        });
      }
    });
    if (a.features.crystal_ball_cancels !== b.features.crystal_ball_cancels) {
      d.push({
        what: 'Negative request on a crystal ball',
        v36: 'zeroed like any other tool',
        v37: 'clamped to −1, the same as a wand',
        cite: b.cites.spe_wand_neg
      });
    }
    if (a.features.flint_stacks !== b.features.flint_stacks) {
      d.push({
        what: 'Wishing for a stack of flint stones',
        v36: 'not in the bulk list — capped by the rnd(6) roll',
        v37: 'in the bulk list — up to ' + b.consts.bulk_count_cap + ' honored',
        cite: b.cites.quan_bulk
      });
    }
    var an = a.objects, bn = b.objects;
    var added = Object.keys(bn).filter(function (k) { return !an[k]; });
    if (added.length) {
      d.push({
        what: 'Objects you can only wish for in 3.7 / 5.0',
        v36: 'do not exist',
        v37: added.slice(0, 8).join(', ')
          + (added.length > 8 ? ', and ' + (added.length - 8) + ' more' : ''),
        cite: null
      });
    }
    return d;
  }

  /* ---------------------------------------------------------------------- */

  var API = {
    RNE_CAP: RNE_CAP,
    pRneAtLeast: pRneAtLeast,
    pRndAtLeast: pRndAtLeast,
    pRangeAtLeast: pRangeAtLeast,
    pRingReroll: pRingReroll,
    pRandomSpeAtLeast: pRandomSpeAtLeast,
    attachClasses: attachClasses,
    randomSpeRange: randomSpeRange,
    speBranch: speBranch,
    usesChargeSyntax: usesChargeSyntax,
    resolveItem: resolveItem,
    findArtifact: findArtifact,
    substitutionFor: substitutionFor,
    artifactFailChance: artifactFailChance,
    buildString: buildString,
    evaluate: evaluate,
    versionDiffs: versionDiffs
  };
  return API;
})();

if (typeof module !== 'undefined' && module.exports) module.exports = WishEngine;
if (typeof window !== 'undefined') window.WishEngine = WishEngine;
