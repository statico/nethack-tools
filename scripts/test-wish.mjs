#!/usr/bin/env node
/* Cross-checks assets/wish-engine.js and data/wish.json against readobjnam()
   and mksobj() as read by hand out of the NetHack source.

   Every expected value below is derived on paper from the C, and the comment
   says where.  No dependencies, no install:   node scripts/test-wish.mjs   */

import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import fs from 'node:fs';

const require = createRequire(import.meta.url);
const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, '..');
const E = require(path.join(root, 'assets', 'wish-engine.js'));

const DATA = JSON.parse(fs.readFileSync(path.join(root, 'data', 'wish.json'), 'utf8'));
const OBJECTS = JSON.parse(
  fs.readFileSync(path.join(root, 'data', 'objects.json'), 'utf8')
);

let pass = 0;
let fail = 0;

function check(desc, got, want, work) {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  ok ? pass++ : fail++;
  console.log(
    `${ok ? 'PASS' : 'FAIL'}  ${desc.padEnd(62)} got ${JSON.stringify(got)}`
  );
  if (!ok) console.log(`      want ${JSON.stringify(want)}`);
  if (work) console.log(`      ${work}`);
}

function near(desc, got, want, work, eps = 1e-9) {
  const ok = Math.abs(got - want) < eps;
  ok ? pass++ : fail++;
  console.log(
    `${ok ? 'PASS' : 'FAIL'}  ${desc.padEnd(62)} got ${got.toFixed(6)}`
  );
  if (!ok) console.log(`      want ${want.toFixed(6)}`);
  if (work) console.log(`      ${work}`);
}

function has(desc, findings, key, status) {
  const f = findings.find((x) => x.key === key);
  check(desc, f ? f.status : '(missing)', status);
  return f;
}

/* ------------------------------------------------------------------ */
console.log('\n=== data joins cleanly with objects.json ===\n');

const orphans = E.attachClasses(DATA, OBJECTS);
check('every wish.json object name exists in objects.json', orphans, []);
check('versions present', Object.keys(DATA.versions), ['3.6', '3.7-5.0']);

for (const key of Object.keys(DATA.versions)) {
  const V = DATA.versions[key];
  check(`[${key}] long sword joined to class "weapon"`, V.objects['long sword'].cls,
    'weapon');
  check(`[${key}] every rule citation has a file and a line`,
    Object.values(V.cites).every((c) => c.file && c.line > 0), true);
}

/* ------------------------------------------------------------------ */
console.log('\n=== probability primitives ===\n');

/* rne(3): tmp starts at 1 and increments while rn2(3) == 0, so
   P(rne >= n) = (1/3)^(n-1) up to the utmp cap of 5 (src/rnd.c:192). */
near('P(rne(3) >= 1)', E.pRneAtLeast(3, 1), 1);
near('P(rne(3) >= 2)', E.pRneAtLeast(3, 2), 1 / 3, 'one rn2(3)==0 needed');
near('P(rne(3) >= 3)', E.pRneAtLeast(3, 3), 1 / 9);
near('P(rne(3) >= 5)', E.pRneAtLeast(3, 5), 1 / 81);
near('P(rne(3) >= 6) at XL < 15', E.pRneAtLeast(3, 6), 0, 'utmp caps at 5');

/* rnd(5) is uniform 1..5 (src/rnd.c) */
near('P(rnd(5) >= 3)', E.pRndAtLeast(5, 3), 3 / 5);
near('P(rnd(5) >= 6)', E.pRndAtLeast(5, 6), 0);
near('P(rnd(6) >= 1)', E.pRndAtLeast(6, 1), 1);

/* rn2(4) - rn2(3): 12 equally likely pairs; >=1 in 6 of them (3+2+1) */
near('P(rn2(4) - rn2(3) >= 1)', E.pRingReroll(1), 6 / 12);
near('P(rn2(4) - rn2(3) >= 2)', E.pRingReroll(2), 3 / 12);
near('P(rn2(4) - rn2(3) >= 3)', E.pRingReroll(3), 1 / 12);
near('P(rn2(4) - rn2(3) >= 4)', E.pRingReroll(4), 0);

near('P(uniform[4,8] >= 4)', E.pRangeAtLeast(4, 8, 4), 1);
near('P(uniform[4,8] >= 8)', E.pRangeAtLeast(4, 8, 8), 1 / 5);
near('P(uniform[4,8] >= 9)', E.pRangeAtLeast(4, 8, 9), 0);

/* ------------------------------------------------------------------ */
console.log('\n=== mksobj() starting spe (src/mkobj.c:869) ===\n');

const V50 = DATA.versions['3.7-5.0'];
const item = (name) => ({ name, cls: V50.objects[name].cls, f: V50.objects[name] });

/* weapons: !rn2(11) -> spe = rne(3); so P(spe >= n) = (1/11)(1/3)^(n-1) */
near('weapon: P(random spe >= 1)', E.pRandomSpeAtLeast(item('long sword'), V50, 1),
  1 / 11);
near('weapon: P(random spe >= 3)', E.pRandomSpeAtLeast(item('long sword'), V50, 3),
  (1 / 11) * (1 / 9));

/* armor: P(cursed branch) = (9/10)(1/11); positive branch = (1-that)(1/10) */
const pArmCursed = (9 / 10) * (1 / 11);
near('armor: P(random spe >= 1)',
  E.pRandomSpeAtLeast(item('gray dragon scale mail'), V50, 1),
  (1 - pArmCursed) * (1 / 10),
  '9/10 * 1/11 curses it; of the rest, 1/10 gets +rne(3)');

/* levitation boots are in mksobj's usually-cursed list, so almost never +N */
near('levitation boots: P(random spe >= 1)',
  E.pRandomSpeAtLeast(item('levitation boots'), V50, 1),
  (1 - 9 / 10) * (1 / 10),
  'the special list makes the cursed branch fire whenever rn2(10) != 0');

/* charged ring: 9/20 chance of +rne(3), 1/10 chance of the rn2(4)-rn2(3) reroll */
near('ring of increase damage: P(random spe >= 2)',
  E.pRandomSpeAtLeast(item('ring of increase damage'), V50, 2),
  (9 / 20) * (1 / 3) + (1 / 10) * (3 / 12));

/* wands roll rn1(5, 4) = 4..8, or rn1(5, 11) = 11..15 when NODIR */
check('beam wand charge range', E.randomSpeRange(item('wand of death'), V50), [4, 8]);
check('NODIR wand charge range', E.randomSpeRange(item('wand of light'), V50),
  [11, 15]);
check('magic marker charge range', E.randomSpeRange(item('magic marker'), V50),
  [30, 99]);
check('non-charged item has no range', E.randomSpeRange(item('long sword'), V50),
  null);

/* ------------------------------------------------------------------ */
console.log('\n=== which arm of the spe switch (objnam.c:5123) ===\n');

check('long sword -> enchantable', E.speBranch(item('long sword'), V50), 'enchant');
check('plate mail -> enchantable', E.speBranch(item('plate mail'), V50), 'enchant');
check('unicorn horn (weptool) -> enchantable',
  E.speBranch(item('unicorn horn'), V50), 'enchant');
check('ring of increase damage (charged) -> enchantable',
  E.speBranch(item('ring of increase damage'), V50), 'enchant');
check('ring of stealth (uncharged) -> other',
  E.speBranch(item('ring of stealth'), V50), 'other');
check('wand of death -> wandlike', E.speBranch(item('wand of death'), V50),
  'wandlike');
check('crystal ball -> wandlike in 3.7/5.0',
  E.speBranch(item('crystal ball'), V50), 'wandlike');
{
  const V36 = DATA.versions['3.6'];
  const cb36 = { name: 'crystal ball', cls: V36.objects['crystal ball'].cls,
    f: V36.objects['crystal ball'] };
  check('crystal ball -> other in 3.6', E.speBranch(cb36, V36), 'other');
}
check('magic marker -> other', E.speBranch(item('magic marker'), V50), 'other');

/* ------------------------------------------------------------------ */
console.log('\n=== canonical wish string ===\n');

const spec = (o) => Object.assign({
  version: '3.7-5.0', item: null, artifact: null, bcu: '', spe: 0,
  speGiven: false, recharged: 0, erodeproof: false, greased: false,
  poisoned: false, quantity: null, luckNeg: false, nArtifacts: 1
}, o);

check('plain item',
  E.buildString(spec({ item: 'long sword' }), DATA).text, 'long sword');
check('the classic armor wish',
  E.buildString(spec({
    item: 'gray dragon scale mail', bcu: 'blessed', greased: true,
    erodeproof: true, spe: 2, speGiven: true
  }), DATA).text,
  'blessed greased fixed +2 gray dragon scale mail',
  'doname_base() order: B/U/C, greased, poisoned, erodeproof word, +N, name');
check('poisoned ammo with a count',
  E.buildString(spec({
    item: 'elven arrow', bcu: 'blessed', poisoned: true, quantity: 20,
    spe: 2, speGiven: true
  }), DATA).text,
  '20 blessed poisoned +2 elven arrow');
check('wands use the (n:m) suffix that doname() prints',
  E.buildString(spec({ item: 'wand of digging', spe: 8, speGiven: true }), DATA).text,
  'wand of digging (0:8)');
check('artifact wishes name the artifact, not the base item',
  E.buildString(spec({ artifact: 'Excalibur' }), DATA).text, 'Excalibur');
check('negative enchantment keeps its sign',
  E.buildString(spec({ item: 'long sword', spe: -3, speGiven: true }), DATA).text,
  '-3 long sword');
check('quantity 1 is not written out',
  E.buildString(spec({ item: 'arrow', quantity: 1 }), DATA).text, 'arrow');

/* ------------------------------------------------------------------ */
console.log('\n=== enchantment clamping (objnam.c:5131) ===\n');

function ench(o) {
  return E.evaluate(spec(o), DATA).findings.find((f) => f.key === 'spe_clamp');
}

/* if (d.spe > rnd(5) && d.spe > d.otmp->spe) d.spe = 0;
   rnd(5) >= 1 always, so +1 can never be zeroed. */
check('+1 long sword is never reduced',
  ench({ item: 'long sword', spe: 1, speGiven: true }).status, 'honored');

/* +3: P(3 > rnd(5)) = 2/5; P(3 > obj spe) = 1 - (1/11)(1/9).
   P(keep) = 1 - (2/5)(1 - 1/99) */
{
  const f = ench({ item: 'long sword', spe: 3, speGiven: true });
  near('+3 long sword survives', f.prob, 1 - (2 / 5) * (1 - (1 / 11) * (1 / 9)),
    'P(3 > rnd(5)) = 2/5, times P(mksobj rolled < 3)');
  check('+3 is reported as a chance', f.status, 'chance');
}

/* +5: P(5 > rnd(5)) = 4/5 */
near('+5 long sword survives',
  ench({ item: 'long sword', spe: 5, speGiven: true }).prob,
  1 - (4 / 5) * (1 - (1 / 11) * (1 / 81)));

/* +7: rnd(5) can never reach 7, so only a lucky mksobj() roll saves it, and
   at XL < 15 rne(3) caps at 5, so nothing does. */
{
  const f = ench({ item: 'long sword', spe: 7, speGiven: true });
  near('+7 long sword survives', f.prob, 0,
    'this is the "you asked for +7 and got +0" rule');
  check('+7 is reported as blocked', f.status, 'blocked');
}
{
  const f = ench({ item: 'gray dragon scale mail', spe: 7, speGiven: true });
  near('+7 gray dragon scale mail survives', f.prob, 0);
}

/* +2 armor: P(2 > rnd(5)) = 1/5 */
near('+2 gray dragon scale mail survives',
  ench({ item: 'gray dragon scale mail', spe: 2, speGiven: true }).prob,
  1 - (1 / 5) * (1 - (1 - pArmCursed) * (1 / 10) * (1 / 3)));

/* the request is ZEROED, not reduced -- assert the text says so */
check('the finding explains that the request is zeroed, not reduced',
  /zeroes the request rather than reducing it/.test(
    ench({ item: 'long sword', spe: 4, speGiven: true }).text), true);

/* negative Luck flips anything above +2 (objnam.c:5133) */
{
  const f = E.evaluate(
    spec({ item: 'long sword', spe: 3, speGiven: true, luckNeg: true }), DATA
  ).findings;
  has('negative Luck blocks +3', f, 'spe_luck', 'blocked');
  const g = E.evaluate(
    spec({ item: 'long sword', spe: 2, speGiven: true, luckNeg: true }), DATA
  ).findings;
  check('negative Luck leaves +2 alone',
    g.some((x) => x.key === 'spe_luck'), false);
}

/* SPE_LIM / SCHAR_LIM cap (objnam.c:4262) */
{
  const f = E.evaluate(
    spec({ item: 'long sword', spe: 500, speGiven: true }), DATA
  ).findings;
  has('+500 is capped at SPE_LIM first', f, 'spe_cap', 'clamped');
  check('5.0 caps at 99', V50.consts.spe_cap, 99);
  check('3.6 caps at 127 (SCHAR_LIM)', DATA.versions['3.6'].consts.spe_cap, 127);
}

/* ------------------------------------------------------------------ */
console.log('\n=== charges on wands and tools (objnam.c:5144) ===\n');

{
  const f = E.evaluate(
    spec({ item: 'wand of death', spe: 8, speGiven: true }), DATA
  ).findings.find((x) => x.key === 'spe_cap_random');
  near('(0:8) wand of death succeeds', f.prob, 1 / 5,
    'capped at mksobj rn1(5,4) = 4..8, so only the 8 roll allows it');
  const g = E.evaluate(
    spec({ item: 'wand of death', spe: 4, speGiven: true }), DATA
  ).findings.find((x) => x.key === 'spe_cap_random');
  check('(0:4) wand of death always works', g.status, 'honored');
  const h = E.evaluate(
    spec({ item: 'wand of death', spe: 15, speGiven: true }), DATA
  ).findings.find((x) => x.key === 'spe_cap_random');
  check('(0:15) wand of death is impossible', h.status, 'clamped');
  near('(0:15) wand of death probability', h.prob, 0);
}
{
  const f = E.evaluate(
    spec({ item: 'wand of wishing', spe: 3, speGiven: true }), DATA
  ).findings;
  has('wand of wishing charges are overwritten', f, 'wan_wishing', 'blocked');
}
{
  const f = E.evaluate(
    spec({ item: 'wand of digging', spe: -5, speGiven: true }), DATA
  ).findings;
  has('a negative wand request clamps to -1', f, 'spe_wand_neg', 'clamped');
}
{
  const f = E.evaluate(
    spec({ item: 'magic marker', spe: 99, speGiven: true }), DATA
  ).findings.find((x) => x.key === 'spe_cap_random');
  near('(0:99) magic marker succeeds', f.prob, 1 / 70,
    'mksobj rolls rn1(70,30) = 30..99');
  const g = E.evaluate(
    spec({ item: 'magic marker', spe: 30, speGiven: true }), DATA
  ).findings.find((x) => x.key === 'spe_cap_random');
  check('(0:30) magic marker always works', g.status, 'honored');
}
{
  /* not enchantable, no charges: the cap is 0 */
  const f = E.evaluate(
    spec({ item: 'scroll of identify', spe: 3, speGiven: true }), DATA
  ).findings.find((x) => x.key === 'spe_cap_random');
  check('+3 scroll of identify is dropped', f.status, 'dropped');
}

/* ------------------------------------------------------------------ */
console.log('\n=== quantity (objnam.c:5100) ===\n');

function quan(o) {
  return E.evaluate(spec(o), DATA).findings.find((f) => f.key === 'quantity');
}
check('20 arrows are granted outright',
  quan({ item: 'arrow', quantity: 20 }).status, 'honored');
check('21 arrows fall back to the rnd(6) roll',
  quan({ item: 'arrow', quantity: 21 }).status, 'dropped');
check('7 wax candles are granted outright',
  quan({ item: 'wax candle', quantity: 7 }).status, 'honored');
check('8 wax candles are not',
  quan({ item: 'wax candle', quantity: 8 }).status, 'dropped');
check('2 potions of full healing is a coin flip, not a promise',
  quan({ item: 'potion of full healing', quantity: 2 }).status, 'chance');
check('6 potions can never be granted',
  quan({ item: 'potion of full healing', quantity: 6 }).status, 'dropped');
check('a count on a non-mergeable item is ignored',
  quan({ item: 'long sword', quantity: 3 }).status, 'dropped');
check('20 flint stones stack in 3.7/5.0',
  quan({ item: 'flint', quantity: 20 }).status, 'honored');
check('20 flint stones do NOT stack in 3.6',
  quan({ version: '3.6', item: 'flint', quantity: 20 }).status, 'dropped');

/* P(cnt < rnd(6)) = (6 - cnt)/6 */
check('the rnd(6) chance is quoted correctly for 2',
  /67%/.test(quan({ item: 'potion of full healing', quantity: 2 }).text), true);

/* ------------------------------------------------------------------ */
console.log('\n=== beatitude, erodeproof, poison, grease ===\n');

{
  const f = E.evaluate(spec({ item: 'long sword', bcu: 'blessed' }), DATA).findings;
  has('blessed at non-negative Luck', f, 'buc', 'honored');
  const g = E.evaluate(
    spec({ item: 'long sword', bcu: 'blessed', luckNeg: true }), DATA
  ).findings;
  has('blessed at negative Luck backfires into cursed', g, 'buc', 'blocked');
  const h = E.evaluate(
    spec({ item: 'long sword', bcu: 'cursed', luckNeg: true }), DATA
  ).findings;
  has('cursed is always honored', h, 'buc', 'honored');
  const i = E.evaluate(spec({ item: 'long sword' }), DATA).findings;
  has('unspecified beatitude is mksobj\'s roll', i, 'buc', 'note');
}
{
  /* mithril is none of rustprone/flammable/rottable/corrodeable/crackable,
     so is_damageable() is false and the flag is parsed then discarded */
  const f = E.evaluate(
    spec({ item: 'elven mithril-coat', erodeproof: true }), DATA
  ).findings;
  has('mithril cannot be erodeproofed', f, 'erodeproof', 'dropped');
  /* dragon hide IS is_rottable() (objclass.h), so readobjnam() does honor
     "fixed" on dragon scale mail -- and doname() calls it "rotproof" */
  const dsm = E.evaluate(
    spec({ item: 'gray dragon scale mail', erodeproof: true }), DATA
  ).findings;
  has('dragon hide is rottable, so "fixed" sticks', dsm, 'erodeproof', 'honored');
  check('and the game calls it rotproof',
    /rotproof/.test(dsm.find((x) => x.key === 'erodeproof').text), true);
  const g = E.evaluate(spec({ item: 'long sword', erodeproof: true }), DATA).findings;
  has('a long sword can', g, 'erodeproof', 'honored');
  check('and the game will call it rustproof',
    /rustproof/.test(g.find((x) => x.key === 'erodeproof').text), true);
  const h = E.evaluate(
    spec({ item: 'long sword', erodeproof: true, luckNeg: true }), DATA
  ).findings;
  has('negative Luck drops erodeproof', h, 'erodeproof', 'dropped');
  const i = E.evaluate(spec({ item: 'crysknife', erodeproof: true }), DATA).findings;
  has('a crysknife takes "fixed"', i, 'erodeproof', 'honored');
}
{
  const f = E.evaluate(spec({ item: 'elven arrow', poisoned: true }), DATA).findings;
  has('arrows can be poisoned', f, 'poisoned', 'honored');
  const g = E.evaluate(spec({ item: 'long sword', poisoned: true }), DATA).findings;
  has('long swords cannot', g, 'poisoned', 'dropped');
  const h = E.evaluate(
    spec({ item: 'elven arrow', poisoned: true, luckNeg: true }), DATA
  ).findings;
  has('negative Luck drops poison', h, 'poisoned', 'dropped');
}
{
  const f = E.evaluate(spec({ item: 'long sword', greased: true }), DATA).findings;
  has('grease is unconditional', f, 'greased', 'honored');
  const g = E.evaluate(
    spec({ item: 'scroll of identify', greased: true, luckNeg: true }), DATA
  ).findings;
  has('even on a scroll at negative Luck', g, 'greased', 'honored');
}

/* ------------------------------------------------------------------ */
console.log('\n=== things you cannot wish for (objnam.c:5033) ===\n');

for (const [from, to] of [
  ['Amulet of Yendor', 'cheap plastic imitation'],
  ['Bell of Opening', 'bell'],
  ['Book of the Dead', 'spellbook of blank paper'],
  ['magic lamp', 'oil lamp'],
  ['Candelabrum of Invocation', 'candle']
]) {
  const f = E.evaluate(spec({ item: from }), DATA).findings
    .find((x) => x.key === 'substitute');
  check(`${from} is substituted`, f ? f.status : '(missing)', 'blocked');
  check(`  ... with something matching /${to}/`,
    f ? new RegExp(to).test(f.text) : false, true);
}
{
  const venom = V50.nowish_rejected[0];
  const f = E.evaluate(spec({ item: venom }), DATA).findings
    .find((x) => x.key === 'nowish');
  check(`${venom} is refused outright`, f ? f.status : '(missing)', 'blocked');
  check('only venom is oc_nowish without a substitute',
    V50.nowish_rejected.every((n) => /venom/.test(n)), true);
}

/* ------------------------------------------------------------------ */
console.log('\n=== artifacts (objnam.c:5402, do_name.c:392) ===\n');

/* rn2(nartifact_exist()) > 1, counted AFTER the new artifact registers.
   rn2(n) is 0..n-1, so it can only exceed 1 when n >= 3. */
check('1st artifact of the game never fails', E.artifactFailChance(1), 0);
check('2nd artifact never fails', E.artifactFailChance(2), 0);
near('3rd artifact fails 1 time in 3', E.artifactFailChance(3), 1 / 3);
near('5th artifact fails 3 times in 5', E.artifactFailChance(5), 3 / 5);
near('10th artifact fails 8 times in 10', E.artifactFailChance(10), 8 / 10);

{
  const f = E.evaluate(spec({ artifact: 'Excalibur', nArtifacts: 1 }), DATA).findings;
  has('a first artifact wish is guaranteed', f, 'arti_roll', 'honored');
  has('and the base item is named', f, 'arti_base', 'note');
  has('the already-exists case is spelled out', f, 'arti_exists', 'note');
  has('SPFX_NOGEN is called out for Excalibur', f, 'arti_nogen', 'note');
  check('Excalibur resolves to a long sword',
    E.resolveItem(spec({ artifact: 'Excalibur' }), DATA).name, 'long sword');

  const g = E.evaluate(spec({ artifact: 'Excalibur', nArtifacts: 4 }), DATA).findings;
  has('a fourth artifact wish is a coin flip', g, 'arti_roll', 'chance');
  check('and the odds are quoted', /50%/.test(
    g.find((x) => x.key === 'arti_roll').text), true);
}
{
  const f = E.evaluate(spec({ artifact: 'The Orb of Detection' }), DATA).findings;
  has('your own quest artifact is blocked', f, 'arti_quest', 'blocked');
  check('and the role is named',
    /Archeologist/.test(f.find((x) => x.key === 'arti_quest').text), true);
}
{
  /* is_quest_artifact() only matches YOUR role's artifact, and the Palantir
     of Westernesse is nobody's, so it has no quest restriction at all */
  const f = E.evaluate(
    spec({ artifact: 'The Palantir of Westernesse' }), DATA
  ).findings;
  check('the Palantir has no quest restriction',
    f.some((x) => x.key === 'arti_quest'), false);
  check('the Palantir is a crystal ball',
    E.resolveItem(spec({ artifact: 'The Palantir of Westernesse' }), DATA).name,
    'crystal ball');
}
{
  const f = E.evaluate(spec({ artifact: 'Stormbringer' }), DATA).findings;
  has('alignment is explicitly not a restriction', f, 'arti_align', 'note');
  check('and the note says so',
    /never for wishes/.test(f.find((x) => x.key === 'arti_align').text), true);
}
check('13 roles have a quest artifact',
  V50.artifacts.filter((a) => a.questrole).length, 13);
check('every artifact base object exists in the object table',
  V50.artifacts.every((a) => !!V50.objects[a.base]), true);

/* ------------------------------------------------------------------ */
console.log('\n=== version differences ===\n');

{
  const d = E.versionDiffs(DATA);
  check('there is at least one difference to show', d.length > 0, true);
  const speCap = d.find((x) => /Cap on a requested/.test(x.what));
  check('the SPE_LIM change is listed', !!speCap, true);
  check('  3.6 side', speCap.v36, 'SCHAR_LIM = 127');
  check('  3.7/5.0 side', speCap.v37, 'SPE_LIM = 99');
  const cb = d.find((x) => /crystal ball/.test(x.what));
  check('the crystal ball charge change is listed', !!cb, true);
  const flint = d.find((x) => /flint/.test(x.what));
  check('the flint stacking change is listed', !!flint, true);
  d.forEach((x) => console.log(`      · ${x.what}: ${x.v36}  ->  ${x.v37}`));
}

/* ------------------------------------------------------------------ */
console.log('\n=== every object can be evaluated without throwing ===\n');

{
  let bad = 0;
  let checked = 0;
  for (const key of Object.keys(DATA.versions)) {
    for (const name of Object.keys(DATA.versions[key].objects)) {
      for (const s of [
        { spe: 3, speGiven: true },
        { spe: -3, speGiven: true },
        { spe: 99, speGiven: true, luckNeg: true },
        { quantity: 5, greased: true, poisoned: true, erodeproof: true,
          bcu: 'blessed' }
      ]) {
        checked++;
        try {
          const sp = spec(Object.assign({ version: key, item: name }, s));
          const r = E.evaluate(sp, DATA);
          const t = E.buildString(sp, DATA).text;
          if (!t || !r.findings.length) bad++;
        } catch (err) {
          bad++;
          console.log(`      THREW for ${key} ${name}: ${err.message}`);
        }
      }
    }
  }
  check(`no object throws or comes out empty (${checked} cases)`, bad, 0);
}
{
  let bad = 0;
  for (const key of Object.keys(DATA.versions)) {
    for (const a of DATA.versions[key].artifacts) {
      for (let n = 1; n <= 6; n++) {
        try {
          const sp = spec({ version: key, artifact: a.name, nArtifacts: n });
          if (!E.evaluate(sp, DATA).findings.length) bad++;
          if (E.buildString(sp, DATA).text !== a.name) bad++;
        } catch (err) {
          bad++;
          console.log(`      THREW for ${key} ${a.name}: ${err.message}`);
        }
      }
    }
  }
  check('no artifact throws', bad, 0);
}

console.log(`\n${pass} passed, ${fail} failed\n`);
process.exit(fail ? 1 : 0);
