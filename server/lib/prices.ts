// Live prices: Yahoo Finance chart API with a Stooq CSV fallback, cached 60s.
export interface Quote {
  price: number;
  prevClose?: number;
  changePct?: number;
  closes?: number[];
}

const TTL_MS = 60_000;
const NEG_TTL_MS = 10_000;
const cache = new Map<string, { at: number; quote: Quote | null }>();

export function resetPriceCache(): void {
  cache.clear();
}

async function yahooCloses(symbol: string): Promise<number[] | null> {
  for (const host of ["query1", "query2"]) {
    try {
      const res = await fetch(
        `https://${host}.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(symbol)}?interval=1d&range=3mo`,
        { signal: AbortSignal.timeout(8000), cache: "no-store", headers: { "User-Agent": "Mozilla/5.0" } }
      );
      if (!res.ok) continue;
      const json = (await res.json()) as {
        chart?: { result?: { indicators?: { quote?: { close?: (number | null)[] }[] } }[] };
      };
      const raw = json?.chart?.result?.[0]?.indicators?.quote?.[0]?.close;
      if (Array.isArray(raw)) {
        const closes = raw.filter((v): v is number => typeof v === "number" && Number.isFinite(v));
        if (closes.length >= 2) return closes;
      }
    } catch {
      // try next host
    }
  }
  return null;
}

async function stooqCloses(symbol: string): Promise<number[] | null> {
  try {
    const s = symbol.toLowerCase().includes(".") ? symbol.toLowerCase() : `${symbol.toLowerCase()}.us`;
    const res = await fetch(`https://stooq.com/q/d/l/?s=${encodeURIComponent(s)}&i=d`, {
      signal: AbortSignal.timeout(8000),
      cache: "no-store",
    });
    if (!res.ok) return null;
    const text = await res.text();
    const lines = text.trim().split("\n");
    const closes: number[] = [];
    for (let i = 1; i < lines.length; i++) {
      const cols = lines[i].split(",");
      const v = Number(cols[cols.length - 1]);
      if (Number.isFinite(v) && v > 0) closes.push(v);
    }
    return closes.length >= 2 ? closes : null;
  } catch {
    return null;
  }
}

async function closesFor(symbol: string): Promise<number[] | null> {
  return (await yahooCloses(symbol)) ?? (await stooqCloses(symbol));
}

export async function getQuotes(symbols: string[]): Promise<Record<string, Quote>> {
  const out: Record<string, Quote> = {};
  await Promise.all(
    symbols.map(async (raw) => {
      const symbol = raw.toUpperCase();
      const hit = cache.get(symbol);
      if (hit && Date.now() - hit.at < (hit.quote ? TTL_MS : NEG_TTL_MS)) {
        if (hit.quote) out[symbol] = hit.quote;
        return;
      }
      const closes = await closesFor(symbol);
      if (!closes) {
        cache.set(symbol, { at: Date.now(), quote: null });
        return;
      }
      const price = closes[closes.length - 1];
      const prevClose = closes[closes.length - 2];
      const quote: Quote = {
        price,
        prevClose,
        changePct: prevClose ? ((price - prevClose) / prevClose) * 100 : undefined,
        closes: closes.slice(-90),
      };
      cache.set(symbol, { at: Date.now(), quote });
      out[symbol] = quote;
    })
  );
  return out;
}
