#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["playwright", "httpx"]
# ///
"""Capture a Squarespace site as a self-contained static mirror.

Renders each URL with a headless browser (so lazy-loaded gallery images
populate), strips Squarespace runtime JS, downloads every CSS/font/image
locally at full resolution, and rewrites all references to root-relative
paths so the result survives Squarespace cancellation.

Usage:
  ./capture.py                 # all URLs in urls.txt
  ./capture.py --sample        # one page of each type (fast fidelity check)
  ./capture.py --limit 5
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import httpx
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).parent
RAW = ROOT / "raw"
SITE = ROOT / "site"
ASSETS = SITE / "assets"
SITE_HOST = "www.alexmilea.com"

ASSET_HOSTS = {
    "images.squarespace-cdn.com",
    "static1.squarespace.com",
    "use.typekit.net",
    "p.typekit.net",
    "fonts.gstatic.com",
    "fonts.googleapis.com",
}

# url regex for both http(s) and protocol-relative, stops at quote/space/paren/comma
URL_RE = re.compile(r"""(?:https?:)?//[^\s"'<>)]+""")
SCRIPT_RE = re.compile(r"<script\b([^>]*)>.*?</script>", re.DOTALL | re.IGNORECASE)
SCRIPT_SELFCLOSE_RE = re.compile(r"<script\b[^>]*/>", re.IGNORECASE)
# any squarespace-cdn content image referenced anywhere in the HTML
CDN_IMG_RE = re.compile(r"https://images\.squarespace-cdn\.com/content/[^\s\"'<>)]+")

# forces every lazy-loaded image visible once Squarespace's JS is removed
FREEZE_CSS = (
    "<style id=\"static-freeze\">"
    "img{opacity:1!important;transition:none!important;}"
    ".sqs-image,.sqs-image-content,.summary-thumbnail-image,img[data-src],"
    "img[data-load]{opacity:1!important;visibility:visible!important;}"
    ".floating-cart,#floatingCart,.sqs-custom-cart{display:none!important;}"
    "</style>"
)


def page_path(url: str) -> Path:
    p = urlparse(url).path
    if p in ("", "/"):
        return RAW / "index.html"
    return RAW / p.strip("/") / "index.html"


def out_path(url: str) -> Path:
    p = urlparse(url).path
    if p in ("", "/"):
        return SITE / "index.html"
    return SITE / p.strip("/") / "index.html"


def norm_url(u: str) -> str:
    if u.startswith("//"):
        u = "https:" + u
    u = u.replace("&amp;", "&")
    # truncate HTML/JSON-escaped junk that regex may have swallowed past the URL
    for stop in ('&quot;', '&#34;', '&#39;', '&apos;', '\\"', "\\'", '\\u', '\\'):
        i = u.find(stop)
        if i != -1:
            u = u[:i]
    return u.rstrip('\\"\';,')


def asset_kind(content_type: str, path: str) -> str | None:
    ct = (content_type or "").lower()
    ext = Path(urlparse(path).path).suffix.lower()
    if "css" in ct or ext == ".css":
        return "css"
    if "font" in ct or ext in (".woff", ".woff2", ".ttf", ".otf", ".eot"):
        return "font"
    if ct.startswith("image/") or ext in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico"):
        return "img"
    return None


def img_key(u: str) -> str:
    """Squarespace serves the same image at many ?format= sizes; key by path only."""
    pr = urlparse(norm_url(u))
    return pr.netloc + pr.path


def fulldl_url(u: str) -> str:
    """Force full-res for squarespace CDN images."""
    pr = urlparse(norm_url(u))
    if "squarespace-cdn.com" in pr.netloc and "/content/" in pr.path:
        return urlunparse(pr._replace(query="format=2500w"))
    return norm_url(u)


CT_EXT = {
    "image/webp": ".webp", "image/jpeg": ".jpg", "image/jpg": ".jpg",
    "image/png": ".png", "image/gif": ".gif", "image/svg+xml": ".svg",
    "text/css": ".css", "font/woff2": ".woff2", "font/woff": ".woff",
    "application/font-woff": ".woff", "font/ttf": ".ttf", "font/otf": ".otf",
}


def ext_for(content_type: str, src_url: str, kind: str) -> str:
    ct = (content_type or "").split(";")[0].strip().lower()
    if ct in CT_EXT:
        return CT_EXT[ct]
    e = Path(urlparse(src_url).path).suffix.lower()
    return e or {"css": ".css", "font": ".woff2", "img": ".jpg"}.get(kind, "")


def local_name(kind: str, key: str, ext: str) -> str:
    h = hashlib.md5(key.encode()).hexdigest()[:12]
    return f"assets/{kind}/{h}{ext}"


def render_all(urls: list[str]) -> dict:
    """Render each page, save raw HTML, collect asset URLs seen on the wire."""
    RAW.mkdir(parents=True, exist_ok=True)
    seen: dict[str, tuple[str, str]] = {}  # norm_url -> (kind, content_type)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            viewport={"width": 1440, "height": 1000},
            device_scale_factor=2,
            user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
        )

        def on_response(resp):
            try:
                url = norm_url(resp.url)
                pr = urlparse(url)
                if pr.netloc not in ASSET_HOSTS:
                    return
                kind = asset_kind(resp.headers.get("content-type", ""), url)
                if kind:
                    seen.setdefault(url, (kind, resp.headers.get("content-type", "")))
            except Exception:
                pass

        ctx.on("response", on_response)
        page = ctx.new_page()

        for i, url in enumerate(urls, 1):
            try:
                page.goto(url, wait_until="networkidle", timeout=60000)
            except Exception as e:
                print(f"  [{i}/{len(urls)}] WARN goto {url}: {str(e)[:80]}")
            # trigger lazy-load: scroll through the page
            try:
                page.evaluate("""async () => {
                    await new Promise(res => {
                        let y = 0; const step = 600;
                        const t = setInterval(() => {
                            window.scrollBy(0, step); y += step;
                            if (y >= document.body.scrollHeight) { clearInterval(t); res(); }
                        }, 80);
                    });
                }""")
                page.wait_for_timeout(1200)
                page.evaluate("window.scrollTo(0, 0)")
            except Exception:
                pass
            html = page.content()
            dest = page_path(url)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(html, encoding="utf-8")
            print(f"  [{i}/{len(urls)}] saved {dest.relative_to(ROOT)}  ({len(html)//1024}kb)")

        browser.close()
    return seen


def scan_html_images(seen: dict) -> None:
    """Add every CDN image referenced in captured HTML (not just network-fetched)."""
    before = sum(1 for v in seen.values() if v[0] == "img")
    for html in RAW.rglob("*.html"):
        text = html.read_text(encoding="utf-8", errors="ignore")
        for u in CDN_IMG_RE.findall(text):
            u = norm_url(u)
            seen.setdefault(u, ("img", "image/jpeg"))
    after = sum(1 for v in seen.values() if v[0] == "img")
    print(f"  scanned HTML: img refs {before} -> {after}")


def download_assets(seen: dict) -> tuple[dict, dict]:
    """Download assets; return (full_url->ref, img_path_key->ref)."""
    full_map: dict[str, str] = {}
    img_map: dict[str, str] = {}
    headers = {"User-Agent": "Mozilla/5.0", "Referer": f"https://{SITE_HOST}/"}

    # collapse image variants to one per path-key (highest res)
    img_targets: dict[str, str] = {}
    other_targets: list[tuple[str, str]] = []
    for url, (kind, _ct) in seen.items():
        if kind == "img":
            img_targets[img_key(url)] = url  # any variant; we force 2500w on download
        else:
            other_targets.append((kind, url))

    with httpx.Client(follow_redirects=True, timeout=60, headers=headers) as client:
        total = len(img_targets) + len(other_targets)
        n = 0
        def fetch(url: str, tries: int = 6):
            last = None
            for attempt in range(tries):
                try:
                    r = client.get(url)
                    r.raise_for_status()
                    return r
                except Exception as e:  # transient CDN throttling: backoff + retry
                    last = e
                    time.sleep(0.5 * (attempt + 1))
            raise last

        for key, url in img_targets.items():
            n += 1
            try:
                r = fetch(fulldl_url(url))
                ref = local_name("img", key, ext_for(r.headers.get("content-type"), url, "img"))
                dest = SITE / ref
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(r.content)
                img_map[key] = "/" + ref
                if n % 20 == 0 or n == total:
                    print(f"  asset {n}/{total} img {key.split('/')[-1][:40]} ({len(r.content)//1024}kb)")
            except Exception as e:
                print(f"  WARN img {url[:70]}: {str(e)[:60]}")
        for kind, url in other_targets:
            n += 1
            try:
                r = fetch(norm_url(url))
                ref = local_name(kind, norm_url(url), ext_for(r.headers.get("content-type"), url, kind))
                dest = SITE / ref
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(r.content)
                full_map[norm_url(url)] = "/" + ref
            except Exception as e:
                print(f"  WARN {kind} {url[:70]}: {str(e)[:60]}")
    return full_map, img_map


def localize(text: str, full_map: dict, img_map: dict) -> str:
    def repl(m: re.Match) -> str:
        raw = m.group(0)
        u = norm_url(raw)
        pr = urlparse(u)
        if pr.netloc == SITE_HOST:
            # internal link/asset -> root-relative path
            return pr.path or "/"
        if pr.netloc in ASSET_HOSTS:
            k = pr.netloc + pr.path
            if k in img_map:
                return img_map[k]
            if u in full_map:
                return full_map[u]
            # try stripping query for css/font matches
            base = urlunparse(pr._replace(query=""))
            if base in full_map:
                return full_map[base]
        return raw
    return URL_RE.sub(repl, text)


def strip_scripts(html: str) -> str:
    def keep_json(m: re.Match) -> str:
        attrs = m.group(1).lower()
        return m.group(0) if "json" in attrs else ""
    html = SCRIPT_RE.sub(keep_json, html)
    html = SCRIPT_SELFCLOSE_RE.sub("", html)
    return html


def rewrite_all(urls: list[str], full_map: dict, img_map: dict, keep_js: bool) -> None:
    for url in urls:
        raw = page_path(url)
        if not raw.exists():
            continue
        html = raw.read_text(encoding="utf-8")
        if not keep_js:
            html = strip_scripts(html)
            if "</head>" in html:
                html = html.replace("</head>", FREEZE_CSS + "</head>", 1)
        html = localize(html, full_map, img_map)
        dest = out_path(url)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(html, encoding="utf-8")
    # rewrite url() refs inside downloaded CSS
    for css in (ASSETS / "css").glob("*.css") if (ASSETS / "css").exists() else []:
        txt = css.read_text(encoding="utf-8", errors="ignore")
        css.write_text(localize(txt, full_map, img_map), encoding="utf-8")
    print(f"  rewrote {len(urls)} pages + css")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--urls", default="urls.txt")
    ap.add_argument("--sample", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--keep-js", action="store_true")
    ap.add_argument("--no-render", action="store_true",
                    help="skip rendering; re-download+rewrite from existing raw/")
    args = ap.parse_args()

    urls = [l.strip() for l in (ROOT / args.urls).read_text().splitlines() if l.strip()]
    if args.sample:
        # home, a painting, a mixed, about, contact, one drawing
        want = ["/", "/about", "/contact"]
        picked = [u for u in urls if urlparse(u).path in want]
        for frag in ("/drawings/", "/paintings/project", "/mixed-techniques/project"):
            nxt = next((u for u in urls if frag in u), None)
            if nxt:
                picked.append(nxt)
        urls = picked
    if args.limit:
        urls = urls[: args.limit]

    if args.no_render:
        seen = {}
        print("== skipping render (using existing raw/) ==")
    else:
        print(f"== rendering {len(urls)} pages ==")
        seen = render_all(urls)
    print("== scanning HTML for all image refs ==")
    scan_html_images(seen)
    print(f"== {len(seen)} unique assets; downloading ==")
    full_map, img_map = download_assets(seen)
    print(f"== rewriting ({len(img_map)} imgs, {len(full_map)} other), keep_js={args.keep_js} ==")
    rewrite_all(urls, full_map, img_map, args.keep_js)
    # root-relative assets Squarespace serves from the site itself (kept at same path)
    with httpx.Client(follow_redirects=True, timeout=30,
                      headers={"User-Agent": "Mozilla/5.0"}) as c:
        for rel in ("/universal/svg/social-accounts.svg",):
            try:
                r = c.get(f"https://{SITE_HOST}{rel}"); r.raise_for_status()
                dest = SITE / rel.lstrip("/"); dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(r.content); print(f"  root asset {rel} ({len(r.content)}b)")
            except Exception as e:
                print(f"  WARN root {rel}: {str(e)[:60]}")
    print("DONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
