import { getQuotes } from "@/lib/prices";
import { ok, bad } from "@/lib/api";

// Public market quotes for the Jexi web + mobile apps.
// GET /api/market?symbols=AAPL,MSFT&closes=1
const DEFAULT_SYMBOLS = ["AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "TSLA", "SPY", "QQQ"];

export async function GET(req: Request) {
  const url = new URL(req.url);
  const symbolsParam = url.searchParams.get("symbols") || "";
  const wantCloses = url.searchParams.get("closes") === "1";

  const symbols = symbolsParam
    .split(",")
    .map((s) => s.trim().toUpperCase())
    .filter((s) => /^[A-Z0-9.\-=^]{1,15}$/.test(s))
    .slice(0, 30);

  const list = symbols.length ? symbols : DEFAULT_SYMBOLS;
  try {
    const quotes = await getQuotes(list);
    const clean: Record<string, unknown> = {};
    for (const [symbol, quote] of Object.entries(quotes)) {
      if (!Number.isFinite(quote.price) || quote.price <= 0) continue;
      clean[symbol] = {
        price: Math.round(quote.price * 100) / 100,
        prevClose: quote.prevClose !== undefined ? Math.round(quote.prevClose * 100) / 100 : undefined,
        changePct: quote.changePct !== undefined ? Math.round(quote.changePct * 100) / 100 : undefined,
        closes: wantCloses ? (quote.closes || []).map((c) => Math.round(c * 100) / 100) : undefined,
      };
    }
    return ok({ quotes: clean, at: new Date().toISOString() });
  } catch (e) {
    return bad(`Could not fetch prices right now: ${String(e)}`, 502);
  }
}
