# NetHack Tools

Player tools for [NetHack](https://www.nethack.org/) 3.6, 3.7 and 5.0, hosted at
**[nethack.statico.io](https://nethack.statico.io)**.

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

It reports honestly: when six items share a base cost, it says six.

### [Sokoban](https://nethack.statico.io/sokoban)

All eight vanilla levels, with maps rendered from `dat/soko*.lua` rather than copied from a
screenshot.

- Clickable level previews with the solution video from each level's wiki page, loaded via
  a click-to-load facade so eight iframes don't load at once.
- **Horizontal and vertical flip toggles**, because 3.7 and 5.0 mirror Sokoban levels at
  generation — so the reference map can be made to match what's actually on screen. 3.6
  never flips.

### [Checklist](https://nethack.statico.io/checklist)

Goals, ascension kit, and a death log, saved to `localStorage`. Nothing is uploaded.

- Every item name and mechanic links to its wiki article. All 199 link targets are
  validated against the wiki dump by `scripts/check-links.py`; the build fails on a dead
  link.
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
python3 scripts/check-links.py     # validates every wiki link target
node scripts/test-prices.mjs       # 44 pricing assertions
```

Both generators refuse to write output if their verification assertions fail.

`data/checklist.json` is authored by hand, not generated — but its link targets are
validated like everything else.

### Adding a tool

Add the page, then add one entry to `TOOLS` in `assets/nav.js`. Every page picks it up.

## Design

Styled after [SMUI](https://smui.statico.io/) — Nord palette, JetBrains Mono, square
corners. The whole system is `assets/smui.css`; pages use its classes and its CSS custom
properties, and don't define colors of their own.

## License

MIT for the code here. NetHack itself is licensed under the
[NetHack General Public License](https://www.nethack.org/common/license.html); game data in
`data/` is derived from the NetHack source and from NetHackWiki, which is
[CC BY-SA](https://creativecommons.org/licenses/by-sa/3.0/).

Not affiliated with the NetHack DevTeam.
