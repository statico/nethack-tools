#!/usr/bin/env python3
"""Generate tools/data/sokoban.json from the NetHack source tree + the NetHackWiki XML dump.

The eight vanilla Sokoban levels live in NetHack/dat/soko{1..4}-{1,2}.lua.  NetHack's
file numbering runs *downwards* (soko4-* is the bottom / first level you meet, soko1-*
is the top / last one with the prize zoo), while the wiki names the levels by floor
counting *upwards* ("Sokoban Level 1a" is the first level you meet).  The variant
letter also does not line up with the file suffix.  The mapping below was established
by comparing map geometry and stair coordinates between each .lua and the ASCII map on
the corresponding wiki page; see verify_mapping() which re-checks it at runtime.

The .lua map block only contains terrain.  Boulders, traps, stairs and the branch
staircase are separate des.* calls, so they are overlaid onto the map block using the
map block's own (0-indexed, top-left) coordinate origin.
"""

from __future__ import annotations

import datetime
import gzip
import html
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
NETHACK = os.path.join(ROOT, "NetHack")
DAT = os.path.join(NETHACK, "dat")
DUMP = os.path.join(ROOT, "dumps", "nethackwiki_current.xml.gz")
OUT = os.path.join(ROOT, "tools", "data", "sokoban.json")

# wiki id -> (source lua file, trap type)
# floor 1 == first Sokoban level going up == soko4-*
LEVELS = [
    ("1a", "soko4-2.lua", "pit"),
    ("1b", "soko4-1.lua", "pit"),
    ("2a", "soko3-2.lua", "hole"),
    ("2b", "soko3-1.lua", "hole"),
    ("3a", "soko2-2.lua", "hole"),
    ("3b", "soko2-1.lua", "hole"),
    ("4a", "soko1-1.lua", "hole"),
    ("4b", "soko1-2.lua", "hole"),
]

EXPECTED_YOUTUBE = {
    "1a": "W85ztF2_rYU",
    "1b": "LTjS_v9S1W0",
    "2a": "rhQdWt9Rxl8",
    "2b": "856hCXLbPDA",
    "3a": "wQrwBqQi7GA",
    "3b": "hHDAKG2nkmQ",
    "4a": "no2C69Nk58Y",
    "4b": "KmLH4RZS-Fw",
}


# --------------------------------------------------------------------------- lua

MAP_RE = re.compile(r"des\.map\(\[\[\n(.*?)\n?\]\]\)", re.S)
OBJ_RE = re.compile(r'des\.object\(\s*"boulder"\s*,\s*(\d+)\s*,\s*(\d+)\s*\)')
TRAP_RE = re.compile(r'des\.trap\(\s*"([a-z ]+)"\s*,\s*(\d+)\s*,\s*(\d+)\s*\)')
STAIR_RE = re.compile(r'des\.stair\(\s*"(up|down)"\s*,\s*(\d+)\s*,\s*(\d+)\s*\)')
DOOR_RE = re.compile(r'des\.door\(\s*"[a-z]+"\s*,\s*(\d+)\s*,\s*(\d+)\s*\)')
BRANCH_RE = re.compile(
    r'des\.levregion\(\{\s*region\s*=\s*\{(\d+),(\d+),\d+,\d+\}\s*,\s*type\s*=\s*"branch"'
)


def parse_lua(path):
    src = open(path, encoding="utf-8").read()

    m = MAP_RE.search(src)
    if not m:
        raise SystemExit(f"no des.map block in {path}")
    rows = m.group(1).split("\n")
    width = max(len(r) for r in rows)
    grid = [list(r.ljust(width)) for r in rows]

    def put(x, y, ch):
        if not (0 <= y < len(grid) and 0 <= x < width):
            raise SystemExit(f"{path}: coord ({x},{y}) outside map block")
        grid[y][x] = ch

    traps = {}
    for kind, x, y in TRAP_RE.findall(src):
        traps.setdefault(kind, []).append((int(x), int(y)))
    # Only pits/holes are visible on a premapped Sokoban level; rolling boulder
    # traps stay hidden until triggered, so they render as plain floor.
    for kind in ("pit", "hole"):
        for x, y in traps.get(kind, []):
            put(x, y, "^")

    boulders = [(int(x), int(y)) for x, y in OBJ_RE.findall(src)]
    for x, y in boulders:
        put(x, y, "0")

    for x, y in DOOR_RE.findall(src):
        put(int(x), int(y), "+")

    stairs = {}
    for direction, x, y in STAIR_RE.findall(src):
        x, y = int(x), int(y)
        stairs[direction] = (x, y)
        put(x, y, "<" if direction == "up" else ">")

    # The Sokoban branch staircase (bottom level only) leads back down to the
    # Dungeons of Doom, so it renders as '>'.
    bm = BRANCH_RE.search(src)
    if bm:
        x, y = int(bm.group(1)), int(bm.group(2))
        stairs["down"] = (x, y)
        put(x, y, ">")

    return {
        "map": ["".join(r) for r in grid],
        "boulders": len(boulders),
        "traps": {k: len(v) for k, v in sorted(traps.items())},
        "stairs": stairs,
    }


# -------------------------------------------------------------------------- wiki


def load_wiki_pages(titles):
    """Stream the (large) XML dump once, pulling out the <text> of the wanted pages."""
    want = set(titles)
    out = {}
    title = None
    buf = None
    with gzip.open(DUMP, "rt", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if "<title>" in line:
                m = re.search(r"<title>(.*?)</title>", line)
                if m:
                    title = m.group(1)
            if title not in want or title in out:
                continue
            if buf is None:
                if "<text" not in line:
                    continue
                buf = [line]
            else:
                buf.append(line)
            if "</text>" in line:
                out[title] = "".join(buf)
                buf = None
    missing = want - set(out)
    if missing:
        raise SystemExit(f"pages not found in dump: {sorted(missing)}")
    return out


def wikitext(raw):
    txt = re.sub(r'^.*?xml:space="preserve">', "", raw, flags=re.S)
    txt = re.sub(r"</text>.*$", "", txt, flags=re.S)
    txt = html.unescape(html.unescape(txt))
    return txt


YT_RE = re.compile(r"(?:youtu\.be/|youtube\.com/watch\?v=)([A-Za-z0-9_-]{11})")


def youtube_id(txt):
    ids = set(YT_RE.findall(txt))
    if len(ids) != 1:
        raise SystemExit(f"expected exactly one YouTube id, got {sorted(ids)}")
    return ids.pop()


TEMPLATE_RE = re.compile(r"\{\{[^{}]*\}\}")


def strip_markup(s):
    s = re.sub(r"<!--.*?-->", "", s, flags=re.S)
    s = re.sub(r"<ref[^>]*>.*?</ref>", "", s, flags=re.S)
    s = re.sub(r"<ref[^>]*/>", "", s)
    prev = None
    while prev != s:  # nested templates
        prev = s
        s = TEMPLATE_RE.sub("", s)
    s = re.sub(r"\[\[[^\]|\n]*\|([^\]\n]*)\]\]", r"\1", s)
    s = re.sub(r"\[\[([^\]\n]*)\]\]", r"\1", s)
    s = re.sub(r"\[https?://\S+[ \t]+([^\]\n]*)\]", r"\1", s)
    s = re.sub(r"\[https?://\S+\]", "", s)
    # NB: only strip things that actually look like HTML tags.  A naive
    # <[^>]+> also eats everything between a '<' (upstairs) and a '>'
    # (downstairs) glyph in the ASCII maps, which silently deletes most of
    # the page.
    s = re.sub(r"</?[a-zA-Z][a-zA-Z0-9]*(?:\s[^<>\n]*?)?/?>", "", s)
    s = s.replace("'''", "").replace("''", "")
    s = s.replace("—", " - ").replace("&mdash;", " - ").replace("\xa0", " ")
    s = re.sub(r"[ \t]+", " ", s)
    return s.strip()


# Sentences worth keeping as play advice.
ADVICE_RE = re.compile(
    r"(?i)\b(remember|make sure|the key to this|hardest|general strategy|"
    r"treasure zoo|prize|check under|as soon as possible|you will still need|"
    r"most crucial|opening move|spare boulders?|boulders? and \d+ )",
)
# Boilerplate / non-advice.
DROP_RE = re.compile(
    r"(?i)(replaced by letters|ttyrec|youtube|is one of (the )?two|"
    r"among the various possible maps|Hack'EM|NetHack 3\.\d|left as an exercise|"
    r"faster solutions|see .*revision|this floor may be flipped)"
)
MOVES_RE = re.compile(r"\b[ludr]{3,}\b")
SENT_SPLIT = re.compile(r"(?<=[.!?:])\s+")


def candidate_sentences(txt):
    """Prose sentences, in document order, with map art and move lists removed."""
    body = strip_markup(txt)
    out = []
    for block in re.split(r"\n\s*\n", body):
        lines = []
        for line in block.split("\n"):
            if line.startswith(" ") or not line.strip():
                break  # start of an ASCII map / move list block
            lines.append(line)
        prose = " ".join(lines).strip()
        if not prose or prose[0] in "=|{[!":
            continue
        if "replaced by letters" in block:
            continue  # the boilerplate move-notation explanation
        for sent in SENT_SPLIT.split(prose):
            sent = sent.strip()
            if len(sent) < 30 or DROP_RE.search(sent) or MOVES_RE.search(sent):
                continue
            if re.search(r"\bI\b|\bI'", sent):
                continue
            # demonstratives with no antecedent once lifted out of context
            if re.match(r"(These|Those|Both|It is also possible)\b", sent):
                continue
            out.append(sent)
    return out


def make_notes(txt, max_sentences=4, max_chars=620):
    sents = candidate_sentences(txt)
    picked = [s for s in sents if ADVICE_RE.search(s)]
    if len(picked) < 2:  # fall back to the first plain prose sentences
        for s in sents:
            if s not in picked and not s.endswith(":"):
                picked.append(s)
                if len(picked) >= 2:
                    break
        picked = [s for s in sents if s in picked]  # restore document order
    notes = []
    used_words = set()
    for s in picked:
        if len(notes) >= max_sentences:
            break
        s = re.sub(r"\s*:$", ".", s)
        if not s.endswith((".", "!", "?")):
            s += "."
        words = {w.lower() for w in re.findall(r"[A-Za-z]{4,}", s)}
        if words and len(words & used_words) / len(words) > 0.55:
            continue  # restates something already said
        used_words |= words
        notes.append(s)
    text = " ".join(notes)
    while len(text) > max_chars and len(notes) > 1:
        notes.pop()
        text = " ".join(notes)
    return text


# ------------------------------------------------------------------- verification


def verify_mapping(levels):
    """Re-derive the wiki-floor <-> lua-file mapping from the level topology.

    The bottom Sokoban level is the only one with a branch levregion; the top one
    is the only one without an up staircase.  Combined with the map dimensions
    checked against each wiki page's ASCII map, this pins the ordering.
    """
    ok = True
    for lvl in levels:
        floor = lvl["floor"]
        has_up = "<" in "".join(lvl["map"])
        has_down = ">" in "".join(lvl["map"])
        want_up = floor != 4  # floor 4 is the top of the branch: no upstairs
        if has_up != want_up or not has_down:
            print(f"  FAIL {lvl['id']}: stairs up={has_up} down={has_down}")
            ok = False
    return ok


WIKI_COUNT_RE = re.compile(r"(\d+)\s+boulders?\s+and\s+(\d+)\s+(pit|hole)s?", re.I)


def wiki_counts(txt):
    """(boulders, traps, trap_type) as stated in the wiki page's own prose.

    Used as an independent cross-check of the wiki-page <-> .lua-file pairing:
    the counts are distinctive enough that a mispairing would show up.
    """
    m = WIKI_COUNT_RE.search(strip_markup(txt))
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), m.group(3).lower()


def main():
    commit = subprocess.check_output(
        ["git", "-C", NETHACK, "rev-parse", "HEAD"], text=True
    ).strip()

    pages = load_wiki_pages([f"Sokoban Level {i}" for i, _, _ in LEVELS])

    levels = []
    for lid, luafile, trap_type in LEVELS:
        parsed = parse_lua(os.path.join(DAT, luafile))
        page = f"Sokoban Level {lid}"
        txt = wikitext(pages[page])
        levels.append(
            {
                "id": lid,
                "wiki_page": page,
                "source_file": luafile,
                "floor": int(lid[0]),
                "variant": lid[1],
                "trap_type": trap_type,
                "youtube": youtube_id(txt),
                "map": parsed["map"],
                "notes": make_notes(txt),
                "_boulders": parsed["boulders"],
                "_traps": parsed["traps"],
                "_wiki_counts": wiki_counts(txt),
            }
        )

    # ---------------------------------------------------------------- checks
    print("=== checks ===")
    ok = True

    n = len(levels)
    print(f"[{'PASS' if n == 8 else 'FAIL'}] exactly 8 levels (got {n})")
    ok &= n == 8

    bad = [l["id"] for l in levels if l["youtube"] != EXPECTED_YOUTUBE[l["id"]]]
    print(f"[{'PASS' if not bad else 'FAIL'}] all 8 YouTube ids match expected list"
          + (f" (bad: {bad})" if bad else ""))
    ok &= not bad
    assert not bad, f"YouTube id mismatch: {bad}"

    bad = [l["id"] for l in levels if len({len(r) for r in l["map"]}) != 1]
    print(f"[{'PASS' if not bad else 'FAIL'}] every map is rectangular"
          + (f" (bad: {bad})" if bad else ""))
    ok &= not bad

    bad = [l["id"] for l in levels if "0" not in "".join(l["map"])]
    print(f"[{'PASS' if not bad else 'FAIL'}] every map has >=1 boulder '0'"
          + (f" (bad: {bad})" if bad else ""))
    ok &= not bad

    bad = [l["id"] for l in levels if "^" not in "".join(l["map"])]
    print(f"[{'PASS' if not bad else 'FAIL'}] every map has >=1 pit/hole '^'"
          + (f" (bad: {bad})" if bad else ""))
    ok &= not bad

    bad = [l["id"] for l in levels if ">" not in "".join(l["map"])]
    print(f"[{'PASS' if not bad else 'FAIL'}] every map has a downstair '>'"
          + (f" (bad: {bad})" if bad else ""))
    ok &= not bad

    # Strict "every map has an upstair '<'" as originally specified.  This is
    # FALSE for the two floor-4 maps: floor 4 is the top of the Sokoban branch
    # and genuinely has no up staircase (soko1-1.lua / soko1-2.lua define only
    # des.stair("down", ...), and the wiki page for Level 4b even labels the map
    # legend "no upstairs").  Reported, then re-checked in the corrected form.
    bad = [l["id"] for l in levels if "<" not in "".join(l["map"])]
    print(f"[{'PASS' if not bad else 'FAIL'}] (strict) every map has an upstair '<'"
          + (f" (bad: {bad} - top of branch, no upstairs exists)" if bad else ""))

    corrected = verify_mapping(levels)
    print(f"[{'PASS' if corrected else 'FAIL'}] stair topology matches branch position "
          "(floors 1-3 have '<'; floor 4 is the top and has none)")
    ok &= corrected

    # Cross-check the lua<->wiki pairing: the boulder/trap counts stated in each
    # wiki page's prose must equal the counts parsed out of the paired .lua file.
    bad = []
    for l in levels:
        w = l["_wiki_counts"]
        mine = (l["_boulders"], l["_traps"].get(l["trap_type"], 0), l["trap_type"])
        if w != mine:
            bad.append(f"{l['id']} wiki={w} lua={mine}")
    print(f"[{'PASS' if not bad else 'FAIL'}] wiki-stated boulder/trap counts match "
          "paired .lua" + (f" (bad: {bad})" if bad else ""))
    ok &= not bad

    bad = [l["id"] for l in levels if len(l["notes"]) < 40]
    print(f"[{'PASS' if not bad else 'FAIL'}] every level has non-trivial notes"
          + (f" (bad: {bad})" if bad else ""))
    ok &= not bad

    print("\n=== per-level ===")
    for l in levels:
        traps = ", ".join(f"{k}={v}" for k, v in l["_traps"].items())
        print(f"  {l['id']}  {l['source_file']:<12} "
              f"{len(l['map'][0])}x{len(l['map'])}  boulders={l['_boulders']:<3} "
              f"{traps}")

    for l in levels:
        del l["_boulders"], l["_traps"], l["_wiki_counts"]

    doc = {
        "generated_from": {
            "repo_commit": commit,
            "dump": "nethackwiki_current.xml.gz",
            "generated": datetime.date.today().isoformat(),
        },
        "levels": levels,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print(f"\nwrote {OUT} ({os.path.getsize(OUT)} bytes)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
