import { ok } from "@/lib/api";

// Public version endpoint for update checks (web + mobile app).
// GET /api/version
// Ops: set APP_LATEST_VERSION / APP_MIN_VERSION / APP_UPDATE_NOTES / APP_DOWNLOAD_URL
// on the server to force-update clients without touching client code.
const FALLBACK_LATEST = "1.2.0";
const FALLBACK_MIN = "1.0.0";
const FALLBACK_URL = "https://github.com/lewiseinstein15-Tech/daily_stock_analysis/releases";

const SEMVER = /^\d+\.\d+\.\d+$/;

export async function GET() {
  const latest = SEMVER.test(process.env.APP_LATEST_VERSION || "")
    ? process.env.APP_LATEST_VERSION!
    : FALLBACK_LATEST;
  const minRequired = SEMVER.test(process.env.APP_MIN_VERSION || "")
    ? process.env.APP_MIN_VERSION!
    : FALLBACK_MIN;
  return ok({
    latest,
    minRequired,
    notes: process.env.APP_UPDATE_NOTES || "Live data briefs, real admin control room, legal pages, update checks.",
    url: process.env.APP_DOWNLOAD_URL || FALLBACK_URL,
    checkedAt: new Date().toISOString(),
  });
}
