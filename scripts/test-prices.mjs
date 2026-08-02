#!/usr/bin/env node
/* Cross-checks assets/price-engine.js against prices derived by hand from
   get_cost() / set_cost() in NetHack src/shk.c.
   No dependencies, no install:   node scripts/test-prices.mjs            */

import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import fs from 'node:fs';

const require = createRequire(import.meta.url);
const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, '..');
const E = require(path.join(root, 'assets', 'price-engine.js'));

let pass = 0;
let fail = 0;

function check(desc, got, want, work) {
  const ok = got === want;
  ok ? pass++ : fail++;
  const tag = ok ? 'PASS' : 'FAIL';
  console.log(
    `${tag}  ${desc.padEnd(52)} got ${String(got).padStart(6)}   want ${String(want).padStart(6)}`
  );
  if (work) console.log(`      ${work}`);
  if (!ok) console.log('      *** ENGINE DISAGREES WITH HAND DERIVATION ***');
}

const buy = (base, o = {}) => E.getCost(base, o);
const sell = (base, o = {}) => E.setCost(base, o);

console.log('\n=== get_cost: shopkeeper sells to you (buy price) ===\n');

/* mult=1 div=1 -> no rounding step at all */
check('base 100, Cha 11, no mods, no surcharge', buy(100, { cha: 11 }), 100,
  'tmp=100, m=1 d=1, divisor not >1 -> 100');

/* m=4 d=3: 100*4=400; 400*10=4000; 4000/3=1333; +5=1338; /10=133 */
check('base 100, Cha 11, unID surcharge', buy(100, { cha: 11, surcharge: true }), 133,
  '400*10=4000 /3=1333 +5=1338 /10=133');

/* Cha 18: m=2 d=3: 200*10=2000; /3=666; +5=671; /10=67 */
check('base 100, Cha 18, no surcharge', buy(100, { cha: 18 }), 67,
  '200*10=2000 /3=666 +5=671 /10=67');

/* Cha 6: m=3 d=2: 300*10=3000; /2=1500; +5=1505; /10=150 */
check('base 100, Cha 6, no surcharge', buy(100, { cha: 6 }), 150,
  '300*10=3000 /2=1500 +5=1505 /10=150');

/* Cha 19: d=2: 100*10=1000; /2=500; +5=505; /10=50 */
check('base 100, Cha 19 (>18), no surcharge', buy(100, { cha: 19 }), 50,
  '100*10=1000 /2=500 +5=505 /10=50');

/* Cha 16: m=3 d=4: 300*10=3000; /4=750; +5=755; /10=75 */
check('base 100, Cha 16, no surcharge', buy(100, { cha: 16 }), 75,
  '300*10=3000 /4=750 +5=755 /10=75');

console.log('\n=== set_cost: shopkeeper buys from you (sell price) ===\n');

/* d=2: 50*10=500; /2=250; +5=255; /10=25 */
check('base 50 sell, no mods', sell(50), 25, '50*10=500 /2=250 +5=255 /10=25');

/* d=3: 50*10=500; /3=166; +5=171; /10=17 */
check('base 50 sell, tourist/dunce', sell(50, { touristy: true }), 17,
  '50*10=500 /3=166 +5=171 /10=17');
check('base 50 sell, dunce cap', sell(50, { dunce: true }), 17, 'same 4/3-family divisor');

console.log('\n=== additional hand-derived checks ===\n');

/* Cha 10: m=4 d=3 -> same shape as the unID surcharge */
check('base 100, Cha 10 (8-10)', buy(100, { cha: 10 }), 133, '400*10/3=1333 +5 /10=133');
/* Cha 5: m=2 d=1 -> no rounding */
check('base 100, Cha 5 (<=5)', buy(100, { cha: 5 }), 200, 'tmp*2, divisor==1');
/* Cha 7: m=3 d=2 */
check('base 100, Cha 7 (6-7)', buy(100, { cha: 7 }), 150, '3000/2=1500 +5 /10=150');
/* Cha 15: no change */
check('base 100, Cha 15 (11-15)', buy(100, { cha: 15 }), 100, 'no change');

/* surcharge 4/3 * Cha16 3/4 = m 12 d 12: 1200*10=12000 /12=1000 +5=1005 /10=100 */
check('base 100, Cha 16 + unID surcharge', buy(100, { cha: 16, surcharge: true }), 100,
  '12000/12=1000 +5=1005 /10=100  (collides with the plain Cha-11 price)');

/* dunce and tourist are if/else-if -> at most one applies, never stacked */
check('base 100, Cha 11, dunce+tourist both set', buy(100, { cha: 11, dunce: true, touristy: true }),
  133, 'only one 4/3 applies (if/else-if in C)');

/* Artifact ×4 lands AFTER rounding: 67*4=268, NOT (m=8,d=3)->267 */
check('base 100, Cha 18, artifact', buy(100, { cha: 18, artifact: true }), 268,
  'round to 67 first, then *4. Folding into the multiplier would give 267.');

/* Angry: tmp += (tmp+2)/3 after rounding. 100 + (102/3=34) = 134 */
check('base 100, Cha 11, angry shk', buy(100, { cha: 11, angry: true }), 134,
  '100 + floor(102/3)=34');

/* Both, in order: 67*4=268; 268+floor(270/3)=268+90=358 */
check('base 100, Cha 18, artifact + angry', buy(100, { cha: 18, artifact: true, angry: true }),
  358, '67 -> *4 = 268 -> +floor(270/3)=90 -> 358');

/* base cost 0 is quoted as if it were 5 */
check('base 0 buy, Cha 11', buy(0, { cha: 11 }), 5, '!tmp -> tmp = 5');
check('base 0 buy, Cha 19', buy(0, { cha: 19 }), 3, '5*10=50 /2=25 +5=30 /10=3');

/* clamp: tiny base with a big divisor must never fall to 0 */
check('base 1 buy, Cha 19', buy(1, { cha: 19 }), 1, '10/2=5 +5=10 /10=1');

/* sell side */
/* m=3 d=8: 50*3=150; 1500/8=187; +5=192; /10=19 */
check('base 50 sell, unID markdown', sell(50, { surcharge: true }), 19,
  '150*10=1500 /8=187 +5=192 /10=19');
/* tmp > 1 gate: base 1 never gets the markdown */
check('base 1 sell, unID markdown set', sell(1, { surcharge: true }), 1,
  'C requires tmp > 1 before applying 3/4; then clamped up to 1');
check('base 0 sell (uncursed water, -1 wand)', sell(0), 0, 'if (tmp >= 1) guard skips everything');
check('base 5 sell', sell(5), 3, '50/2=25 +5=30 /10=3');

console.log('\n=== rounding tweak, direct ===\n');
check('applyTweak(100, 1, 1)', E.applyTweak(100, 1, 1), 100, 'divisor 1 -> untouched');
check('applyTweak(7, 1, 2)', E.applyTweak(7, 1, 2), 4, '70/2=35 +5=40 /10=4 (half rounds up)');
check('applyTweak(5, 1, 2)', E.applyTweak(5, 1, 2), 3, '50/2=25 +5=30 /10=3');
/* The raw tweak can return 0; it is get_cost/set_cost that clamp back up. */
check('applyTweak(1, 1, 3)', E.applyTweak(1, 1, 3), 0, '10/3=3 +5=8 /10=0');
check('getCost never returns 0 for any base/Cha', (() => {
  for (let b = 0; b <= 200; b++) {
    for (let c = 3; c <= 25; c++) {
      for (const s of [false, true]) if (E.getCost(b, { cha: c, surcharge: s }) < 1) return false;
    }
  }
  return true;
})(), true, 'the tmp<=0 -> 1 clamp holds');

console.log('\n=== reverse lookup: round trip ===\n');
{
  const settings = [
    { direction: 'buy', cha: 11 },
    { direction: 'buy', cha: 18, angry: true },
    { direction: 'buy', cha: 6, touristy: true },
    { direction: 'sell', cha: 11 },
    { direction: 'sell', cha: 11, dunce: true }
  ];
  let bad = 0;
  let checked = 0;
  for (const s of settings) {
    for (const base of [1, 2, 5, 10, 20, 50, 60, 80, 100, 150, 200, 300, 500, 950, 4500]) {
      for (const sur of [false, true]) {
        const price = E.priceFor(base, s, sur);
        const hits = E.reverse(Object.assign({ price, maxBase: 5000 }, s));
        const found = hits.some((h) => h.base === base);
        checked++;
        if (!found) {
          bad++;
          console.log(`      MISS base=${base} sur=${sur} price=${price} ${JSON.stringify(s)}`);
        }
      }
    }
  }
  check(`every forward price reverses to its own base (${checked} cases)`, bad, 0);
}

console.log('\n=== reverse lookup: exactness ===\n');
{
  /* Every base the reverse lookup returns must actually produce the price. */
  const obs = { direction: 'buy', cha: 16, price: 100, maxBase: 5000 };
  const hits = E.reverse(obs);
  const allGood = hits.every((h) =>
    h.branches.every((b) => E.priceFor(h.base, obs, b.surcharge) === 100)
  );
  check('every reverse() hit re-derives the observed price', allGood, true);
  console.log(`      buy price 100 @ Cha 16 -> ${hits.length} candidate base costs: ` +
    hits.map((h) => h.base).join(', '));
}

console.log('\n=== multi-observation intersection ===\n');
{
  /* An item with base cost 150 seen at buy 150 (Cha 11, surcharge unknown)
     and sell 75 (no mods). */
  const o1 = { direction: 'buy', cha: 11, price: 150, maxBase: 5000 };
  const o2 = { direction: 'sell', cha: 11, price: 75, maxBase: 5000 };
  const r1 = E.reverse(o1);
  const r2 = E.reverse(o2);
  const both = E.intersect([r1, r2]);
  console.log(`      obs1 -> ${r1.length} bases, obs2 -> ${r2.length} bases, ` +
    `intersection -> ${both.length}: ${both.join(', ')}`);
  check('intersection contains base 150', both.includes(150), true);
  check('intersection is no larger than either input',
    both.length <= Math.min(r1.length, r2.length), true);
}

console.log('\n=== objects.json sanity ===\n');
{
  const data = JSON.parse(fs.readFileSync(path.join(root, 'data', 'objects.json'), 'utf8'));
  const vers = Object.keys(data.versions);
  check('versions present', vers.join(','), '3.6,3.7-5.0');
  check('5.0 weapon prob total is 1002, not 1000',
    data.class_prob_totals['3.7-5.0'].weapon, 1002);
  check('3.6 ring prob total is 0 (uniform fallback needed)',
    data.class_prob_totals['3.6'].ring, 0);

  /* classProbability must not report 0% for 3.6 rings */
  const objs36 = data.versions['3.6'].objects;
  const counts = {};
  objs36.forEach((o) => { counts[o.class] = (counts[o.class] || 0) + 1; });
  const ring = objs36.find((o) => o.class === 'ring');
  const p = E.classProbability(ring, data.class_prob_totals['3.6'], counts);
  check('3.6 ring probability falls back to uniform', p.uniform && p.pct > 0, true,
    `${ring.name}: ${p.pct.toFixed(2)}% uniform over ${p.denom} rings`);

  /* `other` is a mix of C classes -> suppressed */
  const other = objs36.find((o) => o.class === 'other');
  check('`other` class probability suppressed',
    E.classProbability(other, data.class_prob_totals['3.6'], counts).known, false);

  /* enchantment offset only touches weapons/armor */
  const wep = objs36.find((o) => o.name === 'long sword');
  check('+3 long sword base cost', E.effectiveBase(wep, 3), wep.cost + 30);
  const scr = objs36.find((o) => o.class === 'scroll' && o.cost > 0);
  check('+3 does not change a scroll base cost', E.effectiveBase(scr, 3), scr.cost);

  /* candidate mapping excludes cost 0 */
  const zeroCost = objs36.filter((o) => o.cost === 0).length;
  check('cost-0 objects exist in the data (denominator correctness)', zeroCost > 0, true,
    `${zeroCost} objects with cost 0`);
  check('itemsForBase(0) returns nothing', E.itemsForBase(objs36, 0, 0).length, 0);

  /* a real end-to-end: what could a 133-gold quote at Cha 11 be? */
  const hits = E.reverse({ direction: 'buy', cha: 11, price: 133, maxBase: 30000 });
  const names = [];
  hits.forEach((h) => E.itemsForBase(objs36, h.base, 0).forEach((i) => names.push(i.name)));
  console.log(`      buy quote 133 @ Cha 11 -> bases [${hits.map((h) => h.base).join(', ')}]` +
    ` -> ${names.length} candidate items`);
  check('133 @ Cha 11 includes base 100 (unID surcharge branch)',
    hits.some((h) => h.base === 100), true);
}

console.log(`\n${pass} passed, ${fail} failed\n`);
process.exit(fail ? 1 : 0);
