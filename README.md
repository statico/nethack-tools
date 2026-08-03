# statico's NetHack Tools

Player tools for [NetHack](https://www.nethack.org/) 3.6, 3.7 and 5.0.

- **Site:** [nethack.statico.io](https://nethack.statico.io)
- **Source:** [github.com/statico/nethack-tools](https://github.com/statico/nethack-tools)
- **Contact:** `@statico` on Discord — bug reports and corrections welcome, especially if
  you can point at the line of C that proves me wrong.

> [!NOTE]
> This was mostly vibe coded with [Claude Code](https://claude.com/claude-code) and Opus,
> using the NetHack source and [NetHackWiki](https://nethackwiki.com/) as reference.
> The game data isn't hand-transcribed — it's generated straight from the C object tables
> and the wiki database dump by the scripts in `scripts/`, and the pricing math is a direct
> port of `src/shk.c`. Verification details are below.

## Tools

### [Price ID](https://nethack.statico.io/price-id)

Identify unknown items from their shop price. The reason this exists: no calculator on the
wiki has been updated for 5.0.

- **Exact integer math.** A direct port of `get_cost()` and `set_cost()` from `src/shk.c`,
  including the round-half-up tweak `(((tmp * 10) / divisor) + 5) / 10`, and the artifact
  ×4 and angry-shopkeeper `tmp += (tmp + 2) / 3` surcharges that are applied *after*
  rounding. That ordering is what most calculators get wrong.
- **Reverse lookup by brute force.** Every base cost from 1 to 30,000 is run forward
  through the algorithm across both branches of the unknowable 1-in-4 ID surcharge, and
  exact matches are collected. Inverting the arithmetic analytically gives wrong answers
  because of the rounding tweak.
- **Two-observation intersection.** Enter a buy price and a sell price — or prices from two
  shops at different Charisma — and intersect the candidate sets. This usually collapses
  the answer to one item.
- **Probability ranking.** Candidates ranked by how often they actually generate, using the
  `prob` field from the object tables.
- **Quick-pick prices for the scenario you're in.** The twelve base costs backing the most
  objects in your enabled classes — 4, 5, 7, 10, 20, 50, 60, 100, 150, 200, 300, 500, the
  same ladder in both versions — run *forward* through the same algorithm under your
  current Charisma, direction and modifiers, so the chips show what you'd actually be
  quoted. At Cha 8 they read 5/7/9/13/27/67/80/133/200/267/400/667; at Cha 18,
  3/4/5/7/13/33/40/67/100/133/200/333. The list is derived from the object table, so it
  tracks the version switch, the enchantment field and the class filter rather than being
  a hardcoded list that drifts.
- **Charisma defaults to 11**, the bottom of the 11–15 band where the ladder applies no
  adjustment at all, so an untouched form prices at face value. The hint under the field
  names the band you're in.

It reports honestly: when six items share a base cost, it says six.

### [Wish](https://nethack.statico.io/wish)

Build a wish string and find out what the game will actually give you.

- **Canonical output.** Adjectives emitted in the order `readobjnam()` in `src/objnam.c`
  parses them, so it pastes straight into the game.
- **The annotation is the point.** For each part of the wish it says whether the game honors
  it, silently drops it, clamps it, or rolls for it — with the `file:line` that proves it.
  The `rnd(5)` enchantment test *zeroes* your enchantment rather than reducing it, so +7 is
  never granted; charge counts are capped by whatever `mksobj()` already rolled; negative
  Luck turns "blessed" into cursed and quietly discards erodeproof and poison.
- **Artifact odds.** Failure is `rn2(nartifact_exist()) > 1`, so the first two artifacts of a
  game are free and after that it's (n−2)/n.
- Enchantment survival probabilities are computed against the real `mksobj_init()`
  distributions, not assumed.

### [Monsters](https://nethack.statico.io/monsters)

Every monster from the source tables, with a threat filter.

- **What can spawn on me here?** Enter experience level and depth and it runs the game's own
  `rndmonst()` logic from `src/makemon.c` — the `level_difficulty/6` too-weak floor, the
  `(depth + XL)/2` ceiling, the `G_NOGEN` / `G_UNIQ` / Gehennom exclusions, `uncommon()`,
  `align_shift()` and `temperature_shift()`. The percentages shown are exact selection
  probabilities, not estimates.
- Full attack lists, resistances held and conveyed, and the `M1`/`M2`/`M3` flags decoded.
- Dangerous attacks are color-coded off the `AD_*` damage type — a table fact, not an
  opinion about which monsters are scary.

### [Dungeon Map](https://nethack.statico.io/dungeon)

Every branch on one vertical map, parsed from `dat/dungeon.def` (3.6) and `dat/dungeon.lua`
(3.7 / 5.0) — two unrelated file formats.

- Branches attach at the exact level ranges their entrances can generate on, with a bracket
  showing each range.
- Click any dungeon, branch or special level for its level range, entry rules, flags and
  map-variant count.
- Depth is random, so the diagram is drawn at each dungeon's *minimum* depth and
  bottom-anchored levels are labelled symbolically (`levels N−4 to N−1`) rather than pinned
  to a number they don't have.

The dungeon files say nothing about shops, temples or altars, so neither does this page.

### [Sokoban](https://nethack.statico.io/sokoban)

All eight vanilla levels, with maps rendered from `dat/soko*.lua` rather than copied from a
screenshot.

- Clickable level previews with the solution video from each level's wiki page, loaded via
  a click-to-load facade so eight iframes don't load at once.
- **Horizontal and vertical flip toggles**, because 3.7 and 5.0 mirror Sokoban levels at
  generation — so the reference map can be made to match what's actually on screen. 3.6
  never flips. The toggles are repeated inside the level panel, so you can re-orient
  without scrolling back to the top of the page; both sets stay in sync.
- **The walkthrough video mirrors with the map.** Maps are flipped as grid data — the text
  stays selectable — but a video can only be flipped as pixels, so the embed is the one
  place a CSS transform is the right answer. Only the media is transformed, not the
  surrounding box, so the play button doesn't become a backwards triangle. A mirrored
  YouTube player has a mirrored control bar too, so there's an **Unmirror video** escape
  hatch. Flipping while a video is playing patches the DOM in place rather than
  re-rendering, so the video keeps playing instead of restarting.

### [Checklist](https://nethack.statico.io/checklist)

Goals, ascension kit, and a death log, saved to `localStorage`. Nothing is uploaded.

- Every item name and mechanic links to its wiki article. All link targets across the site —
  331 of them — are validated against the wiki dump by `scripts/check-links.py`; the build
  fails on a dead link.
- **Prayer timer.** Tracks turns since your last prayer against the real mechanic — the
  timeout starts at 300 and resets to `rnz(350)`, which is heavy-tailed. So it shows a
  gradient (risky / marginal / safe) rather than claiming a guarantee it can't make.
- Export and import as JSON.

## Notes from building this

Things worth recording, verified against `NetHack-5.0` @ `a8a13bed8`:

- **3.7 and 5.0 have identical object tables.** `include/objects.h` differs between the two
  branches only in header comments. They share one dataset here, labelled as both.
- **5.0 vs 3.6** adds amulet of guarding, amulet of flying, gold dragon scales and scale
  mail, helm of caution, shields of drain and shock resistance, silver mace, spellbook of
  chain lightning, and wand of stasis; renames `huge chunk of meat` to `enormous meatball`
  and the venoms to `splash of ...`.
- **In 3.6, every ring has `prob: 0`** in the C table. That's genuinely what the source
  says — 3.7 changed it to 1. Ring probabilities are shown as uniform for 3.6.
- **5.0 weapon probabilities sum to 1002, not 1000** — silver mace was added without
  rebalancing. Denominators come from the data, never a hardcoded 1000.
- **Unidentified gems sell for a flat 3–8 zorkmids**, derived from the shopkeeper's id. A
  gem's *sell* price carries no information at all.
- **Sokoban floor 4 has no up staircase.** It's the top of the branch, not a missing glyph.
- **The wiki's level letters are inverted relative to the source files** on floors 1–3:
  wiki "Level 1a" is `soko4-2.lua`. Floor 4 is not inverted.
- **Rolling-boulder traps render as floor**, not `^` — they stay hidden on a premapped
  level. Some wiki maps draw them as `^`.
- **3.7 and 5.0 are identical in more places than expected.** Beyond the object tables, the
  monster tables and `dat/dungeon.lua` are also byte-identical apart from comments and
  version stamps. Each page says so rather than implying its version switch reveals a
  difference that isn't there.
- **The Rogue level is defined in all three versions**, not just 3.6. It has no `.des`/`.lua`
  file because `mklev.c` generates it procedurally.
- **3.6 has no `mstrength()`.** `makedefs -m` was deprecated there — `do_monstr()` prints a
  notice and emits a stub — so 3.6 difficulty comes only from the `mons[]` table. 3.7/5.0
  compute it in `src/mondata.c`, and the formula disagrees with the shipped table for exactly
  two monsters (cleric and wizard), both `G_NOGEN` player-monsters where hand-set difficulty
  is explicitly allowed. The table value wins; the discrepancy is asserted in a test.
- **Horned devil, erinys and barbed devil can never be randomly generated** in any version.
  `G_HELL` excludes them outside Gehennom, and inside it `uncommon()` rejects
  `maligntyp > A_NEUTRAL`. They only arrive via demon summoning.
- **Cross-alignment and crowning do not restrict artifact wishes.** `readobjnam()` checks
  only `is_quest_artifact()` and the `rn2()` roll. The alignment field is used by
  `mk_artifact()` for sacrifice gifts, which is where the folklore comes from.
- **The Palantir of Westernesse is freely wishable** — it sits in the quest-artifact index
  range but is nobody's `questarti`.

## Development

Static site. No build step, no dependencies, no `npm install`.

```sh
python3 -m http.server 8000    # serve from the repo root
```

Absolute paths (`/assets/smui.css`) require the server to be rooted at the repo root.

### Regenerating data

The generators read a local NetHack git checkout and a NetHackWiki database dump, neither
of which is vendored here.

```sh
python3 scripts/gen-objects.py     # -> data/objects.json
python3 scripts/gen-sokoban.py     # -> data/sokoban.json
python3 scripts/gen-wish.py        # -> data/wish.json
python3 scripts/gen-monsters.py    # -> data/monsters.json
python3 scripts/gen-dungeon.py     # -> data/dungeon.json
python3 scripts/check-links.py     # validates every wiki link target

node scripts/test-prices.mjs       # 44 pricing assertions
node scripts/test-wish.mjs         # 135 wish-rule assertions
node scripts/test-monsters.mjs     # 106 monster-table assertions
```

Every generator refuses to write output if its verification assertions fail. They locate
rules by pattern in the C source and die if the pattern is gone, so an upstream change
breaks the build loudly instead of silently producing stale numbers.

`data/checklist.json` is authored by hand, not generated — but its link targets are
validated like everything else.

### Adding a tool

Add the page, then add one entry to `TOOLS` in `assets/nav.js`. Every page picks it up.

## Design

Styled after [SMUI](https://smui.statico.io/) — Nord palette, JetBrains Mono, square
corners. The whole system is `assets/smui.css`; pages use its classes and its CSS custom
properties, and don't define colors of their own.

Light and dark are both first-class. The switcher in the nav cycles **system → light →
dark**; system follows your OS live, and an explicit choice persists in `localStorage`.
`assets/theme.js` is loaded synchronously from `<head>` so a stored choice is applied
before first paint rather than flashing the wrong theme. `color-scheme` is set per theme,
so native selects, number spinners and scrollbars follow too.

Nothing renders below **12px**, including the JS-scaled Sokoban maps.

Every numeric field keeps its native up/down spinners on screen. WebKit hides them until
hover or focus, which makes them undiscoverable on values people nudge one at a time —
Charisma, dungeon level, enchantment — so `smui.css` forces them visible in both themes.

`.stack` spaces its children with `margin-top`, which has two consequences worth knowing
before you copy a pattern: a `gap` set on a `.stack` does nothing, and a child carrying its
own `margin: 0` silently cancels the spacing. Both were happening. Use **`.stack-tight`**
where the spacing has to survive that — it is a real flex column, so `gap` applies and no
child margin can override it. Where an element only means "no trailing space", write
`margin-bottom: 0`, never `margin: 0`.

## Credits

Almost nothing here is original. The work was reading other people's work carefully and
wiring it together.

### NetHack itself

The [NetHack DevTeam](https://www.nethack.org/common/devteam.html) and everyone who
contributed to it since 1987. All game data on this site — every base cost, generation
probability, Sokoban map, and the entire pricing algorithm — comes from the
[NetHack source](https://github.com/NetHack/NetHack), specifically:

| What | Where |
|---|---|
| Pricing algorithm | `src/shk.c` — `get_cost()`, `set_cost()`, `getprice()`, `oid_price_adjustment()` |
| Object tables (3.7 / 5.0) | `include/objects.h` |
| Object tables (3.6) | `src/objects.c` |
| Sokoban maps | `dat/soko1-1.lua` … `dat/soko4-2.lua` |
| Prayer timeout | `src/pray.c`, `src/u_init.c` |
| Wish parsing | `src/objnam.c` — `readobjnam()` |
| Wish item defaults | `src/mkobj.c` — `mksobj()`, `mksobj_init()`, `blessorcurse()` |
| Artifacts | `include/artilist.h`, `src/artifact.c`, `src/do_name.c` |
| Monster tables (3.7 / 5.0) | `include/monsters.h` |
| Monster tables (3.6) | `src/monst.c` |
| Monster flags | `include/permonst.h`, `include/monst.h`, `include/monsym.h` |
| Monster difficulty | `src/mondata.c` — `mstrength()` |
| Monster generation | `src/makemon.c` — `rndmonst()`, `uncommon()`, `align_shift()` |
| Dungeon layout (3.6) | `dat/dungeon.def`, `util/dgn_comp.y` |
| Dungeon layout (3.7 / 5.0) | `dat/dungeon.lua` |
| Dungeon placement rules | `src/dungeon.c` — `level_range()`, `init_dungeon_set_entry()` |

NetHack is licensed under the
[NetHack General Public License](https://www.nethack.org/common/license.html).

### NetHackWiki

[NetHackWiki](https://nethackwiki.com/) and its contributors, licensed
[CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/). Used for:

- Sokoban level notes and per-level strategy, condensed from the
  [Sokoban](https://nethackwiki.com/wiki/Sokoban) page and the eight level pages
- The video links on each level page
- Every reference link across the site — 331 targets, validated against the wiki database dump
- Human-readable dungeon and level names, and the article titles they link to
- Cross-checking the price calculator against
  [Price identification](https://nethackwiki.com/wiki/Price_identification)

Note that this site's numbers are derived from the C source, not transcribed from the wiki's
tables. The wiki was the check, not the input.

### Sokoban walkthrough videos

All eight are from the **Concise Nethack** series by
**[Larry Fluckiger](https://www.youtube.com/@larryfluckiger9189)**, linked from the
NetHackWiki level pages. They are embedded here with credit and all rights remain with the
author. Nothing is loaded from YouTube until you press play.

If you're the author and would rather not be embedded, open an issue or find me on Discord
and I'll switch to plain links.

### Design and typography

- [SMUI](https://smui.statico.io/) — the design system this is styled after
- [Nord](https://www.nordtheme.com/) by Arctic Ice Studio — color palette, MIT
- [JetBrains Mono](https://www.jetbrains.com/lp/mono/) by JetBrains — typeface, SIL Open Font License

### This repo

MIT for the code written here (`assets/`, `scripts/`, the HTML). Data in `data/` is derived
from the sources above and carries their licenses.

Built by [statico](https://github.com/statico), mostly by pointing Claude at the source.
Not affiliated with the NetHack DevTeam.
