#!/usr/bin/env python3
"""Generate assets/og/*.png — the 1200x630 social cards referenced by each page's og:image.

Content is read out of the pages themselves (<title> and og:description) rather than kept in a
second list here, so a card can't drift from the page it represents. Rendered with ImageMagick
drawing commands rather than SVG: the local ImageMagick has no rsvg delegate, so SVG text would
fall back to its internal renderer and lose the mono font entirely.

Usage:
    python3 scripts/gen-og-images.py          # write assets/og/*.png
    python3 scripts/gen-og-images.py --check  # verify every page has a card, write nothing
"""

from __future__ import annotations

import argparse
import glob
import html
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.dirname(HERE)
OUT_DIR = os.path.join(SITE, "assets", "og")

W, H = 1200, 630
MARGIN = 76

# Nord, matching assets/smui.css dark mode.
BG = "#191D24"        # --surface-0 dark
PANEL = "#212630"     # --surface-1 dark
LINE = "#3B4252"      # --line dark
TEXT_0 = "#E5E9F0"
TEXT_1 = "#BFC7D5"
FROST_2 = "#88C0D0"   # --accent

# JetBrains Mono is what the site loads; fall back to what macOS ships.
FONT_CANDIDATES = [
    os.path.expanduser("~/Library/Fonts/JetBrainsMono-Regular.ttf"),
    "/Library/Fonts/JetBrainsMono-Regular.ttf",
    "/System/Library/Fonts/Menlo.ttc",
    "/System/Library/Fonts/SFNSMono.ttf",
]


def pick_font():
    for f in FONT_CANDIDATES:
        if os.path.exists(f):
            return f
    raise SystemExit(f"no usable mono font found, tried: {FONT_CANDIDATES}")


TITLE_RE = re.compile(r"<title>(.*?)</title>", re.S | re.I)
OG_DESC_RE = re.compile(r'<meta\s+property="og:description"\s+content="(.*?)"', re.S | re.I)
DESC_RE = re.compile(r'<meta\s+name="description"\s+content="(.*?)"', re.S | re.I)

SUFFIX = re.compile(r"\s*[—-]\s*statico's NetHack Tools\s*$")


def page_meta(path):
    src = open(path, encoding="utf-8").read()
    t = TITLE_RE.search(src)
    d = OG_DESC_RE.search(src) or DESC_RE.search(src)
    if not t:
        raise SystemExit(f"{os.path.basename(path)}: no <title>")
    if not d:
        raise SystemExit(f"{os.path.basename(path)}: no og:description or description")
    title = SUFFIX.sub("", html.unescape(t.group(1)).strip())
    desc = html.unescape(d.group(1)).strip()
    # index.html's title IS the suffix; give it its own headline.
    if not title or title == "statico's NetHack Tools":
        title = "NetHack Tools"
    return title, desc


def wrap(text, width):
    """Greedy wrap by character count — safe here because the font is monospaced."""
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if len(trial) <= width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def render(slug, title, desc, font, out_path):
    title_lines = wrap(title, 30)[:2]
    desc_lines = wrap(desc, 58)[:3]
    if len(wrap(desc, 58)) > 3:
        desc_lines[-1] = desc_lines[-1].rstrip(".,;") + "…"

    args = [
        "magick", "-size", f"{W}x{H}", f"xc:{BG}",
        # inset panel + hairline border, zero radius to match the site's terminal look
        "-fill", PANEL, "-stroke", LINE, "-strokewidth", "2",
        "-draw", f"rectangle 40,40 {W - 40},{H - 40}",
        "-stroke", "none", "-font", font,
    ]

    # site name, accent, top of the panel
    args += ["-fill", FROST_2, "-pointsize", "26",
             "-annotate", f"+{MARGIN}+{MARGIN + 44}", "nethack.statico.io"]
    # rule under it
    args += ["-fill", LINE,
             "-draw", f"rectangle {MARGIN},{MARGIN + 72} {W - MARGIN},{MARGIN + 74}"]

    y = MARGIN + 168
    args += ["-fill", TEXT_0, "-pointsize", "56"]
    for line in title_lines:
        args += ["-annotate", f"+{MARGIN}+{y}", line]
        y += 70

    # Bottom-anchor the description so a two-line title can't push it into the footer;
    # the gap after the title absorbs the difference instead.
    footer_y = H - MARGIN - 8
    desc_bottom = footer_y - 62
    args += ["-fill", TEXT_1, "-pointsize", "25"]
    for n, line in enumerate(desc_lines):
        ly = desc_bottom - (len(desc_lines) - 1 - n) * 40
        args += ["-annotate", f"+{MARGIN}+{ly}", line]

    args += ["-fill", FROST_2, "-pointsize", "24",
             "-annotate", f"+{MARGIN}+{footer_y}", "NetHack 3.6 · 3.7 · 5.0"]
    args += [out_path]
    subprocess.run(args, check=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="verify cards exist, write nothing")
    args = ap.parse_args()

    pages = sorted(glob.glob(os.path.join(SITE, "*.html")))
    if not pages:
        raise SystemExit("no pages found")

    if args.check:
        missing = []
        for p in pages:
            slug = os.path.splitext(os.path.basename(p))[0]
            if not os.path.exists(os.path.join(OUT_DIR, f"{slug}.png")):
                missing.append(slug)
        if missing:
            raise SystemExit(f"missing OG cards for: {missing}")
        print(f"[PASS] all {len(pages)} pages have an OG card")
        return 0

    if not shutil.which("magick"):
        raise SystemExit("ImageMagick 'magick' not on PATH")
    font = pick_font()
    print(f"font: {font}")
    os.makedirs(OUT_DIR, exist_ok=True)

    for p in pages:
        slug = os.path.splitext(os.path.basename(p))[0]
        title, desc = page_meta(p)
        out = os.path.join(OUT_DIR, f"{slug}.png")
        render(slug, title, desc, font, out)
        print(f"  {slug}.png  {title!r}")

    print(f"wrote {len(pages)} cards to {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
