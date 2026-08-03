#!/usr/bin/env python3
"""Generate tools/data/wish.json -- everything the wish validator needs.

The point of this file is that *no rule is written down here as a fact*.
Every number, every list and every line citation is located in the NetHack
source at generation time, and the script dies if the source no longer says
what the wish engine assumes.  When the DevTeam changes readobjnam(), this
script fails instead of the web page quietly lying.

Sources, per version:

    3.6        -> origin/NetHack-3.6
    3.7 / 5.0  -> NetHack-5.0 working tree, cross-checked against
                  origin/NetHack-3.7 (readobjnam() is byte-identical in the
                  two apart from comments; the script proves that)

What is derived here:

  * per-object wish flags (mergeable, charged, nowish, weptool, ammo,
    missile, candle, damageable, poisonable) -- computed from the same
    objects table gen-objects.py parses, using the macros in include/obj.h
    and include/objclass.h, with the enum values read out of
    include/skills.h and include/objclass.h rather than hardcoded
  * the random spe that mksobj() hands a wand or a charged tool, parsed
    out of the switch statement in src/mkobj.c
  * the artifact list from include/artilist.h and the role -> quest
    artifact mapping from src/role.c
  * the wizard-mode-only substitution table from readobjnam()
  * per-rule file:line citations, found by regex, for both branches

Object *names*, costs and probabilities are NOT regenerated: those come
from data/objects.json (gen-objects.py).  This script asserts that its own
object name list matches that file exactly, so the web page can join the
two by name.

Re-runnable; prints a verification summary.  Usage:

    python3 scripts/gen-wish.py
"""

from __future__ import annotations

import datetime
import importlib.util
import json
import os
import re
import subprocess
import sys
from collections import OrderedDict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
REPO = "/Users/ian/dev/nethackwiki/NetHack"
OUT = os.path.join(ROOT, "data", "wish.json")
OBJECTS_JSON = os.path.join(ROOT, "data", "objects.json")

# reuse the object-table parser rather than writing a second one
_spec = importlib.util.spec_from_file_location(
    "gen_objects", os.path.join(HERE, "gen-objects.py")
)
gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gen)

# version key -> (branch used for citations, branch that must agree, object table)
VERSIONS = OrderedDict(
    (
        ("3.6", OrderedDict((
            ("label", "NetHack 3.6"),
            ("ref", "origin/NetHack-3.6"),
            ("also", None),
            ("objtable", "src/objects.c"),
        ))),
        ("3.7-5.0", OrderedDict((
            ("label", "NetHack 3.7 / 5.0"),
            ("ref", None),                       # None = working tree (5.0)
            ("also", "origin/NetHack-3.7"),
            ("objtable", "include/objects.h"),
        ))),
    )
)

failures = []


def check(ok, msg):
    print("  %s %s" % ("PASS" if ok else "FAIL", msg))
    if not ok:
        failures.append(msg)


def die(msg):
    raise SystemExit("gen-wish: " + msg)


# --------------------------------------------------------------------------
# source access
# --------------------------------------------------------------------------
_cache = {}


def src(ref, path):
    key = (ref, path)
    if key not in _cache:
        _cache[key] = gen.read_source(ref, path)
    return _cache[key]


def find_line(ref, path, pattern, what):
    """Line number (1-based) of the first line matching `pattern`.

    Dies if the pattern is gone -- that is the whole point: an upstream
    change to a rule we implement must break the build, not the page.
    """
    rx = re.compile(pattern)
    for i, line in enumerate(src(ref, path).split("\n"), 1):
        if rx.search(line):
            return i
    die("%s: cannot find %s in %s (%r)" % (ref or "5.0 worktree", what, path, pattern))


def find_block(text, header_rx):
    """Body of a C function whose first line matches header_rx, brace-matched."""
    m = re.search(header_rx, text)
    if not m:
        die("cannot find function matching %r" % header_rx)
    i = text.index("{", m.end())
    depth, j = 0, i
    while j < len(text):
        if text[j] == "{":
            depth += 1
        elif text[j] == "}":
            depth -= 1
            if depth == 0:
                return text[i : j + 1]
        j += 1
    die("unbalanced braces after %r" % header_rx)


# --------------------------------------------------------------------------
# enums, read from the headers instead of being retyped here
# --------------------------------------------------------------------------
def read_enum(ref, path, enum_name):
    text = gen.strip_comments(src(ref, path))
    m = re.search(r"enum\s+%s\s*\{(.*?)\}" % re.escape(enum_name), text, re.S)
    if not m:
        die("%s: enum %s not found" % (path, enum_name))
    vals, nxt = OrderedDict(), 0
    for part in m.group(1).split(","):
        part = part.strip()
        if not part:
            continue
        mm = re.match(r"([A-Za-z_]\w*)\s*(?:=\s*(-?\d+))?$", part)
        if not mm:
            die("%s: cannot parse enum member %r" % (path, part))
        nxt = int(mm.group(2)) if mm.group(2) is not None else nxt
        vals[mm.group(1)] = nxt
        nxt += 1
    return vals


# --------------------------------------------------------------------------
# per-object wish flags
# --------------------------------------------------------------------------
# BITS() fields gen-objects.py does not keep, but the wish rules need.
EXTRA_BITS = ("nwsh", "mrg", "chrg", "uniq")


class WishTable(gen.Table):
    """gen-objects.py's parser, plus the BITS fields the wish rules use."""

    def record(self, macro, args):
        rec = gen.Table.record(self, macro, args)
        if rec is None:
            return None
        fields = self.expand(macro, args)
        bits_expr = fields[self.idx["bits"]]
        bits_args, _ = gen.split_args(bits_expr, bits_expr.index("("))
        for f in EXTRA_BITS:
            if f not in self.bits_params:
                die("%s: BITS() has no %r field: %r"
                    % (self.label, f, self.bits_params))
            rec["_" + f] = bool(gen.eval_int(bits_args[self.bits_params.index(f)]))
        # oc_dir / oc_subtyp (skill) / oc_material live in OBJECT() slots
        for name, key in (("dir", "_dir"), ("sub", "_sub"), ("mtrl", "_mtrl")):
            if name not in self.bits_params:
                die("%s: BITS() has no %r field" % (self.label, name))
            rec[key] = bits_args[self.bits_params.index(name)].strip()
        rec["_oprop"] = fields[self.object_params.index("prp")].strip()
        return rec


# 3.6's objects.c has no `sn` field: the object enum is generated by
# util/makedefs.c do_objs() from the table name.  Reproduce that here so
# 3.6 gets the same symbol -> name map that 3.7/5.0 declare outright.
MAKEDEFS_PREFIX = {
    "WAND_CLASS": "WAN_", "RING_CLASS": "RIN_", "POTION_CLASS": "POT_",
    "SPBOOK_CLASS": "SPE_", "SCROLL_CLASS": "SCR_",
}
# gen-objects.py prepends these to the raw table name; strip them back off
BARE_PREFIX = {
    "WAND_CLASS": "wand of ", "RING_CLASS": "ring of ",
    "POTION_CLASS": "potion of ", "SPBOOK_CLASS": "spellbook of ",
    "SCROLL_CLASS": "scroll of ",
}


def makedefs_obj_symbol(rec):
    """ART_/object enum symbol makedefs would emit for one table entry."""
    cls = rec["_sym"]
    bare = rec["name"]
    pre = BARE_PREFIX.get(cls)
    if pre and bare.startswith(pre):
        bare = bare[len(pre):]
    up = "".join(c.upper() if ("a" <= c <= "z" or "A" <= c <= "Z") else "_"
                 for c in bare)
    prefix = MAKEDEFS_PREFIX.get(cls, "")
    return prefix + up[: 26 if prefix else 30]


def resolve(sym, enums, default=None):
    """Resolve a BITS() argument that is an enum symbol or a literal int."""
    sym = sym.strip()
    v = gen.eval_int(sym)
    if v is not None:
        return v
    if sym in enums:
        return enums[sym]
    m = re.match(r"^-\s*([A-Za-z_]\w*)$", sym)
    if m and m.group(1) in enums:
        return -enums[m.group(1)]
    m = re.match(r"^HARDGEM\s*\(", sym)
    if m:
        return 0  # gem hardness, not a skill
    if default is not None:
        return default
    die("cannot resolve enum symbol %r" % sym)


def object_flags(objs, mat, skill, dirs, label):
    """Apply the include/obj.h + include/objclass.h macros to each object."""
    out = OrderedDict()
    for o in objs:
        cls = o["_sym"]
        material = resolve(o["_mtrl"], mat)
        sub = resolve(o["_sub"], skill, default=0)
        oprop = o["_oprop"]
        name = o["name"]

        # is_weptool(o): TOOL_CLASS && oc_skill != P_NONE
        weptool = cls == "TOOL_CLASS" and sub != skill["P_NONE"]
        # is_ammo: (WEAPON|GEM) && -P_CROSSBOW <= skill <= -P_BOW
        ammo = (cls in ("WEAPON_CLASS", "GEM_CLASS")
                and -skill["P_CROSSBOW"] <= sub <= -skill["P_BOW"])
        # is_missile: (WEAPON|TOOL) && -P_BOOMERANG <= skill <= -P_DART
        missile = (cls in ("WEAPON_CLASS", "TOOL_CLASS")
                   and -skill["P_BOOMERANG"] <= sub <= -skill["P_DART"])
        # is_poisonable: WEAPON && -P_SHURIKEN <= skill <= -P_BOW
        #                (|| permapoisoned(), which is Grimtooth only)
        poisonable = (cls == "WEAPON_CLASS"
                      and -skill["P_SHURIKEN"] <= sub <= -skill["P_BOW"])
        # is_multigen: WEAPON && -P_SHURIKEN <= skill <= -P_BOW  (same range)
        multigen = poisonable

        candle = name in ("tallow candle", "wax candle")
        # is_flammable(): not candles, not fire-res-conveying, not wand of fire
        flammable = (not candle
                     and oprop != "FIRE_RES" and name != "wand of fire"
                     and ((material <= mat["WOOD"] and material != mat["LIQUID"])
                          or material == mat["PLASTIC"]))
        rustprone = material == mat["IRON"]
        rottable = ((material <= mat["WOOD"] and material != mat["LIQUID"])
                    or material == mat["DRAGON_HIDE"])
        corrodeable = material in (mat["COPPER"], mat["IRON"])
        crackable = material == mat["GLASS"] and cls == "ARMOR_CLASS"
        damageable = (rustprone or flammable or rottable or corrodeable
                      or crackable)
        # erosion_matters(): weptools, weapons, armor, balls, chains
        ero_matters = (weptool
                       or cls in ("WEAPON_CLASS", "ARMOR_CLASS",
                                  "BALL_CLASS", "CHAIN_CLASS"))

        f = OrderedDict()
        if o["_mrg"]:
            f["mrg"] = 1
        if o["_chrg"]:
            f["chg"] = 1
        if o["_nwsh"]:
            f["nws"] = 1
        if o["_uniq"]:
            f["unq"] = 1
        if weptool:
            f["wpt"] = 1
        if ammo:
            f["amo"] = 1
        if missile:
            f["mis"] = 1
        if multigen:
            f["mgn"] = 1
        if candle:
            f["cnd"] = 1
        if poisonable:
            f["psn"] = 1
        if ero_matters and damageable:
            f["ero"] = 1
            # add_erosion_words() picks exactly one word, in this order
            f["epw"] = ("rustproof" if rustprone
                        else "corrodeproof" if corrodeable
                        else "fireproof" if flammable
                        else "tempered" if crackable
                        else "rotproof" if rottable
                        else "")
        elif name == "crysknife":
            # readobjnam() erodeproofs a crysknife explicitly even though
            # is_damageable() is false for it; add_erosion_words() says "fixed"
            f["ero"] = 1
            f["epw"] = "fixed"
        if cls == "WAND_CLASS":
            f["dir"] = "nodir" if resolve(o["_dir"], dirs, default=0) == 1 else "beam"
        if name in out:
            die("%s: duplicate object name %r" % (label, name))
        out[name] = f
    return out


# --------------------------------------------------------------------------
# what mksobj() rolls for spe -- parsed out of src/mkobj.c
# --------------------------------------------------------------------------
def spe_expr_range(expr):
    """rn1(a,b) -> [b, b+a-1]; rnd(a) -> [1,a]; literal -> [n,n]."""
    expr = expr.strip()
    m = re.fullmatch(r"rn1\(\s*(\d+)\s*,\s*(\d+)\s*\)", expr)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        return [b, b + a - 1]
    m = re.fullmatch(r"rnd\(\s*(\d+)\s*\)", expr)
    if m:
        return [1, int(m.group(1))]
    m = re.fullmatch(r"(\d+)", expr)
    if m:
        return [int(m.group(1)), int(m.group(1))]
    return None


TOOL_SPE_EXPECT = {
    "MAGIC_MARKER", "TINNING_KIT", "EXPENSIVE_CAMERA", "CAN_OF_GREASE",
    "CRYSTAL_BALL", "HORN_OF_PLENTY", "BAG_OF_TRICKS", "BELL_OF_OPENING",
    "MAGIC_FLUTE", "MAGIC_HARP", "FROST_HORN", "FIRE_HORN",
    "DRUM_OF_EARTHQUAKE", "TALLOW_CANDLE", "WAX_CANDLE", "BRASS_LANTERN",
    "OIL_LAMP", "MAGIC_LAMP",
}


def parse_mksobj(ref, sym_to_name, label):
    """Random initial spe per object type, from mksobj()'s TOOL/WAND switch."""
    text = gen.strip_comments(src(ref, "src/mkobj.c"))
    # 3.6 does it inline in mksobj(); 3.7/5.0 split it into mksobj_init()
    body = None
    for hdr in (r"\nmksobj_init\(", r"\nmksobj\("):
        if re.search(hdr, text):
            body = find_block(text, hdr)
            break
    if body is None:
        die("%s: neither mksobj_init() nor mksobj() found in src/mkobj.c" % label)

    def class_block(cls):
        m = re.search(r"case\s+%s:" % cls, body)
        if not m:
            die("%s: no `case %s:` in mksobj" % (label, cls))
        rest = body[m.end():]
        # up to the next top-level class label
        stop = re.search(r"\n\s{4,8}case\s+[A-Z_]+_CLASS:", rest)
        return rest[: stop.start()] if stop else rest

    # ---- tools ----
    tool = class_block("TOOL_CLASS")
    ranges, pending, seen = OrderedDict(), [], set()
    for line in tool.split("\n"):
        s = line.strip()
        m = re.match(r"case\s+([A-Z_0-9]+):", s)
        if m:
            pending.append(m.group(1))
            continue
        m = re.match(r"otmp->spe\s*=\s*(.+?);", s)
        if m and pending:
            rng = spe_expr_range(m.group(1))
            if rng:
                for sym in pending:
                    ranges[sym] = rng
                    seen.add(sym)
            continue
        if s.startswith("break;"):
            pending = []
    missing = TOOL_SPE_EXPECT - seen
    if missing:
        die("%s: mksobj no longer sets spe for %s" % (label, sorted(missing)))

    # ---- wands ----
    wand = class_block("WAND_CLASS")
    m = re.search(
        r"otmp->spe\s*=\s*rn1\(\s*(\d+),\s*\(objects\[otmp->otyp\]\.oc_dir"
        r"\s*==\s*NODIR\)\s*\?\s*(\d+)\s*:\s*(\d+)\)",
        re.sub(r"\s+", " ", wand),
    )
    if not m:
        die("%s: mksobj's generic wand charge formula changed" % label)
    span, nodir, beam = int(m.group(1)), int(m.group(2)), int(m.group(3))
    wands = OrderedDict((
        ("nodir", [nodir, nodir + span - 1]),
        ("beam", [beam, beam + span - 1]),
    ))
    flat = re.sub(r"\s+", " ", wand)
    for sym in ("WAN_WISHING", "WAN_STASIS"):
        mm = re.search(
            r"otyp\s*==\s*%s\)?\s*(?:/\*.*?\*/)?\s*otmp->spe\s*=\s*([^;]+);" % sym,
            flat,
        )
        if mm:
            rng = spe_expr_range(mm.group(1))
            if rng:
                ranges[sym] = rng

    # ---- armor types mksobj() usually curses (they also get -rne(3)) ----
    armor = class_block("ARMOR_CLASS")
    head = re.sub(r"\s+", " ", armor)
    head = head[: head.index("!rn2(11)")] if "!rn2(11)" in head else head
    cursed_armor = []
    for sym in re.findall(r"otmp->otyp\s*==\s*([A-Z_0-9]+)", head):
        nm = sym_to_name.get(sym)
        if nm and nm not in cursed_armor:
            cursed_armor.append(nm)
    if len(cursed_armor) < 3:
        die("%s: mksobj's usually-cursed armor list changed (%r)"
            % (label, cursed_armor))

    out = OrderedDict()
    for sym, rng in ranges.items():
        nm = sym_to_name.get(sym)
        if nm:
            out[nm] = rng
    return out, wands, cursed_armor


# --------------------------------------------------------------------------
# artifacts
# --------------------------------------------------------------------------
ALIGN = {"A_LAWFUL": "lawful", "A_NEUTRAL": "neutral", "A_CHAOTIC": "chaotic",
         "A_NONE": "unaligned"}


def parse_roles(ref):
    """Role display name -> ART_xxx symbol, from src/role.c."""
    text = gen.strip_comments(src(ref, "src/role.c"))
    m = re.search(r"struct\s+Role\s+roles\[[^\]]*\]\s*=\s*\{", text)
    if not m:
        die("src/role.c: roles[] table not found")
    body = text[m.end():]
    # Each role entry opens with its own name and closes (as far as we care)
    # with its ART_xxx quest artifact; the nine rank titles in between look
    # exactly like the name, so pair each ART_ with the first name string
    # that follows the previous ART_.
    roles, cursor = OrderedDict(), 0
    for art in re.finditer(r"\bART_[A-Z_0-9]+\b", body):
        nm = re.search(r'"([A-Za-z][A-Za-z ]*)"\s*,\s*0\s*\}',
                       body[cursor:art.start()])
        if not nm:
            die("src/role.c: no role name before %s" % art.group(0))
        roles[nm.group(1)] = art.group(0)
        cursor = art.end()
    if len(roles) < 10:
        die("src/role.c: only found %d role->artifact pairs" % len(roles))
    return roles


def makedefs_art_symbol(name):
    """The ART_xxx symbol makedefs derives from an artifact name.

    3.6 has no `bn` field in A(); its ART_ constants are generated by
    util/makedefs.c (do_objs(): uppercase, non-letters to '_', drop a
    leading "THE_" and a leading "PLATINUM_", truncate to 26 chars).
    """
    s = "".join(c.upper() if c.isalpha() and c.isascii() else "_" for c in name)
    if s.startswith("THE_"):
        s = s[4:]
    if s.startswith("PLATINUM_"):
        s = s[9:]
    return "ART_" + s[:26]


def parse_artifacts(ref, sym_to_name, label):
    raw = src(ref, "include/artilist.h")
    text = re.sub(r"\\[ \t]*\n", " ", gen.strip_comments(raw))

    # derive A()'s argument order rather than assuming it
    params = None
    for m in re.finditer(r"#\s*define\s+A\(", text):
        args, _ = gen.split_args(text, text.index("(", m.end() - 1))
        args = [a.strip() for a in args]
        if params is not None and args != params:
            die("%s: artilist.h A() definitions disagree" % label)
        params = args
    if not params:
        die("%s: no A() macro definition in artilist.h" % label)
    for need in ("nam", "typ", "s1", "al", "cl"):
        if need not in params:
            die("%s: A() has no %r field: %r" % (label, need, params))
    ix = {k: params.index(k) for k in params}

    arts, pos = [], 0
    while True:
        m = re.compile(r"\bA\(").search(text, pos)
        if not m:
            break
        try:
            args, end = gen.split_args(text, m.end() - 1)
        except ValueError:
            pos = m.end()
            continue
        pos = end
        if len(args) != len(params):
            continue  # this is the #define itself, or something else
        name = gen.parse_c_string(args[ix["nam"]])
        if not name:
            continue  # dummy element #0
        bn = ("ART_" + args[ix["bn"]].strip()) if "bn" in ix \
            else makedefs_art_symbol(name)
        arts.append(OrderedDict((
            ("name", name),
            ("_otyp", args[ix["typ"]].strip()),
            ("_spfx", args[ix["s1"]]),
            ("_align", args[ix["al"]].strip()),
            ("_role", args[ix["cl"]].strip()),
            ("bn", bn),
        )))
    if len(arts) < 25:
        die("%s: only parsed %d artifacts from artilist.h" % (label, len(arts)))

    # any_quest_artifact(): oartifact >= ART_ORB_OF_DETECTION, i.e. everything
    # from that entry onward in table order
    idx = [i for i, a in enumerate(arts) if a["bn"] == "ART_ORB_OF_DETECTION"]
    if not idx:
        die("%s: ART_ORB_OF_DETECTION not in artilist.h" % label)
    first_quest = idx[0]

    roles = parse_roles(ref)
    art_to_role = OrderedDict((v, k) for k, v in roles.items())
    known = {a["bn"] for a in arts}
    unknown = [s for s in art_to_role if s not in known]
    if unknown:
        die("%s: src/role.c names quest artifacts absent from artilist.h: %s"
            % (label, unknown))

    out = []
    for i, a in enumerate(arts):
        base = sym_to_name.get(a["_otyp"])
        if base is None:
            die("%s: artifact %r has unknown base object %r"
                % (label, a["name"], a["_otyp"]))
        rec = OrderedDict()
        rec["name"] = a["name"]
        rec["base"] = base
        rec["align"] = ALIGN.get(a["_align"], a["_align"])
        rec["nogen"] = "SPFX_NOGEN" in a["_spfx"]
        if i >= first_quest:
            rec["inquestrange"] = True
        qrole = art_to_role.get(a["bn"])
        if qrole:
            rec["questrole"] = qrole
        m = re.match(r"PM_([A-Z_]+)$", a["_role"])
        if m:
            rec["giftrole"] = m.group(1).replace("_", " ").title()
        out.append(rec)
    return out


# --------------------------------------------------------------------------
# citations: every rule the engine implements, located in the source
# --------------------------------------------------------------------------
# key -> (file, regex, human description)
RULES = OrderedDict((
    ("prefix_loop", ("src/objnam.c", r'"blessed ", l = 8',
                     "adjective prefix loop (order-independent)")),
    ("charge_paren", ("src/objnam.c", r"rechrg = .*\bspe;",
                      "(n:m) charge syntax")),
    ("spe_unspecified", ("src/objnam.c", r"spesgn == 0",
                         "no +N given: keep the rolled spe")),
    ("spe_cap", ("src/objnam.c", r"spe > (SPE_LIM|SCHAR_LIM)",
                 "absolute cap on requested spe")),
    ("rechrg_cap", ("src/objnam.c", r"rechrg < 0 \|\| .*rechrg > 7",
                    "recharge count capped at 7")),
    ("gold_cap", ("src/objnam.c", r"cnt > 5000 && !wizard",
                  "gold quantity capped at 5000")),
    ("wizonly_subs", ("src/objnam.c", r"case AMULET_OF_YENDOR:",
                      "wizard-mode-only objects substituted")),
    ("nowish", ("src/objnam.c", r"oc_nowish",
                "oc_nowish objects rejected outright")),
    ("quan_merge", ("src/objnam.c", r"oc_merge",
                    "count only honored for mergeable objects")),
    ("quan_rnd6", ("src/objnam.c", r"cnt < rnd\(6\)",
                   "small counts pass a rnd(6) roll")),
    ("quan_candle", ("src/objnam.c", r"cnt <= 7 && Is_candle",
                     "candles: up to 7 always honored")),
    ("quan_bulk", ("src/objnam.c", r"cnt <= 20",
                   "rocks/missiles/ammo: up to 20 always honored")),
    ("spe_clamp", ("src/objnam.c", r"spe > rnd\(5\) && .*spe > .*otmp->spe",
                   "enchantment beyond rnd(5) is zeroed")),
    ("spe_luck", ("src/objnam.c", r"spe > 2 && Luck < 0",
                  "+3 or better with negative Luck becomes negative")),
    ("spe_wand_neg", ("src/objnam.c", r"spe > 1 && .*spesgn == -1",
                      "wands cancel to (n:-1)")),
    ("spe_other_neg", ("src/objnam.c", r"spe > 0 && .*spesgn == -1",
                       "other classes cannot be given negative spe")),
    ("spe_cap_random", ("src/objnam.c", r"^\s*if \(\S*spe > \S*otmp->spe\)$",
                        "charges capped at what mksobj() rolled")),
    ("wan_wishing", ("src/objnam.c", r"spe = \(rn2\(10\) \? -1 : 0\)",
                     "wished wand of wishing gets 0 or -1 charges")),
    ("wan_wishing_rechrg", ("src/objnam.c", r"rechrg = 1;",
                            "wished wand of wishing counts as recharged")),
    ("bcu", ("src/objnam.c", r"blessed = \(Luck >= 0",
             "blessed/uncursed honored only at non-negative Luck")),
    ("erodeproof", ("src/objnam.c", r"oerodeproof = \(Luck >= 0",
                    "erodeproof honored only at non-negative Luck")),
    ("poisoned", ("src/objnam.c", r"opoisoned = \(Luck >= 0\)",
                  "poisoned honored only at non-negative Luck")),
    ("greased", ("src/objnam.c", r"otmp->greased = 1;",
                 "greased always honored")),
    ("arti_fail", ("src/objnam.c", r"rn2\(nartifact_exist\(\)\) > 1",
                   "artifact wish failure roll")),
    ("arti_quest", ("src/objnam.c", r"is_quest_artifact\(",
                    "your own quest artifact is never granted")),
    ("arti_exists", ("src/do_name.c", r"exist_artifact\(obj->otyp, name\)",
                     "an artifact that already exists is not re-made")),
    ("arti_name", ("src/artifact.c", r"^artifact_name\(",
                   "artifact recognized by name only")),
    ("nartifact_exist", ("src/artifact.c", r"^nartifact_exist\(",
                         "count of artifacts that exist")),
    ("mksobj_weapon", ("src/mkobj.c", r"otmp->spe = rne\(3\);",
                       "random weapon/armor enchantment")),
    ("mksobj_ring", ("src/mkobj.c", r"spe = rn2\(4\) - rn2\(3\)",
                     "random ring enchantment")),
    ("rne", ("src/rnd.c", r"^rne\((int x|x)\)", "rne(): geometric with a cap")),
    ("blessorcurse", ("src/mkobj.c", r"^blessorcurse\(",
                      "default blessed/cursed roll")),
))


def cites(ref, also, label):
    out = OrderedDict()
    for key, (path, rx, what) in RULES.items():
        line = find_line(ref, path, rx, "%s (%s)" % (what, key))
        rec = OrderedDict((("file", path), ("line", line), ("what", what)))
        if also:
            rec["line_alt"] = find_line(also, path, rx, "%s (%s)" % (what, key))
        out[key] = rec
    print("  %s: located all %d rule citations" % (label, len(out)))
    return out


# --------------------------------------------------------------------------
# constants pulled out of the source
# --------------------------------------------------------------------------
def constants(ref, label):
    obj = src(ref, "src/objnam.c")
    flat = gen.strip_comments(obj)

    m = re.search(r"spe\s*>\s*(SPE_LIM|SCHAR_LIM)", flat)
    cap_name = m.group(1)
    cap = None
    for path in ("include/obj.h", "src/objnam.c", "include/global.h"):
        mm = re.search(r"#\s*define\s+%s\s+(\d+)" % cap_name, src(ref, path))
        if mm:
            cap = int(mm.group(1))
            break
    if cap is None:
        die("%s: cannot find the value of %s" % (label, cap_name))

    m = re.search(r"rechrg\s*<\s*0\s*\|\|\s*\S*rechrg\s*>\s*(\d+)", flat)
    if not m:
        die("%s: recharge cap changed" % label)
    rechrg_cap = int(m.group(1))

    m = re.search(r"cnt\s*>\s*(\d+)\s*&&\s*!wizard", flat)
    if not m:
        die("%s: gold cap changed" % label)
    gold_cap = int(m.group(1))

    # the whole quantity test, on one line, so the three limits can be read
    # off in order without matching similar text elsewhere in the file
    one = re.sub(r"\s+", " ", flat)
    m = re.search(r"cnt < rnd\((\d+)\)", one)
    if not m:
        die("%s: quantity test changed shape" % label)
    quan_die, tail = int(m.group(1)), one[m.end() : m.end() + 300]
    mm = re.search(r"cnt <= (\d+) && Is_candle", tail)
    if not mm:
        die("%s: candle quantity rule changed" % label)
    candle_cap = int(mm.group(1))
    mm = re.search(r"cnt <= (\d+)(?! && Is_candle)", tail[tail.index("Is_candle"):])
    if not mm:
        die("%s: bulk quantity rule changed" % label)
    bulk_cap = int(mm.group(1))

    m = re.search(r"spe\s*>\s*rnd\((\d+)\)", flat)
    ench_die = int(m.group(1))
    m = re.search(r"spe\s*>\s*(\d+)\s*&&\s*Luck\s*<\s*0", flat)
    luck_ench_floor = int(m.group(1))

    # behaviour that is present in one branch and absent in the other
    wandlike = re.search(r"oclass == WAND_CLASS([^)]*)\)", one)
    if not wandlike:
        die("%s: wand-like spe branch not found" % label)
    features = OrderedDict((
        ("crystal_ball_cancels", "CRYSTAL_BALL" in wandlike.group(1)),
        ("flint_stacks", "FLINT" in tail),
    ))

    return features, OrderedDict((
        ("spe_cap", cap),
        ("spe_cap_name", cap_name),
        ("recharge_cap", rechrg_cap),
        ("gold_cap", gold_cap),
        ("quan_die", quan_die),
        ("candle_count_cap", candle_cap),
        ("bulk_count_cap", bulk_cap),
        ("ench_die", ench_die),
        ("luck_ench_floor", luck_ench_floor),
    ))


def substitutions(ref, sym_to_name, label):
    """The `if (typ && !wizard) switch (typ)` table in readobjnam()."""
    flat = gen.strip_comments(src(ref, "src/objnam.c"))
    m = re.search(r"handle some objects that are only allowed in wizard mode",
                  src(ref, "src/objnam.c"))
    start = flat.index("if (objects[")  # fallback anchor
    m = re.search(r"typ\s*&&\s*!wizard\)\s*\{\s*switch\s*\(\S*typ\)\s*\{",
                  re.sub(r"\s+", " ", flat))
    if not m:
        die("%s: wizard-mode substitution switch not found" % label)
    seg = re.sub(r"\s+", " ", flat)[m.end():]
    seg = seg[: seg.index("default:")]
    subs = []
    for mm in re.finditer(r"case\s+([A-Z_0-9]+):\s*\S*typ\s*=\s*([^;]+);", seg):
        frm, to = mm.group(1), mm.group(2).strip()
        rng = re.fullmatch(r"rnd_class\(\s*([A-Z_0-9]+)\s*,\s*([A-Z_0-9]+)\s*\)", to)
        if rng:
            got = "a random %s .. %s" % (sym_to_name.get(rng.group(1), rng.group(1)),
                                         sym_to_name.get(rng.group(2), rng.group(2)))
        else:
            got = sym_to_name.get(to, to)
        src_name = sym_to_name.get(frm, frm)
        subs.append(OrderedDict((("from", src_name), ("to", got))))
    if len(subs) < 5:
        die("%s: only %d wizard-mode substitutions found" % (label, len(subs)))
    return subs


# --------------------------------------------------------------------------
def main():
    head = subprocess.run(["git", "-C", REPO, "rev-parse", "HEAD"],
                          check=True, capture_output=True, text=True).stdout.strip()

    with open(OBJECTS_JSON, "r", encoding="utf-8") as f:
        objects_json = json.load(f)

    out_versions = OrderedDict()

    for key, cfg in VERSIONS.items():
        ref, also, label = cfg["ref"], cfg["also"], cfg["label"]
        print("\n[%s] %s" % (key, label))

        # 3.7 and 5.0 must actually agree about wishing, or the shared
        # dataset is a lie
        if also:
            for path, fn in (("src/objnam.c", "readobjnam"),
                             ("src/mkobj.c", "mksobj_init")):
                a = gen.strip_comments(src(also, path))
                b = gen.strip_comments(src(ref, path))
                fa = find_block(a, r"\n%s\(" % fn)
                fb = find_block(b, r"\n%s\(" % fn)
                same = re.sub(r"\s+", " ", fa) == re.sub(r"\s+", " ", fb)
                check(same, "%s() identical in 3.7 and 5.0 (%s)" % (fn, path))

        table = WishTable(src(ref, cfg["objtable"]), label)
        objs = table.objects()
        sym_to_name, derived_ok, derived_bad = OrderedDict(), 0, []
        for o in objs:
            guess = makedefs_obj_symbol(o)
            if o["_sn"]:
                sym_to_name.setdefault(o["_sn"], o["name"])
                if o["_sn"] == guess:
                    derived_ok += 1
                else:
                    derived_bad.append((o["name"], o["_sn"], guess))
            else:
                sym_to_name.setdefault(guess, o["name"])
        # 3.6 has no declared symbols, so the derivation above has to be
        # right; prove it against the version that does declare them
        if derived_ok or derived_bad:
            print("  makedefs symbol derivation reproduces %d/%d declared "
                  "enum names (exceptions: %s)"
                  % (derived_ok, derived_ok + len(derived_bad),
                     ", ".join(n for n, _, _ in derived_bad[:6]) or "none"))
        # the fake Amulet is the one entry makedefs special-cases by material
        sym_to_name.setdefault("FAKE_AMULET_OF_YENDOR",
                               "cheap plastic imitation of the Amulet of Yendor")

        mat = read_enum(ref, "include/objclass.h", "obj_material_types")
        skill = read_enum(ref, "include/skills.h", "p_skills")
        dirs = {"NODIR": 1, "IMMEDIATE": 2, "RAY": 3}

        flags = object_flags(objs, mat, skill, dirs, label)
        tool_spe, wand_spe, cursed_armor = parse_mksobj(ref, sym_to_name, label)
        arts = parse_artifacts(ref, sym_to_name, label)
        features, consts = constants(ref, label)
        subs = substitutions(ref, sym_to_name, label)
        cite = cites(ref, also, label)

        v = OrderedDict()
        v["label"] = label
        v["branch"] = ref or "NetHack-5.0 (working tree)"
        if also:
            v["also"] = also
        v["features"] = features
        v["consts"] = consts
        v["cites"] = cite
        v["substitutions"] = subs
        v["nowish"] = sorted(n for n, f in flags.items() if f.get("nws"))
        # oc_nowish is only reached by the `default:` arm of the switch, so
        # anything the switch substitutes first is not actually rejected
        subbed = {s["from"] for s in subs}
        v["nowish_rejected"] = [n for n in v["nowish"] if n not in subbed]
        v["tool_spe"] = tool_spe
        v["wand_spe"] = wand_spe
        v["cursed_armor"] = cursed_armor
        v["objects"] = flags
        v["artifacts"] = arts
        out_versions[key] = v

        print("  %d objects, %d artifacts, %d nowish, %d charged tools"
              % (len(flags), len(arts), len(v["nowish"]), len(tool_spe)))

    # ---------------- verification ----------------
    print("\nVerification:")
    for key, v in out_versions.items():
        names_here = set(v["objects"])
        names_there = {o["name"] for o in objects_json["versions"][key]["objects"]}
        # objects.json drops "strange object" (ILLOBJ) the same way we do
        check(names_here == names_there,
              "[%s] object names match data/objects.json (%d vs %d, diff %s)"
              % (key, len(names_here), len(names_there),
                 sorted(names_here ^ names_there)[:4] or "none"))

        f = v["objects"]
        check(f.get("arrow", {}).get("amo") == 1, "[%s] arrow is ammo" % key)
        check(f.get("dart", {}).get("mis") == 1, "[%s] dart is a missile" % key)
        check(f.get("dagger", {}).get("mis") is None,
              "[%s] a dagger is thrown but is not is_missile()" % key)
        check(f.get("unicorn horn", {}).get("wpt") == 1,
              "[%s] unicorn horn is a weptool" % key)
        check(f.get("towel", {}).get("wpt") is None,
              "[%s] towel is not a weptool" % key)
        check(f.get("wax candle", {}).get("cnd") == 1, "[%s] wax candle" % key)
        check(f.get("ring of increase damage", {}).get("chg") == 1,
              "[%s] ring of increase damage is charged" % key)
        check(f.get("ring of stealth", {}).get("chg") is None,
              "[%s] ring of stealth is not charged" % key)
        check(f.get("long sword", {}).get("ero") == 1,
              "[%s] long sword is erodeproofable" % key)
        check(f.get("elven mithril-coat", {}).get("ero") is None,
              "[%s] mithril is not erodeproofable" % key)
        check(f.get("crysknife", {}).get("epw") == "fixed",
              "[%s] crysknife takes 'fixed'" % key)
        check(f.get("long sword", {}).get("epw") == "rustproof",
              "[%s] long sword takes 'rustproof'" % key)
        check(f.get("elven cloak", {}).get("epw") == "fireproof",
              "[%s] elven cloak takes 'fireproof'" % key)
        check(f.get("arrow", {}).get("psn") == 1, "[%s] arrow is poisonable" % key)
        check(f.get("long sword", {}).get("psn") is None,
              "[%s] long sword is not poisonable" % key)
        check(f.get("wand of death", {}).get("dir") == "beam",
              "[%s] wand of death is a beam wand" % key)
        check(f.get("wand of wishing", {}).get("dir") == "nodir",
              "[%s] wand of wishing is NODIR" % key)
        check(any("venom" in n for n in v["nowish"]),
              "[%s] venom is nowish (%s)" % (key, v["nowish"]))
        check(f.get("Amulet of Yendor", {}).get("unq") == 1,
              "[%s] Amulet of Yendor is unique" % key)

        w = v["wand_spe"]
        check(w["beam"] == [4, 8], "[%s] beam wands roll 4..8 charges" % key)
        check(w["nodir"] == [11, 15], "[%s] NODIR wands roll 11..15 charges" % key)
        check(v["tool_spe"].get("magic marker") == [30, 99],
              "[%s] magic marker rolls 30..99 charges" % key)
        check(v["consts"]["gold_cap"] == 5000, "[%s] gold cap 5000" % key)
        check(v["consts"]["ench_die"] == 5, "[%s] enchantment roll is rnd(5)" % key)
        check(v["consts"]["bulk_count_cap"] == 20, "[%s] bulk count cap 20" % key)
        check(v["consts"]["candle_count_cap"] == 7, "[%s] candle count cap 7" % key)
        check("levitation boots" in v["cursed_armor"],
              "[%s] levitation boots are usually generated cursed (%s)"
              % (key, v["cursed_armor"]))

        byname = {a["name"]: a for a in v["artifacts"]}
        check(byname.get("Excalibur", {}).get("base") == "long sword",
              "[%s] Excalibur is a long sword" % key)
        check(byname.get("Excalibur", {}).get("nogen") is True,
              "[%s] Excalibur is SPFX_NOGEN" % key)
        check(byname.get("The Orb of Detection", {}).get("questrole")
              == "Archeologist",
              "[%s] Orb of Detection is the Archeologist quest artifact" % key)
        check(byname.get("The Palantir of Westernesse", {}).get("questrole")
              is None,
              "[%s] the Palantir is not any role's quest artifact" % key)
        check(byname.get("The Palantir of Westernesse", {}).get("inquestrange")
              is True,
              "[%s] the Palantir is inside the quest-artifact index range" % key)
        nq = sum(1 for a in v["artifacts"] if a.get("questrole"))
        check(nq == 13, "[%s] 13 roles have quest artifacts (got %d)" % (key, nq))

        subs = {s["from"]: s["to"] for s in v["substitutions"]}
        check(subs.get("Amulet of Yendor")
              == "cheap plastic imitation of the Amulet of Yendor",
              "[%s] Amulet of Yendor -> fake" % key)
        check(subs.get("Bell of Opening") == "bell",
              "[%s] Bell of Opening -> bell" % key)
        check(subs.get("magic lamp") == "oil lamp",
              "[%s] magic lamp -> oil lamp" % key)

    # version differences we advertise on the page
    a, b = out_versions["3.6"]["consts"], out_versions["3.7-5.0"]["consts"]
    check(a["spe_cap"] != b["spe_cap"],
          "3.6 (%s=%d) and 3.7/5.0 (%s=%d) cap requested spe differently"
          % (a["spe_cap_name"], a["spe_cap"], b["spe_cap_name"], b["spe_cap"]))
    check(out_versions["3.6"]["features"]["crystal_ball_cancels"] is False
          and out_versions["3.7-5.0"]["features"]["crystal_ball_cancels"] is True,
          "crystal ball joined the wand-like cancel rule in 3.7")
    check(out_versions["3.6"]["features"]["flint_stacks"] is False
          and out_versions["3.7-5.0"]["features"]["flint_stacks"] is True,
          "flint joined the bulk quantity list in 3.7")
    check(out_versions["3.6"]["tool_spe"].get("crystal ball")
          != out_versions["3.7-5.0"]["tool_spe"].get("crystal ball"),
          "crystal ball charge range changed between 3.6 and 3.7 (%s -> %s)"
          % (out_versions["3.6"]["tool_spe"].get("crystal ball"),
             out_versions["3.7-5.0"]["tool_spe"].get("crystal ball")))

    if failures:
        print("\n%d VERIFICATION FAILURE(S) -- not writing output" % len(failures))
        return 1

    out = OrderedDict()
    out["generated_from"] = OrderedDict((
        ("repo_commit", head),
        ("generated", datetime.date.today().isoformat()),
    ))
    out["versions"] = out_versions

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"), ensure_ascii=False)
    print("\nWrote %s (%d bytes)" % (OUT, os.path.getsize(OUT)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
