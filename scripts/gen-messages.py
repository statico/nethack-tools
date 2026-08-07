#!/usr/bin/env python3
"""Generate tools/data/messages.json from the NetHackWiki XML dump + the NetHack source tree.

The wiki keeps two curated disambiguation pages, [[You feel]] and [[You hear]], each a list
of {{message|text|explanation}} entries grouped under == headings ==. Every entry already has
a hand-written explanation and wikilinks, which is what makes these two pages usable as a
lookup tool instead of a raw grep over 16k source string literals.

This script does the deterministic half: parse the wiki markup into structured entries,
normalize it to HTML, and merge in a source-verification sidecar. *Finding* a message's
emitting call site from its wiki wording is unbounded reading of C control flow around format
strings ("%s slurping sound%s." needs the singular/plural call sites both found), which is why
that step is done by fanned-out agents and handed to this script as
scripts/messages-verification.json: a flat list of {id, versions} objects (forward
verification, keyed to --extract-only's output) plus, for messages found by sweeping the
source for You_feel()/You_hear() call sites with no matching wiki entry, full new entries
carrying their own {id, prefix, text, explanation_html, versions}.

Once a call site *is* known in one branch, though, checking the other branch for it stops
being open-ended: the 5.0 citation hands us the exact C string literal, and locating that
literal in 3.7 is a plain search. backfill_3_7() does that pass, which is what keeps the
5.0-only reverse sweep from leaving ~190 entries permanently "unverified" for 3.7.

Usage:
    python3 scripts/gen-messages.py --extract-only   # dump raw entries, no verification needed
    python3 scripts/gen-messages.py                  # full build, requires the verification sidecar
"""

from __future__ import annotations

import argparse
import datetime
import gzip
import html
import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
NETHACK = os.path.join(ROOT, "NetHack")
DUMP = os.path.join(ROOT, "dumps", "nethackwiki_current.xml.gz")
HERE = os.path.dirname(os.path.abspath(__file__))
VERIFICATION = os.path.join(HERE, "messages-verification.json")
RAW_OUT = os.path.join(HERE, "messages-raw.json")
OUT = os.path.join(ROOT, "tools", "data", "messages.json")

PAGES = ("You feel", "You hear")
BRANCHES = {"3.7": "origin/NetHack-3.7", "5.0": "origin/NetHack-5.0"}

# A handful of entries whose meaning we already know cold, used as a sanity check that
# extraction + verification didn't silently drop or garble anything.
KNOWN_ANCHORS = {
    "you-feel": [
        "You feel shuddering vibrations.",
        "You feel very firm.",
    ],
    "you-hear": [
        "You hear the footsteps of a guard on patrol.",
        "You hear someone counting money.",
    ],
}


# --------------------------------------------------------------------------- wiki dump access
def load_pages():
    pages = {}
    with gzip.open(DUMP, "rt", encoding="utf-8", errors="replace") as f:
        for _, el in ET.iterparse(f, events=("end",)):
            if el.tag.split("}")[-1] != "page":
                continue
            title = el.findtext(".//{*}title") or ""
            if title in PAGES:
                pages[title] = el.findtext(".//{*}revision/{*}text") or ""
            el.clear()
    missing = [p for p in PAGES if p not in pages]
    if missing:
        raise SystemExit(f"missing wiki pages in dump: {missing}")
    return pages


def git_head(ref):
    return subprocess.run(
        ["git", "-C", NETHACK, "rev-parse", ref], check=True, capture_output=True, text=True
    ).stdout.strip()


# --------------------------------------------------------------------------- source tree access
_tree_cache = {}


def source_tree(branch):
    """{path: [lines]} for every src/*.c and include/*.h at the pinned commit of `branch`.
    Read out of git rather than the working tree so a build never depends on which branch
    happens to be checked out."""
    if branch in _tree_cache:
        return _tree_cache[branch]
    ref = BRANCHES[branch]
    names = subprocess.run(
        ["git", "-C", NETHACK, "ls-tree", "-r", "--name-only", ref],
        check=True, capture_output=True, text=True,
    ).stdout.split("\n")
    wanted = [n for n in names if re.fullmatch(r"(src/.*\.c|include/.*\.h)", n)]
    tree = {}
    for name in wanted:
        blob = subprocess.run(
            ["git", "-C", NETHACK, "show", f"{ref}:{name}"],
            check=True, capture_output=True, text=True, errors="replace",
        ).stdout
        tree[name] = blob.split("\n")
    _tree_cache[branch] = tree
    return tree


C_STRING_RE = re.compile(r'"((?:[^"\\]|\\.)*)"')


def _wordiness(q):
    """Letters left once printf specifiers are removed, used to rank candidates by how much
    actual prose they carry. "%s %s." scores 0 and can locate nothing; "slower." scores 6;
    "less %s!" scores 4 and is still perfectly locatable, since the specifier is searched
    for literally too. The acceptance bar is deliberately low — find_literal()'s
    ambiguous-across-files guard is what actually keeps a vague candidate from matching the
    wrong call site."""
    return len(re.sub(r"[^a-zA-Z]", "", re.sub(r"%[-0-9.]*[a-zA-Z]", "", q)))


def call_site_literals(branch, path, line):
    """Usable C string literals on the cited line and the two continuation lines after it,
    most distinctive first. A multi-line call like
        You_hear("%s %s.", (confused || scursed) ? "sad wailing"
                 : "maniacal laughter", ...);
    keeps its best literal off the first line, so don't stop at line 1 — and return all of
    them rather than just the best, because the wordiest one is not always the one that
    survives into the other branch."""
    tree = source_tree(branch)
    src = tree.get(path)
    if not src or not (1 <= line <= len(src)):
        return []
    quoted = []
    for i in range(line - 1, min(len(src), line + 2)):
        for q in C_STRING_RE.findall(src[i]):
            if _wordiness(q) >= 3 and q not in quoted:
                quoted.append(q)
    return sorted(quoted, key=_wordiness, reverse=True)


def find_literal(branch, literal, prefer_file=None, near_line=None):
    """(path, line) of `literal` in `branch`, or None. Prefers the file the other branch
    put it in — the same string can legitimately appear at several call sites (e.g. two
    "an explosion" sites), and the sibling branch's file is by far the best tiebreaker."""
    tree = source_tree(branch)
    hits = []
    for path, src in tree.items():
        for i, text in enumerate(src):
            if literal in text:
                hits.append((path, i + 1))
    if not hits:
        return None
    same = [h for h in hits if h[0] == prefer_file]
    if same:
        if near_line is not None:
            return min(same, key=lambda h: abs(h[1] - near_line))
        return same[0]
    if len({h[0] for h in hits}) == 1:
        return hits[0]
    return None  # ambiguous across files with no hint from the other branch; stay unverified


def backfill_3_7(entries):
    """Resolve entries left 'unverified' for 3.7 by looking up their 5.0 call site's string
    literal in the 3.7 tree. Only ever promotes unverified -> present; a miss is left alone
    rather than downgraded to 'absent', since not finding the literal here means the search
    was inconclusive, not that the message is known to be gone."""
    filled = missed = 0
    for e in entries:
        v37 = e.get("versions", {}).get("3.7", {})
        v50 = e.get("versions", {}).get("5.0", {})
        if v37.get("status") != "unverified" or v50.get("status") != "present":
            continue
        hit = literal = None
        for cand in call_site_literals("5.0", v50.get("file", ""), v50.get("line", 0)):
            hit = find_literal("3.7", cand, v50.get("file"), v50.get("line"))
            if hit:
                literal = cand
                break
        if not hit:
            missed += 1
            v37["note"] = (
                "not found in 3.7 by literal backfill; the 5.0 call site's string literal "
                "could not be located unambiguously, so 3.7 remains unchecked"
            )
            continue
        path, line = hit
        e["versions"]["3.7"] = {
            "status": "present",
            "file": path,
            "line": line,
            "literal": literal,
            "via": "literal-backfill from the 5.0 call site",
        }
        filled += 1
    return filled, missed


# --------------------------------------------------------------------------- wikitext -> HTML
LINK_RE = re.compile(r"\[\[([^\]|#]*)(?:#([^\]|]*))?(?:\|([^\]]*))?\]\]")
WIKIPEDIA_RE = re.compile(r"\[\[wikipedia:([^\]|#]+)(?:#[^\]|]*)?(?:\|([^\]]*))?\]\]")
BOLD_RE = re.compile(r"'''(.+?)'''")
ITALIC_RE = re.compile(r"''(.+?)''")
FRAC_RE = re.compile(r"\{\{frac\|(\d+)(?:\|(\d+))?\}\}")
TT_RE = re.compile(r"<tt>(.*?)</tt>", re.S)
TEMPLATE_RE = re.compile(r"\{\{[^{}]*\}\}")  # leftover unhandled templates, dropped

WIKI_BASE = "https://nethackwiki.com/wiki/"


def wiki_url(title):
    return WIKI_BASE + title.strip().replace(" ", "_")


def strip_links_plain(wikitext):
    """Message *text* fields are sometimes themselves wrapped in a wikilink to that
    message's own page (e.g. "[[You feel shuddering vibrations]]"). Unwrap to plain
    text — this is display text, not HTML, so no <a> tags here."""
    s = WIKIPEDIA_RE.sub(lambda m: (m.group(2) or m.group(1)).strip(), wikitext)
    s = LINK_RE.sub(lambda m: (m.group(3) or m.group(1) or m.group(2) or "").strip(), s)
    s = BOLD_RE.sub(r"\1", s)
    s = ITALIC_RE.sub(r"\1", s)
    s = s.replace("&minus;", "−").replace("&ndash;", "–").replace("&nbsp;", " ")
    s = re.sub(r"'{2,}", "", s)  # stray/unpaired '' or ''' left over from source typos
    return s.strip()


def extract_links(wikitext, page=None):
    """Collect {title, label} for every [[...]] link before the markup is thrown away."""
    links = []
    for m in WIKIPEDIA_RE.finditer(wikitext):
        target, label = m.group(1), m.group(2)
        links.append({"title": "wikipedia:" + target.strip(), "label": (label or target).strip()})
    stripped = WIKIPEDIA_RE.sub("", wikitext)
    for m in LINK_RE.finditer(stripped):
        target, anchor, label = m.group(1).strip(), m.group(2), m.group(3)
        title = target or (page or "")  # same-page anchor link, e.g. [[#Magic traps|...]]
        display_label = (label or target or anchor or "").strip()
        if not display_label:
            continue
        links.append({"title": title, "label": display_label})
    return links


def wikitext_to_html(wikitext, page=None):
    if not wikitext:
        return ""
    s = wikitext

    def frac_sub(m):
        num, den = m.group(1), m.group(2)
        return f"{num}/{den}" if den else f"1/{num}"

    s = FRAC_RE.sub(frac_sub, s)
    s = s.replace("&minus;", "−").replace("&ndash;", "–").replace("&nbsp;", " ")
    s = TEMPLATE_RE.sub("", s)  # {{refsrc|...}} and similar cite templates: drop, not shown here

    def wikipedia_sub(m):
        target, label = m.group(1), m.group(2)
        text = html.escape((label or target).strip())
        return f'<a href="https://en.wikipedia.org/wiki/{target.strip().replace(" ", "_")}">{text}</a>'

    s = WIKIPEDIA_RE.sub(wikipedia_sub, s)

    def link_sub(m):
        target, anchor, label = m.group(1).strip(), m.group(2), m.group(3)
        title = target or (page or "")  # same-page anchor link
        text = html.escape((label or target or anchor or "").strip())
        href = wiki_url(title) + (f"#{anchor.strip().replace(' ', '_')}" if anchor else "")
        return f'<a href="{href}">{text}</a>'

    s = LINK_RE.sub(link_sub, s)
    s = BOLD_RE.sub(r"<strong>\1</strong>", s)
    s = ITALIC_RE.sub(r"<em>\1</em>", s)
    s = TT_RE.sub(r"<code>\1</code>", s)
    s = re.sub(r"'{2,}", "", s)  # stray/unpaired '' or ''' left over from source typos
    s = s.replace("<br>", "<br>\n")
    return s.strip()


# --------------------------------------------------------------------------- entry extraction
HEADING_RE = re.compile(r"^(={2,6})\s*(.+?)\s*\1\s*$", re.M)
MESSAGE_START_RE = re.compile(r"\{\{message\|")


def find_messages(body):
    """{{message|...}} bodies routinely nest other {{templates}} (e.g. {{frac|10}}) and
    [[links]], so a regex terminating on the first "}}" truncates at the nested template's
    close instead of the outer one. Scan by brace depth instead, matching split_message_field's
    own [[ ]] / {{ }} depth tracking so the two stay consistent."""
    for start_m in MESSAGE_START_RE.finditer(body):
        i = start_m.end()
        depth = 1  # already inside the outer {{ from "{{message|"
        n = len(body)
        while i < n and depth > 0:
            two = body[i : i + 2]
            if two in ("[[", "{{"):
                depth += 1
                i += 2
            elif two in ("]]", "}}"):
                depth -= 1
                i += 2
            else:
                i += 1
        if depth != 0:
            continue  # unterminated template near end of body; skip rather than guess
        yield body[start_m.end() : i - 2]


def split_sections(wikitext):
    """Yield (heading_path, body_text) for every heading-delimited chunk, deepest-first
    heading stack tracked by '=' count. Text before the first heading has path []."""
    marks = [(m.start(), m.end(), len(m.group(1)), m.group(2)) for m in HEADING_RE.finditer(wikitext)]

    preamble_end = marks[0][0] if marks else len(wikitext)
    yield [], wikitext[:preamble_end]

    stack = []  # list of (level, title)
    for i, (_start, end, level, title) in enumerate(marks):
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, title))
        body_end = marks[i + 1][0] if i + 1 < len(marks) else len(wikitext)
        yield [t for _, t in stack], wikitext[end:body_end]


def split_message_field(field):
    """A {{message|...}} field can itself contain [[...|...]] and {{frac|..}} which use the
    same | and }} delimiters as the template. Split top-level |, respecting [[ ]] / {{ }} depth."""
    parts = []
    depth = 0
    buf = []
    i = 0
    n = len(field)
    while i < n:
        c = field[i]
        two = field[i : i + 2]
        if two in ("[[", "{{"):
            depth += 1
            buf.append(two)
            i += 2
            continue
        if two in ("]]", "}}"):
            depth -= 1
            buf.append(two)
            i += 2
            continue
        if c == "|" and depth == 0:
            parts.append("".join(buf))
            buf = []
            i += 1
            continue
        buf.append(c)
        i += 1
    parts.append("".join(buf))
    return parts


def slugify(prefix, n):
    return f"{prefix}-{n:03d}"


def norm_text(s):
    """Lowercase, punctuation-light form used for search matching, kept separate from the
    display text so <placeholder> markup and capitalization survive for rendering."""
    s = re.sub(r"<[^>]*>", " ", s)
    s = re.sub(r"[^a-z0-9 ]+", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


def extract_page(page_title, prefix, wikitext):
    entries = []
    n = 0
    for path, body in split_sections(wikitext):
        for msg_body in find_messages(body):
            fields = split_message_field(msg_body)
            raw_text = strip_links_plain(fields[0].strip())
            raw_expl = fields[1].strip() if len(fields) > 1 else ""
            if not raw_text:
                continue
            n += 1
            # A few entries pack more than one literal variant separated by <br>; keep the
            # first as the canonical display text and record the rest as alt phrasings so
            # search still matches them without duplicating the explanation.
            variants = [v.strip() for v in raw_text.split("<br>") if v.strip()]
            text = variants[0]
            alt_texts = variants[1:]
            entries.append(
                {
                    "id": slugify(prefix, n),
                    "prefix": prefix,
                    "text": text,
                    "text_norm": norm_text(text),
                    "alt_texts": alt_texts,
                    "category": path,
                    "explanation_html": wikitext_to_html(raw_expl, page=page_title),
                    "explanation_norm": norm_text(
                        re.sub(r"<[^>]*>", " ", wikitext_to_html(raw_expl, page=page_title))
                    ),
                    "wiki_links": extract_links(raw_expl, page=page_title),
                    "source_page": page_title,
                }
            )
    return entries


def backfill_shared_explanations(entries):
    """A few adjacent {{message}} entries under the same heading are randomized flavor
    variants of one event (e.g. "a slow drip" / "a gurgling noise" / "dishes being
    washed" are all just "there's a sink on the level") and the wiki only states the
    explanation once, on the last variant. Forward-fill blanks from the next explained
    entry in the same category so nothing renders with an empty explanation."""
    by_cat = {}
    for e in entries:
        by_cat.setdefault(tuple(e["category"]), []).append(e)
    for group in by_cat.values():
        pending = []
        for e in group:
            if not e["explanation_html"]:
                pending.append(e)
                continue
            for p in pending:
                p["explanation_html"] = e["explanation_html"] + " (same cause as the next listed message.)"
                p["explanation_norm"] = norm_text(re.sub(r"<[^>]*>", " ", p["explanation_html"]))
                p["wiki_links"] = e["wiki_links"]
            pending = []


def extract_all():
    pages = load_pages()
    entries = []
    entries += extract_page("You feel", "you-feel", pages["You feel"])
    entries += extract_page("You hear", "you-hear", pages["You hear"])
    backfill_shared_explanations(entries)
    return entries


# --------------------------------------------------------------------------- main
def check_anchors(entries):
    by_prefix = {}
    for e in entries:
        by_prefix.setdefault(e["prefix"], set()).add(e["text"])
    bad = []
    for prefix, wanted in KNOWN_ANCHORS.items():
        for w in wanted:
            if w not in by_prefix.get(prefix, set()):
                bad.append((prefix, w))
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--extract-only", action="store_true", help="write messages-raw.json and stop")
    args = ap.parse_args()

    entries = extract_all()
    print(f"extracted {len(entries)} entries "
          f"({sum(1 for e in entries if e['prefix']=='you-feel')} you-feel, "
          f"{sum(1 for e in entries if e['prefix']=='you-hear')} you-hear)")

    bad = check_anchors(entries)
    if bad:
        raise SystemExit(f"known-anchor check failed, missing: {bad}")
    print("[PASS] known anchors present")

    empty_expl = [e["id"] for e in entries if not e["explanation_html"]]
    if empty_expl:
        print(f"[WARN] {len(empty_expl)} entries have no explanation: {empty_expl[:10]}")

    if args.extract_only:
        with open(RAW_OUT, "w", encoding="utf-8") as fh:
            json.dump(entries, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        print(f"wrote {RAW_OUT} ({os.path.getsize(RAW_OUT)} bytes)")
        return 0

    if not os.path.exists(VERIFICATION):
        raise SystemExit(
            f"{VERIFICATION} not found — run with --extract-only first, "
            "fan out verification agents over messages-raw.json, then rerun without --extract-only"
        )
    with open(VERIFICATION, "r", encoding="utf-8") as fh:
        verification = json.load(fh)

    by_id = {v["id"]: v for v in verification["entries"]}
    missing_v = [e["id"] for e in entries if e["id"] not in by_id]
    if missing_v:
        raise SystemExit(f"verification sidecar missing {len(missing_v)} ids: {missing_v[:10]}")

    unverified_count = 0
    for e in entries:
        v = by_id[e["id"]]
        e["versions"] = v["versions"]
        for branch, info in v["versions"].items():
            if info["status"] == "unverified":
                unverified_count += 1
                break

    # sorted(), not set order: Python randomizes string hashing per process, so iterating the
    # set directly reshuffled these 190 entries on every run and made data/messages.json diff
    # by thousands of lines without a single content change.
    extra_ids = sorted(set(by_id) - {e["id"] for e in entries})
    new_entries = [by_id[i] for i in extra_ids if by_id[i].get("prefix") in ("you-feel", "you-hear")]
    for e in new_entries:
        e.setdefault("text_norm", norm_text(e["text"]))
        e.setdefault("alt_texts", [])
        e.setdefault("category", e.get("category", []))
        e.setdefault("explanation_norm", norm_text(re.sub(r"<[^>]*>", " ", e.get("explanation_html", ""))))
        e.setdefault("wiki_links", [])
        e.setdefault("source_page", None)
    entries += new_entries
    if new_entries:
        print(f"[INFO] {len(new_entries)} 5.0-only entries added from the reverse sweep")

    print(f"[INFO] {unverified_count} entries have at least one unverified branch "
          "before the 3.7 backfill")
    filled, missed = backfill_3_7(entries)
    print(f"[INFO] 3.7 backfill resolved {filled} entries by literal lookup, "
          f"{missed} left unverified")

    still_unverified = sum(
        1 for e in entries if any(i["status"] == "unverified" for i in e["versions"].values())
    )
    print(f"[INFO] {still_unverified} entries still have an unverified branch")

    doc = {
        "generated_from": {
            "repo_commit_3_7": git_head(BRANCHES["3.7"]),
            "repo_commit_5_0": git_head(BRANCHES["5.0"]),
            "dump": "nethackwiki_current.xml.gz",
            "generated": datetime.date.today().isoformat(),
        },
        "entries": entries,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print(f"wrote {OUT} ({os.path.getsize(OUT)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
