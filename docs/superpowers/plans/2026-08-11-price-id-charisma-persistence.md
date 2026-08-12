# Price ID Charisma Persistence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Persist Price ID Charisma in localStorage and clear it from Checklist Reset.

**Architecture:** Add pure Charisma normalize/load helpers on `PriceUI`; wire Price ID to sync all observations; Checklist Reset removes the shared key.

**Tech Stack:** Static HTML/JS, Node assertion scripts, localStorage.

## Global Constraints

- Key: `nethack-tools:price-id:cha`
- Valid range: 3–25; missing/invalid → 11
- Changing any Cha field updates every observation

---

### Task 1: Pure Charisma helpers + tests

**Files:** `assets/price-ui.js`, `scripts/test-price-ui.mjs`

- [ ] Tests for `normalizeCha` and `CHA_KEY`
- [ ] Implement helpers

### Task 2: Wire Price ID + Checklist Reset

**Files:** `price-id.html`, `checklist.html`

- [ ] Load/save/sync Charisma across observations
- [ ] Checklist Reset removes `nethack-tools:price-id:cha`

### Task 3: Verify

- [ ] Run `node scripts/test-price-ui.mjs` and related suites
