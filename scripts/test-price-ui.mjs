#!/usr/bin/env node
/* Candidate-table presentation and sorting checks.
   No dependencies, no install:   node scripts/test-price-ui.mjs */

import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const require = createRequire(import.meta.url);
const here = path.dirname(fileURLToPath(import.meta.url));
const UI = require(path.resolve(here, '..', 'assets', 'price-ui.js'));

let passed = 0;

function test(name, fn) {
  fn();
  passed++;
  console.log(`PASS  ${name}`);
}

function row(name, cls, pct) {
  return {
    item: { name, class: cls },
    p: pct === null ? { known: false, pct: 0 } : { known: true, pct }
  };
}

const candidates = [
  row('scroll of identify', 'scroll', 18),
  row('apple', 'food', 7),
  row('scroll of charging', 'scroll', 3),
  row('amulet of life saving', 'amulet', 1),
  row('mystery', 'other', null)
];

test('item sort is case-insensitive and ascending', () => {
  const mixedCase = [row('Zorkmid', 'other', null), row('apple', 'food', 1)];
  assert.deepEqual(
    UI.sortCandidates(mixedCase, 'item', 1).map((r) => r.item.name),
    ['apple', 'Zorkmid']
  );
});

test('class sort follows NetHack class order and groups scrolls', () => {
  assert.deepEqual(
    UI.sortCandidates(candidates, 'class', 1).map((r) => r.item.name),
    [
      'amulet of life saving',
      'apple',
      'scroll of charging',
      'scroll of identify',
      'mystery'
    ]
  );
});

test('chance sort is numeric descending with unknown values last', () => {
  assert.deepEqual(
    UI.sortCandidates(candidates, 'chance', -1).map((r) => r.item.name),
    [
      'scroll of identify',
      'apple',
      'scroll of charging',
      'amulet of life saving',
      'mystery'
    ]
  );
});

test('sorting returns a copy instead of mutating candidate order', () => {
  const before = candidates.map((r) => r.item.name);
  UI.sortCandidates(candidates, 'class', 1);
  assert.deepEqual(candidates.map((r) => r.item.name), before);
});

test('new textual sorts ascend and chance sorts descend', () => {
  assert.deepEqual(UI.nextSort('chance', -1, 'class'), { key: 'class', direction: 1 });
  assert.deepEqual(UI.nextSort('class', 1, 'chance'), { key: 'chance', direction: -1 });
});

test('selecting the active sort reverses its direction', () => {
  assert.deepEqual(UI.nextSort('class', 1, 'class'), { key: 'class', direction: -1 });
});

test('every supported class has an existing colored badge style', () => {
  const allowed = new Set([
    'b-frost', 'b-green', 'b-yellow', 'b-orange', 'b-red', 'b-purple', 'b-dim'
  ]);
  UI.CLASS_ORDER.forEach((cls) => assert.ok(allowed.has(UI.classBadgeClass(cls)), cls));
  assert.equal(UI.classBadgeClass('unknown-class'), 'b-dim');
});

console.log(`\n${passed} passed, 0 failed\n`);
