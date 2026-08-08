# Price ID Class Sorting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Price ID magic marker with colored class badges and sortable Item, Class, and Chance columns.

**Architecture:** Add a small browser/Node-compatible `PriceUI` module for class presentation and candidate sorting. Keep pricing calculations in `PriceEngine`; the page owns shared sort state and re-renders all base-cost tables when a header is selected.

**Tech Stack:** Static HTML, CSS, ES5-compatible browser JavaScript, Node.js assertion scripts.

## Global Constraints

- Use only existing SMUI badge colors.
- Preserve chance-descending as the default order.
- Apply one sort selection to every rendered base-cost table.
- Do not change price calculations or candidate membership.

---

### Task 1: Pure sorting and class presentation

**Files:**
- Create: `assets/price-ui.js`
- Create: `scripts/test-price-ui.mjs`

**Interfaces:**
- Produces: `PriceUI.classBadgeClass(className) -> string`
- Produces: `PriceUI.sortCandidates(candidates, key, direction) -> candidate[]`
- Produces: `PriceUI.nextSort(currentKey, currentDirection, selectedKey) -> { key, direction }`

- [ ] **Step 1: Write failing tests**

Test literal fixtures proving class order, case-insensitive item order, numeric chance order, unknown chance placement, non-mutating output, badge mappings, and sort-direction toggling.

- [ ] **Step 2: Run test to verify it fails**

Run: `node scripts/test-price-ui.mjs`

Expected: FAIL because `assets/price-ui.js` does not exist.

- [ ] **Step 3: Write minimal implementation**

Create a UMD-style module exposing the three interfaces. Use the established `CLASS_ORDER` and existing badge class names.

- [ ] **Step 4: Run test to verify it passes**

Run: `node scripts/test-price-ui.mjs`

Expected: all assertions pass.

### Task 2: Price ID table integration

**Files:**
- Modify: `price-id.html`

**Interfaces:**
- Consumes: `window.PriceUI`
- Produces: sortable Item, Class, and Chance headers sharing `state.sort` and `state.sortDir`

- [ ] **Step 1: Load `assets/price-ui.js` before the inline page script**

- [ ] **Step 2: Replace inline candidate sorting with `PriceUI.sortCandidates`**

- [ ] **Step 3: Remove the magic badge and render the Class cell with `PriceUI.classBadgeClass`**

- [ ] **Step 4: Render accessible sort buttons and direction indicators in Item, Class, and Chance headers**

- [ ] **Step 5: Add delegated click handling that updates shared sort state and recomputes results**

### Task 3: Verification and shipment

**Files:**
- Verify: all changed files

- [ ] **Step 1: Run every Node test suite**

Run: `node scripts/test-price-ui.mjs && node scripts/test-prices.mjs && node scripts/test-wish.mjs && node scripts/test-monsters.mjs && node scripts/test-messages.mjs`

Expected: all assertions pass.

- [ ] **Step 2: Serve the static site and verify Price ID in a browser**

Confirm the magic badge is absent, class badges are colored, all three headers sort in both directions, and one selected sort applies to every base-cost table.

- [ ] **Step 3: Review the final diff, commit, push, and deploy production**

Push only after tests and browser verification succeed; confirm the production URL responds after deployment.
