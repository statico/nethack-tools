# Price ID class badges and sorting

## Goal

Make candidate object classes easier to scan and allow users to sort each price result by item, class, or generation chance.

## Design

- Remove the `magic` badge from candidate item names.
- Render each class name as a colored badge, using a stable mapping from object class to the existing SMUI badge colors.
- Use one shared sort state for every base-cost result table.
- Preserve the current initial order: chance within class, descending.
- Make Item, Class, and Chance headers clickable and keyboard-focusable through native button elements.
- Clicking the active header reverses its direction. Selecting Item or Class starts ascending; selecting Chance starts descending.
- Class sorting follows the existing NetHack class order rather than alphabetical order. Item sorting is case-insensitive alphabetical order. Chance sorting is numeric, with unknown values after known values.
- Use item name as the deterministic tie-breaker.

## Scope

Sorting changes presentation only. Candidate calculations, base-cost grouping, class filters, probabilities, and derivations are unchanged.

## Verification

Add pure-function tests for all sort keys, direction toggling defaults, unknown probabilities, and class badge mappings. Run all existing static-site test suites and manually verify the rendered table interaction in a browser.
