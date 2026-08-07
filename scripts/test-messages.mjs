#!/usr/bin/env node
/* Cross-checks data/messages.json's structure and assets/message-engine.js's
   search/filter/highlight logic.

   No dependencies, no install:   node scripts/test-messages.mjs             */

import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import fs from 'node:fs';

const require = createRequire(import.meta.url);
const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, '..');
const E = require(path.join(root, 'assets', 'message-engine.js'));
const DATA = JSON.parse(fs.readFileSync(path.join(root, 'data', 'messages.json'), 'utf8'));

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

const ENTRIES = DATA.entries;
const byId = {};
ENTRIES.forEach((e) => { byId[e.id] = e; });

/* ====================================================================== */
console.log('\n-- data/messages.json structure --\n');

check('every entry has a unique id',
  new Set(ENTRIES.map((e) => e.id)).size, ENTRIES.length,
  `${ENTRIES.length} entries`);

check('every id starts with its own prefix',
  ENTRIES.every((e) => e.id.startsWith(e.prefix)), true);

check('every prefix is you-feel or you-hear',
  ENTRIES.every((e) => e.prefix === 'you-feel' || e.prefix === 'you-hear'), true);

const STATUSES = new Set(['present', 'absent', 'unverified']);
check('every entry has 3.7 and 5.0 version info with a known status',
  ENTRIES.every((e) =>
    e.versions && STATUSES.has((e.versions['3.7'] || {}).status) &&
    STATUSES.has((e.versions['5.0'] || {}).status)),
  true);

check('every "present" version carries file/line/literal',
  ENTRIES.every((e) => ['3.7', '5.0'].every((v) => {
    const info = e.versions[v];
    return info.status !== 'present' ||
      (typeof info.file === 'string' && typeof info.line === 'number' &&
       typeof info.literal === 'string');
  })),
  true);

const reverse = ENTRIES.filter((e) => e.source_page === null);
check('reverse-sweep entries (not on the wiki) are all 5.0-present',
  reverse.length > 0 && reverse.every((e) => e.versions['5.0'].status === 'present'),
  true,
  `${reverse.length} reverse-sweep entries`);

/* The sweep only reads 5.0, so its entries start out 3.7-unverified; backfill_3_7()
   then resolves them by looking up the 5.0 call site's literal in the 3.7 tree. A
   sweep entry may therefore be 3.7-present or 3.7-unverified, but never 3.7-absent —
   failing to find the literal means the search was inconclusive, not that the message
   is known to be missing, and conflating those is exactly the bug this guards. */
check('the 3.7 backfill never marks a reverse-sweep entry absent',
  reverse.every((e) => e.versions['3.7'].status !== 'absent'), true);

const backfilled = reverse.filter((e) => e.versions['3.7'].status === 'present');
check('the 3.7 backfill resolved the large majority of the sweep',
  backfilled.length > reverse.length * 0.9, true,
  `${backfilled.length}/${reverse.length} resolved against 3.7`);

check('every backfilled 3.7 citation records how it was derived',
  backfilled.every((e) => typeof e.versions['3.7'].via === 'string'), true);

/* A status of "absent" is a positive claim that the message is not in that branch, so it
   has to carry the search that justifies it — an unexplained "absent" is how "You hear
   chewing." ended up wrongly marked missing while its own call site sat in muse.c. */
const absent = ENTRIES.flatMap((e) => ['3.7', '5.0'].map((v) => e.versions[v]))
  .filter((i) => i.status === 'absent');
check('every "absent" verdict carries a note explaining the search',
  absent.length > 0 && absent.every((i) => typeof i.note === 'string' && i.note.length > 40),
  true,
  `${absent.length} absent verdicts`);

/* ====================================================================== */
console.log('\n-- MessageEngine.normalize mirrors gen-messages.py norm_text() --\n');

/* text_norm/explanation_norm are pre-computed by the Python generator; the
   engine's normalize() must reproduce that exact transform, or a typed query
   would fail to match text that visibly contains it. */
const sample = ENTRIES.slice(0, 50);
check('normalize(text) matches every sampled entry\'s stored text_norm',
  sample.every((e) => E.normalize(e.text) === e.text_norm), true,
  `checked ${sample.length} entries`);

check('normalize strips HTML tags, lowercases, and drops punctuation',
  E.normalize('You feel <b>a tug</b> from the "iron ball," don\'t you?'),
  'you feel a tug from the iron ball don t you');

check('normalize collapses whitespace',
  E.normalize('  a   b\tc  '), 'a b c');

/* ====================================================================== */
console.log('\n-- MessageEngine.search --\n');

check('an empty query returns no results',
  E.search(ENTRIES, '', {}), { results: [], total: 0, truncated: false });

check('an all-whitespace query returns no results',
  E.search(ENTRIES, '   ', {}).results.length, 0);

const quickness = E.search(ENTRIES, 'quickness', { version: 'any' });
check('"quickness" finds the absent you-feel-054 entry',
  quickness.results.some((e) => e.id === 'you-feel-054'), true,
  `${quickness.results.length} result(s)`);

check('filtering to 3.7-present excludes an entry that is absent in 3.7',
  E.search(ENTRIES, 'quickness', { version: '3.7' }).results
    .some((e) => e.id === 'you-feel-054'),
  false);

check('filtering to 5.0-present excludes an entry that is absent in 5.0',
  E.search(ENTRIES, 'quickness', { version: '5.0' }).results
    .some((e) => e.id === 'you-feel-054'),
  false);

check('filtering to a version a message is actually present in keeps it',
  E.search(ENTRIES, 'cat', { version: '3.7' }).results.some((e) => e.id === 'you-feel-001'),
  true);

/* you-hear-new-sounds_c_257's *text* says "gold coins"; you-feel-143's text
   doesn't mention gold at all but its explanation does — a direct check that
   text hits outrank explanation-only hits regardless of list position. */
check('a text match ranks before an explanation-only match',
  (() => {
    const r = E.search(ENTRIES, 'gold', { version: 'any' });
    const textHit = r.results.findIndex((e) => e.id === 'you-hear-new-sounds_c_257');
    const explHit = r.results.findIndex((e) => e.id === 'you-feel-143');
    return textHit >= 0 && explHit >= 0 && textHit < explHit;
  })(),
  true);

check('results are capped at `limit` and report the real total',
  (() => {
    const full = E.search(ENTRIES, 'you', { version: 'any' });
    const capped = E.search(ENTRIES, 'you', { version: 'any', limit: 5 });
    return capped.results.length === 5 && capped.truncated === true &&
      capped.total === full.total && full.total > 5;
  })(),
  true);

check('a query with no matches returns an empty, non-truncated result',
  E.search(ENTRIES, 'zzzznonexistentzzzz', { version: 'any' }),
  { results: [], total: 0, truncated: false });

/* ====================================================================== */
console.log('\n-- MessageEngine.highlight / statusBadge --\n');

check('highlight wraps a case-insensitive match in <mark> and escapes the rest',
  E.highlight('You feel <special> & "odd"', 'FEEL'),
  'You <mark>feel</mark> &lt;special&gt; &amp; &quot;odd&quot;');

check('highlight with an empty query just escapes',
  E.highlight('<b>x</b>', ''), '&lt;b&gt;x&lt;/b&gt;');

check('statusBadge maps known statuses to badge classes',
  ['present', 'absent', 'unverified'].map((s) => E.statusBadge(s).cls),
  ['b-green', 'b-red', 'b-yellow']);

check('statusBadge falls back to b-dim for an unknown status',
  E.statusBadge('mystery').cls, 'b-dim');

console.log(`\n${pass} passed, ${fail} failed\n`);
process.exit(fail ? 1 : 0);
