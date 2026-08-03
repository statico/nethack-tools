#!/usr/bin/env node
/* Cross-checks data/monsters.json and assets/monster-engine.js against values
   read by hand out of the NetHack source:

     include/monsters.h  (3.7 / 5.0)   src/monst.c (3.6)   -- the tables
     src/mondata.c  mstrength()                            -- difficulty
     src/makemon.c  rndmonst() / uncommon() / align_shift() -- generation
     include/monst.h  monmin_difficulty() / monmax_difficulty()
     include/monflag.h  G_* bit values

   No dependencies, no install:   node scripts/test-monsters.mjs             */

import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import fs from 'node:fs';

const require = createRequire(import.meta.url);
const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, '..');
const E = require(path.join(root, 'assets', 'monster-engine.js'));
const DATA = JSON.parse(fs.readFileSync(path.join(root, 'data', 'monsters.json'), 'utf8'));

let pass = 0;
let fail = 0;

function check(desc, got, want, work) {
  const g = JSON.stringify(got);
  const w = JSON.stringify(want);
  const ok = g === w;
  ok ? pass++ : fail++;
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${desc}`);
  if (work) console.log(`      ${work}`);
  if (!ok) console.log(`      got  ${g}\n      want ${w}`);
}

const V = DATA.versions;
const LEG = DATA.legend;
const byName = {};
const indexOf = {};
for (const key of Object.keys(V)) {
  byName[key] = {};
  indexOf[key] = {};
  V[key].mons.forEach((m, i) => {
    byName[key][m.n] = m;
    indexOf[key][m.n] = i;
  });
}

/* ====================================================================== */
console.log('\n=== dataset shape ===\n');

check('versions present', Object.keys(V), ['3.6', '3.7-5.0']);
check('3.6 mons[] length', V['3.6'].mons.length, 382,
  '394 MON() calls in src/monst.c, minus 9 in #if 0 blocks, minus 2 #ifdef CHARON, minus the array terminator');
check('3.7-5.0 mons[] length', V['3.7-5.0'].mons.length, 383,
  '394 MON() calls in include/monsters.h, minus 9 in #if 0, minus 2 #ifdef CHARON');
check('3.6 SPECIAL_PM index == index of long worm tail',
  V['3.6'].special_pm, indexOf['3.6']['long worm tail']);
check('3.7-5.0 SPECIAL_PM index == index of long worm tail',
  V['3.7-5.0'].special_pm, indexOf['3.7-5.0']['long worm tail']);
check('3.7 and 5.0 ship the same table', DATA.generated_from.identical_3_7_5_0, true);

/* ====================================================================== */
console.log('\n=== G_* bit values (include/monflag.h) ===\n');

const gbits = Object.fromEntries(LEG.g.map(([v, sym]) => [sym, v]));
check('G_UNIQ', E.G_UNIQ, gbits.G_UNIQ);
check('G_NOHELL', E.G_NOHELL, gbits.G_NOHELL);
check('G_HELL', E.G_HELL, gbits.G_HELL);
check('G_NOGEN', E.G_NOGEN, gbits.G_NOGEN);
check('G_SGROUP', E.G_SGROUP, gbits.G_SGROUP);
check('G_LGROUP', E.G_LGROUP, gbits.G_LGROUP);
check('G_FREQ mask', E.G_FREQ, LEG.g_freq_mask);
check('G_FREQ mask is 0x0007', LEG.g_freq_mask, 7);
check('ALIGNWEIGHT', E.ALIGNWEIGHT, LEG.alignweight, 'include/global.h:411');

/* ====================================================================== */
console.log('\n=== monster stats, read by hand out of the tables ===\n');

/* [name, level, speed, ac, magic resistance, alignment, weight, nutrition,
    difficulty, symbol] */
const HAND = {
  '3.6': [
    ['giant ant', 2, 18, 3, 0, 0, 10, 10, 4, 'a'],
    ['killer bee', 1, 18, -1, 0, 0, 1, 5, 5, 'a'],
    ['cockatrice', 5, 6, 6, 30, 0, 30, 30, 8, 'c'],
    ['floating eye', 2, 1, 9, 10, 0, 10, 10, 3, 'e'],
    ['mind flayer', 9, 12, 5, 90, -8, 1450, 400, 13, 'h'],
    ['green slime', 6, 6, 6, 0, 0, 400, 150, 8, 'P'],
    ['Medusa', 20, 12, 2, 50, -15, 1450, 400, 25, '@'],
    ['Wizard of Yendor', 30, 12, -8, 100, -128, 1450, 400, 34, '@'],
    ['soldier ant', 3, 18, 3, 0, 0, 20, 5, 6, 'a']
  ],
  '3.7-5.0': [
    ['giant ant', 2, 18, 3, 0, 0, 10, 10, 4, 'a'],
    ['killer bee', 1, 18, -1, 0, 0, 1, 5, 6, 'a'],
    ['cockatrice', 5, 6, 6, 30, 0, 30, 30, 8, 'c'],
    ['floating eye', 2, 1, 9, 10, 0, 10, 10, 3, 'e'],
    ['mind flayer', 9, 12, 5, 90, -8, 1450, 400, 13, 'h'],
    ['green slime', 6, 6, 6, 0, 0, 400, 150, 8, 'P'],
    ['Medusa', 20, 12, 2, 50, -15, 1450, 400, 25, '@'],
    ['Wizard of Yendor', 30, 12, -8, 100, -128, 1450, 400, 34, '@'],
    ['soldier ant', 3, 18, 3, 0, 0, 20, 5, 7, 'a']
  ]
};

for (const key of Object.keys(HAND)) {
  for (const [n, lv, mv, ac, mr, al, wt, nu, d, s] of HAND[key]) {
    const m = byName[key][n];
    check(`[${key}] ${n}`,
      m ? [m.lv, m.mv, m.ac, m.mr, m.al, m.wt, m.nu, m.d, m.s] : null,
      [lv, mv, ac, mr, al, wt, nu, d, s]);
  }
}

/* ====================================================================== */
console.log('\n=== attacks, decoded ===\n');

function attacks(key, name) {
  return byName[key][name].a.map((a) => {
    const t = E.attackText(a, LEG);
    return `${t.atSym} ${t.adSym} ${t.dice || '-'}`;
  });
}

check('[3.7-5.0] soldier ant attacks', attacks('3.7-5.0', 'soldier ant'),
  ['AT_BITE AD_PHYS 2d4', 'AT_STNG AD_DRST 3d4']);
check('[3.6] soldier ant attacks', attacks('3.6', 'soldier ant'),
  ['AT_BITE AD_PHYS 2d4', 'AT_STNG AD_DRST 3d4']);
check('[3.7-5.0] cockatrice attacks', attacks('3.7-5.0', 'cockatrice'),
  ['AT_BITE AD_PHYS 1d3', 'AT_TUCH AD_STON -', 'AT_NONE AD_STON -']);
check('[3.7-5.0] floating eye attacks', attacks('3.7-5.0', 'floating eye'),
  ['AT_NONE AD_PLYS 0d70']);
check('[3.7-5.0] Medusa attacks', attacks('3.7-5.0', 'Medusa'),
  ['AT_WEAP AD_PHYS 2d4', 'AT_CLAW AD_PHYS 1d8', 'AT_GAZE AD_STON -',
   'AT_BITE AD_DRST 1d6']);
check('[3.7-5.0] disenchanter attacks', attacks('3.7-5.0', 'disenchanter'),
  ['AT_CLAW AD_ENCH 4d4', 'AT_NONE AD_ENCH -']);
check('[3.7-5.0] green slime attacks', attacks('3.7-5.0', 'green slime'),
  ['AT_TUCH AD_SLIM 1d4', 'AT_NONE AD_SLIM -']);

check('petrification is flagged red', E.worstSeverity(byName['3.7-5.0'].cockatrice, LEG), 'red');
check('sliming is flagged red', E.worstSeverity(byName['3.7-5.0']['green slime'], LEG), 'red');
check('life drain is flagged red', E.worstSeverity(byName['3.7-5.0'].wraith, LEG), 'red');
check('disenchantment is flagged orange',
  E.worstSeverity(byName['3.7-5.0'].disenchanter, LEG), 'orange');
check('a plain physical attacker has no severity',
  E.worstSeverity(byName['3.7-5.0'].jackal, LEG), null);

/* ====================================================================== */
console.log('\n=== resistances and conveyed resistances ===\n');

const mrbits = Object.fromEntries(LEG.mr.map(([v, sym]) => [sym, v]));
const res = (key, n) => E.bits(byName[key][n].re, LEG.mr).map((b) => b.sym);
const cnv = (key, n) => E.bits(byName[key][n].cv, LEG.mr).map((b) => b.sym);

check('MR_STONE bit', mrbits.MR_STONE, 0x80);
check('[3.7-5.0] cockatrice resists', res('3.7-5.0', 'cockatrice'),
  ['MR_POISON', 'MR_STONE']);
check('[3.7-5.0] cockatrice conveys', cnv('3.7-5.0', 'cockatrice'),
  ['MR_POISON', 'MR_STONE']);
check('[3.7-5.0] killer bee conveys poison', cnv('3.7-5.0', 'killer bee'), ['MR_POISON']);
check('[3.6] killer bee conveys poison', cnv('3.6', 'killer bee'), ['MR_POISON']);
check('[3.7-5.0] wraith conveys nothing (level gain is not a resistance)',
  cnv('3.7-5.0', 'wraith'), []);
check('[3.7-5.0] gray dragon has an empty mresists field',
  res('3.7-5.0', 'gray dragon'), [],
  'its magic-missile immunity comes from its own breath type, not mresists');
check('[3.7-5.0] green slime resists',
  res('3.7-5.0', 'green slime'),
  ['MR_COLD', 'MR_ELEC', 'MR_POISON', 'MR_ACID', 'MR_STONE']);
check('[3.7-5.0] green slime conveys',
  cnv('3.7-5.0', 'green slime'), ['MR_ACID', 'MR_STONE']);

/* ====================================================================== */
console.log('\n=== difficulty gates (include/monst.h:267-273) ===\n');

check('minDifficulty(1)', E.minDifficulty(1), 0, '1/6 = 0 with C truncation');
check('minDifficulty(11)', E.minDifficulty(11), 1);
check('minDifficulty(30)', E.minDifficulty(30), 5);
check('maxDifficulty(1, 1)', E.maxDifficulty(1, 1), 1, '(1+1)/2');
check('maxDifficulty(10, 8)', E.maxDifficulty(10, 8), 9, '(10+8)/2');
check('maxDifficulty(11, 8)', E.maxDifficulty(11, 8), 9, '(11+8)/2 = 9 (truncated)');
check('maxDifficulty(45, 20)', E.maxDifficulty(45, 20), 32);

/* ====================================================================== */
console.log('\n=== align_shift (src/makemon.c) ===\n');

const wraith = byName['3.7-5.0'].wraith;       /* maligntyp -6 */
const newt = byName['3.7-5.0'].newt;           /* maligntyp  0 */
check('wraith alignment is -6', wraith.al, -6);
check('align_shift(wraith, unaligned)', E.alignShift(wraith, 'none'), 0);
check('align_shift(wraith, lawful)', E.alignShift(wraith, 'lawful'), 1, '(-6+20)/8 = 1');
check('align_shift(wraith, neutral)', E.alignShift(wraith, 'neutral'), 3, '(20-6)/4 = 3');
check('align_shift(wraith, chaotic)', E.alignShift(wraith, 'chaotic'), 3, '(20+6)/8 = 3');
check('align_shift(newt, neutral)', E.alignShift(newt, 'neutral'), 5, '(20-0)/4 = 5');
check('align_shift(newt, lawful)', E.alignShift(newt, 'lawful'), 2, '(0+20)/8 = 2');

/* ====================================================================== */
console.log('\n=== rndmonst() eligibility ===\n');

function q(key, over) {
  return Object.assign(
    { levelDifficulty: 1, ulevel: 1, specialPm: V[key].special_pm },
    over
  );
}
function poolNames(key, over) {
  return E.pool(V[key].mons, q(key, over)).list.map((h) => h.mon.n);
}

const p1 = E.pool(V['3.7-5.0'].mons, q('3.7-5.0'));
check('DL1/XL1 gates', [p1.conditions.minmlev, p1.conditions.maxmlev], [0, 1]);
const n1 = p1.list.map((h) => h.mon.n).sort();
console.log(`      DL1/XL1 pool (${n1.length}): ${n1.join(', ')}`);
check('DL1/XL1 includes grid bug', n1.includes('grid bug'), true);
check('DL1/XL1 includes newt', n1.includes('newt'), true);
check('DL1/XL1 excludes soldier ant (difficulty 7 > 1)',
  n1.includes('soldier ant'), false);
check('DL1/XL1 probabilities sum to 1',
  Math.abs(p1.list.reduce((s, h) => s + h.chance, 0) - 1) < 1e-12, true);

check('Medusa is never in the pool at any depth',
  [1, 10, 25, 40, 53].some((dl) =>
    poolNames('3.7-5.0', { levelDifficulty: dl, ulevel: 30 }).includes('Medusa')),
  false, 'G_UNIQ | G_NOGEN');
check('shopkeeper is never in the pool',
  [1, 10, 25, 40, 53].some((dl) =>
    poolNames('3.7-5.0', { levelDifficulty: dl, ulevel: 30 }).includes('shopkeeper')),
  false, 'G_NOGEN');
check('the Wizard of Yendor is never in the pool',
  [1, 10, 25, 40, 53].some((dl) =>
    poolNames('3.7-5.0', { levelDifficulty: dl, ulevel: 30 })
      .includes('Wizard of Yendor')),
  false);

/* G_HELL / G_NOHELL */
const deepOut = poolNames('3.7-5.0', { levelDifficulty: 30, ulevel: 14 });
const deepIn = poolNames('3.7-5.0', { levelDifficulty: 30, ulevel: 14, inHell: true });
check('green slime is G_HELL: absent outside Gehennom',
  deepOut.includes('green slime'), false);
check('green slime is G_HELL: present inside Gehennom',
  deepIn.includes('green slime'), true);
check('hell hound is G_HELL: absent outside Gehennom',
  deepOut.includes('hell hound'), false);
check('disenchanter is G_HELL: absent outside Gehennom',
  deepOut.includes('disenchanter'), false);

/* uncommon(): inside Gehennom only maligntyp <= A_NEUTRAL is generated */
const lawfulInHell = E.pool(V['3.7-5.0'].mons,
  q('3.7-5.0', { levelDifficulty: 40, ulevel: 20, inHell: true }))
  .list.filter((h) => h.mon.al > 0);
check('no monster with maligntyp > 0 is generated in Gehennom',
  lawfulInHell.length, 0, 'uncommon(): `return mons[mndx].maligntyp > A_NEUTRAL`');

/* rejection reporting */
check('rejections() explains Medusa',
  E.rejections(byName['3.7-5.0'].Medusa, indexOf['3.7-5.0'].Medusa,
    E.conditions(q('3.7-5.0', { levelDifficulty: 25, ulevel: 20 }))).slice(0, 2),
  ['G_NOGEN', 'G_UNIQ']);
check('rejections() explains a too-strong monster',
  E.rejections(byName['3.7-5.0']['purple worm'], indexOf['3.7-5.0']['purple worm'],
    E.conditions(q('3.7-5.0'))),
  ['too strong (difficulty 17 > 1)']);
check('rejections() explains a too-weak monster at depth',
  E.rejections(byName['3.7-5.0'].newt, indexOf['3.7-5.0'].newt,
    E.conditions(q('3.7-5.0', { levelDifficulty: 30, ulevel: 14 }))),
  ['too weak (difficulty 1 < 5)']);

/* weights */
const ga = byName['3.7-5.0']['giant ant'];
check('giant ant frequency', E.frequency(ga), 3);
check('giant ant weight on an unaligned level',
  E.weight(ga, { align: 'none' }), 3);
check('giant ant weight on a neutral level',
  E.weight(ga, { align: 'neutral' }), 8, 'freq 3 + (20-0)/4 = 3 + 5');
check('giant ant appears in small groups', E.groupSize(ga), 'small group');
check('killer bee appears in large groups',
  E.groupSize(byName['3.7-5.0']['killer bee']), 'large group');

/* frequency-0 monsters are only reachable through align_shift */
const babyLongWorm = byName['3.7-5.0']['baby long worm'];
check('baby long worm has frequency 0', E.frequency(babyLongWorm), 0);
check('a frequency-0 monster gets weight 0 on an unaligned level',
  E.weight(babyLongWorm, { align: 'none' }), 0);
check('a frequency-0 monster is excluded on an unaligned level',
  poolNames('3.7-5.0', { levelDifficulty: 25, ulevel: 14 }).includes('baby long worm'),
  false);
check('...but reachable on an aligned level, exactly as rndmonst() computes it',
  poolNames('3.7-5.0', { levelDifficulty: 25, ulevel: 14, align: 'neutral' })
    .includes('baby long worm'),
  true);

/* ====================================================================== */
console.log('\n=== difficulty formula bookkeeping ===\n');

check('mstrength() disagrees with the 3.7/5.0 table in exactly 2 places',
  DATA.formulas.difficulty.mismatches_3_7_5_0.map((r) => r[0]),
  ['cleric', 'wizard'],
  'both are G_NOGEN player-monsters; the DevTeam allows manual difficulty values');
check('3.6 difficulty is documented as table-only',
  /no difficulty formula/.test(DATA.formulas.difficulty['3.6']), true);
check('difficulty citation points at src/mondata.c',
  /^mstrength\(\), src\/mondata\.c:\d+\./.test(DATA.formulas.difficulty['3.7-5.0']),
  true);

/* ====================================================================== */
console.log('\n=== version differences ===\n');

const a36 = new Set(V['3.6'].mons.map((m) => m.n));
const a50 = new Set(V['3.7-5.0'].mons.map((m) => m.n));
const added = [...a50].filter((n) => !a36.has(n));
const removed = [...a36].filter((n) => !a50.has(n));
console.log(`      added in 3.7/5.0 (${added.length}): ${added.join(', ')}`);
console.log(`      gone from 3.6 (${removed.length}): ${removed.join(', ')}`);
check('gold dragon is new in 3.7/5.0', added.includes('gold dragon'), true);
check('genetic engineer is new in 3.7/5.0', added.includes('genetic engineer'), true);
check('displacer beast is new in 3.7/5.0', added.includes('displacer beast'), true);
check('succubus/incubus were merged into "amorous demon"',
  removed.includes('succubus') && removed.includes('incubus')
    && added.includes('amorous demon'), true);

const changed = [...a36].filter((n) => a50.has(n) && byName['3.6'][n].d !== byName['3.7-5.0'][n].d);
console.log(`      difficulty changed for ${changed.length}: ` +
  changed.map((n) => `${n} ${byName['3.6'][n].d}->${byName['3.7-5.0'][n].d}`).join(', '));
check('killer bee difficulty went 5 -> 6', changed.includes('killer bee'), true,
  'mstrength() gained the killer bee / soldier ant +2 fudge in 3.7');

/* ====================================================================== */
console.log('\n=== data sanity across every row ===\n');

let bad = [];
for (const key of Object.keys(V)) {
  V[key].mons.forEach((m, i) => {
    if (typeof m.n !== 'string' || !m.n) bad.push(`${key}[${i}] name`);
    if (!LEG.classes[m.s]) bad.push(`${key} ${m.n}: unknown class symbol ${m.s}`);
    if (m.a.length > 6) bad.push(`${key} ${m.n}: ${m.a.length} attacks`);
    m.a.forEach((a) => {
      if (!LEG.at[String(a[0])]) bad.push(`${key} ${m.n}: unknown AT_ ${a[0]}`);
      if (!LEG.ad[String(a[1])]) bad.push(`${key} ${m.n}: unknown AD_ ${a[1]}`);
    });
    if (!(String(m.sz) in LEG.size)) bad.push(`${key} ${m.n}: unknown size ${m.sz}`);
    if (m.d < 0) bad.push(`${key} ${m.n}: negative difficulty`);
  });
}
check('every row decodes cleanly against the legend', bad.slice(0, 5), []);

/* every generatable monster must be reachable at some (depth, XL) */
for (const key of Object.keys(V)) {
  const reachable = new Set();
  for (let dl = 1; dl <= 53; dl++) {
    for (const hell of [false, true]) {
      for (const h of E.pool(V[key].mons, {
        levelDifficulty: dl, ulevel: 30, inHell: hell, align: 'neutral',
        specialPm: V[key].special_pm
      }).list) reachable.add(h.mon.n);
    }
  }
  const shouldBe = V[key].mons.slice(0, V[key].special_pm)
    .filter((m) => !(m.g & (E.G_NOGEN | E.G_UNIQ)));
  const missing = shouldBe.filter((m) => !reachable.has(m.n)).map((m) => m.n);
  /* The three lawful devils are unreachable by construction, not by a bug in
     this port: G_HELL keeps them out of the main dungeon, and inside Gehennom
     uncommon()'s `maligntyp > A_NEUTRAL` test keeps them out too. They only
     ever arrive via demon summoning (msummon), never via rndmonst(). */
  check(`[${key}] the only monsters rndmonst() can never reach are the ` +
    `lawful G_HELL devils`, missing.sort(),
    ['barbed devil', 'erinys', 'horned devil'],
    `${reachable.size} of ${shouldBe.length} reachable in DL1-53`);
  const explained = missing.every((n) =>
    (byName[key][n].g & E.G_HELL) && byName[key][n].al > 0);
  check(`[${key}] ...and each of those is G_HELL with maligntyp > 0`,
    explained, true);
}

console.log(`\n${pass} passed, ${fail} failed\n`);
process.exit(fail ? 1 : 0);
