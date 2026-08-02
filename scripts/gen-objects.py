#!/usr/bin/env python3
"""Generate tools/data/objects.json from the NetHack object tables.

Reads the object tables straight out of the NetHack git checkout:

    3.6      -> src/objects.c        (origin/NetHack-3.6)
    3.7      -> include/objects.h    (origin/NetHack-3.7)
    5.0      -> include/objects.h    (NetHack-5.0, working checkout)

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
        self.mgc_idx = self.bits_params.index("mgc") if "mgc" in self.bits_params else None

    def describe_mapping(self):
        return "OBJECT(%s)\n    prob -> slot %d, cost -> slot %d, sym -> slot %d, BITS mgc -> slot %s" % (
            ",".join(self.object_params),
            self.idx["prob"],
            self.idx["cost"],
            self.idx["sym"],
            self.mgc_idx,
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

        magic = None
        bits_expr = fields[self.idx["bits"]]
        if self.mgc_idx is not None and re.match(r"\s*BITS\s*\(", bits_expr):
            bits_args, _ = split_args(bits_expr, bits_expr.index("("))
            v = eval_int(bits_args[self.mgc_idx])
            if v is not None:
                magic = bool(v)

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
        return rec


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
        datasets[key] = (label, objs)

    print()
    totals = OrderedDict()
    for key, (label, objs) in datasets.items():
        per = defaultdict(int)
        cnt = defaultdict(int)
        for o in objs:
            per[o["class"]] += o["prob"]
            cnt[o["class"]] += 1
        totals[key] = OrderedDict(sorted(per.items()))
        print("Summary [%s] %d objects (%d priced):"
              % (key, len(objs), sum(1 for o in objs if o["cost"] > 0)))
        for c in sorted(cnt):
            print("    %-10s %4d objects, prob total %5d" % (c, cnt[c], per[c]))
    print()

    for key, (label, objs) in datasets.items():
        verify(key, objs)

    if failures:
        print("\n%d VERIFICATION FAILURE(S) -- not writing output" % len(failures))
        return 1

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
