#!/usr/bin/env python3
"""Generate tools/data/objects.json from the NetHack object tables.

Reads the object tables straight out of the NetHack git checkout:

    3.6      -> src/objects.c        (origin/NetHack-3.6)
    3.7      -> include/objects.h    (origin/NetHack-3.7)
    5.0      -> include/objects.h    (NetHack-5.0, working checkout)

The per-object `shuffled` flag is derived from src/o_init.c of the matching
branch (obj_shuffle_range() / shuffle_all() / init_objects()), and the script
asserts that o_init.c still says what this code assumes.

The tables are C preprocessor soup: every object is written as a call to a
per-class macro (SCROLL(), WEAPON(), ...) which expands to OBJECT(...).  The
argument order differs per class *and* per version, so nothing is hardcoded
here: the script parses the `#define` lines, works out which OBJECT() slot
holds oc_prob / oc_cost / oc_magic, and expands each macro call positionally.

Re-runnable; prints a per-class summary and the verification results.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import subprocess
import sys
from collections import OrderedDict, defaultdict

REPO = "/Users/ian/dev/nethackwiki/NetHack"
OUT = "/Users/ian/dev/nethackwiki/tools/data/objects.json"

SOURCES = OrderedDict(
    (
        ("3.6", ("origin/NetHack-3.6", "src/objects.c")),
        ("3.7", ("origin/NetHack-3.7", "include/objects.h")),
        ("5.0", (None, "include/objects.h")),  # None = working tree
    )
)
O_INIT = "src/o_init.c"

# Armor sub-ranges from obj_shuffle_range(): (enum symbol, object name) pairs.
# The C code compares object indices, so the range is simply the table-order
# slice between the two endpoints -- whatever happens to live in between.
ARMOR_RANGES = [
    (("HELMET", "helmet"), ("HELM_OF_TELEPATHY", "helm of telepathy")),
    (("LEATHER_GLOVES", "leather gloves"),
     ("GAUNTLETS_OF_DEXTERITY", "gauntlets of dexterity")),
    (("CLOAK_OF_PROTECTION", "cloak of protection"),
     ("CLOAK_OF_DISPLACEMENT", "cloak of displacement")),
    (("SPEED_BOOTS", "speed boots"), ("LEVITATION_BOOTS", "levitation boots")),
]
# whole classes handed to shuffle_all(), with their obj_shuffle_range() rule
WHOLE_CLASS_SHUFFLE = ["AMULET_CLASS", "POTION_CLASS", "RING_CLASS", "SCROLL_CLASS",
                       "SPBOOK_CLASS", "WAND_CLASS", "VENOM_CLASS"]
MAGIC_UNIQUE_STOP = {"AMULET_CLASS", "SCROLL_CLASS", "SPBOOK_CLASS"}
FULL_RANGE = {"RING_CLASS", "WAND_CLASS", "VENOM_CLASS"}

# macros that are helpers / not object definitions
NON_OBJECT_MACROS = {"OBJ", "BITS", "HARDGEM", "COLOR_FIELD", "MARKER", "GENERIC"}

CLASS_MAP = {
    "WEAPON_CLASS": "weapon",
    "ARMOR_CLASS": "armor",
    "RING_CLASS": "ring",
    "AMULET_CLASS": "amulet",
    "TOOL_CLASS": "tool",
    "FOOD_CLASS": "food",
    "POTION_CLASS": "potion",
    "SCROLL_CLASS": "scroll",
    "SPBOOK_CLASS": "spellbook",
    "WAND_CLASS": "wand",
    "GEM_CLASS": "gem",
    "ROCK_CLASS": "rock",
    # everything else (coins, iron balls, chains, venom, illobj) -> "other"
}

# macro name -> prefix that turns the bare table name into the true object name
NAME_PREFIX = {
    "SCROLL": "scroll of ",
    "POTION": "potion of ",
    "RING": "ring of ",
    "WAND": "wand of ",
    "SPELL": "spellbook of ",
    # AMULET entries already carry their full name ("amulet of ESP",
    # "Amulet of Yendor", "cheap plastic imitation of the Amulet of Yendor"),
    # and so do the raw OBJECT() entries ("novel", "Book of the Dead").
}


# --------------------------------------------------------------------------
# source acquisition
# --------------------------------------------------------------------------
def read_source(ref, path):
    if ref is None:
        with open(os.path.join(REPO, path), "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    # list-arg subprocess: never let a shell see "ref:path"
    return subprocess.run(
        ["git", "-C", REPO, "show", "%s:%s" % (ref, path)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def git_head():
    return subprocess.run(
        ["git", "-C", REPO, "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()


# --------------------------------------------------------------------------
# C-ish lexing helpers
# --------------------------------------------------------------------------
def strip_comments(text):
    """Remove /* */ and // comments, preserving line count and string literals."""
    out = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == '"' or c == "'":
            q = c
            out.append(c)
            i += 1
            while i < n:
                if text[i] == "\\":
                    out.append(text[i : i + 2])
                    i += 2
                    continue
                out.append(text[i])
                if text[i] == q:
                    i += 1
                    break
                i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "*":
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append("\n" * text.count("\n", i, j))  # keep line structure
            i = j
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            j = text.find("\n", i)
            j = n if j < 0 else j
            i = j
            continue
        out.append(c)
        i += 1
    return "".join(out)


def drop_if_zero_blocks(text):
    """Drop `#if 0` ... `#endif` regions (DEFERRED objects are not in the game)."""
    out = []
    depth = 0          # nesting depth inside a skipped region
    skipping = False
    for line in text.split("\n"):
        s = line.strip()
        if skipping:
            if re.match(r"#\s*(if|ifdef|ifndef)\b", s):
                depth += 1
            elif re.match(r"#\s*endif\b", s):
                depth -= 1
                if depth == 0:
                    skipping = False
            out.append("")
            continue
        if re.match(r"#\s*if\s+0\b", s):
            skipping, depth = True, 1
            out.append("")
            continue
        out.append(line)
    return "\n".join(out)


def split_args(text, start):
    """text[start] == '('; return (list of top-level args, index after ')')."""
    assert text[start] == "(", text[start : start + 40]
    args, depth, buf = [], 0, []
    i, n = start, len(text)
    while i < n:
        c = text[i]
        if c == '"' or c == "'":
            q, j = c, i + 1
            while j < n:
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == q:
                    j += 1
                    break
                j += 1
            buf.append(text[i:j])
            i = j
            continue
        if c == "(":
            depth += 1
            if depth == 1:
                i += 1
                continue
        elif c == ")":
            depth -= 1
            if depth == 0:
                args.append("".join(buf).strip())
                return args, i + 1
        elif c == "," and depth == 1:
            args.append("".join(buf).strip())
            buf = []
            i += 1
            continue
        buf.append(c)
        i += 1
    raise ValueError("unbalanced parens at offset %d" % start)


def substitute(expr, mapping):
    """Replace identifiers with macro arguments, skipping string literals."""
    out, i, n = [], 0, len(expr)
    while i < n:
        c = expr[i]
        if c == '"' or c == "'":
            q, j = c, i + 1
            while j < n:
                if expr[j] == "\\":
                    j += 2
                    continue
                if expr[j] == q:
                    j += 1
                    break
                j += 1
            out.append(expr[i:j])
            i = j
            continue
        m = re.match(r"[A-Za-z_]\w*", expr[i:])
        if m:
            out.append(mapping.get(m.group(0), m.group(0)))
            i += m.end()
            continue
        out.append(c)
        i += 1
    return "".join(out)


def parse_c_string(expr):
    """"foo" "bar" -> 'foobar'; NoDes/None/NULL/0 -> None."""
    expr = expr.strip()
    if re.fullmatch(r"(NoDes|None|NULL|0|\(char \*\) 0)", expr):
        return None
    lits = re.findall(r'"((?:[^"\\]|\\.)*)"', expr)
    if not lits:
        return None
    s = "".join(lits)
    return s.replace('\\"', '"').replace("\\\\", "\\")


def eval_int(expr):
    """Evaluate a constant integer expression with C truncating division."""
    expr = expr.strip()
    if not re.fullmatch(r"[\d\s+\-*/()]+", expr) or not re.search(r"\d", expr):
        return None
    try:
        val = eval(re.sub(r"/", "//", expr), {"__builtins__": {}}, {})  # noqa: S307
    except Exception:
        return None
    return int(val)


# --------------------------------------------------------------------------
# the parser proper
# --------------------------------------------------------------------------
class Table(object):
    def __init__(self, text, label):
        self.label = label
        text = re.sub(r"\\[ \t]*\n", " ", text)      # join line continuations
        text = strip_comments(text)
        text = drop_if_zero_blocks(text)
        self.defines = {}                             # name -> (params, body)
        object_params = []
        bits_params = []
        body_lines = []
        for line in text.split("\n"):
            s = line.lstrip()
            if s.startswith("#"):
                m = re.match(r"#\s*define\s+([A-Za-z_]\w*)\(", s)
                if m:
                    name = m.group(1)
                    args, end = split_args(s, s.index("(", m.end(1) - 1))
                    body = s[end:].strip()
                    if name == "OBJECT":
                        object_params.append(args)
                    elif name == "BITS":
                        bits_params.append(args)
                    elif name not in NON_OBJECT_MACROS and body.strip():
                        self.defines[name] = (args, body)
                    elif name in ("GENERIC",):
                        self.defines[name] = (args, body)
                body_lines.append("")                 # keep line numbering
                continue
            body_lines.append(line)
        self.body = "\n".join(body_lines)

        if not object_params:
            raise SystemExit("%s: no OBJECT() macro definition found" % label)
        for p in object_params[1:]:
            if p != object_params[0]:
                raise SystemExit("%s: OBJECT() definitions disagree" % label)
        self.object_params = object_params[0]
        self.bits_params = bits_params[0] if bits_params else []

        # ---- derive the slot mapping instead of assuming it ----
        self.idx = {k: self.object_params.index(k) for k in ("obj", "bits", "sym", "prob", "cost")}
        if "sn" in self.object_params:
            self.idx["sn"] = self.object_params.index("sn")
        self.bits_idx = {}
        for field in ("mgc", "uniq", "nmkn"):
            if field not in self.bits_params:
                raise SystemExit("%s: BITS() has no %r field: %r"
                                 % (label, field, self.bits_params))
            self.bits_idx[field] = self.bits_params.index(field)

    def describe_mapping(self):
        return (
            "OBJECT(%s)\n    prob -> slot %d, cost -> slot %d, sym -> slot %d\n"
            "  BITS(%s)\n    mgc -> slot %d, uniq -> slot %d, nmkn -> slot %d"
            % (
                ",".join(self.object_params),
                self.idx["prob"],
                self.idx["cost"],
                self.idx["sym"],
                ",".join(self.bits_params),
                self.bits_idx["mgc"],
                self.bits_idx["uniq"],
                self.bits_idx["nmkn"],
            )
        )

    # -- expansion ---------------------------------------------------------
    def expand(self, name, args, depth=0):
        """Expand a macro call down to the final OBJECT() argument list."""
        if depth > 8:
            raise SystemExit("%s: macro recursion too deep at %s" % (self.label, name))
        if name == "OBJECT":
            return args
        params, body = self.defines[name]
        if len(params) != len(args):
            raise SystemExit(
                "%s: %s() expects %d args, got %d: %r"
                % (self.label, name, len(params), len(args), args)
            )
        mapping = dict(zip(params, args))
        m = re.match(r"\s*([A-Za-z_]\w*)\s*\(", body)
        if not m:
            raise SystemExit("%s: cannot find call in body of %s" % (self.label, name))
        inner_name = m.group(1)
        inner_args, _ = split_args(body, body.index("(", m.end(1) - 1))
        inner_args = [substitute(a, mapping) for a in inner_args]
        return self.expand(inner_name, inner_args, depth + 1)

    def objects(self):
        known = set(self.defines) | {"OBJECT"}
        pattern = re.compile(r"\b([A-Z][A-Z_0-9]*)\s*\(")
        results = []
        pos = 0
        while True:
            m = pattern.search(self.body, pos)
            if not m:
                break
            name = m.group(1)
            if name not in known:
                pos = m.end()
                continue
            try:
                args, end = split_args(self.body, self.body.index("(", m.end(1) - 1))
            except ValueError:
                pos = m.end()
                continue
            pos = end
            rec = self.record(name, args)
            if rec:
                results.append(rec)
        return results

    def record(self, macro, args):
        if macro == "GENERIC":
            return None                                   # class placeholders
        fields = self.expand(macro, args)
        if len(fields) != len(self.object_params):
            raise SystemExit(
                "%s: OBJECT() got %d fields, expected %d (%s)"
                % (self.label, len(fields), len(self.object_params), macro)
            )
        obj_expr = fields[self.idx["obj"]]
        m = re.match(r"\s*OBJ\s*\(", obj_expr)
        if not m:
            return None
        obj_args, _ = split_args(obj_expr, obj_expr.index("("))
        name = parse_c_string(obj_args[0])
        if not name:
            return None                                   # fencepost / labels
        appearance = parse_c_string(obj_args[1]) if len(obj_args) > 1 else None

        sym = fields[self.idx["sym"]].strip()
        oclass = CLASS_MAP.get(sym, "other")
        if oclass == "other" and sym == "ILLOBJ_CLASS":
            return None                                   # "strange object"

        bits_expr = fields[self.idx["bits"]]
        if not re.match(r"\s*BITS\s*\(", bits_expr):
            raise SystemExit("%s: %r has no BITS(): %r" % (self.label, name, bits_expr))
        bits_args, _ = split_args(bits_expr, bits_expr.index("("))
        bits = {}
        for field, slot in self.bits_idx.items():
            bits[field] = eval_int(bits_args[slot])
        magic = None if bits["mgc"] is None else bool(bits["mgc"])

        full = NAME_PREFIX.get(macro, "") + name
        cost = eval_int(fields[self.idx["cost"]])
        prob = eval_int(fields[self.idx["prob"]])
        if cost is None or prob is None:
            raise SystemExit(
                "%s: could not evaluate cost/prob for %r: cost=%r prob=%r"
                % (self.label, full, fields[self.idx["cost"]], fields[self.idx["prob"]])
            )
        rec = OrderedDict()
        rec["name"] = full
        rec["cost"] = cost
        rec["prob"] = prob
        rec["class"] = oclass
        rec["appearance"] = appearance
        if magic is not None:
            rec["magic"] = magic
        rec["shuffled"] = False           # filled in by mark_shuffled()
        # internal, stripped before output
        rec["_sym"] = sym
        rec["_unique"] = bool(bits["uniq"])
        rec["_nmkn"] = bool(bits["nmkn"])
        rec["_sn"] = fields[self.idx["sn"]].strip() if "sn" in self.idx else None
        return rec


# --------------------------------------------------------------------------
# shuffling (src/o_init.c)
# --------------------------------------------------------------------------
def check_o_init(text, label):
    """Fail loudly if o_init.c no longer matches the rules implemented below."""
    needed = [
        (r"otyp\s*>=\s*HELMET\s*&&\s*otyp\s*<=\s*HELM_OF_TELEPATHY", "helm range"),
        (r"otyp\s*>=\s*LEATHER_GLOVES\s*&&\s*otyp\s*<=\s*GAUNTLETS_OF_DEXTERITY",
         "glove range"),
        (r"otyp\s*>=\s*CLOAK_OF_PROTECTION\s*&&\s*otyp\s*<=\s*CLOAK_OF_DISPLACEMENT",
         "cloak range"),
        (r"otyp\s*>=\s*SPEED_BOOTS\s*&&\s*otyp\s*<=\s*LEVITATION_BOOTS", "boot range"),
        (r"\*hi_p\s*=\s*POT_WATER\s*-\s*1", "potion stops before POT_WATER"),
        (r"oc_unique\s*\|\|\s*!objects\[i\]\.oc_magic", "amulet/scroll/book stop rule"),
        (r"case\s+RING_CLASS:\s*case\s+WAND_CLASS:\s*case\s+VENOM_CLASS:",
         "ring/wand/venom whole class"),
        (r"objects\[j\]\.oc_name_known", "shuffle() skips pre-known names"),
        (r"num_to_shuffle\s*<\s*2", "shuffle() needs >= 2 members"),
    ]
    flat = re.sub(r"\s+", " ", strip_comments(text))
    for pat, what in needed:
        if not re.search(pat, flat):
            raise SystemExit("%s: %s: o_init.c no longer matches assumption (%s)"
                             % (label, O_INIT, what))
    # does init_objects() normalise oc_name_known to "has no description"?
    normalises = bool(re.search(r"!OBJ_DESCR\(objects\[i\]\)\s*\^\s*nmkn", flat))
    # which classes get handed to shuffle_all()
    m = re.search(r"shuffle_classes\[\]\s*=\s*\{([^}]*)\}", flat)
    if not m:
        raise SystemExit("%s: cannot find shuffle_classes[] in o_init.c" % label)
    classes = [c.strip() for c in m.group(1).split(",") if c.strip()]
    if sorted(classes) != sorted(WHOLE_CLASS_SHUFFLE):
        raise SystemExit("%s: shuffle_classes[] changed: %r" % (label, classes))
    m = re.search(r"shuffle_types\[\]\s*=\s*\{([^}]*)\}", flat)
    types = [c.strip() for c in m.group(1).split(",") if c.strip()]
    expected_types = [lo[0] for lo, _hi in ARMOR_RANGES]
    if sorted(types) != sorted(expected_types):
        raise SystemExit("%s: shuffle_types[] changed: %r" % (label, types))
    return normalises


def mark_shuffled(objs, label, normalises):
    """Set rec['shuffled'] per src/o_init.c.  objs must be in table order."""
    # objects of a class must be contiguous (init_objects() panics otherwise)
    seen = []
    for o in objs:
        if not seen or seen[-1] != o["_sym"]:
            if o["_sym"] in seen:
                raise SystemExit("%s: class %s is not contiguous" % (label, o["_sym"]))
            seen.append(o["_sym"])
    spans = {}
    for i, o in enumerate(objs):
        lo, hi = spans.get(o["_sym"], (i, i))
        spans[o["_sym"]] = (min(lo, i), max(hi, i))

    in_range = set()

    def add(lo, hi, what):
        if lo > hi:
            raise SystemExit("%s: empty shuffle range for %s (%d..%d)"
                             % (label, what, lo, hi))
        in_range.update(range(lo, hi + 1))

    for sym in WHOLE_CLASS_SHUFFLE:
        if sym not in spans:
            raise SystemExit("%s: no objects of class %s" % (label, sym))
        base, end = spans[sym]
        if sym in FULL_RANGE:
            add(base, end, sym)
        elif sym == "POTION_CLASS":
            water = [i for i in range(base, end + 1)
                     if objs[i]["name"] == "potion of water"]
            if len(water) != 1:
                raise SystemExit("%s: expected exactly one potion of water" % label)
            add(base, water[0] - 1, sym)          # *hi_p = POT_WATER - 1
        elif sym in MAGIC_UNIQUE_STOP:
            i = base
            while i <= end:
                if objs[i].get("magic") is None:
                    raise SystemExit("%s: %r has no oc_magic" % (label, objs[i]["name"]))
                if objs[i]["_unique"] or not objs[i]["magic"]:
                    break
                i += 1
            if i > end:
                raise SystemExit("%s: %s never hits a unique/non-magic entry" % (label, sym))
            add(base, i - 1, sym)
        else:
            raise SystemExit("%s: unhandled shuffle class %s" % (label, sym))

    by_name = {}
    by_sn = {}
    for i, o in enumerate(objs):
        by_name.setdefault(o["name"], i)
        if o["_sn"]:
            by_sn.setdefault(o["_sn"], i)
    for (lo_sn, lo_name), (hi_sn, hi_name) in ARMOR_RANGES:
        for sn, nm in ((lo_sn, lo_name), (hi_sn, hi_name)):
            if nm not in by_name:
                raise SystemExit("%s: armor range endpoint %r missing" % (label, nm))
            if sn in by_sn and by_sn[sn] != by_name[nm]:
                raise SystemExit("%s: enum %s is not %r" % (label, sn, nm))
        lo, hi = by_name[lo_name], by_name[hi_name]
        if objs[lo]["_sym"] != "ARMOR_CLASS" or objs[hi]["_sym"] != "ARMOR_CLASS":
            raise SystemExit("%s: armor range %s..%s is not armor" % (label, lo_sn, hi_sn))
        if lo > hi:
            raise SystemExit("%s: armor range %s(%d) > %s(%d)"
                             % (label, lo_sn, lo, hi_sn, hi))
        add(lo, hi, "%s..%s" % (lo_sn, hi_sn))

    # shuffle() skips oc_name_known entries; init_objects() may first force
    # oc_name_known to mean "this object has no alternate description"
    def known(o):
        return (o["appearance"] is None) if normalises else o["_nmkn"]

    # each shuffled group is handled independently; a group with fewer than
    # two shufflable members is left alone (shuffle(): num_to_shuffle < 2)
    for o in objs:
        o["shuffled"] = False
    groups = []
    for sym in WHOLE_CLASS_SHUFFLE:
        groups.append([i for i in sorted(in_range) if objs[i]["_sym"] == sym])
    for (lo_sn, lo_name), (hi_sn, hi_name) in ARMOR_RANGES:
        groups.append(list(range(by_name[lo_name], by_name[hi_name] + 1)))
    for grp in groups:
        movable = [i for i in grp if not known(objs[i])]
        if len(movable) < 2:
            continue
        for i in movable:
            objs[i]["shuffled"] = True

    # report where the raw table flag and the runtime normalisation disagree
    odd = [o["name"] for o in objs
           if o["_nmkn"] != (o["appearance"] is None)]
    return odd


# --------------------------------------------------------------------------
# verification
# --------------------------------------------------------------------------
COST_CHECKS = [
    ("scroll of identify", 20),
    ("scroll of blank paper", 60),
    ("potion of water", 100),
    ("ring of levitation", 200),
    ("wand of wishing", 500),
    ("amulet of life saving", 150),
    ("bag of holding", 100),
    ("luckstone", 60),
]
NEW_IN_37 = [
    "amulet of guarding",
    "amulet of flying",
    "silver mace",
    "wand of stasis",
    "chain lightning",
]

failures = []


def check(ok, msg):
    print("  %s %s" % ("PASS" if ok else "FAIL", msg))
    if not ok:
        failures.append(msg)


SHUFFLE_CHECKS = [
    ("potion of water", False),
    ("potion of healing", True),
    ("scroll of blank paper", False),
    ("scroll of identify", True),
    ("Amulet of Yendor", False),
    ("amulet of life saving", True),
    ("spellbook of blank paper", False),
    ("Book of the Dead", False),
    ("diamond", False),
    ("worthless piece of white glass", False),
    ("bag of holding", False),
    ("sack", False),
    ("helmet", True),
    ("helm of telepathy", True),
    ("dwarvish iron helm", False),
    ("speed boots", True),
    ("low boots", False),
    ("plate mail", False),
]


def verify(key, objs):
    print("Verification [%s]:" % key)
    by_name = {o["name"]: o for o in objs}
    names = list(by_name)
    for name, cost in COST_CHECKS:
        o = by_name.get(name)
        check(o is not None and o["cost"] == cost,
              "%s cost == %d (got %s)" % (name, cost, o["cost"] if o else "MISSING"))
    present = lambda s: any(s in n for n in names)
    if key == "3.6":
        for s in NEW_IN_37:
            check(not present(s), "3.6 does NOT contain %r" % s)
        check(present("huge chunk of meat"), "3.6 has 'huge chunk of meat'")
        check(not present("enormous meatball"), "3.6 does NOT have 'enormous meatball'")
    else:
        for s in NEW_IN_37:
            check(present(s), "contains %r" % s)
        check(present("enormous meatball"), "has 'enormous meatball'")
        check(not present("huge chunk of meat"), "does NOT have 'huge chunk of meat'")

    for name, want in SHUFFLE_CHECKS:
        o = by_name.get(name)
        got = o["shuffled"] if o else "MISSING"
        check(o is not None and o["shuffled"] is want,
              "%s shuffled == %s (got %s)" % (name, want, got))
    for cls in ("gem", "rock", "tool", "weapon", "food"):
        bad = [o["name"] for o in objs if o["class"] == cls and o["shuffled"]]
        check(not bad, "no %s is shuffled (offenders: %s)" % (cls, bad or "none"))
    for cls in ("ring", "wand"):
        bad = [o["name"] for o in objs if o["class"] == cls and not o["shuffled"]]
        check(not bad, "every %s is shuffled (offenders: %s)" % (cls, bad or "none"))
    nulls = [o["name"] for o in objs if o["appearance"] is None and o["shuffled"]]
    check(not nulls, "no object without an appearance is shuffled (%s)" % (nulls or "none"))


# --------------------------------------------------------------------------
def main():
    head = git_head()
    raw = {k: read_source(ref, path) for k, (ref, path) in SOURCES.items()}

    # 3.7 and 5.0 tables are expected to be identical apart from comments
    def decomment(t):
        return re.sub(r"\s+", " ", strip_comments(t))

    same = decomment(raw["3.7"]) == decomment(raw["5.0"])
    print("3.7 vs 5.0 object table identical (comments ignored): %s" % same)
    if not same:
        print("  WARNING: tables differ; 3.7-5.0 dataset is built from 5.0")

    datasets = OrderedDict()
    for key, srckey, label in (
        ("3.6", "3.6", "NetHack 3.6"),
        ("3.7-5.0", "5.0", "NetHack 3.7 / 5.0"),
    ):
        table = Table(raw[srckey], label)
        print("\n[%s] derived macro mapping from %s:" % (key, SOURCES[srckey][1]))
        print("  " + table.describe_mapping())
        objs = table.objects()
        o_init = read_source(SOURCES[srckey][0], O_INIT)
        normalises = check_o_init(o_init, label)
        print("  %s: rules confirmed; oc_name_known normalised to "
              "'has no description': %s" % (O_INIT, normalises))
        odd = mark_shuffled(objs, label, normalises)
        if odd:
            print("  note: table nmkn flag disagrees with 'has a description' for: %s"
                  % ", ".join(odd))
        datasets[key] = (label, objs)

    print()
    totals = OrderedDict()
    for key, (label, objs) in datasets.items():
        per = defaultdict(int)
        cnt = defaultdict(int)
        shuf = defaultdict(int)
        for o in objs:
            per[o["class"]] += o["prob"]
            cnt[o["class"]] += 1
            shuf[o["class"]] += 1 if o["shuffled"] else 0
        totals[key] = OrderedDict(sorted(per.items()))
        print("Summary [%s] %d objects (%d priced, %d shuffled):"
              % (key, len(objs), sum(1 for o in objs if o["cost"] > 0),
                 sum(1 for o in objs if o["shuffled"])))
        for c in sorted(cnt):
            print("    %-10s %4d objects, prob total %5d, shuffled %3d / fixed %3d"
                  % (c, cnt[c], per[c], shuf[c], cnt[c] - shuf[c]))
    print()

    for key, (label, objs) in datasets.items():
        verify(key, objs)

    if failures:
        print("\n%d VERIFICATION FAILURE(S) -- not writing output" % len(failures))
        return 1

    for _label, objs in datasets.values():          # drop internal fields
        for o in objs:
            for k in [k for k in o if k.startswith("_")]:
                del o[k]

    out = OrderedDict()
    out["generated_from"] = OrderedDict(
        (("repo_commit", head), ("generated", datetime.date.today().isoformat()))
    )
    out["versions"] = OrderedDict(
        (k, OrderedDict((("label", lbl), ("objects", objs))))
        for k, (lbl, objs) in datasets.items()
    )
    out["class_prob_totals"] = totals

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"), ensure_ascii=False)
    print("\nWrote %s (%d bytes)" % (OUT, os.path.getsize(OUT)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
