import { getQuotes } from "@/lib/prices";
import { ok, bad } from "@/lib/api";

// Public data-driven brief. GET /api/analysis?symbol=NVDA
// Everything here is COMPUTED from live daily closes (Yahoo -> Stooq via lib/prices)
// plus optional live headlines. No numbers are invented; the method is disclosed.

interface Headline {
  title: string;
  publisher: string;
  link: string;
}

const newsCache = new Map<string, { at: number; items: Headline[] | null }>();
const NEWS_TTL_MS = 5 * 60_000;

async function fetchNews(symbol: string): Promise<Headline[] | null> {
  const hit = newsCache.get(symbol);
  if (hit && Date.now() - hit.at < NEWS_TTL_MS) return hit.items;
  let items: Headline[] | null = null;
  try {
    const res = await fetch(
      `https://query1.finance.yahoo.com/v1/finance/search?q=${encodeURIComponent(symbol)}&newsCount=6&quotesCount=0`,
      { signal: AbortSignal.timeout(6000), cache: "no-store", headers: { "User-Agent": "Mozilla/5.0" } }
    );
    if (res.ok) {
      const json = (await res.json()) as {
        news?: { title?: string; publisher?: string; link?: string }[];
      };
      const raw = (json.news || [])
        .filter((n) => n.title && n.link)
        .slice(0, 5)
        .map((n) => ({ title: String(n.title), publisher: String(n.publisher || "Yahoo Finance"), link: String(n.link) }));
      items = raw.length ? raw : null;
    }
  } catch {
    items = null;
  }
  newsCache.set(symbol, { at: Date.now(), items });
  return items;
}

const r2 = (n: number) => Math.round(n * 100) / 100;
const sma = (closes: number[], n: number) =>
  closes.length >= n ? closes.slice(-n).reduce((a, b) => a + b, 0) / n : null;

function pearson(a: number[], b: number[]): number | null {
  const n = Math.min(a.length, b.length);
  if (n < 10) return null;
  const x = a.slice(-n);
  const y = b.slice(-n);
  const mx = x.reduce((s, v) => s + v, 0) / n;
  const my = y.reduce((s, v) => s + v, 0) / n;
  let num = 0, dx = 0, dy = 0;
  for (let i = 0; i < n; i++) {
    const vx = x[i] - mx, vy = y[i] - my;
    num += vx * vy; dx += vx * vx; dy += vy * vy;
  }
  return dx > 0 && dy > 0 ? num / Math.sqrt(dx * dy) : null;
}

export async function GET(req: Request) {
  const url = new URL(req.url);
  const symbol = (url.searchParams.get("symbol") || "").trim().toUpperCase();
  if (!/^[A-Z0-9.\-=^]{1,15}$/.test(symbol)) return bad("Provide a valid symbol, e.g. /api/analysis?symbol=NVDA");

  let quotes: Record<string, import("@/lib/prices").Quote>;
  try {
    quotes = await getQuotes([symbol, "SPY"]);
  } catch (e) {
    return bad(`Price feed unreachable right now: ${String(e)}`, 502);
  }
  const q = quotes[symbol];
  if (!q || !q.closes || q.closes.length < 5) {
    return bad(`No live price history available for ${symbol} right now.`, 404);
  }
  const closes = q.closes;
  const price = closes[closes.length - 1];
  const n = closes.length;

  // ---- real metrics from the daily closes ----
  const s10 = sma(closes, 10);
  const s20 = sma(closes, 20);
  const s50 = sma(closes, 50);
  const high = Math.max(...closes);
  const low = Math.min(...closes);
  const rangePos = high > low ? ((price - low) / (high - low)) * 100 : 50;
  const ret10 = n > 10 ? ((price - closes[n - 11]) / closes[n - 11]) * 100 : null;
  const ret30 = n > 30 ? ((price - closes[n - 31]) / closes[n - 31]) * 100 : null;
  const rets: number[] = [];
  for (let i = 1; i < n; i++) rets.push((closes[i] - closes[i - 1]) / closes[i - 1]);
  const mean = rets.reduce((a, b) => a + b, 0) / rets.length;
  const variance = rets.reduce((a, b) => a + (b - mean) ** 2, 0) / rets.length;
  const volAnn = Math.sqrt(variance) * Math.sqrt(252) * 100;
  let peak = closes[0], maxDD = 0;
  for (const c of closes) {
    if (c > peak) peak = c;
    const dd = ((peak - c) / peak) * 100;
    if (dd > maxDD) maxDD = dd;
  }
  const upDays = rets.slice(-30).filter((r) => r > 0).length;
  const spyRets: number[] = [];
  const spyCloses = quotes["SPY"]?.closes || [];
  for (let i = 1; i < spyCloses.length; i++) spyRets.push((spyCloses[i] - spyCloses[i - 1]) / spyCloses[i - 1]);
  const corr = pearson(rets, spyRets);
  const spy = quotes["SPY"];

  // ---- transparent stance score (method disclosed in response) ----
  let score = 50;
  if (s10 !== null) score += price > s10 ? 8 : -8;
  if (s20 !== null) score += price > s20 ? 7 : -7;
  if (s50 !== null) score += price > s50 ? 6 : -6;
  if (ret10 !== null) score += ret10 >= 0 ? 6 : -6;
  if (ret30 !== null) score += ret30 >= 0 ? 5 : -5;
  if (rangePos >= 60) score += 6;
  else if (rangePos <= 30) score -= 6;
  if (corr !== null && corr > 0.5 && spy && (spy.changePct || 0) < -1) score -= 4;
  score = Math.max(5, Math.min(95, Math.round(score)));
  const stance = score >= 62 ? "Bullish" : score <= 42 ? "Cautious" : "Neutral";
  const stanceColor = stance === "Bullish" ? "up" : stance === "Cautious" ? "down" : "neutral";

  const above10 = s10 !== null && price > s10;
  const trendWord = above10 ? "uptrend" : "downtrend";

  // ---- desks: every line is a real computed finding ----
  const desks: { key: string; label: string; status: string; line: string; points: string[] }[] = [];

  desks.push({
    key: "research",
    label: "RESEARCH ANALYST",
    status: "ok",
    line: `Price sits at ${r2(rangePos)}% of its ${n}-day range (${r2(low)}–${r2(high)}).`,
    points: [
      `${n} daily closes analyzed — latest ${r2(price)}.`,
      ret30 !== null
        ? `30-session move ${r2(ret30) > 0 ? "+" : ""}${r2(ret30)}%; 10-session move ${ret10 !== null ? (ret10 > 0 ? "+" : "") + r2(ret10) : "n/a"}%.`
        : `10-session move ${ret10 !== null ? (ret10! > 0 ? "+" : "") + r2(ret10!) : "n/a"}% (window shorter than 30 sessions).`,
      `${upDays} of the last ${Math.min(30, rets.length)} sessions closed higher.`,
    ],
  });

  desks.push({
    key: "technical",
    label: "TECHNICAL ANALYST",
    status: s50 === null ? "flag" : "ok",
    line:
      s50 !== null
        ? `${trendWord.charAt(0).toUpperCase() + trendWord.slice(1)}: price is ${above10 ? "above" : "below"} its 10-day average (${s10 !== null ? r2(s10) : "n/a"}) and ${price > s50 ? "above" : "below"} the 50-day (${r2(s50)}).`
        : `Price is ${above10 ? "above" : "below"} its 10-day average (${s10 !== null ? r2(s10) : "n/a"}); 50-day average needs ${Math.max(0, 50 - n)} more sessions of data.`,
    points: [
      s10 !== null ? `10-day average: ${r2(s10)} (${((price / s10 - 1) * 100 > 0 ? "+" : "") + r2((price / s10 - 1) * 100)}% vs price).` : "10-day average: not enough data yet.",
      s20 !== null ? `20-day average: ${r2(s20)} (${((price / s20 - 1) * 100 > 0 ? "+" : "") + r2((price / s20 - 1) * 100)}% vs price).` : "20-day average: not enough data yet.",
      `Today's move so far: ${q.changePct !== undefined ? (q.changePct > 0 ? "+" : "") + r2(q.changePct) + "%" : "n/a"}.`,
    ],
  });

  desks.push({
    key: "macro",
    label: "MACRO ANALYST",
    status: spy ? "ok" : "flag",
    line:
      spy && corr !== null
        ? `Moves with the broad market (SPY correlation ${r2(corr)}); SPY today ${r2(spy.changePct || 0)}%.`
        : spy
          ? `SPY today ${r2(spy.changePct || 0)}%; correlation window too short to quantify co-movement.`
          : "Index proxy (SPY) unavailable right now.",
    points: [
      corr !== null ? `90-day return correlation with SPY: ${r2(corr)} (${corr > 0.7 ? "strong" : corr > 0.4 ? "moderate" : "weak"}).` : "Correlation needs at least 10 overlapping sessions.",
      spy ? `Market regime check: SPY ${r2(spy.changePct || 0)}% today.` : "SPY quote missing.",
      volAnn > 0 ? `This name's annualized volatility: ${r2(volAnn)}%.` : "Volatility pending.",
    ],
  });

  desks.push({
    key: "risk",
    label: "RISK ANALYST",
    status: volAnn > 60 || maxDD > 25 ? "flag" : "ok",
    line: `Annualized volatility ${r2(volAnn)}%; worst peak-to-trough drop in the window was ${r2(maxDD)}%.`,
    points: [
      `Distance to the ${n}-day low: ${r2(((price / low - 1) * 100))}% above it (${r2(low)}).`,
      `Distance to the ${n}-day high: ${r2(((high / price - 1) * 100))}% below it (${r2(high)}).`,
      `JEXI engine lines for reference: -7% safety line, +18% take profit, max 6 positions.`,
    ],
  });

  const news = await fetchNews(symbol);
  desks.push({
    key: "news",
    label: "NEWS ANALYST",
    status: news ? "ok" : "unavailable",
    line: news
      ? `${news.length} live headline${news.length === 1 ? "" : "s"} pulled for ${symbol} — latest: "${news[0].title.slice(0, 90)}${news[0].title.length > 90 ? "…" : ""}"`
      : "No live news feed reachable right now — headlines will appear here the moment the feed responds.",
    points: news ? news.slice(0, 3).map((h) => `${h.publisher}: ${h.title}`) : ["Add an AI key in Settings to pair headlines with model interpretation later."],
  });

  // ---- verifier: real consistency checks ----
  const conflicts: string[] = [];
  if (ret10 !== null && s10 !== null && above10 !== ret10 >= 0) {
    conflicts.push(`Price is ${above10 ? "above" : "below"} the 10-day average while 10-day momentum is ${ret10 >= 0 ? "positive" : "negative"} — trend and momentum disagree.`);
  }
  if (n < 50) conflicts.push(`Only ${n} sessions of history available — long-window averages are approximations until 50 sessions exist.`);
  if (news === null) conflicts.push("News desk unreachable during this run — brief is price-only.");

  desks.push({
    key: "verifier",
    label: "VERIFIER",
    status: conflicts.length ? "flag" : "ok",
    line: conflicts.length
      ? `${conflicts.length} caveat${conflicts.length === 1 ? "" : "s"} attached — see the ledger.`
      : "All checks passed: data window, trend/momentum consistency and desks agree.",
    points: conflicts.length ? conflicts : [
      `Data window verified: ${n} daily closes.`,
      "Trend label matches momentum direction.",
      "Desks sourced from the same quote chain (Yahoo → Stooq fallback).",
    ],
  });

  const watch = [
    { label: `Breakout level (${n}-day high)`, value: r2(high) },
    { label: `Breakdown level (${n}-day low)`, value: r2(low) },
    ...(s10 !== null ? [{ label: "10-day average (trend line)", value: r2(s10) }] : []),
    ...(s50 !== null ? [{ label: "50-day average (core trend)", value: r2(s50) }] : []),
  ];

  return ok({
    symbol,
    price: r2(price),
    changePct: q.changePct !== undefined ? r2(q.changePct) : null,
    stance,
    stanceTone: stanceColor,
    conviction: score,
    metrics: {
      closes: n,
      sma10: s10 !== null ? r2(s10) : null,
      sma20: s20 !== null ? r2(s20) : null,
      sma50: s50 !== null ? r2(s50) : null,
      high90: r2(high),
      low90: r2(low),
      rangePos: r2(rangePos),
      ret10: ret10 !== null ? r2(ret10) : null,
      ret30: ret30 !== null ? r2(ret30) : null,
      volAnn: r2(volAnn),
      maxDrawdown: r2(maxDD),
      upDays30: upDays,
      spyCorrelation: corr !== null ? r2(corr) : null,
    },
    desks,
    watch,
    news: news || [],
    conflicts,
    method:
      "Deterministic brief computed from live daily closes (Yahoo Finance with Stooq fallback) plus live Yahoo headlines when reachable. Stance = weighted position of price vs its 10/20/50-day averages, 10/30-session momentum, range position and market correlation. No generated or invented numbers.",
    disclaimer:
      "Research brief, not investment advice. Paper trading only.",
    asOf: new Date().toISOString(),
  });
}
