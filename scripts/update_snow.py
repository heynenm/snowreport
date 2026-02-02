#!/usr/bin/env python3
"""Update data/snow.json

Goal:
- Keep Open-Meteo modeled snowfall (reliable, keyless)
- Add resort ops stats (lifts/trails/base depth) from a source that works in GitHub Actions.

Implementation:
- Use OnTheSnow resort pages and parse embedded JSON-LD (application/ld+json)
  which typically includes: numberOfItems (trails), and sometimes additional fields.
- Also parse visible text fallbacks for lifts/trails/base depth when present.

Notes:
- This is best-effort scraping. If OnTheSnow changes markup, we fail gracefully and keep nulls.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional, Tuple

import requests
from bs4 import BeautifulSoup


@dataclass
class Resort:
    name: str
    region: str
    elevation_ft: int
    lat: float
    lon: float
    report_url: str
    webcams_url: str
    onthesnow_url: str


RESORTS = [
    Resort(
        name="Palisades Tahoe",
        region="Olympic Valley",
        elevation_ft=6200,
        lat=39.1973,
        lon=-120.2358,
        report_url="https://www.palisadestahoe.com/mountain-information/snow-and-weather-report",
        webcams_url="https://www.palisadestahoe.com/mountain-information/webcams",
        onthesnow_url="https://www.onthesnow.com/california/palisades-tahoe/skireport",
    ),
    Resort(
        name="Heavenly",
        region="South Lake Tahoe",
        elevation_ft=10067,
        lat=38.9351,
        lon=-119.9390,
        report_url="https://www.skiheavenly.com/the-mountain/mountain-conditions/snow-and-weather-report.aspx",
        webcams_url="https://www.skiheavenly.com/the-mountain/mountain-conditions/mountain-cams.aspx",
        onthesnow_url="https://www.onthesnow.com/california/heavenly-mountain-resort/skireport",
    ),
    Resort(
        name="Northstar California",
        region="Truckee",
        elevation_ft=8610,
        lat=39.2746,
        lon=-120.1210,
        report_url="https://www.northstarcalifornia.com/the-mountain/mountain-conditions/snow-and-weather-report.aspx",
        webcams_url="https://www.northstarcalifornia.com/the-mountain/mountain-conditions/mountain-cams.aspx",
        onthesnow_url="https://www.onthesnow.com/california/northstar-california/skireport",
    ),
    Resort(
        name="Kirkwood",
        region="Kirkwood",
        elevation_ft=9800,
        lat=38.6846,
        lon=-120.0650,
        report_url="https://www.kirkwood.com/the-mountain/mountain-conditions/snow-and-weather-report.aspx",
        webcams_url="https://www.kirkwood.com/the-mountain/mountain-conditions/mountain-cams.aspx",
        onthesnow_url="https://www.onthesnow.com/california/kirkwood/skireport",
    ),
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def fetch_open_meteo_snow(lat: float, lon: float) -> Tuple[Optional[float], Optional[float]]:
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": str(lat),
        "longitude": str(lon),
        "hourly": "snowfall",
        "past_days": "3",
        "forecast_days": "1",
        "timezone": "UTC",
    }
    r = requests.get(url, params=params, headers={"User-Agent": "tahoe-snow-report/1.0"}, timeout=30)
    r.raise_for_status()
    data = r.json()

    times = data.get("hourly", {}).get("time", [])
    snowfall_cm = data.get("hourly", {}).get("snowfall", [])
    n = min(len(times), len(snowfall_cm))
    if n == 0:
        return None, None

    last24 = snowfall_cm[max(0, n - 24) : n]
    last72 = snowfall_cm[max(0, n - 72) : n]

    def s(arr):
        return sum(float(x) for x in arr if isinstance(x, (int, float)))

    cm_to_in = lambda cm: cm / 2.54
    snow24 = round(cm_to_in(s(last24)), 1)
    snow72 = round(cm_to_in(s(last72)), 1)
    return snow24, snow72


def _first_int(text: str) -> Optional[int]:
    m = re.search(r"(\d+)", text.replace(",", ""))
    return int(m.group(1)) if m else None


def _parse_base_depth_in(text: str) -> Optional[int]:
    # Look for patterns like "Base Depth 45 in" or "Base depth: 45" etc.
    m = re.search(r"base\s*depth[^\d]*(\d{1,3})\s*(in|\")?", text, re.IGNORECASE)
    if m:
        return int(m.group(1))
    return None


def fetch_ops_from_onthesnow(onthesnow_url: str) -> dict[str, Optional[int]]:
    """Best-effort parse lifts/trails/base depth from OnTheSnow skireport page."""

    out: dict[str, Optional[int]] = {
        "base_depth_in": None,
        "trails_open": None,
        "trails_total": None,
        "lifts_open": None,
        "lifts_total": None,
    }

    r = requests.get(
        onthesnow_url,
        headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
        timeout=30,
    )
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")

    # 1) JSON-LD blocks
    for tag in soup.select('script[type="application/ld+json"]'):
        try:
            payload = json.loads(tag.get_text(strip=True))
        except Exception:
            continue

        # payload can be dict or list
        items = payload if isinstance(payload, list) else [payload]
        for it in items:
            if not isinstance(it, dict):
                continue
            # Some pages include "numberOfItems" for trails
            if out["trails_total"] is None and isinstance(it.get("numberOfItems"), int):
                out["trails_total"] = it["numberOfItems"]

    # 2) Text-based fallbacks
    text = soup.get_text(" ", strip=True)

    # Trails open/total patterns like "Trails Open 97/111" or "Trails 97 / 111"
    m = re.search(r"Trails\s*(Open)?\s*(\d{1,3})\s*/\s*(\d{1,3})", text, re.IGNORECASE)
    if m:
        out["trails_open"] = int(m.group(2))
        out["trails_total"] = int(m.group(3))

    # Lifts open/total patterns
    m = re.search(r"Lifts\s*(Open)?\s*(\d{1,3})\s*/\s*(\d{1,3})", text, re.IGNORECASE)
    if m:
        out["lifts_open"] = int(m.group(2))
        out["lifts_total"] = int(m.group(3))

    # Base depth
    bd = _parse_base_depth_in(text)
    if bd is not None:
        out["base_depth_in"] = bd

    return out


def main() -> None:
    resorts_out: list[dict[str, Any]] = []

    for r in RESORTS:
        snow24, snow72 = fetch_open_meteo_snow(r.lat, r.lon)
        ops = {}
        try:
            ops = fetch_ops_from_onthesnow(r.onthesnow_url)
        except Exception:
            ops = {
                "base_depth_in": None,
                "trails_open": None,
                "trails_total": None,
                "lifts_open": None,
                "lifts_total": None,
            }

        resorts_out.append(
            {
                "name": r.name,
                "region": r.region,
                "elevation_ft": r.elevation_ft,
                "snow_24h_in": snow24,
                "snow_72h_in": snow72,
                "base_depth_in": ops.get("base_depth_in"),
                "trails_open": ops.get("trails_open"),
                "trails_total": ops.get("trails_total"),
                "lifts_open": ops.get("lifts_open"),
                "lifts_total": ops.get("lifts_total"),
                "report_url": r.report_url,
                "webcams_url": r.webcams_url,
                "notes": "Snowfall from Open-Meteo (modeled). Ops stats best-effort from OnTheSnow skireport.",
            }
        )

    out = {
        "updated_at": _now_iso(),
        "source": "Open-Meteo (modeled snowfall) + OnTheSnow (ops stats best-effort)",
        "resorts": resorts_out,
    }

    with open("data/snow.json", "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
        f.write("\n")


if __name__ == "__main__":
    main()
