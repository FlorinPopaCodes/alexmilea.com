#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow"]
# ///
"""Generate responsive WebP derivatives and rewire the (currently fake) srcset.

Operates in-place on the frozen `site/`. Squarespace's markup already declares a
srcset, but capture.py collapsed every candidate to the single 2500px file, so a
gallery thumbnail downloads the full ~3MB image. This:

  1. emits 500/1000/1500w WebP derivatives per source image (q80, no upscaling),
     leaving the full-res original byte-for-byte untouched (pristine artwork view);
  2. rewrites each <img>'s srcset/src to point at the real files;
  3. marks the first image on every page eager + fetchpriority=high (LCP).

Idempotent: derivatives are skipped if present; srcset is rebuilt from scratch
each run, so re-running is safe.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from PIL import Image

SITE = Path(__file__).parent / "site"
IMG = SITE / "assets" / "img"
RUNGS = [500, 1000, 1500]
QUALITY = 80
RUNG_RE = re.compile(r"-\d+\.webp$")  # marks an already-generated derivative


def generate() -> None:
    """Create downscaled WebP rungs for every source image."""
    sources = [
        p for p in IMG.glob("*.webp") if not RUNG_RE.search(p.name)
    ]
    made = skipped = 0
    saved = 0
    for src in sorted(sources):
        with Image.open(src) as im:
            w = im.width
            for r in RUNGS:
                if r >= w:  # never upscale
                    continue
                out = src.with_name(f"{src.stem}-{r}.webp")
                if out.exists():
                    skipped += 1
                    continue
                ratio = r / w
                resized = im.resize((r, round(im.height * ratio)), Image.LANCZOS)
                resized.save(out, "WEBP", quality=QUALITY, method=6)
                made += 1
                saved += src.stat().st_size - out.stat().st_size
    print(f"derivatives: {made} created, {skipped} present (~{saved/1048576:.0f}MB lighter than full-res)")


IMG_TAG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
SRC_RE = re.compile(r'(?<![-\w])src="/assets/img/([A-Za-z0-9]+)\.webp"')
WIDTH_RE = re.compile(r'\bwidth="(\d+)"')


def _build_srcset(stem: str, src_w: int) -> tuple[str, str]:
    """Return (srcset, fallback_src) using only rungs that actually exist."""
    cands: list[tuple[str, int]] = []
    for r in RUNGS:
        if r < src_w and (IMG / f"{stem}-{r}.webp").exists():
            cands.append((f"{stem}-{r}.webp", r))
    cands.append((f"{stem}.webp", src_w))  # original at its true width
    srcset = ", ".join(f"/assets/img/{name} {w}w" for name, w in cands)
    # fallback src: smallest candidate >= 1000, else the largest available
    mid = next((n for n, w in cands if w >= 1000), cands[-1][0])
    return srcset, f"/assets/img/{mid}"


def _rewrite_tag(tag: str, first: bool) -> str:
    m = SRC_RE.search(tag)
    if not m:
        return tag
    stem = m.group(1)
    wm = WIDTH_RE.search(tag)
    if not wm:
        return tag
    src_w = int(wm.group(1))
    srcset, fallback = _build_srcset(stem, src_w)

    # replace srcset value (attr always present in Squarespace markup)
    if 'srcset="' in tag:
        tag = re.sub(r'\bsrcset="[^"]*"', f'srcset="{srcset}"', tag, count=1)
    else:
        tag = tag[:-1] + f' srcset="{srcset}">'
    # point src at a sane fallback rung
    tag = SRC_RE.sub(f'src="{fallback}"', tag, count=1)

    # loading priority
    eager = first
    tag = re.sub(r'\bloading="[^"]*"', "", tag)
    tag = re.sub(r'\bfetchpriority="[^"]*"', "", tag)
    attrs = 'loading="eager" fetchpriority="high"' if eager else 'loading="lazy"'
    tag = tag[:-1].rstrip() + f" {attrs}>"
    # collapse any double spaces introduced
    return re.sub(r"\s{2,}", " ", tag)


def rewrite_html() -> None:
    pages = list(SITE.rglob("*.html"))
    touched = 0
    for page in pages:
        html = page.read_text(encoding="utf-8")
        seen = {"first": True}

        def repl(m: re.Match[str]) -> str:
            tag = _rewrite_tag(m.group(0), seen["first"])
            if SRC_RE.search(m.group(0)):
                seen["first"] = False
            return tag

        new = IMG_TAG_RE.sub(repl, html)
        if new != html:
            page.write_text(new, encoding="utf-8")
            touched += 1
    print(f"html: rewrote srcset/src + LCP hints across {touched}/{len(pages)} pages")


if __name__ == "__main__":
    if not IMG.is_dir():
        sys.exit(f"no image dir at {IMG}")
    generate()
    rewrite_html()
