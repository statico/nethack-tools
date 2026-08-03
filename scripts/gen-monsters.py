#!/usr/bin/env python3
"""Generate tools/data/monsters.json from the NetHack monster tables.

Reads the monster tables straight out of the NetHack git checkout:

    3.6      -> src/monst.c         (origin/NetHack-3.6)
    3.7      -> include/monsters.h  (origin/NetHack-3.7)
    5.0      -> include/monsters.h  (NetHack-5.0, working checkout)

The tables are C preprocessor soup: every monster is a call to MON() whose
sub-fields are themselves macros -- LVL(), SIZ(), A(), ATTK(), NAM()/NAMS().
Nothing about the argument order is hardcoded here: the script parses the
`#define` lines out of src/monst.c and works out which slot holds which
field, so a reordering upstream shows up as a loud failure rather than as
quietly wrong data.

Every symbolic constant (M1_*, M2_*, M3_*, MR_*, MZ_*, G_*, AT_*, AD_*,
WT_*, S_*, A_*) is likewise read from the headers of the matching branch.

Two derived things also come from source, with the citations recorded in
the JSON so the page can show them:

  * difficulty -- mstrength() in src/mondata.c (3.7 / 5.0).  3.6 has no such
    function: `makedefs -m` was deprecated there (util/makedefs.c do_monstr()
    emits a stub) and mons[].difficulty is the authority.  For 3.7 / 5.0 the
    script recomputes mstrength() and asserts it agrees with the table.

  * random generation -- rndmonst()/rndmonst_adj() in src/makemon.c plus the
    monmin_difficulty()/monmax_difficulty()/montooweak()/montoostrong()
    macros in include/monst.h.

Re-runnable; prints a per-version summary and the verification results.
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
OUT = "/Users/ian/dev/nethackwiki/tools/data/monsters.json"

# key -> (git ref or None for working tree, table path, macro-definition path)
SOURCES = OrderedDict(
    (
        ("3.6", ("origin/NetHack-3.6", "src/monst.c", "src/monst.c")),
        ("3.7", ("origin/NetHack-3.7", "include/monsters.h", "src/monst.c")),
        ("5.0", (None, "include/monsters.h", "src/monst.c")),
    )
)

# Preprocessor symbols as a default unix build sees them.  Anything not
# listed here that shows up in a #if makes the script stop.
DEFINED = {
    "MAIL_STRUCTURES": True,   # include/global.h:430 (3.7 / 5.0)
    "MAIL": True,              # include/unixconf.h:152 (3.6 default unix build)
    "CHARON": False,           # never defined in the shipped tree
    "MONS_ENUM": False,        # monsters.h is included by monst.c, not by the
    "DUMP_ENUMS": False,       # enum-generating passes
    "MON": True,               # monst.c defines MON before #include
    "SPLITMON_1": False,       # 3.6 atari-gcc kludge, both halves off
    "SPLITMON_2": False,
    "TEXTCOLOR": True,
    "NHSTDC": False,
    "PMNAME_MACROS": False,
    "C": False,                # 3.6 monst.c guards its own C(color) helper
}

# ---------------------------------------------------------------------------
# readable names for the decoded bit fields.  The *bit values* are read from
# monflag.h; these are only the human labels.
# ---------------------------------------------------------------------------
M1_LABELS = OrderedDict([
    ("M1_FLY", "flies"), ("M1_SWIM", "swims"), ("M1_AMORPHOUS", "amorphous"),
    ("M1_WALLWALK", "phases through rock"), ("M1_CLING", "clings to ceiling"),
    ("M1_TUNNEL", "tunnels"), ("M1_NEEDPICK", "needs pick to tunnel"),
    ("M1_CONCEAL", "hides under objects"), ("M1_HIDE", "hides / mimics"),
    ("M1_AMPHIBIOUS", "amphibious"), ("M1_BREATHLESS", "breathless"),
    ("M1_NOTAKE", "cannot pick up objects"), ("M1_NOEYES", "no eyes"),
    ("M1_NOHANDS", "no hands"), ("M1_NOLIMBS", "no limbs"),
    ("M1_NOHEAD", "no head"), ("M1_MINDLESS", "mindless"),
    ("M1_HUMANOID", "humanoid"), ("M1_ANIMAL", "animal"),
    ("M1_SLITHY", "serpentine"), ("M1_UNSOLID", "not solid"),
    ("M1_THICK_HIDE", "thick hide"), ("M1_OVIPAROUS", "lays eggs"),
    ("M1_REGEN", "regenerates"), ("M1_SEE_INVIS", "sees invisible"),
    ("M1_TPORT", "teleports"), ("M1_TPORT_CNTRL", "teleport control"),
    ("M1_ACID", "acidic to eat"), ("M1_POIS", "poisonous to eat"),
    ("M1_CARNIVORE", "carnivore"), ("M1_HERBIVORE", "herbivore"),
    ("M1_METALLIVORE", "eats metal"),
])
M2_LABELS = OrderedDict([
    ("M2_NOPOLY", "cannot be polymorphed into"), ("M2_UNDEAD", "undead"),
    ("M2_WERE", "lycanthrope"), ("M2_HUMAN", "human"), ("M2_ELF", "elf"),
    ("M2_DWARF", "dwarf"), ("M2_GNOME", "gnome"), ("M2_ORC", "orc"),
    ("M2_DEMON", "demon"), ("M2_MERC", "guard or soldier"),
    ("M2_LORD", "lord of its kind"), ("M2_PRINCE", "prince of its kind"),
    ("M2_MINION", "minion of a deity"), ("M2_GIANT", "giant"),
    ("M2_SHAPESHIFTER", "shapeshifter"), ("M2_MALE", "always male"),
    ("M2_FEMALE", "always female"), ("M2_NEUTER", "neuter"),
    ("M2_PNAME", "proper name"), ("M2_HOSTILE", "always hostile"),
    ("M2_PEACEFUL", "always peaceful"), ("M2_DOMESTIC", "tameable by food"),
    ("M2_WANDER", "wanders"), ("M2_STALK", "follows you between levels"),
    ("M2_NASTY", "extra nasty"), ("M2_STRONG", "strong"),
    ("M2_ROCKTHROW", "throws boulders"), ("M2_GREEDY", "picks up gold"),
    ("M2_JEWELS", "picks up gems"), ("M2_COLLECT", "picks up weapons/food"),
    ("M2_MAGIC", "picks up magic items"),
])
M3_LABELS = OrderedDict([
    ("M3_WANTSAMUL", "wants the Amulet"), ("M3_WANTSBELL", "wants the Bell"),
    ("M3_WANTSBOOK", "wants the Book"),
    ("M3_WANTSCAND", "wants the Candelabrum"),
    ("M3_WANTSARTI", "wants the quest artifact"),
    ("M3_WAITFORU", "waits for you"), ("M3_CLOSE", "lets you approach"),
    ("M3_INFRAVISION", "has infravision"),
    ("M3_INFRAVISIBLE", "seen by infravision"),
    ("M3_DISPLACES", "displaces other monsters"),
])
MR_LABELS = OrderedDict([
    ("MR_FIRE", "fire"), ("MR_COLD", "cold"), ("MR_SLEEP", "sleep"),
    ("MR_DISINT", "disintegration"), ("MR_ELEC", "shock"),
    ("MR_POISON", "poison"), ("MR_ACID", "acid"), ("MR_STONE", "petrification"),
])
G_LABELS = OrderedDict([
    ("G_UNIQ", "unique"), ("G_NOHELL", "not in Gehennom"),
    ("G_HELL", "Gehennom only"), ("G_NOGEN", "never generated randomly"),
    ("G_SGROUP", "small groups"), ("G_LGROUP", "large groups"),
    ("G_GENO", "genocidable"), ("G_NOCORPSE", "never leaves a corpse"),
])
MZ_LABELS = OrderedDict([
    ("MZ_TINY", "tiny"), ("MZ_SMALL", "small"), ("MZ_MEDIUM", "medium"),
    ("MZ_LARGE", "large"), ("MZ_HUGE", "huge"), ("MZ_GIGANTIC", "gigantic"),
])

AT_LABELS = {
    "AT_NONE": "passive", "AT_CLAW": "claw", "AT_BITE": "bite",
    "AT_KICK": "kick", "AT_BUTT": "butt", "AT_TUCH": "touch",
    "AT_STNG": "sting", "AT_HUGS": "crushing hug", "AT_SPIT": "spit",
    "AT_ENGL": "engulf", "AT_BREA": "breath", "AT_EXPL": "explode",
    "AT_BOOM": "explode when killed", "AT_GAZE": "gaze",
    "AT_TENT": "tentacles", "AT_WEAP": "weapon", "AT_MAGC": "spellcast",
}
AD_LABELS = {
    "AD_PHYS": "physical", "AD_MAGM": "magic missile", "AD_FIRE": "fire",
    "AD_COLD": "cold", "AD_SLEE": "sleep", "AD_DISN": "disintegration",
    "AD_ELEC": "shock", "AD_DRST": "poison (drains Str)", "AD_ACID": "acid",
    "AD_SPC1": "buzz extension 1", "AD_SPC2": "buzz extension 2",
    "AD_BLND": "blinds", "AD_STUN": "stuns", "AD_SLOW": "slows",
    "AD_PLYS": "paralyses", "AD_DRLI": "drains life level",
    "AD_DREN": "drains magic energy", "AD_LEGS": "wounds legs",
    "AD_STON": "petrifies", "AD_STCK": "sticks to you",
    "AD_SGLD": "steals gold", "AD_SITM": "steals an item",
    "AD_SEDU": "seduces and steals", "AD_TLPT": "teleports you",
    "AD_RUST": "rusts armour", "AD_CONF": "confuses", "AD_DGST": "digests",
    "AD_HEAL": "heals you", "AD_WRAP": "wraps around you",
    "AD_WERE": "lycanthropy", "AD_DRDX": "drains Dex",
    "AD_DRCO": "drains Con", "AD_DRIN": "drains Int",
    "AD_DISE": "disease", "AD_DCAY": "decays organics",
    "AD_SSEX": "seduction", "AD_HALU": "hallucination",
    "AD_DETH": "Death's touch", "AD_PEST": "Pestilence's touch",
    "AD_FAMN": "Famine's touch", "AD_SLIM": "turns you into green slime",
    "AD_ENCH": "disenchants", "AD_CORR": "corrodes armour",
    "AD_POLY": "polymorphs you", "AD_CLRC": "clerical spell",
    "AD_SPEL": "arcane spell", "AD_RBRE": "random breath",
    "AD_SAMU": "may steal the Amulet", "AD_CURS": "random curse",
}

# Damage types that end games.  Severity drives the badge colour on the page;
# the *membership* of each list is a source-derived statement about what the
# damage type does (see monattk.h comments and the mhitu.c handlers), not an
# opinion about which monsters are scary.
AD_SEVERITY = {
    "AD_STON": "red", "AD_SLIM": "red", "AD_DETH": "red", "AD_PEST": "red",
    "AD_FAMN": "red", "AD_DISN": "red", "AD_DRLI": "red", "AD_DGST": "red",
    "AD_ENCH": "orange", "AD_SEDU": "orange", "AD_SSEX": "orange",
    "AD_SITM": "orange", "AD_SGLD": "orange", "AD_PLYS": "orange",
    "AD_DRST": "orange", "AD_DRDX": "orange", "AD_DRCO": "orange",
    "AD_DRIN": "orange", "AD_WERE": "orange", "AD_CORR": "orange",
    "AD_RUST": "orange", "AD_DISE": "orange", "AD_TLPT": "orange",
    "AD_POLY": "orange", "AD_DREN": "orange", "AD_CURS": "orange",
    "AD_SAMU": "orange", "AD_STCK": "yellow", "AD_WRAP": "yellow",
    "AD_BLND": "yellow", "AD_CONF": "yellow", "AD_STUN": "yellow",
    "AD_SLOW": "yellow", "AD_HALU": "yellow", "AD_SLEE": "yellow",
    "AD_LEGS": "yellow", "AD_DCAY": "yellow",
}

# ---------------------------------------------------------------------------
# source acquisition
# ---------------------------------------------------------------------------
def read_source(ref, path):
    if ref is None:
        with open(os.path.join(REPO, path), "r", encoding="utf-8",
                  errors="replace") as f:
            return f.read()
    # list-arg subprocess: never let a shell see "ref:path"
    return subprocess.run(
        ["git", "-C", REPO, "show", "%s:%s" % (ref, path)],
        check=True, capture_output=True, text=True,
    ).stdout


def git_head():
    return subprocess.run(
        ["git", "-C", REPO, "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()


def line_of(text, needle, label, at_start=False):
    """1-based line number of the first line containing `needle`.

    With at_start, the line must *begin* with it -- which is how a K&R-style
    function definition is written, so the call sites don't win the race.
    """
    for i, line in enumerate(text.split("\n"), 1):
        if line.startswith(needle) if at_start else (needle in line):
            return i
    raise SystemExit("%s: cannot locate %r for a source citation" % (label, needle))


# ---------------------------------------------------------------------------
# C-ish lexing helpers
# ---------------------------------------------------------------------------
def strip_comments(text):
    """Remove /* */ and // comments, preserving line count and literals."""
    out, i, n = [], 0, len(text)
    while i < n:
        c = text[i]
        if c == '"' or c == "'":
            q = c
            out.append(c)
            i += 1
            while i < n:
                if text[i] == "\\":
                    out.append(text[i:i + 2])
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
            out.append("\n" * text.count("\n", i, j))
            i = j
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            j = text.find("\n", i)
            i = n if j < 0 else j
            continue
        out.append(c)
        i += 1
    return "".join(out)


COND_RE = re.compile(r"^#\s*(if|ifdef|ifndef|elif|else|endif)\b(.*)$")


def eval_cond(expr, label):
    """Evaluate a #if expression using DEFINED. Unknown forms are fatal."""
    e = expr.strip()
    if re.fullmatch(r"0", e):
        return False
    if re.fullmatch(r"1", e):
        return True
    # only defined(X) / !defined(X) joined by || and && are supported
    tokens = re.findall(r"defined\s*\(\s*([A-Za-z_]\w*)\s*\)|([A-Za-z_]\w*)", e)
    py = e
    for name in re.findall(r"defined\s*\(\s*([A-Za-z_]\w*)\s*\)", e):
        if name not in DEFINED:
            raise SystemExit("%s: unknown preprocessor symbol %r in #if %r"
                             % (label, name, e))
        py = re.sub(r"defined\s*\(\s*%s\s*\)" % re.escape(name),
                    "True" if DEFINED[name] else "False", py)
    py = py.replace("||", " or ").replace("&&", " and ").replace("!", " not ")
    if re.search(r"[A-Za-z_]\w*", py.replace("True", "").replace("False", "")
                 .replace("or", "").replace("and", "").replace("not", "")):
        raise SystemExit("%s: cannot evaluate #if %r" % (label, e))
    del tokens
    try:
        return bool(eval(py, {"__builtins__": {}}, {}))  # noqa: S307
    except Exception as exc:
        raise SystemExit("%s: cannot evaluate #if %r (%s)" % (label, e, exc))


def preprocess(text, label):
    """Apply #if/#ifdef/#ifndef/#else/#elif/#endif using DEFINED.

    Returns the text with dead branches blanked out (line count preserved)
    and every remaining directive line blanked, so the result is pure C.
    """
    out = []
    # stack entries: [currently_active, any_branch_taken_yet, parent_active]
    stack = []
    for raw in text.split("\n"):
        s = raw.strip()
        m = COND_RE.match(s)
        active = all(f[0] for f in stack)
        if m:
            kind, rest = m.group(1), m.group(2)
            if kind in ("if", "ifdef", "ifndef"):
                parent = active
                if kind == "ifdef":
                    name = rest.strip().split()[0] if rest.strip() else ""
                    if name not in DEFINED:
                        raise SystemExit("%s: unknown #ifdef %r" % (label, name))
                    val = DEFINED[name]
                elif kind == "ifndef":
                    name = rest.strip().split()[0] if rest.strip() else ""
                    if name not in DEFINED:
                        raise SystemExit("%s: unknown #ifndef %r" % (label, name))
                    val = not DEFINED[name]
                else:
                    val = eval_cond(rest, label)
                stack.append([parent and val, val, parent])
            elif kind == "elif":
                if not stack:
                    raise SystemExit("%s: #elif without #if" % label)
                fr = stack[-1]
                val = eval_cond(rest, label) if not fr[1] else False
                fr[0] = fr[2] and val and not fr[1]
                fr[1] = fr[1] or val
            elif kind == "else":
                if not stack:
                    raise SystemExit("%s: #else without #if" % label)
                fr = stack[-1]
                fr[0] = fr[2] and not fr[1]
                fr[1] = True
            elif kind == "endif":
                if not stack:
                    raise SystemExit("%s: #endif without #if" % label)
                stack.pop()
            out.append("")
            continue
        if not active:
            out.append("")
            continue
        if s.startswith("#"):
            out.append("")           # #define / #include / #error / #pragma
            continue
        out.append(raw)
    if stack:
        raise SystemExit("%s: unterminated #if" % label)
    return "\n".join(out)


def split_args(text, start):
    """text[start] == '('; return (list of top-level args, index after ')')."""
    assert text[start] == "(", text[start:start + 40]
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


def split_braced(expr, label):
    """'{ a, b, c }' -> ['a','b','c'] at brace depth 1."""
    expr = expr.strip()
    if not (expr.startswith("{") and expr.endswith("}")):
        raise SystemExit("%s: expected a braced initialiser, got %r" % (label, expr))
    inner = expr[1:-1]
    parts, depth, buf = [], 0, []
    i, n = 0, len(inner)
    while i < n:
        c = inner[i]
        if c == '"' or c == "'":
            q, j = c, i + 1
            while j < n:
                if inner[j] == "\\":
                    j += 2
                    continue
                if inner[j] == q:
                    j += 1
                    break
                j += 1
            buf.append(inner[i:j])
            i = j
            continue
        if c in "({[":
            depth += 1
        elif c in ")}]":
            depth -= 1
        elif c == "," and depth == 0:
            parts.append("".join(buf).strip())
            buf = []
            i += 1
            continue
        buf.append(c)
        i += 1
    parts.append("".join(buf).strip())
    return parts


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
    expr = expr.strip()
    if re.fullmatch(r"(0|NULL|\(const char \*\)\s*0|\(char \*\)\s*0)", expr):
        return None
    lits = re.findall(r'"((?:[^"\\]|\\.)*)"', expr)
    if not lits:
        return None
    return "".join(lits).replace('\\"', '"').replace("\\\\", "\\")


# ---------------------------------------------------------------------------
# constants
# ---------------------------------------------------------------------------
class Constants(object):
    """#define / enum constants harvested from the branch's headers."""

    def __init__(self, label):
        self.label = label
        self.vals = {}

    def add_defines(self, text, only_prefix=None):
        text = re.sub(r"\\[ \t]*\n", " ", text)
        text = strip_comments(text)
        for line in text.split("\n"):
            m = re.match(r"\s*#\s*define\s+([A-Za-z_]\w*)\s+(.+)$", line)
            if not m:
                continue
            name, body = m.group(1), m.group(2).strip()
            if only_prefix and not name.startswith(only_prefix):
                continue
            v = self.try_eval(body)
            if v is not None:
                self.vals[name] = v

    def add_enum(self, text, enum_name):
        text = strip_comments(text)
        m = re.search(r"enum\s+%s\s*\{" % re.escape(enum_name), text)
        if not m:
            raise SystemExit("%s: enum %s not found" % (self.label, enum_name))
        start = text.index("{", m.end() - 1)
        depth, i = 0, start
        while i < len(text):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        body = text[start + 1:i]
        nxt = 0
        for part in body.split(","):
            part = part.strip()
            if not part:
                continue
            if "=" in part:
                name, val = part.split("=", 1)
                v = self.try_eval(val)
                if v is None:
                    continue
                self.vals[name.strip()] = v
                nxt = v + 1
            else:
                self.vals[part] = nxt
                nxt += 1

    def try_eval(self, expr):
        expr = expr.strip()
        # C integer literals: strip U/L suffixes, fold hex to decimal
        expr = re.sub(r"\b(0[xX][0-9a-fA-F]+|\d+)[uUlL]*\b",
                      lambda m: str(int(m.group(1), 0)), expr)
        if re.fullmatch(r"'(\\.|[^'\\])'", expr):
            body = expr[1:-1]
            if body.startswith("\\"):
                return ord({"n": "\n", "t": "\t", "\\": "\\", "'": "'",
                            "0": "\0"}.get(body[1], body[1]))
            return ord(body)
        expr = re.sub(r"\s+", " ", expr)   # table entries wrap across lines
        subbed = re.sub(r"[A-Za-z_]\w*",
                        lambda m: str(self.vals[m.group(0)])
                        if m.group(0) in self.vals else m.group(0), expr)
        if re.search(r"[A-Za-z_]", subbed):
            return None
        if not re.search(r"\d", subbed):
            return None
        if not re.fullmatch(r"[\d\s+\-*/()|&^~<>]+", subbed):
            return None
        try:
            return int(eval(subbed.replace("/", "//"), {"__builtins__": {}}, {}))  # noqa: S307
        except Exception:
            return None

    def value(self, expr, what):
        v = self.try_eval(expr)
        if v is None:
            raise SystemExit("%s: cannot evaluate %s expression %r"
                             % (self.label, what, expr))
        return v

    def require(self, names, where):
        missing = [n for n in names if n not in self.vals]
        if missing:
            raise SystemExit("%s: %s no longer defines %s"
                             % (self.label, where, ", ".join(missing)))


# ---------------------------------------------------------------------------
# the table parser
# ---------------------------------------------------------------------------
class Table(object):
    def __init__(self, macro_src, table_src, consts, label):
        self.label = label
        self.K = consts
        self.defines = {}       # name -> (params, body) for function-like
        self.obj_defines = {}   # name -> body for object-like macros

        for src in (macro_src, table_src):
            self._collect_defines(src)

        for need, arity in (("MON", None), ("LVL", 5), ("SIZ", 4),
                            ("ATTK", 4), ("A", 6)):
            if need not in self.defines:
                raise SystemExit("%s: no #define %s()" % (label, need))
            if arity is not None and len(self.defines[need][0]) != arity:
                raise SystemExit("%s: %s() now takes %d args, expected %d"
                                 % (label, need, len(self.defines[need][0]), arity))

        self.mon_params = self.defines["MON"][0]
        for f in ("nam", "sym", "lvl", "gen", "atk", "siz", "mr1", "mr2",
                  "flg1", "flg2", "flg3", "d"):
            if f not in self.mon_params:
                raise SystemExit("%s: MON() has no %r parameter: %r"
                                 % (label, f, self.mon_params))
        self.mon_idx = {f: self.mon_params.index(f) for f in self.mon_params}

        self.lvl_params = self.defines["LVL"][0]
        for f in ("lvl", "mov", "ac", "mr", "aln"):
            if f not in self.lvl_params:
                raise SystemExit("%s: LVL() has no %r: %r" % (label, f, self.lvl_params))
        self.siz_params = self.defines["SIZ"][0]
        for f in ("wt", "nut", "snd", "siz"):
            if f not in self.siz_params:
                raise SystemExit("%s: SIZ() has no %r: %r" % (label, f, self.siz_params))
        self.attk_params = self.defines["ATTK"][0]
        for f in ("at", "ad", "n", "d"):
            if f not in self.attk_params:
                raise SystemExit("%s: ATTK() has no %r: %r"
                                 % (label, f, self.attk_params))

        # name macros: NAM (3.7/5.0), NAMS (3.7/5.0); 3.6 uses a plain string
        self.has_nam = "NAM" in self.defines
        if self.has_nam:
            self.K.require(["NEUTRAL"], "monflag.h enum mgender")
            self.neutral = self.K.vals["NEUTRAL"]

        self.body = preprocess(
            strip_comments(re.sub(r"\\[ \t]*\n", " ", table_src)), label)

    def _collect_defines(self, src):
        text = re.sub(r"\\[ \t]*\n", " ", src)
        text = strip_comments(text)
        for line in text.split("\n"):
            s = line.lstrip()
            m = re.match(r"#\s*define\s+([A-Za-z_]\w*)\(", s)
            if m:
                name = m.group(1)
                args, end = split_args(s, s.index("(", m.end(1) - 1))
                body = s[end:].strip()
                if body:
                    self.defines[name] = (args, body)
                continue
            m = re.match(r"#\s*define\s+([A-Za-z_]\w*)\s+(.+)$", s)
            if m and m.group(2).strip().startswith(("{", "A(")):
                self.obj_defines[m.group(1)] = m.group(2).strip()

    def describe_mapping(self):
        return ("MON(%s)\n    LVL(%s)  SIZ(%s)  ATTK(%s)"
                % (",".join(self.mon_params), ",".join(self.lvl_params),
                   ",".join(self.siz_params), ",".join(self.attk_params)))

    # -- expansion ---------------------------------------------------------
    def expand_call(self, name, args):
        """Expand a function-like macro one level, returning its body text."""
        params, body = self.defines[name]
        if len(params) != len(args):
            raise SystemExit("%s: %s() expects %d args, got %d"
                             % (self.label, name, len(params), len(args)))
        return substitute(body, dict(zip(params, args)))

    def call_args(self, expr, macro):
        """'MACRO(a, b)' -> ['a','b'], asserting the macro name."""
        expr = expr.strip()
        m = re.match(r"([A-Za-z_]\w*)\s*\(", expr)
        if not m or m.group(1) != macro:
            raise SystemExit("%s: expected %s(...), got %r"
                             % (self.label, macro, expr[:60]))
        args, _ = split_args(expr, expr.index("(", m.end(1) - 1))
        return args

    def monsters(self):
        out = []
        pos = 0
        pattern = re.compile(r"\bMON\s*\(")
        while True:
            m = pattern.search(self.body, pos)
            if not m:
                break
            args, end = split_args(self.body, self.body.index("(", m.end() - 1))
            pos = end
            rec = self.record(args)
            if rec:
                out.append(rec)
        return out

    def field(self, args, name):
        return args[self.mon_params.index(name)]

    def record(self, args):
        if len(args) != len(self.mon_params):
            raise SystemExit("%s: MON() got %d args, expected %d: %r"
                             % (self.label, len(args), len(self.mon_params),
                                args[:2]))
        K = self.K

        # ---- name(s) ----
        nam = self.field(args, "nam").strip()
        if self.has_nam:
            m = re.match(r"([A-Za-z_]\w*)\s*\(", nam)
            if not m or m.group(1) not in ("NAM", "NAMS"):
                raise SystemExit("%s: unexpected name macro %r" % (self.label, nam))
            inner = self.expand_call(m.group(1),
                                     self.call_args(nam, m.group(1)))
            parts = split_braced(inner, self.label)
            if len(parts) != 3:
                raise SystemExit("%s: %s expands to %d names" % (self.label,
                                                                 nam, len(parts)))
            names = [parse_c_string(p) for p in parts]
            name = names[self.neutral]
            alt = [n for n in names if n and n != name]
        else:
            name = parse_c_string(nam)
            alt = []
        if not name:
            return None                      # array terminator

        # ---- symbol / class ----
        sym_expr = self.field(args, "sym").strip()
        if sym_expr == "0":
            return None
        if not re.fullmatch(r"S_\w+", sym_expr):
            raise SystemExit("%s: %r has odd symbol %r" % (self.label, name, sym_expr))

        # ---- LVL() ----
        lvl_args = self.call_args(self.field(args, "lvl"), "LVL")
        lvl = {p: K.value(a, "LVL." + p)
               for p, a in zip(self.lvl_params, lvl_args)}

        # ---- SIZ() ----
        siz_args = self.call_args(self.field(args, "siz"), "SIZ")
        siz = {p: K.value(a, "SIZ." + p)
               for p, a in zip(self.siz_params, siz_args)}

        # ---- attacks ----
        atk_expr = self.field(args, "atk").strip()
        m = re.match(r"([A-Za-z_]\w*)\s*(\(|$)", atk_expr)
        if m and m.group(1) in self.obj_defines:
            atk_expr = self.obj_defines[m.group(1)]
        atk_args = self.call_args(atk_expr, "A")
        if len(atk_args) != 6:
            raise SystemExit("%s: %r has %d attack slots" % (self.label, name,
                                                             len(atk_args)))
        attacks = []
        for a in atk_args:
            a = a.strip()
            if a in self.obj_defines:            # NO_ATTK
                a = self.obj_defines[a]
            if a.startswith("{"):
                parts = split_braced(a, self.label)
            else:
                parts = self.call_args(a, "ATTK")
            if len(parts) != 4:
                raise SystemExit("%s: %r attack %r has %d fields"
                                 % (self.label, name, a, len(parts)))
            vals = {p: K.value(v, "ATTK." + p)
                    for p, v in zip(self.attk_params, parts)}
            if vals["at"] == 0 and vals["ad"] == 0 and vals["n"] == 0 \
               and vals["d"] == 0:
                continue                          # NO_ATTK slot
            attacks.append([vals["at"], vals["ad"], vals["n"], vals["d"]])

        rec = OrderedDict()
        rec["name"] = name
        rec["alt"] = alt
        rec["_sym"] = sym_expr
        rec["lvl"] = lvl["lvl"]
        rec["mov"] = lvl["mov"]
        rec["ac"] = lvl["ac"]
        rec["mr"] = lvl["mr"]
        rec["aln"] = lvl["aln"]
        rec["geno"] = K.value(self.field(args, "gen"), "geno")
        rec["atk"] = attacks
        rec["wt"] = siz["wt"]
        rec["nut"] = siz["nut"]
        rec["size"] = siz["siz"]
        rec["res"] = K.value(self.field(args, "mr1"), "mresists")
        rec["cnv"] = K.value(self.field(args, "mr2"), "mconveys")
        rec["f1"] = K.value(self.field(args, "flg1"), "mflags1")
        rec["f2"] = K.value(self.field(args, "flg2"), "mflags2")
        rec["f3"] = K.value(self.field(args, "flg3"), "mflags3")
        rec["diff"] = K.value(self.field(args, "d"), "difficulty")
        return rec


# ---------------------------------------------------------------------------
# mstrength() -- src/mondata.c (3.7 / 5.0 only)
# ---------------------------------------------------------------------------
def mstrength(mon, K):
    """Straight port of mstrength(), src/mondata.c:428 (5.0) / :428 (3.7)."""
    AT_WEAP, AT_MAGC = K.vals["AT_WEAP"], K.vals["AT_MAGC"]
    AT_EXPL = K.vals["AT_EXPL"]
    AT_BREA, AT_SPIT, AT_GAZE = K.vals["AT_BREA"], K.vals["AT_SPIT"], K.vals["AT_GAZE"]
    AD_COLD, AD_FIRE, AD_ELEC = K.vals["AD_COLD"], K.vals["AD_FIRE"], K.vals["AD_ELEC"]
    AD_PHYS = K.vals["AD_PHYS"]
    AD_DRLI, AD_STON, AD_DRST = K.vals["AD_DRLI"], K.vals["AD_STON"], K.vals["AD_DRST"]
    AD_DRDX, AD_DRCO, AD_WERE = K.vals["AD_DRDX"], K.vals["AD_DRCO"], K.vals["AD_WERE"]
    G_SGROUP, G_LGROUP = K.vals["G_SGROUP"], K.vals["G_LGROUP"]
    M2_STRONG = K.vals["M2_STRONG"]
    NATTK = 6

    # attacks are stored packed; mstrength() walks all NATTK slots, and the
    # empty ones are AT_NONE/AD_PHYS/0/0 which contribute nothing except
    # through the `tmp2 != AD_PHYS` clause -- AD_PHYS, so still nothing.
    attks = list(mon["atk"]) + [[0, 0, 0, 0]] * (NATTK - len(mon["atk"]))

    tmp = mon["lvl"]
    if tmp > 49:
        tmp = 2 * (tmp - 6) // 4

    n = 1 if (mon["geno"] & G_SGROUP) else 0
    n += (1 if (mon["geno"] & G_LGROUP) else 0) << 1

    ranged = any(a[0] >= AT_WEAP or (a[0] < 32 and a[0] in (AT_BREA, AT_SPIT, AT_GAZE))
                 for a in attks)
    if ranged:
        n += 1

    n += 1 if mon["ac"] < 4 else 0
    n += 1 if mon["ac"] < 0 else 0
    n += 1 if mon["mov"] >= 18 else 0

    for a in attks:
        tmp2 = a[0]
        n += 1 if tmp2 > 0 else 0
        n += 1 if tmp2 == AT_MAGC else 0
        n += 1 if (tmp2 == AT_WEAP and (mon["f2"] & M2_STRONG)) else 0
        if tmp2 == AT_EXPL:
            tmp3 = a[1]
            n += 3 if tmp3 in (AD_COLD, AD_FIRE) else (5 if tmp3 == AD_ELEC else 0)

    for a in attks:
        tmp2 = a[1]
        if tmp2 in (AD_DRLI, AD_STON, AD_DRST, AD_DRDX, AD_DRCO, AD_WERE):
            n += 2
        elif mon["name"] != "grid bug":
            n += 1 if tmp2 != AD_PHYS else 0
        n += 1 if (a[3] * a[2]) > 23 else 0

    if mon["name"] == "leprechaun":
        n -= 2
    if mon["name"] in ("killer bee", "soldier ant"):
        n += 2

    if n == 0:
        tmp -= 1
    elif n < 6:
        tmp += (n // 3 + 1)
    else:
        tmp += (n // 2)
    return tmp if tmp >= 0 else 0


# ---------------------------------------------------------------------------
# source-assumption checks
# ---------------------------------------------------------------------------
def check_makemon(text, label, has_temperature):
    """rndmonst()'s eligibility rules must still be what the page implements."""
    flat = re.sub(r"\s+", " ", strip_comments(text))
    needed = [
        (r"mons\[mndx\]\.geno & \(G_NOGEN \| G_UNIQ\)", "uncommon(): NOGEN|UNIQ"),
        (r"if \(Inhell\) return \(boolean\) \(mons\[mndx\]\.maligntyp > A_NEUTRAL\)",
         "uncommon(): in hell, only non-lawful"),
        (r"\(boolean\) \(\(mons\[mndx\]\.geno & G_HELL\) != 0\)",
         "uncommon(): G_HELL outside hell"),
        (r"Inhell && \(ptr->geno & G_NOHELL\)", "rndmonst(): G_NOHELL in hell"),
        (r"case AM_LAWFUL: alshift = \(ptr->maligntyp \+ 20\) / \(2 \* ALIGNWEIGHT\)",
         "align_shift(): lawful"),
        (r"case AM_NEUTRAL: alshift = \(20 - abs\(ptr->maligntyp\)\) / ALIGNWEIGHT",
         "align_shift(): neutral"),
        (r"case AM_CHAOTIC: alshift = \(-\(ptr->maligntyp - 20\)\) / \(2 \* ALIGNWEIGHT\)",
         "align_shift(): chaotic"),
    ]
    if has_temperature:
        needed += [
            (r"minmlev = monmin_difficulty\(zlevel\) \+ minadj", "min difficulty"),
            (r"maxmlev = monmax_difficulty\(zlevel\) \+ maxadj", "max difficulty"),
            (r"weight = \(int\) \(ptr->geno & G_FREQ\) \+ align_shift\(ptr\)",
             "weight = freq + align_shift"),
            (r"weight \+= temperature_shift\(ptr\)", "weight += temperature_shift"),
            (r"if \(weight > 0\) \{ totalweight \+= weight; if \(rn2\(totalweight\) < weight\)",
             "weighted reservoir sampling"),
        ]
    else:
        needed += [
            (r"minmlev = zlevel / 6", "3.6 min difficulty = zlevel/6"),
            (r"maxmlev = \(zlevel \+ u\.ulevel\) / 2",
             "3.6 max difficulty = (zlevel+ulevel)/2"),
            (r"ct = \(int\) \(ptr->geno & G_FREQ\) \+ align_shift\(ptr\)",
             "3.6 weight = freq + align_shift"),
            (r"if \(tooweak\(mndx, minmlev\) \|\| toostrong\(mndx, maxmlev\)\)",
             "3.6 too weak / too strong"),
        ]
    for pat, what in needed:
        if not re.search(pat, flat):
            raise SystemExit("%s: src/makemon.c no longer matches assumption (%s)"
                             % (label, what))


def check_monst_h(text, label):
    flat = re.sub(r"\s+", " ", strip_comments(text))
    for pat, what in (
        (r"#define monmax_difficulty\(levdif\) \(\(\(levdif\) \+ u\.ulevel\) / 2\)",
         "monmax_difficulty"),
        (r"#define monmin_difficulty\(levdif\) \(\(levdif\) / 6\)",
         "monmin_difficulty"),
        (r"#define montoostrong\(monindx, lev\) \(mons\[monindx\]\.difficulty > lev\)",
         "montoostrong"),
        (r"#define montooweak\(monindx, lev\) \(mons\[monindx\]\.difficulty < lev\)",
         "montooweak"),
    ):
        if not re.search(pat, flat):
            raise SystemExit("%s: include/monst.h no longer matches (%s)" % (label, what))


def check_36_tooweak(text, label):
    flat = re.sub(r"\s+", " ", strip_comments(text))
    for pat, what in (
        (r"#define toostrong\(monindx, lev\) \(mons\[monindx\]\.difficulty > lev\)",
         "3.6 toostrong"),
        (r"#define tooweak\(monindx, lev\) \(mons\[monindx\]\.difficulty < lev\)",
         "3.6 tooweak"),
    ):
        if not re.search(pat, flat):
            raise SystemExit("%s: 3.6 makemon.c no longer matches (%s)" % (label, what))


# ---------------------------------------------------------------------------
# monster class symbols
# ---------------------------------------------------------------------------
def class_table_37(defsym_text, label):
    """MONSYM(idx, ch, basename, sym, desc) rows out of include/defsym.h."""
    text = strip_comments(re.sub(r"\\[ \t]*\n", " ", defsym_text))
    # drop the #define MONSYM(...) prototypes; keep only the table rows
    text = "\n".join("" if ln.lstrip().startswith("#") else ln
                     for ln in text.split("\n"))
    rows = OrderedDict()
    for m in re.finditer(r"\bMONSYM\s*\(", text):
        args, _ = split_args(text, text.index("(", m.end() - 1))
        if len(args) != 5:
            raise SystemExit("%s: MONSYM() has %d args" % (label, len(args)))
        ch = args[1].strip()
        sym = args[3].strip()
        desc = parse_c_string(args[4])
        if not re.fullmatch(r"'(\\.|[^'\\])'", ch):
            raise SystemExit("%s: odd MONSYM char %r" % (label, ch))
        c = ch[1:-1]
        if c.startswith("\\"):
            c = {"n": "\n", "t": "\t", "\\": "\\", "'": "'"}.get(c[1], c[1])
        rows[sym] = (c, desc)
    if not rows:
        raise SystemExit("%s: no MONSYM() rows in defsym.h" % label)
    return rows


def class_table_36(monsym_text, drawing_text, label):
    """3.6: enum mon_class_types + DEF_* chars + def_monsyms[] descriptions."""
    text = strip_comments(monsym_text)
    m = re.search(r"enum\s+mon_class_types\s*\{(.*?)\}", text, re.S)
    if not m:
        raise SystemExit("%s: no enum mon_class_types in monsym.h" % label)
    order = []
    for part in m.group(1).split(","):
        part = part.strip()
        if not part or part.startswith("MAXMCLASSES"):
            continue
        nm = part.split("=")[0].strip()
        if nm.startswith("S_"):
            order.append(nm)
    chars = {}
    for mm in re.finditer(r"#\s*define\s+DEF_(\w+)\s+('(?:\\.|[^'\\])')", text):
        c = mm.group(2)[1:-1]
        if c.startswith("\\"):
            c = {"n": "\n", "t": "\t", "\\": "\\", "'": "'"}.get(c[1], c[1])
        chars["DEF_" + mm.group(1)] = c

    dtext = strip_comments(drawing_text)
    dm = re.search(r"def_monsyms\[MAXMCLASSES\]\s*=\s*\{(.*?)\n\};", dtext, re.S)
    if not dm:
        raise SystemExit("%s: no def_monsyms[] in drawing.c" % label)
    descs = []
    for row in re.finditer(r"\{([^{}]*)\}", dm.group(1)):
        parts = [p.strip() for p in row.group(1).split(",")]
        descs.append(parse_c_string(parts[-1]))
    # descs[0] is the unused class 0 placeholder; enum starts at S_ANT == 1
    rows = OrderedDict()
    for i, sym in enumerate(order, 1):
        ch = chars.get("DEF_" + sym[2:].upper())
        desc = descs[i] if i < len(descs) else None
        if ch is None:
            continue        # S_invisible has no DEF_ char in 3.6; no monsters use it
        rows[sym] = (ch, desc)
    if "S_ANT" not in rows:
        raise SystemExit("%s: 3.6 class table came out empty" % label)
    return rows


# ---------------------------------------------------------------------------
# verification
# ---------------------------------------------------------------------------
failures = []


def check(ok, msg):
    print("  %s %s" % ("PASS" if ok else "FAIL", msg))
    if not ok:
        failures.append(msg)


# Hand-read out of the tables; the same numbers are asserted in
# scripts/test-monsters.mjs.
HAND = {
    "3.6": [
        # name, lvl, mov, ac, mr, aln, wt, nut, diff, sym
        ("giant ant", 2, 18, 3, 0, 0, 10, 10, 4, "a"),
        ("killer bee", 1, 18, -1, 0, 0, 1, 5, 5, "a"),
        ("cockatrice", 5, 6, 6, 30, 0, 30, 30, 8, "c"),
        ("floating eye", 2, 1, 9, 10, 0, 10, 10, 3, "e"),
        ("mind flayer", 9, 12, 5, 90, -8, 1450, 400, 13, "h"),
        ("green slime", 6, 6, 6, 0, 0, 400, 150, 8, "P"),
        ("Medusa", 20, 12, 2, 50, -15, 1450, 400, 25, "@"),
        ("Wizard of Yendor", 30, 12, -8, 100, -128, 1450, 400, 34, "@"),
    ],
    "3.7-5.0": [
        ("giant ant", 2, 18, 3, 0, 0, 10, 10, 4, "a"),
        ("killer bee", 1, 18, -1, 0, 0, 1, 5, 6, "a"),
        ("cockatrice", 5, 6, 6, 30, 0, 30, 30, 8, "c"),
        ("floating eye", 2, 1, 9, 10, 0, 10, 10, 3, "e"),
        ("mind flayer", 9, 12, 5, 90, -8, 1450, 400, 13, "h"),
        ("green slime", 6, 6, 6, 0, 0, 400, 150, 8, "P"),
        ("Medusa", 20, 12, 2, 50, -15, 1450, 400, 25, "@"),
        ("Wizard of Yendor", 30, 12, -8, 100, -128, 1450, 400, 34, "@"),
    ],
}


def verify(key, mons, classes, K):
    print("Verification [%s]:" % key)
    by_name = {m["name"]: m for m in mons}

    for row in HAND[key]:
        name, lvl, mov, ac, mr, aln, wt, nut, diff, sym = row
        m = by_name.get(name)
        if not m:
            check(False, "%s present" % name)
            continue
        got = (m["lvl"], m["mov"], m["ac"], m["mr"], m["aln"], m["wt"],
               m["nut"], m["diff"], classes[m["_sym"]][0])
        want = (lvl, mov, ac, mr, aln, wt, nut, diff, sym)
        check(got == want, "%s stats %s (got %s)" % (name, want, got))

    # attacks, read by hand out of the tables
    def attk(name):
        m = by_name.get(name)
        return [tuple(a) for a in m["atk"]] if m else None

    V = K.vals
    check(attk("soldier ant") == [(V["AT_BITE"], V["AD_PHYS"], 2, 4),
                                  (V["AT_STNG"], V["AD_DRST"], 3, 4)],
          "soldier ant: bite 2d4 phys + sting 3d4 poison (got %s)"
          % (attk("soldier ant"),))
    check(attk("floating eye") == [(V["AT_NONE"], V["AD_PLYS"], 0, 70)],
          "floating eye: passive paralysis 0d70 (got %s)" % (attk("floating eye"),))
    check(attk("cockatrice") == [(V["AT_BITE"], V["AD_PHYS"], 1, 3),
                                 (V["AT_TUCH"], V["AD_STON"], 0, 0),
                                 (V["AT_NONE"], V["AD_STON"], 0, 0)],
          "cockatrice: bite 1d3 + touch stone + passive stone (got %s)"
          % (attk("cockatrice"),))
    check(attk("green slime")[0][1] == V["AD_SLIM"],
          "green slime's first attack is AD_SLIM")

    # flags / resistances
    def has(name, field, flag):
        m = by_name.get(name)
        return bool(m and (m[field] & V[flag]))

    check(has("cockatrice", "res", "MR_STONE"), "cockatrice resists petrification")
    check(has("cockatrice", "cnv", "MR_STONE"), "cockatrice conveys petrification")
    check(has("killer bee", "cnv", "MR_POISON"), "killer bee conveys poison resistance")
    check(has("wraith", "f2", "M2_UNDEAD"), "wraith is M2_UNDEAD")
    check(has("Medusa", "geno", "G_UNIQ"), "Medusa is G_UNIQ")
    check(has("Medusa", "geno", "G_NOGEN"), "Medusa is G_NOGEN")
    check(not has("giant ant", "geno", "G_NOGEN"), "giant ant is randomly generated")
    check((by_name["giant ant"]["geno"] & V["G_FREQ"]) == 3,
          "giant ant frequency == 3 (got %d)"
          % (by_name["giant ant"]["geno"] & V["G_FREQ"]))
    check(has("giant ant", "geno", "G_SGROUP"), "giant ant appears in small groups")
    check(has("killer bee", "geno", "G_LGROUP"), "killer bee appears in large groups")
    check(has("hell hound", "geno", "G_HELL"), "hell hound is G_HELL")

    # class contiguity: mons[] keeps each class together over the randomly
    # generated range (mkclass() relies on it).  Past SPECIAL_PM the quest
    # leaders/nemeses/guardians deliberately repeat earlier classes.
    special = next(i for i, m in enumerate(mons) if m["name"] == "long worm tail")
    seen = []
    for m in mons[:special]:
        if not seen or seen[-1] != m["_sym"]:
            if m["_sym"] in seen:
                check(False, "class %s is not contiguous" % m["_sym"])
                break
            seen.append(m["_sym"])
    else:
        check(True, "every class is contiguous in mons[0..SPECIAL_PM)")

    # the long worm tail marks the start of the never-randomly-generated tail
    idx = [i for i, m in enumerate(mons) if m["name"] == "long worm tail"]
    check(len(idx) == 1, "exactly one 'long worm tail' (SPECIAL_PM anchor)")

    check(all(m["diff"] >= 0 for m in mons), "no negative difficulty")
    check(all(len(m["atk"]) <= 6 for m in mons), "no monster has more than 6 attacks")


# ---------------------------------------------------------------------------
def build(key, ref, table_path, macro_path, out_notes):
    label = "NetHack %s" % key
    K = Constants(label)

    monflag = read_source(ref, "include/monflag.h")
    monattk = read_source(ref, "include/monattk.h")
    align = read_source(ref, "include/align.h")
    permonst = read_source(ref, "include/permonst.h")
    global_h = read_source(ref, "include/global.h")
    monst_h = read_source(ref, "include/monst.h")
    makemon = read_source(ref, "src/makemon.c")

    K.add_defines(monflag)
    if key != "3.6":
        # 3.6 spells the same things out as #define; 3.7 moved them to enums
        K.add_enum(monflag, "ms_sounds")
        K.add_enum(monflag, "mgender")
    K.add_defines(monattk)
    K.add_defines(align)
    K.add_defines(permonst)
    K.add_defines(global_h)

    if key == "3.6":
        classes = class_table_36(read_source(ref, "include/monsym.h"),
                                 read_source(ref, "src/drawing.c"), label)
        check_36_tooweak(makemon, label)
    else:
        classes = class_table_37(read_source(ref, "include/defsym.h"), label)
        check_monst_h(monst_h, label)

    check_makemon(makemon, label, has_temperature=(key != "3.6"))

    # real line numbers, so the citations on the page cannot drift
    cites = out_notes.setdefault("cites", {})
    cites["uncommon"] = "src/makemon.c:%d" % line_of(
        makemon, "uncommon(mndx)" if key == "3.6" else "uncommon(int mndx)",
        label, at_start=True)
    cites["align_shift"] = "src/makemon.c:%d" % line_of(
        makemon, "align_shift(ptr)" if key == "3.6" else "align_shift(struct permonst *ptr)",
        label, at_start=True)
    cites["rndmonst"] = "src/makemon.c:%d" % line_of(
        makemon, "rndmonst()" if key == "3.6" else "rndmonst_adj(int minadj, int maxadj)",
        label, at_start=True)
    if key != "3.6":
        mondata = read_source(ref, "src/mondata.c")
        cites["mstrength"] = "src/mondata.c:%d" % line_of(
            mondata, "mstrength(struct permonst *ptr)", label, at_start=True)
        cites["temperature_shift"] = "src/makemon.c:%d" % line_of(
            makemon, "temperature_shift(struct permonst *ptr)", label, at_start=True)
        cites["gates"] = "include/monst.h:%d" % line_of(
            monst_h, "#define monmax_difficulty(levdif)", label)
        cites["table"] = "include/monsters.h"
    else:
        cites["gates"] = "src/makemon.c:%d (inline)" % line_of(
            makemon, "minmlev = zlevel / 6", label)
        cites["table"] = "src/monst.c"
    cites["difficulty_field"] = "include/permonst.h:%d" % line_of(
        permonst, "difficulty", label)

    macro_src = read_source(ref, macro_path)
    table_src = read_source(ref, table_path) if table_path != macro_path else macro_src
    K.add_defines(macro_src)                    # 3.6 WT_ELF / WT_DRAGON
    if key != "3.6":
        K.add_enum(read_source(ref, "include/weight.h"), "weight_constants")

    K.require(list(M1_LABELS) + list(M2_LABELS) + list(M3_LABELS)
              + list(MR_LABELS) + list(G_LABELS) + list(MZ_LABELS)
              + ["G_FREQ"], "include/monflag.h")
    # AD_POLY (the genetic engineer's attack) is new in 3.7; everything else
    # in monattk.h has been stable since 3.6.
    added_in_37 = {"AD_POLY"} if key == "3.6" else set()
    K.require([n for n in (list(AT_LABELS) + list(AD_LABELS))
               if n not in added_in_37], "include/monattk.h")

    table = Table(macro_src, table_src, K, label)
    print("[%s] macro mapping derived from %s:" % (key, macro_path))
    print("  " + table.describe_mapping())
    mons = table.monsters()

    for m in mons:
        if m["_sym"] not in classes:
            raise SystemExit("%s: %r has unknown class %s"
                             % (label, m["name"], m["_sym"]))

    # difficulty cross-check
    if key != "3.6":
        bad = []
        for m in mons:
            want = mstrength(m, K)
            if want != m["diff"]:
                bad.append((m["name"], m["diff"], want))
        out_notes["mstrength_mismatches"] = bad
        print("  mstrength() recomputed for %d monsters: %d disagree with the table"
              % (len(mons), len(bad)))
        for nm, tbl, calc in bad[:40]:
            print("      %-28s table %3d  mstrength() %3d" % (nm, tbl, calc))
    else:
        out_notes["mstrength_mismatches"] = None
        print("  3.6 has no mstrength(); mons[].difficulty is the only source")

    return mons, classes, K


def encode(mons, classes):
    """Compact per-monster records.  Bit fields stay as integers; the page
    decodes them through the legend.  Order is mons[] order, which is also
    PM_ enum order, so a record's array index is its mons[] index."""
    out = []
    for m in mons:
        r = OrderedDict()
        r["n"] = m["name"]
        if m["alt"]:
            r["an"] = m["alt"]
        r["s"] = classes[m["_sym"]][0]
        r["lv"] = m["lvl"]
        r["mv"] = m["mov"]
        r["ac"] = m["ac"]
        r["mr"] = m["mr"]
        r["al"] = m["aln"]
        r["g"] = m["geno"]
        r["a"] = m["atk"]
        r["sz"] = m["size"]
        r["wt"] = m["wt"]
        r["nu"] = m["nut"]
        r["re"] = m["res"]
        r["cv"] = m["cnv"]
        r["f1"] = m["f1"]
        r["f2"] = m["f2"]
        r["f3"] = m["f3"]
        r["d"] = m["diff"]
        out.append(r)
    return out


def bit_legend(labels, K):
    """[[bitvalue, symbol, label], ...] in monflag.h order."""
    return [[K.vals[name], name, text] for name, text in labels.items()]


def main():
    head = git_head()
    notes = {}
    datasets = OrderedDict()

    raw_tables = {}
    for key, (ref, table_path, macro_path) in SOURCES.items():
        raw_tables[key] = read_source(ref, table_path)

    def decomment(t):
        return re.sub(r"\s+", " ", strip_comments(t))

    same = decomment(raw_tables["3.7"]) == decomment(raw_tables["5.0"])
    print("3.7 vs 5.0 monster table identical (comments ignored): %s\n" % same)
    if not same:
        print("  WARNING: tables differ; the 3.7-5.0 dataset is built from 5.0\n")

    built = {}
    for key in ("3.6", "5.0"):
        ref, table_path, macro_path = SOURCES[key]
        n = {}
        mons, classes, K = build(key, ref, table_path, macro_path, n)
        built[key] = (mons, classes, K, n)
        print()

    out_key = {"3.6": "3.6", "5.0": "3.7-5.0"}
    labels = {"3.6": "NetHack 3.6", "5.0": "NetHack 3.7 / 5.0"}

    for key in ("3.6", "5.0"):
        mons, classes, K, n = built[key]
        notes[out_key[key]] = n
        per = defaultdict(int)
        for m in mons:
            per[classes[m["_sym"]][0]] += 1
        randomly = [m for m in mons
                    if not (m["geno"] & (K.vals["G_NOGEN"] | K.vals["G_UNIQ"]))]
        print("Summary [%s]: %d monsters in mons[], %d classes, "
              "%d not excluded by G_NOGEN/G_UNIQ"
              % (out_key[key], len(mons), len(per), len(randomly)))
        freq0 = [m["name"] for m in randomly if (m["geno"] & K.vals["G_FREQ"]) == 0]
        print("  %d of those carry frequency 0 (reachable only via align_shift): %s"
              % (len(freq0), ", ".join(freq0[:8]) + ("..." if len(freq0) > 8 else "")))
    print()

    for key in ("3.6", "5.0"):
        mons, classes, K, _n = built[key]
        verify(out_key[key], mons, classes, K)
        print()

    if failures:
        print("%d VERIFICATION FAILURE(S) -- not writing output" % len(failures))
        return 1

    # ---- assemble ----
    versions = OrderedDict()
    all_classes = OrderedDict()
    for key in ("3.6", "5.0"):
        mons, classes, K, _n = built[key]
        vkey = out_key[key]
        special = next(i for i, m in enumerate(mons) if m["name"] == "long worm tail")
        for sym, (ch, desc) in classes.items():
            if ch not in all_classes and any(m["_sym"] == sym for m in mons):
                all_classes[ch] = desc
        versions[vkey] = OrderedDict((
            ("label", labels[key]),
            ("special_pm", special),
            ("mons", encode(mons, classes)),
        ))

    K = built["5.0"][2]
    K36 = built["3.6"][2]
    at_legend = OrderedDict()
    for name, text in sorted(AT_LABELS.items(), key=lambda kv: K.vals[kv[0]]):
        at_legend[str(K.vals[name])] = [name, text]
    ad_legend = OrderedDict()
    for name, text in sorted(AD_LABELS.items(), key=lambda kv: K.vals[kv[0]]):
        entry = [name, text]
        if name in AD_SEVERITY:
            entry.append(AD_SEVERITY[name])
        ad_legend[str(K.vals[name])] = entry
    # every AT_/AD_ code must mean the same thing in 3.6
    for name in list(AT_LABELS) + list(AD_LABELS):
        if name in K36.vals and K36.vals[name] != K.vals[name]:
            raise SystemExit("attack constant %s differs between 3.6 (%d) and 5.0 (%d)"
                             % (name, K36.vals[name], K.vals[name]))

    size_legend = OrderedDict((str(K.vals[n]), t) for n, t in MZ_LABELS.items())

    out = OrderedDict()
    out["generated_from"] = OrderedDict((
        ("repo_commit", head),
        ("generated", datetime.date.today().isoformat()),
        ("tables", OrderedDict((
            ("3.6", "src/monst.c @ origin/NetHack-3.6"),
            ("3.7-5.0", "include/monsters.h @ NetHack-5.0 "
                        "(byte-identical to 3.7 apart from comments)"
             if same else
             "include/monsters.h @ NetHack-5.0 (3.7 differs; 5.0 shown)"),
        ))),
        ("identical_3_7_5_0", same),
    ))
    c36 = notes["3.6"]["cites"]
    c50 = notes["3.7-5.0"]["cites"]
    out["formulas"] = OrderedDict((
        ("difficulty", OrderedDict((
            ("3.6", "3.6 has no difficulty formula in the source at all: "
                    "`makedefs -m` was deprecated (util/makedefs.c do_monstr() "
                    "prints a deprecation notice and emits a stub file), so the "
                    "mons[].difficulty column of src/monst.c is the only source."),
            ("3.7-5.0", "mstrength(), %s. This generator re-implements it and "
                        "checks the result against every row of the table."
                        % c50["mstrength"]),
            ("field", "struct permonst.difficulty, %s" % c50["difficulty_field"]),
            ("mismatches_3_7_5_0",
             [[n, t, c] for n, t, c in notes["3.7-5.0"]["mstrength_mismatches"]]),
        ))),
        ("generation", OrderedDict((
            ("rndmonst", OrderedDict((("3.6", c36["rndmonst"]),
                                      ("3.7-5.0", c50["rndmonst"])))),
            ("gates", OrderedDict((("3.6", c36["gates"]),
                                   ("3.7-5.0", c50["gates"])))),
            ("min", "monmin_difficulty = level_difficulty / 6"),
            ("max", "monmax_difficulty = (level_difficulty + experience_level) / 2"),
            ("uncommon", OrderedDict((
                ("3.6", c36["uncommon"]), ("3.7-5.0", c50["uncommon"]),
                ("rule", "G_NOGEN and G_UNIQ are never picked; inside Gehennom "
                         "only monsters with maligntyp <= A_NEUTRAL may appear, "
                         "outside it G_HELL monsters may not; G_NOHELL monsters "
                         "are excluded inside Gehennom by rndmonst() itself"),
            ))),
            ("weight", "(geno & G_FREQ) + align_shift()"
                       " [+ temperature_shift() in 3.7/5.0];"
                       " a monster whose weight comes out 0 is never picked"),
            ("align_shift", OrderedDict((
                ("3.6", c36["align_shift"]), ("3.7-5.0", c50["align_shift"]),
                ("rule", "lawful level: (maligntyp + 20) / (2 * ALIGNWEIGHT); "
                         "neutral level: (20 - |maligntyp|) / ALIGNWEIGHT; "
                         "chaotic level: (20 - maligntyp) / (2 * ALIGNWEIGHT); "
                         "unaligned: 0. ALIGNWEIGHT is 4, include/global.h:411"),
            ))),
            ("temperature_shift",
             "%s: +3 if the level is hot/cold and the monster resists that "
             "element. Only 3.7 / 5.0; no ordinary dungeon level sets it."
             % c50["temperature_shift"]),
            ("special_pm", "only mons[LOW_PM .. SPECIAL_PM-1] are considered; "
                           "SPECIAL_PM is PM_LONG_WORM_TAIL, include/permonst.h"),
        ))),
    ))
    out["legend"] = OrderedDict((
        ("keys", OrderedDict((
            ("n", "name"), ("an", "alternate (gendered) names"),
            ("s", "display symbol"), ("lv", "base level"), ("mv", "speed"),
            ("ac", "armor class"), ("mr", "magic resistance %"),
            ("al", "alignment"), ("g", "geno mask (G_* bits, low 3 = frequency)"),
            ("a", "attacks: [attack type, damage type, dice count, die size]"),
            ("sz", "size"), ("wt", "corpse weight"), ("nu", "nutrition"),
            ("re", "resistances (MR_* bits)"),
            ("cv", "resistances conveyed by eating (MR_* bits)"),
            ("f1", "M1_* flags"), ("f2", "M2_* flags"), ("f3", "M3_* flags"),
            ("d", "difficulty"),
        ))),
        ("classes", all_classes),
        ("at", at_legend),
        ("ad", ad_legend),
        ("size", size_legend),
        ("mr", bit_legend(MR_LABELS, K)),
        ("g", bit_legend(G_LABELS, K)),
        ("m1", bit_legend(M1_LABELS, K)),
        ("m2", bit_legend(M2_LABELS, K)),
        ("m3", bit_legend(M3_LABELS, K)),
        ("g_freq_mask", K.vals["G_FREQ"]),
        ("alignweight", K.vals["ALIGNWEIGHT"]),
    ))
    out["versions"] = versions

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"), ensure_ascii=False)
    print("Wrote %s (%d bytes, %.0f KB)"
          % (OUT, os.path.getsize(OUT), os.path.getsize(OUT) / 1024.0))
    for vkey, v in versions.items():
        print("  %-8s %d monsters, SPECIAL_PM index %d"
              % (vkey, len(v["mons"]), v["special_pm"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
