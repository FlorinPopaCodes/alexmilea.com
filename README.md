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

## Deploy

```sh
bunx wrangler pages deploy site --project-name=alexmilea --branch=main
```

Live preview: https://alexmilea.pages.dev

## Preview locally

```sh
cd site && python3 -m http.server 8765   # http://localhost:8765
```
