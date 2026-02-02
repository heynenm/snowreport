# US Snow Report

Static page that renders US resort snow stats.

- **Frontend:** `index.html`
- **Static fallback data:** `data/snow.json`
- **Live API (Vercel):** `GET /api/snow` (Open-Meteo modeled snowfall)

The frontend prefers `/api/snow` when available and falls back to `data/snow.json`.

## Local preview

```bash
cd tahoe-snow-report
python3 -m http.server 8000
```
Open http://localhost:8000

## API

- `GET /api/snow` → all resorts
- `GET /api/snow?state=CO` → filter by state (2-letter code)

## Data notes

- Snowfall values are **modeled** (Open-Meteo hourly snowfall), not official resort ops reports.
- Ops stats (lifts/trails/base depth) are left `null` unless you wire in a provider.
