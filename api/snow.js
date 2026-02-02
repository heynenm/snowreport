// Vercel Serverless Function: /api/snow
// Fetches US resort snow data from Open-Meteo (free, no API key) and returns
// JSON in the same shape as /data/snow.json so the frontend can consume it.
//
// NOTE: This is *snowfall* (precip as snow) from a weather model, not each resort's
// official ops report (lifts/trails). But it's reliable, automated, and keyless.

import { RESORTS } from "./resorts.js";

function sum(arr) {
  return arr.reduce((a, b) => a + (Number.isFinite(b) ? b : 0), 0);
}

async function fetchOpenMeteoSnow(lat, lon) {
  // We use hourly snowfall (cm). We'll sum last 24h and last 72h.
  // Open-Meteo returns arrays aligned to timestamps.
  const url = new URL("https://api.open-meteo.com/v1/forecast");
  url.searchParams.set("latitude", String(lat));
  url.searchParams.set("longitude", String(lon));
  url.searchParams.set("hourly", "snowfall");
  url.searchParams.set("past_days", "3");
  url.searchParams.set("forecast_days", "1");
  url.searchParams.set("timezone", "UTC");

  const res = await fetch(url.toString(), {
    headers: { "User-Agent": "snowreport/1.0" },
  });
  if (!res.ok) throw new Error(`Open-Meteo error ${res.status}`);
  const data = await res.json();

  const times = data?.hourly?.time || [];
  const snowfallCm = data?.hourly?.snowfall || [];

  const n = Math.min(times.length, snowfallCm.length);
  if (n === 0) return { snow24_in: null, snow72_in: null };

  const last24 = snowfallCm.slice(Math.max(0, n - 24), n);
  const last72 = snowfallCm.slice(Math.max(0, n - 72), n);

  // cm -> inches
  const cmToIn = (cm) => cm / 2.54;
  const snow24_in = Number(cmToIn(sum(last24)).toFixed(1));
  const snow72_in = Number(cmToIn(sum(last72)).toFixed(1));

  return { snow24_in, snow72_in };
}

export default async function handler(req, res) {
  try {
    // Optional filtering: /api/snow?state=CO
    const state = (req?.query?.state || "").toString().trim().toUpperCase();

    const list = state
      ? RESORTS.filter((r) => (r.state || "").toUpperCase() === state)
      : RESORTS;

    const resorts = await Promise.all(
      list.map(async (r) => {
        const { snow24_in, snow72_in } = await fetchOpenMeteoSnow(r.lat, r.lon);
        return {
          name: r.name,
          state: r.state,
          region: r.region,
          elevation_ft: r.elevation_ft,
          snow_24h_in: snow24_in,
          snow_72h_in: snow72_in,
          // These are resort-ops metrics; Open-Meteo doesn't provide them.
          base_depth_in: null,
          trails_open: null,
          trails_total: null,
          lifts_open: null,
          lifts_total: null,
          terrain_open_pct: null,
          report_url: r.report_url,
          webcam_url: r.webcam_url,
        };
      })
    );

    res.setHeader("Cache-Control", "s-maxage=900, stale-while-revalidate=3600");
    res.status(200).json({
      updated_at: new Date().toISOString(),
      source: "Open-Meteo hourly snowfall (model) via /api/snow",
      resorts,
      filters: state ? { state } : {},
    });
  } catch (e) {
    res.status(500).json({
      error: "Failed to fetch snow data",
      detail: String(e?.message || e),
      updated_at: new Date().toISOString(),
    });
  }
}
