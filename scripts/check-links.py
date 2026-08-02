#!/usr/bin/env python3
"""Verify that every NetHackWiki link target used by the tools site actually exists.

Streams the gzipped MediaWiki XML dump line by line (never loads it into memory),
collecting every <title> and every "#REDIRECT [[Target]]" mapping. Then it walks
the data JSON files, pulls out every "page" value it can find, and reports any
target that is neither a real article title nor a redirect.

Usage:
    python3 scripts/check-links.py                 # check all known data files
    python3 scripts/check-links.py data/foo.json   # check specific files
    python3 scripts/check-links.py --dump-titles /tmp/titles.txt

Exits non-zero if any target is dead.
"""

import gzip
import html
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DUMP = os.path.join(
    os.path.dirname(ROOT), "dumps", "nethackwiki_current.xml.gz"
)

# Data files scanned by default. Add new JSON files here as the site grows;
# any file whose structure contains {"page": "..."} objects works as-is.
DATA_FILES = [
    "data/checklist.json",
]

TITLE_RE = re.compile(r"<title>(.*?)</title>")
# MediaWiki dumps mark redirect pages with a <redirect title="..." /> element
# right after <title>. That is authoritative; the wikitext scan below is a
# fallback for pages where the element is missing.
REDIRECT_EL_RE = re.compile(r'<redirect title="([^"]*)"')
# Only wikitext that *starts* with #REDIRECT makes a redirect page, so anchor on
# the opening of the <text> element. This keeps prose and <comment> lines that
# merely mention "#REDIRECT" from registering bogus mappings.
REDIRECT_RE = re.compile(
    r'<text\b[^>]*>\s*#REDIRECT\s*:?\s*(?:&nbsp;|\s)*'
    r'\[\[\s*([^\]|#]+?)\s*(?:[|#][^\]]*)?\]\]',
    re.I,
)


def norm(title):
    """Normalize a wiki title for comparison: underscores -> spaces, collapse
    whitespace, and upper-case the first letter (MediaWiki is first-letter
    case-insensitive)."""
    t = html.unescape(title).replace("_", " ").strip()
    t = re.sub(r"\s+", " ", t)
    if t:
        t = t[0].upper() + t[1:]
    return t


def load_dump(path):
    """Stream the dump. Returns (titles set, redirects dict src->dst), both
    normalized. Only mainspace-ish titles matter but we keep them all so that
    Category:/Help: targets validate too."""
    titles = set()
    redirects = {}
    current = None
    with gzip.open(path, "rt", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if "<title>" in line:
                m = TITLE_RE.search(line)
                if m:
                    current = norm(m.group(1))
                    titles.add(current)
                continue
            if "<redirect title=" in line:
                m = REDIRECT_EL_RE.search(line)
                if m and current:
                    redirects[current] = norm(m.group(1))
                continue
            if "#REDIRECT" in line or "#redirect" in line:
                m = REDIRECT_RE.search(line)
                if m and current and current not in redirects:
                    redirects[current] = norm(m.group(1))
    return titles, redirects


def collect_pages(obj, path="$", out=None):
    """Recursively pull every {"page": "..."} value out of a decoded JSON tree,
    recording where it came from so errors are actionable."""
    if out is None:
        out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "page" and isinstance(v, str):
                out.append((v, path))
            else:
                collect_pages(v, "%s.%s" % (path, k), out)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            collect_pages(v, "%s[%d]" % (path, i), out)
    return out


def check_terms(data, source):
    """Every links[].term must actually occur in its item's text, otherwise the
    substitution is a silent no-op. Returns a list of problem strings."""
    problems = []

    def pair(text, links, path, field):
        if not isinstance(text, str) or not isinstance(links, list):
            return
        for i, ln in enumerate(links):
            if not isinstance(ln, dict):
                continue
            term = ln.get("term")
            if isinstance(term, str) and term not in text:
                problems.append(
                    "%s: %s.%s[%d] term %r not found in text %r"
                    % (source, path, field, i, term, text)
                )

    def walk(node, path):
        if isinstance(node, dict):
            pair(node.get("text"), node.get("links"), path, "links")
            body = node.get("body")
            if isinstance(body, list):
                pair("\n".join(x for x in body if isinstance(x, str)),
                     node.get("bodyLinks"), path, "bodyLinks")
            for k, v in node.items():
                walk(v, "%s.%s" % (path, k))
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, "%s[%d]" % (path, i))

    walk(data, "$")
    return problems


def main(argv):
    args = list(argv[1:])
    dump_titles_to = None
    if "--dump-titles" in args:
        i = args.index("--dump-titles")
        dump_titles_to = args[i + 1]
        del args[i:i + 2]

    files = args or DATA_FILES
    files = [f if os.path.isabs(f) else os.path.join(ROOT, f) for f in files]

    if not os.path.exists(DUMP):
        print("ERROR: dump not found at %s" % DUMP, file=sys.stderr)
        return 2

    print("Reading %s ..." % DUMP)
    titles, redirects = load_dump(DUMP)
    print("  %d titles, %d redirects" % (len(titles), len(redirects)))

    if dump_titles_to:
        with open(dump_titles_to, "w", encoding="utf-8") as fh:
            for t in sorted(titles):
                fh.write(t + "\n")
        print("  wrote titles to %s" % dump_titles_to)

    dead = []
    via_redirect = []
    term_problems = []
    total = 0

    for f in files:
        if not os.path.exists(f):
            print("ERROR: no such data file: %s" % f, file=sys.stderr)
            return 2
        rel = os.path.relpath(f, ROOT)
        with open(f, encoding="utf-8") as fh:
            data = json.load(fh)
        term_problems.extend(check_terms(data, rel))
        pages = collect_pages(data)
        total += len(pages)
        for page, where in pages:
            n = norm(page)
            if n in redirects:
                dst = redirects[n]
                via_redirect.append((rel, page, dst, dst in titles))
                if dst not in titles:
                    dead.append((rel, where, page, "redirects to missing %r" % dst))
            elif n not in titles:
                dead.append((rel, where, page, "no such title"))

    print("\nChecked %d link targets across %d file(s)." % (total, len(files)))

    if via_redirect:
        print("\n%d target(s) resolve via redirect (OK, but not canonical):"
              % len(via_redirect))
        for rel, page, dst, ok in sorted(set(via_redirect)):
            print("  %-22s %-40s -> %s%s"
                  % (rel, page, dst.replace(" ", "_"), "" if ok else "  [BROKEN]"))

    if term_problems:
        print("\n%d link term(s) do not occur in their item text:" % len(term_problems))
        for p in term_problems:
            print("  " + p)

    if dead:
        print("\n%d DEAD link target(s):" % len(dead))
        for rel, where, page, why in dead:
            print("  %s %s: %r — %s" % (rel, where, page, why))
        return 1

    if term_problems:
        return 1

    print("\nAll link targets resolve. All link terms occur in their text.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
