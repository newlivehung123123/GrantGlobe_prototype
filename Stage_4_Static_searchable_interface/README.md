# GrantGlobe — Static Searchable Interface (Stage 4)

## What this is

A zero-backend, statically served searchable interface for the GrantGlobe grant database.
All filtering and fuzzy search run in the browser; the page can be served from GitHub Pages
at zero hosting cost. No Node.js build step is required.

## Prerequisites

- Python 3.10+
- `psycopg2-binary` and `python-dotenv` installed (`pip install psycopg2-binary python-dotenv`)
- A running PostgreSQL instance with the Stage 3 `grants` table populated
- `DATABASE_URL` environment variable set (e.g. in a `.env` file in this directory)

## Step 1 — Export grant data

Run the export script from this directory:

    python export_grants.py

This queries the database and writes `data/grants.json`. By default, grants with
`current_status = 'Closed'` are excluded. To include them:

    python export_grants.py --include-closed

The JSON file is the sole data dependency of the static interface.

## Step 2 — Preview locally

Serve the directory with Python's built-in HTTP server:

    python -m http.server 8000

Then open http://localhost:8000 in a browser. Do NOT open index.html directly from the
filesystem — the `fetch()` call for `data/grants.json` will fail under the `file://` protocol.

## Step 3 — Deploy to GitHub Pages

1. Push this directory (including `data/grants.json`) to a GitHub repository.
2. In the repository Settings → Pages, set the source to the branch and folder containing
   this directory.
3. GitHub Pages will serve `index.html` as the root page. The `.nojekyll` file ensures
   the pipeline does not interfere with the static files.

## Refreshing the data

Re-run `python export_grants.py` whenever the database has been updated, then push the
new `data/grants.json` to the repository. The interface will reflect the latest data on
the next page load.

## File structure

    Stage_4_Static_Searchable_Interface/
    ├── export_grants.py        # Database → data/grants.json export script
    ├── index.html              # Page structure and CDN imports
    ├── styles.css              # Visual design and layout
    ├── app.js                  # Data loading, search, filters, and modal
    ├── data/
    │   └── grants.json         # Exported grant records (git-tracked; updated on refresh)
    ├── .nojekyll               # Disables Jekyll on GitHub Pages
    └── README.md               # This file

## Dependencies (all CDN — no install required for the browser)

- [Inter](https://fonts.google.com/specimen/Inter) — Google Fonts
- [Fuse.js 7.x](https://www.fusejs.io/) — client-side fuzzy search (jsDelivr CDN)
