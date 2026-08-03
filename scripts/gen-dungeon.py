#!/usr/bin/env python3
"""Generate tools/data/dungeon.json from the NetHack dungeon definition files.

NetHack describes its whole dungeon topology -- how many levels each dungeon has,
where every branch entrance can generate, and where every named special level can
land -- in a single data file.  That file changed format between releases:

    NetHack 3.6   dat/dungeon.def   a bespoke line format compiled by
                                    util/dgn_comp (grammar: util/dgn_comp.y)
    NetHack 3.7   dat/dungeon.lua   a Lua table read at runtime by
    NetHack 5.0   dat/dungeon.lua   src/dungeon.c:init_dungeons()

Both formats are parsed here into one normalised structure so the three versions
can be diffed against each other.  Nothing on the page is hand-written game lore:
every number comes out of these files.  The only editorial additions are the
human-readable display names and the NetHackWiki article titles (LEVEL_INFO /
DUNGEON_INFO below), and those titles are verified against the wiki XML dump.

Placement semantics, from util/dgn_comp.y (3.6) and src/dungeon.c (3.7/5.0) --
both releases agree, only the syntax differs:

    dungeon (base, range)   num_dunlevs = range ? rn1(range, base) : base
                            i.e. base .. base + range - 1 levels
    level/branch base > 0   absolute level number from the top
                 base < 0   reverse index; base = num_dunlevs + base + 1
                 chainlevel base is added to the resolved chain level
                 range == 0 exactly one choice
                 range == -1 from base to the bottom of the dungeon
                 range  > 0 range consecutive choices, clipped at the bottom
    entry        < 0 from the bottom (-1 == bottom level), 0 == top, > 0 absolute

Because bottom-anchored levels move with the (random) dungeon depth, the diagram
rows emitted here are resolved against the *minimum* depth of each dungeon and the
JSON also carries an anchor + a symbolic placement string, so the page can say
"levels N-4 to N-1" rather than pretending Medusa is always on level 21.
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

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                      # .../tools
REPO = os.path.dirname(ROOT)                      # .../nethackwiki
NETHACK = os.path.join(REPO, "NetHack")
DUMP = os.path.join(REPO, "dumps", "nethackwiki_current.xml.gz")
OUT = os.path.join(ROOT, "data", "dungeon.json")

# id, git ref, path to the dungeon file, format
VERSIONS = [
    ("3.6", "origin/NetHack-3.6", "dat/dungeon.def", "def"),
    ("3.7", "origin/NetHack-3.7", "dat/dungeon.lua", "lua"),
    ("5.0", "NetHack-5.0", "dat/dungeon.lua", "lua"),
]

# Levels that legitimately have no level-description file of their own:
#   rogue    generated procedurally by mklev.c, flagged roguelike
#   dummy    the endgame surface placeholder ("should be unreachable")
#   x-*      quest proto levels; the real files are role-prefixed (Arc-strt, ...)
NO_LEVEL_FILE = {"rogue", "dummy", "x-strt", "x-loca", "x-goal"}

# ---------------------------------------------------------------- editorial ---
# Display names and wiki article titles.  These are *labels*, not facts about
# placement -- every number on the page comes from the dungeon file.  The "page"
# keys are validated against the wiki dump by check_wiki_pages().

DUNGEON_INFO = {
    "The Dungeons of Doom": ("The Dungeons of Doom", "Dungeons of Doom"),
    "Gehennom": ("Gehennom", "Gehennom"),
    "The Gnomish Mines": ("The Gnomish Mines", "Gnomish Mines"),
    "The Quest": ("The Quest", "Quest"),
    "Sokoban": ("Sokoban", "Sokoban"),
    "Fort Ludios": ("Fort Ludios", "Fort Ludios"),
    "Vlad's Tower": ("Vlad's Tower", "Vlad's Tower"),
    "The Elemental Planes": ("The Elemental Planes", "Elemental Planes"),
    "The Tutorial": ("The Tutorial", "Tutorial"),
}

LEVEL_INFO = {
    "rogue":    ("Rogue Level", "Rogue level"),
    "oracle":   ("Oracle", "Oracle"),
    "bigrm":    ("Big Room", "Big Room"),
    "medusa":   ("Medusa's Island", "Medusa's Island"),
    "castle":   ("The Castle", "Castle"),
    "valley":   ("Valley of the Dead", "Valley of the Dead"),
    "sanctum":  ("The Sanctum", "Moloch's Sanctum"),
    "juiblex":  ("Juiblex's Swamp", "Juiblex's swamp"),
    "baalz":    ("Baalzebub's Lair", "Baalzebub's Lair"),
    "asmodeus": ("Asmodeus' Lair", "Asmodeus' Lair"),
    "orcus":    ("Orcus Town", "Orcus-town"),
    "wizard1":  ("Wizard's Tower 1", "Wizard's Tower"),
    "wizard2":  ("Wizard's Tower 2", "Wizard's Tower"),
    "wizard3":  ("Wizard's Tower 3", "Wizard's Tower"),
    "fakewiz1": ("Fake Wizard's Tower 1", "Fake Wizard's Tower"),
    "fakewiz2": ("Fake Wizard's Tower 2", "Fake Wizard's Tower"),
    "minetn":   ("Mine Town", "Minetown"),
    "minend":   ("Mine's End", "Mines' End"),
    "x-strt":   ("Quest home level", "Quest"),
    "x-loca":   ("Quest locate level", "Quest"),
    "x-goal":   ("Quest goal level", "Quest"),
    "knox":     ("Fort Ludios", "Fort Ludios"),
    "soko1":    ("Sokoban level 1", "Sokoban"),
    "soko2":    ("Sokoban level 2", "Sokoban"),
    "soko3":    ("Sokoban level 3", "Sokoban"),
    "soko4":    ("Sokoban level 4", "Sokoban"),
    "tower1":   ("Vlad's Tower 1", "Vlad's Tower"),
    "tower2":   ("Vlad's Tower 2", "Vlad's Tower"),
    "tower3":   ("Vlad's Tower 3", "Vlad's Tower"),
    "astral":   ("Astral Plane", "Astral Plane"),
    "water":    ("Plane of Water", "Plane of Water"),
    "fire":     ("Plane of Fire", "Plane of Fire"),
    "air":      ("Plane of Air", "Plane of Air"),
    "earth":    ("Plane of Earth", "Plane of Earth"),
    "dummy":    ("dummy (surface placeholder)", None),
    "tut-1":    ("Tutorial level 1", "Tutorial"),
    "tut-2":    ("Tutorial level 2", "Tutorial"),
}

# Glosses for the branch connection types, taken from the constant definitions
# in include/dungeon.h and correct_branch_type() in src/dungeon.c.
BRANCH_TYPE_NOTE = {
    "stair": "Two-way staircase.",
    "portal": "Magic portal; both ends sit at the same depth.",
    "no_up": "One-way: no up staircase on this connection.",
    "no_down": "One-way: no down staircase on this connection.",
}


# ------------------------------------------------------------------ helpers ---


def git_show(ref, path):
    """Read a file at a git ref.  Always a list, never a shell string -- zsh eats
    the ':' in `$ref:path` as a history modifier."""
    return subprocess.run(
        ["git", "-C", NETHACK, "show", "%s:%s" % (ref, path)],
        check=True, capture_output=True, text=True,
    ).stdout


def git_ls_dat(ref):
    out = subprocess.run(
        ["git", "-C", NETHACK, "ls-tree", "--name-only", "%s:dat" % ref],
        check=True, capture_output=True, text=True,
    ).stdout
    return [l.strip() for l in out.splitlines() if l.strip()]


def git_rev(ref):
    return subprocess.run(
        ["git", "-C", NETHACK, "rev-parse", ref],
        check=True, capture_output=True, text=True,
    ).stdout.strip()


def new_dungeon(name):
    return {
        "name": name, "bonetag": None, "base": None, "range": 0,
        "alignment": None, "flags": [], "entry": 0,
        "protofile": None, "lvlfill": None, "themerooms": None,
        "levels": [], "branches": [],
    }


def new_level(name):
    return {
        "name": name, "bonetag": None, "base": None, "range": 0,
        "chainlevel": None, "nlevels": 0, "chance": 100,
        "alignment": None, "flags": [],
    }


def new_branch(name):
    return {
        "name": name, "base": None, "range": 0, "chainlevel": None,
        "branchtype": "stair", "direction": "down",
    }


# ------------------------------------------------------------ 3.6 .def parse ---

STR = r'"([^"]*)"'
COUPLE = r"\(\s*(-?\d+)\s*,\s*(-?\d+)\s*\)"

RE_DUNGEON = re.compile(r"^DUNGEON:\s+%s\s+%s\s+%s\s*(\d+)?\s*$" % (STR, STR, COUPLE))
RE_ALIGN = re.compile(r"^ALIGNMENT:\s+(\w+)\s*$")
RE_DESC = re.compile(r"^DESCRIPTION:\s+(\w+)\s*$")
RE_LEVDESC = re.compile(r"^LEVELDESC:\s+(\w+)\s*$")
RE_LEVALIGN = re.compile(r"^LEVALIGN:\s+(\w+)\s*$")
RE_ENTRY = re.compile(r"^ENTRY:\s+(-?\d+)\s*$")
RE_PROTO = re.compile(r"^PROTOFILE:\s+%s\s*$" % STR)
RE_LEVEL = re.compile(r"^LEVEL:\s+%s\s+%s\s+@\s*%s\s*(\d+)?\s*$" % (STR, STR, COUPLE))
RE_RNDLEVEL = re.compile(
    r"^RNDLEVEL:\s+%s\s+%s\s+@\s*%s\s+(\d+)(?:\s+(\d+))?\s*$" % (STR, STR, COUPLE)
)
RE_CHLEVEL = re.compile(
    r"^CHAINLEVEL:\s+%s\s+%s\s+%s\s+\+\s*%s\s*(\d+)?\s*$" % (STR, STR, STR, COUPLE)
)
RE_RNDCHLEVEL = re.compile(
    r"^RNDCHLEVEL:\s+%s\s+%s\s+%s\s+\+\s*%s\s+(\d+)(?:\s+(\d+))?\s*$"
    % (STR, STR, STR, COUPLE)
)
RE_BRANCH = re.compile(r"^BRANCH:\s+%s\s+@\s*%s\s*(.*)$" % (STR, COUPLE))
RE_CHBRANCH = re.compile(
    r"^CHAINBRANCH:\s+%s\s+%s\s+\+\s*%s\s*(.*)$" % (STR, STR, COUPLE)
)

BR_TYPES = {"stair", "portal", "no_down", "no_up"}
BR_DIRS = {"up", "down"}


def parse_branch_tail(tail, br, where):
    """`branch_type direction`, both optional, in that order (dgn_comp.y)."""
    for tok in tail.split():
        if tok in BR_TYPES:
            br["branchtype"] = tok
        elif tok in BR_DIRS:
            br["direction"] = tok
        else:
            raise SystemExit("%s: unknown branch token %r" % (where, tok))


def parse_def(text, where):
    dungeons = []
    cur = None
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        line = re.sub(r"\s+", " ", line.replace("\t", " ")).strip()
        loc = "%s:%d" % (where, lineno)

        m = RE_DUNGEON.match(line)
        if m:
            cur = new_dungeon(m.group(1))
            cur["bonetag"] = m.group(2) if m.group(2) != "none" else None
            cur["base"] = int(m.group(3))
            cur["range"] = int(m.group(4))
            if m.group(5):
                cur["chance"] = int(m.group(5))
            dungeons.append(cur)
            continue
        if cur is None:
            raise SystemExit("%s: statement before any DUNGEON: %r" % (loc, line))

        m = RE_ALIGN.match(line)
        if m:
            cur["alignment"] = m.group(1)
            continue
        m = RE_DESC.match(line)
        if m:
            cur["flags"].append(m.group(1))
            continue
        m = RE_ENTRY.match(line)
        if m:
            cur["entry"] = int(m.group(1))
            continue
        m = RE_PROTO.match(line)
        if m:
            cur["protofile"] = m.group(1)
            continue
        m = RE_LEVALIGN.match(line)
        if m:
            cur["levels"][-1]["alignment"] = m.group(1)
            continue
        m = RE_LEVDESC.match(line)
        if m:
            cur["levels"][-1]["flags"].append(m.group(1))
            continue

        m = RE_LEVEL.match(line)
        if m:
            lv = new_level(m.group(1))
            lv["bonetag"] = m.group(2) if m.group(2) != "none" else None
            lv["base"], lv["range"] = int(m.group(3)), int(m.group(4))
            if m.group(5):
                lv["chance"] = int(m.group(5))
            cur["levels"].append(lv)
            continue
        m = RE_RNDLEVEL.match(line)
        if m:
            lv = new_level(m.group(1))
            lv["bonetag"] = m.group(2) if m.group(2) != "none" else None
            lv["base"], lv["range"] = int(m.group(3)), int(m.group(4))
            # one trailing int == rndlevs; two == chance then rndlevs
            if m.group(6) is None:
                lv["nlevels"] = int(m.group(5))
            else:
                lv["chance"] = int(m.group(5))
                lv["nlevels"] = int(m.group(6))
            cur["levels"].append(lv)
            continue
        m = RE_CHLEVEL.match(line) or RE_RNDCHLEVEL.match(line)
        if m:
            lv = new_level(m.group(1))
            lv["bonetag"] = m.group(2) if m.group(2) != "none" else None
            lv["chainlevel"] = m.group(3)
            lv["base"], lv["range"] = int(m.group(4)), int(m.group(5))
            if line.startswith("RNDCHLEVEL"):
                if m.group(7) is None:
                    lv["nlevels"] = int(m.group(6))
                else:
                    lv["chance"] = int(m.group(6))
                    lv["nlevels"] = int(m.group(7))
            elif m.group(6):
                lv["chance"] = int(m.group(6))
            cur["levels"].append(lv)
            continue

        m = RE_BRANCH.match(line)
        if m:
            br = new_branch(m.group(1))
            br["base"], br["range"] = int(m.group(2)), int(m.group(3))
            parse_branch_tail(m.group(4), br, loc)
            cur["branches"].append(br)
            continue
        m = RE_CHBRANCH.match(line)
        if m:
            br = new_branch(m.group(1))
            br["chainlevel"] = m.group(2)
            br["base"], br["range"] = int(m.group(3)), int(m.group(4))
            parse_branch_tail(m.group(5), br, loc)
            cur["branches"].append(br)
            continue

        raise SystemExit("%s: unrecognised line %r" % (loc, line))

    return dungeons


# ------------------------------------------------------------ 3.7 .lua parse ---
# dungeon.lua is one flat `dungeon = { {...}, {...} }` table of literals: no
# expressions, no function calls, no string escapes.  A small recursive-descent
# reader over the literal grammar is exact here and avoids depending on a Lua
# interpreter being installed.


class LuaReader:
    TOKEN = re.compile(
        r"""(?P<tok>\{|\}|,|;|=|"[^"]*"|'[^']*'|-?\d+|[A-Za-z_][A-Za-z0-9_]*)"""
    )
    LONG_COMMENT = re.compile(r"--\[\[.*?\]\]", re.S)
    LINE_COMMENT = re.compile(r"--[^\n]*")

    def __init__(self, text, where):
        self.s = text
        self.i = 0
        self.where = where

    def skip(self, pos):
        """Advance past whitespace and any run of Lua comments."""
        while True:
            j = pos
            while j < len(self.s) and self.s[j].isspace():
                j += 1
            m = self.LONG_COMMENT.match(self.s, j) or self.LINE_COMMENT.match(self.s, j)
            if not m:
                return j
            pos = m.end()

    def peek(self):
        j = self.skip(self.i)
        m = self.TOKEN.match(self.s, j)
        return (m.group("tok"), m.end()) if m else (None, self.i)

    def next(self):
        tok, end = self.peek()
        if tok is None:
            raise SystemExit("%s: unexpected end of file" % self.where)
        self.i = end
        return tok

    def expect(self, want):
        tok = self.next()
        if tok != want:
            raise SystemExit("%s: expected %r, got %r" % (self.where, want, tok))

    def value(self):
        tok = self.next()
        if tok == "{":
            return self.table()
        if tok[0] in "\"'":
            return tok[1:-1]
        if re.fullmatch(r"-?\d+", tok):
            return int(tok)
        if tok in ("true", "false"):
            return tok == "true"
        if tok == "nil":
            return None
        raise SystemExit("%s: unexpected token %r" % (self.where, tok))

    def table(self):
        """Returns a dict for a keyed table, or a list for an array table."""
        d, arr = {}, []
        while True:
            tok, end = self.peek()
            if tok is None:
                raise SystemExit("%s: unterminated table" % self.where)
            if tok == "}":
                self.i = end
                break
            if tok in (",", ";"):
                self.i = end
                continue
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", tok):
                nxt = self.TOKEN.match(self.s, self.skip(end))
                after = nxt.group("tok") if nxt else None
                if after == "=":
                    self.i = end
                    self.expect("=")
                    d[tok] = self.value()
                    continue
            arr.append(self.value())
        return d if d else arr


def parse_lua(text, where):
    i = text.index("dungeon")
    i = text.index("{", i)
    rd = LuaReader(text, where)
    rd.i = i + 1
    raw = rd.table()
    if not isinstance(raw, list):
        raise SystemExit("%s: top-level dungeon table is not an array" % where)

    def flags_of(v):
        if v is None:
            return []
        return list(v) if isinstance(v, list) else [v]

    dungeons = []
    for d in raw:
        dg = new_dungeon(d["name"])
        dg["bonetag"] = d.get("bonetag") or None
        dg["base"] = d["base"]
        dg["range"] = d.get("range", 0)
        dg["alignment"] = d.get("alignment")
        dg["flags"] = flags_of(d.get("flags"))
        dg["entry"] = d.get("entry", 0)
        dg["protofile"] = d.get("protofile")
        dg["lvlfill"] = d.get("lvlfill")
        dg["themerooms"] = d.get("themerooms")
        if "chance" in d:
            dg["chance"] = d["chance"]
        for lv in d.get("levels", []) or []:
            l = new_level(lv["name"])
            l["bonetag"] = lv.get("bonetag") or None
            l["base"] = lv["base"]
            l["range"] = lv.get("range", 0)
            l["chainlevel"] = lv.get("chainlevel")
            l["nlevels"] = lv.get("nlevels", 0)
            l["chance"] = lv.get("chance", 100)
            l["alignment"] = lv.get("alignment")
            l["flags"] = flags_of(lv.get("flags"))
            dg["levels"].append(l)
        for br in d.get("branches", []) or []:
            b = new_branch(br["name"])
            b["base"] = br["base"]
            b["range"] = br.get("range", 0)
            b["chainlevel"] = br.get("chainlevel")
            b["branchtype"] = br.get("branchtype", "stair")
            b["direction"] = br.get("direction", "down")
            dg["branches"].append(b)
        dungeons.append(dg)
    return dungeons


# ------------------------------------------------------------ placement math ---


def ordinal(n):
    return "%d%s" % (n, "th" if 11 <= n % 100 <= 13
                     else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th"))


def resolve(base, rng, lmax, chain_rows):
    """Return (lo, hi, anchor) resolved against a dungeon of `lmax` levels.

    Mirrors level_range() in src/dungeon.c.  `chain_rows` is the (lo, hi) of the
    chained-to level, or None for an absolute placement.  For a chained entry the
    span is widened by the chain level's own span, because the chain target is
    itself placed randomly.
    """
    if chain_rows is not None:
        lo = chain_rows[0] + base
        hi = chain_rows[1] + base
        anchor = "chain"
    elif base < 0:
        lo = hi = lmax + base + 1
        anchor = "bottom"
    else:
        lo = hi = base
        anchor = "top"

    if rng == -1:
        hi = lmax
    elif rng > 0:
        hi = hi + rng - 1
    lo = max(1, min(lo, lmax))
    hi = max(lo, min(hi, lmax))
    return lo, hi, anchor


def span_text(base, rng, anchor, lo, hi, chain_display):
    """Symbolic placement text, independent of the nominal dungeon depth."""
    if anchor == "chain":
        # "The Castle" -> "the Castle" so the sentence does not read "the The".
        who = (chain_display[4:] if chain_display.startswith("The ")
               else chain_display)
        if base == 0 and rng in (0, 1):
            return "on the %s level" % who
        end = base + (rng - 1 if rng > 0 else 0)
        word = "below" if base > 0 else "above"
        a, b = abs(base), abs(end)
        if a == b:
            return "%d level%s %s the %s" % (a, "" if a == 1 else "s", word, who)
        return "%d–%d levels %s the %s" % (min(a, b), max(a, b), word, who)

    if anchor == "bottom":
        # base is a reverse index: -1 == bottom.  Express against N so the text
        # stays true for every possible dungeon depth.
        off_lo = -(base + 1)                       # 0 for the bottom level
        off_hi = off_lo - (rng - 1 if rng > 0 else 0)
        if off_lo == 0 and off_hi == 0:
            return "the bottom level (N)"
        def term(off):
            return "N" if off == 0 else "N−%d" % off
        if off_lo == off_hi:
            return "level %s" % term(off_lo)
        return "levels %s to %s" % (term(max(off_lo, off_hi)),
                                    term(min(off_lo, off_hi)))

    if rng == -1:
        return "levels %d to N (the bottom)" % base
    if lo == hi:
        return "level %d" % base
    return "levels %d–%d" % (base, base + rng - 1)


def entry_text(entry, nominal):
    if entry < 0:
        lev = max(1, nominal + entry + 1)
        if entry == -1:
            return lev, "the bottom level (entry = -1)"
        return lev, "the %s level from the bottom (entry = %d)" % (
            ordinal(-entry), entry)
    if entry > 0:
        return min(entry, nominal), "level %d (entry = %d)" % (entry, entry)
    return 1, "the top level (entry defaults to the top)"


def annotate(dungeons):
    """Add derived, display-ready fields to every dungeon/level/branch."""
    by_name = {d["name"]: d for d in dungeons}

    # Pass 1: dungeon-level fields only, so a branch can reference the display
    # name of a dungeon that is defined later in the file.
    for d in dungeons:
        nominal = d["base"]                        # minimum depth of this dungeon
        d["nominal_levels"] = nominal
        d["max_levels"] = nominal + (d["range"] - 1 if d["range"] else 0)
        d["size_text"] = ("%d" % nominal if not d["range"]
                          else "%d–%d" % (nominal, d["max_levels"]))
        disp, page = DUNGEON_INFO.get(d["name"], (d["name"], None))
        d["display"] = disp
        if page:
            d["page"] = page
        d["entry_level"], d["entry_text"] = entry_text(d["entry"], nominal)

    # Pass 2: levels and branches.
    for d in dungeons:
        nominal = d["nominal_levels"]
        rows_by_level = {}
        for lv in d["levels"]:
            chain_rows = None
            chain_disp = None
            if lv["chainlevel"]:
                if lv["chainlevel"] not in rows_by_level:
                    raise SystemExit("%s: level %s chains to unknown level %s"
                                     % (d["name"], lv["name"], lv["chainlevel"]))
                chain_rows = rows_by_level[lv["chainlevel"]]
                chain_disp = LEVEL_INFO.get(lv["chainlevel"],
                                            (lv["chainlevel"], None))[0]
            lo, hi, anchor = resolve(lv["base"], lv["range"], nominal, chain_rows)
            rows_by_level[lv["name"]] = (lo, hi)
            ldisp, lpage = LEVEL_INFO.get(lv["name"], (lv["name"], None))
            lv["display"] = ldisp
            if lpage:
                lv["page"] = lpage
            lv["rows"] = [lo, hi]
            lv["anchor"] = anchor
            lv["placement"] = span_text(lv["base"], lv["range"], anchor, lo, hi,
                                        chain_disp)
            lv["is_entry"] = (lo == hi == d["entry_level"])

        for br in d["branches"]:
            chain_rows = None
            chain_disp = None
            if br["chainlevel"]:
                if br["chainlevel"] not in rows_by_level:
                    raise SystemExit("%s: branch %s chains to unknown level %s"
                                     % (d["name"], br["name"], br["chainlevel"]))
                chain_rows = rows_by_level[br["chainlevel"]]
                chain_disp = LEVEL_INFO.get(br["chainlevel"],
                                            (br["chainlevel"], None))[0]
            lo, hi, anchor = resolve(br["base"], br["range"], nominal, chain_rows)
            br["rows"] = [lo, hi]
            br["anchor"] = anchor
            br["placement"] = span_text(br["base"], br["range"], anchor, lo, hi,
                                        chain_disp)
            br["from"] = d["name"]
            tgt = by_name.get(br["name"])
            if tgt is None:
                raise SystemExit("branch %r has no matching dungeon" % br["name"])
            br["display"] = tgt["display"]
            br["type_note"] = BRANCH_TYPE_NOTE[br["branchtype"]]
            tgt.setdefault("entered_by", []).append({
                "from": d["name"], "from_display": d["display"],
                "placement": br["placement"], "direction": br["direction"],
                "branchtype": br["branchtype"], "rows": [lo, hi],
            })

    for d in dungeons:
        d.setdefault("entered_by", [])
    return dungeons


# ---------------------------------------------------------------- notes ------
# Facts that are *not* in the dungeon file but come from other game sources are
# tagged with the file they came from, so the page can label them.

def extra_notes(dungeons):
    out = []
    names = {d["name"] for d in dungeons}
    if "Gehennom" in names:
        out.append({
            "dungeon": "Gehennom",
            "source": "src/dungeon.c",
            "title": "The invocation level",
            "text": "Invocation_lev() returns true for the Gehennom level "
                    "numbered num_dunlevs - 1, i.e. the level immediately above "
                    "the Sanctum. The dungeon file does not name it.",
        })
    if "The Elemental Planes" in names:
        out.append({
            "dungeon": "The Elemental Planes",
            "source": "a comment in the dungeon file itself",
            "title": "Why entry is -2",
            "text": "The file's own comment: \"Enter on 2nd level from bottom; "
                    "1st (from bottom) is a placeholder for surface level, and "
                    "should be unreachable.\"",
        })
    if "Sokoban" in names:
        out.append({
            "dungeon": "Sokoban",
            "source": "the dungeon file, read together with the Sokoban Helper",
            "title": "Two different numberings",
            "text": "The dungeon file numbers Sokoban top-down: soko1 is dungeon "
                    "level 1, soko4 is level 4. Because entry = -1 you arrive on "
                    "level 4 and climb, so the wiki (and this site's Sokoban "
                    "Helper) call soko4 \"floor 1\" and soko1 \"floor 4\". "
                    "The rows below are the file's numbering.",
        })
    return out


# --------------------------------------------------------------- cross-check --


def level_file_index(ref, fmt):
    """Which level-description names does this release actually ship?

    An independent source for the `nlevels` counts in the dungeon file: 3.7/5.0
    ship one dat/<name>.lua per level, 3.6 declares them with MAZE:/LEVEL: inside
    the dat/*.des files.
    """
    if fmt == "lua":
        return {f[:-4] for f in git_ls_dat(ref) if f.endswith(".lua")}
    names = set()
    pat = re.compile(r'^\s*(?:MAZE|LEVEL)\s*:\s*"([^"]+)"')
    for f in git_ls_dat(ref):
        if not f.endswith(".des"):
            continue
        for line in git_show(ref, "dat/" + f).splitlines():
            m = pat.match(line)
            if m:
                names.add(m.group(1))
    return names


def check_level_files(dungeons, have):
    """Every level must be backed by the right number of description files."""
    problems = []
    for d in dungeons:
        for lv in d["levels"]:
            name = lv["name"]
            if name in NO_LEVEL_FILE:
                continue
            n = lv["nlevels"]
            if n:
                want = {"%s-%d" % (name, i) for i in range(1, n + 1)}
            else:
                want = {name}
            missing = sorted(want - have)
            if missing:
                problems.append("%s/%s: missing %s" % (d["name"], name,
                                                       ", ".join(missing)))
            # a stray extra variant would mean nlevels drifted
            extra = sorted(x for x in have
                           if re.fullmatch(re.escape(name) + r"-\d+", x)
                           and x not in want)
            if extra:
                problems.append("%s/%s: nlevels=%d but dat/ also has %s"
                                % (d["name"], name, n, ", ".join(extra)))
    return problems


# ------------------------------------------------------------- wiki checking --

TITLE_RE = re.compile(r"<title>(.*?)</title>")
REDIRECT_EL_RE = re.compile(r'<redirect title="([^"]*)"')


def wiki_norm(t):
    t = html.unescape(t).replace("_", " ").strip()
    t = re.sub(r"\s+", " ", t)
    return t[0].upper() + t[1:] if t else t


def check_wiki_pages(doc):
    """Validate every "page" value against the NetHackWiki XML dump."""
    if not os.path.exists(DUMP):
        return None, ["dump not found at %s" % DUMP]

    wanted = set()

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k == "page" and isinstance(v, str):
                    wanted.add(wiki_norm(v))
                else:
                    walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(doc)

    titles, redirects, current = set(), {}, None
    with gzip.open(DUMP, "rt", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if "<title>" in line:
                m = TITLE_RE.search(line)
                if m:
                    current = wiki_norm(m.group(1))
                    titles.add(current)
            elif "<redirect title=" in line and current:
                m = REDIRECT_EL_RE.search(line)
                if m:
                    redirects[current] = wiki_norm(m.group(1))

    dead, via = [], []
    for w in sorted(wanted):
        if w in redirects:
            dst = redirects[w]
            via.append((w, dst))
            if dst not in titles:
                dead.append("%s -> missing %s" % (w, dst))
        elif w not in titles:
            dead.append(w)
    return (len(wanted), via), dead


# ------------------------------------------------------------------- diffing --

def flatten(dungeons):
    """A comparable {path: value} view of one version, for cross-version diffs."""
    flat = {}
    KEEP_D = ("bonetag", "base", "range", "alignment", "flags", "entry",
              "protofile", "lvlfill", "themerooms")
    KEEP_L = ("bonetag", "base", "range", "chainlevel", "nlevels", "chance",
              "alignment", "flags")
    KEEP_B = ("base", "range", "chainlevel", "branchtype", "direction")
    for d in dungeons:
        for k in KEEP_D:
            flat["%s | %s" % (d["name"], k)] = d.get(k)
        for lv in d["levels"]:
            for k in KEEP_L:
                flat["%s | level %s | %s" % (d["name"], lv["name"], k)] = lv.get(k)
        for br in d["branches"]:
            for k in KEEP_B:
                flat["%s | branch %s | %s" % (d["name"], br["name"], k)] = br.get(k)
    return flat


def diff_versions(a_id, a, b_id, b):
    fa, fb = flatten(a), flatten(b)
    names_a = {d["name"] for d in a}
    names_b = {d["name"] for d in b}
    out = []
    for n in sorted(names_b - names_a):
        out.append({"kind": "added", "path": n,
                    "detail": "dungeon added in %s" % b_id})
    for n in sorted(names_a - names_b):
        out.append({"kind": "removed", "path": n,
                    "detail": "dungeon removed in %s" % b_id})
    dropped = (names_a ^ names_b)
    for key in sorted(set(fa) | set(fb)):
        if key.split(" | ")[0] in dropped:
            continue
        va, vb = fa.get(key, "—"), fb.get(key, "—")
        if va != vb:
            out.append({"kind": "changed", "path": key,
                        "from": va, "to": vb})
    return out


# ---------------------------------------------------------------------- main --


def main():
    versions = {}
    checks = []          # (ok, text)
    per_version_problems = []

    for vid, ref, path, fmt in VERSIONS:
        text = git_show(ref, path)
        where = "%s:%s" % (ref, path)
        dungeons = parse_def(text, where) if fmt == "def" else parse_lua(text, where)
        annotate(dungeons)
        have = level_file_index(ref, fmt)
        problems = check_level_files(dungeons, have)
        per_version_problems.append((vid, problems))
        versions[vid] = {
            "id": vid,
            "label": "NetHack %s" % vid,
            "source_file": path,
            "source_format": ("bespoke format, compiled by util/dgn_comp"
                              if fmt == "def"
                              else "Lua table, read at runtime by src/dungeon.c"),
            "commit": git_rev(ref),
            "dungeons": dungeons,
            "notes": extra_notes(dungeons),
        }

    order = [v[0] for v in VERSIONS]
    diffs = {}
    for i in range(len(order) - 1):
        a, b = order[i], order[i + 1]
        diffs["%s->%s" % (a, b)] = diff_versions(
            a, versions[a]["dungeons"], b, versions[b]["dungeons"])

    doc = {
        "generated": datetime.date.today().isoformat(),
        "version_order": order,
        "versions": versions,
        "diffs": diffs,
    }

    # ------------------------------------------------------------ invariants --
    # Each of these was read out of the dungeon files before being written down;
    # they exist so that a parser regression fails loudly instead of quietly
    # producing a plausible-looking but wrong map.
    print("=== invariants (all three versions) ===")
    ok = True

    def get_d(vid, name):
        for d in versions[vid]["dungeons"]:
            if d["name"] == name:
                return d
        raise SystemExit("%s: no dungeon %r" % (vid, name))

    def get_l(vid, dname, lname):
        for lv in get_d(vid, dname)["levels"]:
            if lv["name"] == lname:
                return lv
        raise SystemExit("%s: no level %r in %r" % (vid, lname, dname))

    def get_b(vid, dname, bname):
        for br in get_d(vid, dname)["branches"]:
            if br["name"] == bname:
                return br
        raise SystemExit("%s: no branch %r in %r" % (vid, bname, dname))

    def check(desc, fn):
        nonlocal ok
        bad = []
        for vid in order:
            try:
                if not fn(vid):
                    bad.append(vid)
            except SystemExit as e:
                bad.append("%s(%s)" % (vid, e))
        good = not bad
        print("[%s] %s%s" % ("PASS" if good else "FAIL", desc,
                             "" if good else "  <- %s" % bad))
        ok &= good
        assert good, "invariant failed: %s (%s)" % (desc, bad)

    DOOM = "The Dungeons of Doom"

    check("Dungeons of Doom is the first dungeon and is 25-29 levels deep",
          lambda v: (versions[v]["dungeons"][0]["name"] == DOOM
                     and get_d(v, DOOM)["base"] == 25
                     and get_d(v, DOOM)["range"] == 5))

    check("Gnomish Mines entrance: Dungeons of Doom levels 2-4, down staircase",
          lambda v: (get_b(v, DOOM, "The Gnomish Mines")["base"] == 2
                     and get_b(v, DOOM, "The Gnomish Mines")["range"] == 3
                     and get_b(v, DOOM, "The Gnomish Mines")["rows"] == [2, 4]
                     and get_b(v, DOOM, "The Gnomish Mines")["direction"] == "down"
                     and get_b(v, DOOM, "The Gnomish Mines")["branchtype"] == "stair"))

    check("Sokoban branches UP, chained to the oracle level at +1",
          lambda v: (get_b(v, DOOM, "Sokoban")["chainlevel"] == "oracle"
                     and get_b(v, DOOM, "Sokoban")["base"] == 1
                     and get_b(v, DOOM, "Sokoban")["range"] == 0
                     and get_b(v, DOOM, "Sokoban")["direction"] == "up"))

    check("Sokoban is entered at its own bottom level and climbs (entry = -1)",
          lambda v: (get_d(v, "Sokoban")["entry"] == -1
                     and get_d(v, "Sokoban")["base"] == 4
                     and get_d(v, "Sokoban")["entry_level"] == 4))

    check("Oracle is the chain anchor and sits on levels 5-9",
          lambda v: (get_l(v, DOOM, "oracle")["base"] == 5
                     and get_l(v, DOOM, "oracle")["range"] == 5
                     and get_l(v, DOOM, "oracle")["rows"] == [5, 9]))

    check("Castle is the bottom level of the Dungeons of Doom (base = -1)",
          lambda v: (get_l(v, DOOM, "castle")["base"] == -1
                     and get_l(v, DOOM, "castle")["range"] == 0
                     and get_l(v, DOOM, "castle")["anchor"] == "bottom"
                     and get_l(v, DOOM, "castle")["rows"]
                         == [get_d(v, DOOM)["nominal_levels"]] * 2))

    check("Gehennom hangs off the Castle level with no down staircase",
          lambda v: (get_b(v, DOOM, "Gehennom")["chainlevel"] == "castle"
                     and get_b(v, DOOM, "Gehennom")["base"] == 0
                     and get_b(v, DOOM, "Gehennom")["branchtype"] == "no_down"
                     and get_b(v, DOOM, "Gehennom")["direction"] == "down"))

    check("Gehennom is entered on the Valley: entry defaults to the top level, "
          "and valley is Gehennom level 1",
          lambda v: (get_d(v, "Gehennom")["entry"] == 0
                     and get_d(v, "Gehennom")["entry_level"] == 1
                     and get_l(v, "Gehennom", "valley")["base"] == 1
                     and get_l(v, "Gehennom", "valley")["rows"] == [1, 1]))

    check("Gehennom is flagged hellish + mazelike and is 20-24 levels",
          lambda v: (set(get_d(v, "Gehennom")["flags"]) == {"hellish", "mazelike"}
                     and get_d(v, "Gehennom")["base"] == 20
                     and get_d(v, "Gehennom")["range"] == 5))

    check("Sanctum is the bottom of Gehennom (base = -1)",
          lambda v: (get_l(v, "Gehennom", "sanctum")["base"] == -1
                     and get_l(v, "Gehennom", "sanctum")["anchor"] == "bottom"))

    check("Medusa sits above the Castle: bottom-anchored, 4 slots, 4 variants",
          lambda v: (get_l(v, DOOM, "medusa")["base"] == -5
                     and get_l(v, DOOM, "medusa")["range"] == 4
                     and get_l(v, DOOM, "medusa")["nlevels"] == 4
                     and get_l(v, DOOM, "medusa")["rows"][1]
                         < get_l(v, DOOM, "castle")["rows"][0]))

    check("Quest and Fort Ludios are portal branches",
          lambda v: (get_b(v, DOOM, "The Quest")["branchtype"] == "portal"
                     and get_b(v, DOOM, "Fort Ludios")["branchtype"] == "portal"))

    check("Vlad's Tower branches UP out of Gehennom, levels 9-13",
          lambda v: (get_b(v, "Gehennom", "Vlad's Tower")["base"] == 9
                     and get_b(v, "Gehennom", "Vlad's Tower")["range"] == 5
                     and get_b(v, "Gehennom", "Vlad's Tower")["rows"] == [9, 13]
                     and get_b(v, "Gehennom", "Vlad's Tower")["direction"] == "up"
                     and get_d(v, "Vlad's Tower")["entry"] == -1))

    check("Elemental Planes: 6 levels, entered 2nd from the bottom, no way back",
          lambda v: (get_d(v, "The Elemental Planes")["base"] == 6
                     and get_d(v, "The Elemental Planes")["entry"] == -2
                     and get_d(v, "The Elemental Planes")["entry_level"] == 5
                     and get_b(v, DOOM, "The Elemental Planes")["direction"] == "up"
                     and get_b(v, DOOM, "The Elemental Planes")["branchtype"]
                         == "no_down"))

    check("Gnomish Mines: 8-9 levels, lawful, mazelike; Mine Town on 3-4, "
          "Mine's End at the bottom",
          lambda v: (get_d(v, "The Gnomish Mines")["base"] == 8
                     and get_d(v, "The Gnomish Mines")["range"] == 2
                     and get_d(v, "The Gnomish Mines")["alignment"] == "lawful"
                     and "mazelike" in get_d(v, "The Gnomish Mines")["flags"]
                     and get_l(v, "The Gnomish Mines", "minetn")["rows"] == [3, 4]
                     and "town" in get_l(v, "The Gnomish Mines", "minetn")["flags"]
                     and get_l(v, "The Gnomish Mines", "minend")["base"] == -1))

    check("every branch names a dungeon defined in the same file, and every "
          "dungeon except the Dungeons of Doom is reached by exactly one branch "
          "(or is flagged unconnected)",
          lambda v: all(
              (len(d["entered_by"]) == 1) if
              (d["name"] != DOOM and "unconnected" not in d["flags"])
              else (len(d["entered_by"]) == 0)
              for d in versions[v]["dungeons"]))

    check("every level and branch resolves inside its dungeon",
          lambda v: all(
              1 <= x["rows"][0] <= x["rows"][1] <= d["nominal_levels"]
              for d in versions[v]["dungeons"]
              for x in d["levels"] + d["branches"]))

    # ---------------------------------------------- independent cross-checks --
    print("\n=== cross-check: nlevels vs level files shipped in dat/ ===")
    for vid, problems in per_version_problems:
        print("[%s] %s: every declared level has its description file(s)%s"
              % ("PASS" if not problems else "FAIL", vid,
                 "" if not problems else "\n      " + "\n      ".join(problems)))
        ok &= not problems
        assert not problems, "level file mismatch in %s: %s" % (vid, problems)

    print("\n=== cross-check: NetHackWiki link targets ===")
    stats, dead = check_wiki_pages(doc)
    if stats is None:
        print("[SKIP] %s" % dead[0])
    else:
        n, via = stats
        print("[%s] %d distinct wiki targets resolve%s"
              % ("PASS" if not dead else "FAIL", n,
                 "" if not dead else "  dead: %s" % dead))
        ok &= not dead
        for src, dst in sorted(set(via)):
            print("      redirect: %s -> %s" % (src, dst))
        assert not dead, "dead wiki links: %s" % dead

    # ------------------------------------------------------------- summary ----
    print("\n=== per-version summary ===")
    for vid in order:
        v = versions[vid]
        nd = len(v["dungeons"])
        nl = sum(len(d["levels"]) for d in v["dungeons"])
        nb = sum(len(d["branches"]) for d in v["dungeons"])
        print("  %-4s %-14s %2d dungeons, %2d special levels, %d branches"
              % (vid, v["source_file"].split("/")[-1], nd, nl, nb))

    print("\n=== version differences ===")
    for key, items in diffs.items():
        print("  %s: %d difference(s)" % (key, len(items)))
        for it in items:
            if it["kind"] == "changed":
                print("    ~ %-52s %r -> %r" % (it["path"], it["from"], it["to"]))
            else:
                print("    %s %s" % ("+" if it["kind"] == "added" else "-",
                                     it["path"]))

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print("\nwrote %s (%d bytes)" % (OUT, os.path.getsize(OUT)))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
