# alexmilea.com

Static mirror of [alexmilea.com](https://alexmilea.com) (Alex Milea Art portfolio),
migrated off Squarespace to **Cloudflare Pages** to eliminate ~$200/yr hosting cost.

The site is a frozen, fully self-contained static snapshot: no Squarespace runtime
JS, no external dependencies, all images self-hosted. It survives cancellation of the
Squarespace subscription.

## Structure

| Path | What |
|------|------|
| `site/` | The deployable static site (83 pages, 239 self-hosted full-res images). **This is the backup** — once Squarespace is cancelled it can't be re-scraped. |
| `site/assets/` | Localized images (`img/`), stylesheets (`css/`), fonts (`font/`). |
| `site/_redirects` | Cloudflare Pages redirects (`/drawings` → `/`). |
| `raw/` | Unprocessed rendered HTML from the original Squarespace site (kept for a future rebuild). |
| `capture.py` | The scraper/localizer that produced `site/` from `urls.txt`. Idempotent. |
| `optimize.py` | Post-processor: generates responsive WebP rungs (500/1000/1500w, q80) per image and rewires the srcset to real files. Idempotent. |
| `urls.txt` | Inventory of all 83 source URLs (2 text pages, 3 galleries, 78 project pages). |

## Pages

- Text: `/about`, `/contact`
- Galleries: `/` (Drawings), `/paintings`, `/mixed-techniques`
- 78 individual project pages under each gallery

## Regenerate (only possible while the Squarespace original is still live)

```sh
uv run capture.py            # all pages
uv run capture.py --sample   # one page of each type (fast check)
```

Renders each page headless (Squarespace lazy-loads gallery images via JS), strips the
Squarespace runtime, downloads every image at full resolution, and rewrites all
references to root-relative paths.

Then generate responsive image variants (run once on the built `site/`):

```sh
uv run optimize.py           # 500/1000/1500w WebP rungs + real srcset + LCP hints
```

The full-res 2500px originals are left untouched (pristine full-artwork view); only
the smaller rungs are re-encoded (q80). The first image on each page is marked
`eager`/`fetchpriority=high`, the rest stay lazy.

## Deploy

```sh
bunx wrangler pages deploy site --project-name=alexmilea --branch=main
```

Live preview: https://alexmilea.pages.dev

## Preview locally

```sh
cd site && python3 -m http.server 8765   # http://localhost:8765
```
