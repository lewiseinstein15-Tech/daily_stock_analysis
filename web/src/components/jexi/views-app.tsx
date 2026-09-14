"use client";

// App views part 1: Command Center, Markets, Asset page.
import { useMemo, useState } from "react";
import { ArrowRight, Plus, Search, Star, TrendingDown, TrendingUp } from "lucide-react";
import { AreaChart, ConvictionDial, Sparkline } from "@/components/jexi/charts";
import { Delta, EmptyState, KindDot, LiveDot, Panel, Pill, SectionTitle, Stat, TickerStrip } from "@/components/jexi/bits";
import {
  AccountInfo,
  FeedEvent,
  Quote,
  Quotes,
  UNIVERSE,
  briefingFromQuotes,
  demoThesis,
  money,
  priceFmt,
  pct,
  symbolName,
  timeAgo,
  useLocalList,
  useQuotes,
} from "@/lib/jexi/data";

export interface ViewProps {
  go: (view: string, symbol?: string) => void;
  token: string | null;
  account: AccountInfo | null;
  feed: FeedEvent[];
  isDemo: boolean;
}

// ---------------- Command Center ----------------

export function CommandView({ go, account, feed, isDemo }: ViewProps) {
  const symbols = useMemo(() => UNIVERSE.map((u) => u.s), []);
  const { quotes } = useQuotes(symbols, 22000);
  const [watchlist, setWatchlist] = useLocalList<string[]>("jexi.watchlist", ["NVDA", "AAPL", "MSFT", "TSLA"]);
  const briefing = briefingFromQuotes(quotes);

  const entries = Object.entries(quotes).filter(([, q]) => Number.isFinite(q.changePct || NaN));
  const gainers = [...entries].sort((a, b) => (b[1].changePct || 0) - (a[1].changePct || 0)).slice(0, 3);
  const losers = [...entries].sort((a, b) => (a[1].changePct || 0) - (b[1].changePct || 0)).slice(0, 3);

  const equity = account?.equity ?? 10000;
  const positions = account?.positions ?? [];

  return (
    <div className="view-enter">
      <div className="mb-5 flex items-center justify-between">
        <div>
          <div className="label">Market command center</div>
          <h1 className="display mt-1 text-[30px] leading-tight">
            {new Date().toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" })}
          </h1>
        </div>
        <Pill tone="brand">
          <LiveDot /> live
        </Pill>
      </div>

      <div className="grid gap-4 lg:grid-cols-[1.4fr_1fr]">
        {/* briefing */}
        <Panel className="min-w-0 overflow-hidden">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="min-w-0">
              <div className="label">Today&apos;s briefing</div>
              <div className="display mt-1.5 flex flex-wrap items-center gap-3 text-[26px]">
                {briefing.regime}
                <Pill tone={briefing.regime === "Risk-on" ? "up" : briefing.regime === "Risk-off" ? "down" : "neutral"}>
                  <span className="whitespace-normal text-center leading-snug">{briefing.regimeDetail}</span>
                </Pill>
              </div>
            </div>
          </div>
          <ul className="mt-4 flex flex-col gap-2">
            {briefing.lines.map((l, i) => (
              <li key={i} className="flex gap-2.5 text-[13.5px] leading-relaxed" style={{ color: "var(--ink-2)" }}>
                <span style={{ color: "var(--ember)" }}>—</span>
                <span className="min-w-0 break-words">{l}</span>
              </li>
            ))}
          </ul>
          <div className="mt-4 border-t pt-3" style={{ borderColor: "var(--line-soft)" }}>
            <TickerStrip quotes={quotes} onSelect={(s) => go("asset", s)} />
          </div>
        </Panel>

        {/* account snapshot */}
        <Panel>
          <div className="label">Your account {isDemo && <span style={{ color: "var(--gold)" }}>· demo</span>}</div>
          <div className="mt-1 flex items-baseline gap-3">
            <span className="data text-[34px] tracking-tight" style={{ color: "var(--ink)" }}>
              {money(equity)}
            </span>
            {account && <Delta value={account.pnlPct} />}
          </div>
          <div className="mt-1 text-[13px]" style={{ color: "var(--ink-3)" }}>
            {account
              ? `${money(account.cash)} cash · ${positions.length} open position${positions.length === 1 ? "" : "s"}`
              : "Sign in to sync your real paper account, keys and feed."}
          </div>
          <div className="mt-4 grid grid-cols-3 gap-3">
            {gainers.map(([s, q]) => (
              <button key={s} className="panel-2 row-link p-3 text-left" onClick={() => go("asset", s)}>
                <div className="data text-[13px]">{s.replace("-USD", "")}</div>
                <div className="data mt-1 text-[12.5px]" style={{ color: "var(--up)" }}>
                  +{Math.abs(q.changePct || 0).toFixed(2)}%
                </div>
                <div className="data text-[11px]" style={{ color: "var(--ink-3)" }}>
                  {priceFmt(q.price)}
                </div>
              </button>
            ))}
          </div>
          <button className="btn btn-ghost mt-4 w-full" onClick={() => go(isDemo ? "auth" : "portfolio")}>
            {isDemo ? "Connect your account" : "Open portfolio"} <ArrowRight size={15} />
          </button>
        </Panel>
      </div>

      {/* movers + watchlist */}
      <div className="mt-4 grid gap-4 lg:grid-cols-3">
        <Panel>
          <div className="label mb-3 flex items-center gap-2">
            <TrendingUp size={13} style={{ color: "var(--up)" }} /> Leaders
          </div>
          <div className="flex flex-col">
            {gainers.map(([s, q]) => (
              <QuoteRow key={s} s={s} q={q} go={go} />
            ))}
          </div>
        </Panel>
        <Panel>
          <div className="label mb-3 flex items-center gap-2">
            <TrendingDown size={13} style={{ color: "var(--down)" }} /> Laggards
          </div>
          <div className="flex flex-col">
            {losers.map(([s, q]) => (
              <QuoteRow key={s} s={s} q={q} go={go} />
            ))}
          </div>
        </Panel>
        <Panel>
          <div className="label mb-3 flex items-center gap-2">
            <Star size={13} style={{ color: "var(--gold)" }} /> Watchlist
          </div>
          <div className="flex flex-col">
            {watchlist.map((s) => {
              const q = quotes[s];
              return q ? (
                <QuoteRow key={s} s={s} q={q} go={go} />
              ) : (
                <div key={s} className="flex items-center justify-between py-2 text-[13.5px]">
                  <span className="data">{s}</span>
                  <span className="label">loading…</span>
                </div>
              );
            })}
          </div>
          <button className="btn btn-line mt-3 w-full" style={{ minHeight: 36 }} onClick={() => go("markets")}>
            <Plus size={14} /> Add symbols
          </button>
        </Panel>
      </div>

      {/* positions + feed */}
      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Panel>
          <SectionTitle sub={isDemo ? "demo data" : "live from your engine"}>Positions</SectionTitle>
          {positions.length === 0 ? (
            <EmptyState
              title={isDemo ? "No positions in demo" : "No open positions"}
              body={
                isDemo
                  ? "Sign in and JEXI's engine will start building a paper portfolio for you."
                  : "JEXI only enters on uptrends above the 10-day average. Nothing qualified yet — that's discipline, not inactivity."
              }
              action={
                <button className="btn btn-ghost" onClick={() => go(isDemo ? "auth" : "intelligence")}>
                  {isDemo ? "Create account" : "Read the research"}
                </button>
              }
            />
          ) : (
            <div className="flex flex-col">
              {positions.map((p) => (
                <button
                  key={p.symbol}
                  className="row-link flex items-center justify-between rounded-lg px-2 py-2.5 text-left"
                  onClick={() => go("asset", p.symbol)}
                >
                  <div>
                    <div className="data text-[14px]">{p.symbol}</div>
                    <div className="text-[12px]" style={{ color: "var(--ink-3)" }}>
                      {p.qty} @ {priceFmt(p.avgPrice)}
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="data text-[14px]">{money(p.value)}</div>
                    <div className="data text-[12.5px]" style={{ color: p.pnl >= 0 ? "var(--up)" : "var(--down)" }}>
                      {p.pnl >= 0 ? "+" : ""}
                      {money(p.pnl)}
                    </div>
                  </div>
                </button>
              ))}
            </div>
          )}
        </Panel>

        <Panel>
          <SectionTitle sub={isDemo ? "demo feed" : "plain english, always"}>Activity</SectionTitle>
          <div className="flex max-h-[300px] flex-col gap-3 overflow-y-auto pr-1">
            {(feed.length ? feed : []).map((e) => (
              <div key={e.id} className="flex gap-3 text-[13.5px] leading-relaxed">
                <KindDot kind={e.kind} />
                <div>
                  <span style={{ color: "var(--ink-2)" }}>{e.message}</span>
                  <span className="ml-2 text-[11.5px]" style={{ color: "var(--ink-3)" }}>
                    {timeAgo(e.created_at)}
                  </span>
                </div>
              </div>
            ))}
            {!feed.length && (
              <EmptyState title="Quiet log" body="JEXI posts here the moment it buys, sells, protects capital or processes a withdrawal." />
            )}
          </div>
        </Panel>
      </div>
    </div>
  );
}

function QuoteRow({ s, q, go }: { s: string; q: Quote; go: (v: string, s?: string) => void }) {
  return (
    <button className="row-link flex items-center justify-between rounded-lg px-2 py-2 text-left" onClick={() => go("asset", s)}>
      <div>
        <div className="data text-[13.5px]">{s.replace("-USD", "")}</div>
        <div className="text-[11.5px]" style={{ color: "var(--ink-3)" }}>
          {symbolName(s)}
        </div>
      </div>
      <div className="flex items-center gap-3">
        {q.closes && q.closes.length > 4 && <Sparkline data={q.closes.slice(-30)} w={64} h={22} />}
        <div className="text-right">
          <div className="data text-[13.5px]">{priceFmt(q.price)}</div>
          <Delta value={q.changePct || 0} showPill={false} size={12} />
        </div>
      </div>
    </button>
  );
}

// ---------------- Markets ----------------

export function MarketsView({ go }: { go: (v: string, s?: string) => void }) {
  const symbols = useMemo(() => UNIVERSE.map((u) => u.s), []);
  const { quotes, loading } = useQuotes(symbols, 25000);
  const [query, setQuery] = useState("");

  const rows = UNIVERSE.filter(
    (u) =>
      !query ||
      u.s.toLowerCase().includes(query.toLowerCase()) ||
      u.name.toLowerCase().includes(query.toLowerCase()) ||
      u.sector.toLowerCase().includes(query.toLowerCase())
  ).map((u) => ({ ...u, q: quotes[u.s] }));

  const sectors = useMemo(() => {
    const map = new Map<string, { sum: number; n: number }>();
    for (const u of UNIVERSE) {
      const c = quotes[u.s]?.changePct;
      if (Number.isFinite(c || NaN)) {
        const cur = map.get(u.sector) || { sum: 0, n: 0 };
        map.set(u.sector, { sum: cur.sum + (c || 0), n: cur.n + 1 });
      }
    }
    return [...map.entries()].map(([sector, v]) => ({ sector, avg: v.sum / v.n })).sort((a, b) => b.avg - a.avg);
  }, [quotes]);

  return (
    <div className="view-enter">
      <SectionTitle sub={`${UNIVERSE.length} instruments · live`}>Markets overview</SectionTitle>

      {/* sector heat */}
      <Panel className="mb-4">
        <div className="label mb-3">Sector pulse (average move today)</div>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-7">
          {sectors.map((s) => {
            const up = s.avg >= 0;
            return (
              <div
                key={s.sector}
                className="rounded-xl p-3"
                style={{
                  background: `color-mix(in srgb, ${up ? "var(--up)" : "var(--down)"} ${Math.min(16, Math.abs(s.avg) * 8 + 4)}%, var(--panel-2))`,
                  border: "1px solid var(--line-soft)",
                }}
              >
                <div className="truncate text-[12px]" style={{ color: "var(--ink-2)" }}>
                  {s.sector}
                </div>
                <div className="data mt-1 text-[14px]" style={{ color: up ? "var(--up)" : "var(--down)" }}>
                  {pct(s.avg)}
                </div>
              </div>
            );
          })}
          {!sectors.length && loading && <div className="skeleton h-[64px] col-span-4" />}
        </div>
      </Panel>

      <Panel pad={false}>
        <div className="flex items-center gap-3 border-b px-5 py-3.5" style={{ borderColor: "var(--line-soft)" }}>
          <Search size={15} style={{ color: "var(--ink-3)" }} />
          <input
            className="w-full bg-transparent text-[14px] outline-none placeholder:text-[var(--ink-3)]"
            placeholder="Search symbol, name or sector…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <div className="flex flex-col">
          {rows.map(({ s, name, q }) => (
            <button
              key={s}
              className="row-link flex items-center justify-between gap-4 px-5 py-3 text-left"
              onClick={() => go("asset", s)}
            >
              <div className="min-w-[120px]">
                <div className="data text-[14px]">{s.replace("-USD", "")}</div>
                <div className="text-[12px]" style={{ color: "var(--ink-3)" }}>
                  {name}
                </div>
              </div>
              <div className="hidden sm:block">
                {q?.closes && q.closes.length > 4 ? <Sparkline data={q.closes.slice(-40)} /> : <div style={{ width: 92 }} />}
              </div>
              <div className="flex items-center gap-4">
                <div className="data w-[90px] text-right text-[14px]">{q ? priceFmt(q.price) : "—"}</div>
                <div className="w-[92px] text-right">{q ? <Delta value={q.changePct || 0} /> : <span className="label">…</span>}</div>
              </div>
            </button>
          ))}
        </div>
      </Panel>
    </div>
  );
}

// ---------------- Asset page ----------------

export function AssetView({ symbol, go }: { symbol: string; go: (v: string, s?: string) => void }) {
  const { quotes } = useQuotes([symbol, "SPY"], 20000);
  const [range, setRange] = useState<"1M" | "3M">("1M");
  const [watchlist, setWatchlist] = useLocalList<string[]>("jexi.watchlist", ["NVDA", "AAPL", "MSFT", "TSLA"]);
  const q: Quote | undefined = quotes[symbol];
  const thesis = demoThesis(symbol);
  const meta = UNIVERSE.find((u) => u.s === symbol);
  const starred = watchlist.includes(symbol);

  const closes = useMemo(() => {
    const all = q?.closes || [];
    return range === "1M" ? all.slice(-21) : all;
  }, [q, range]);

  const periodHigh = closes.length ? Math.max(...closes) : 0;
  const periodLow = closes.length ? Math.min(...closes) : 0;
  const sma10 = closes.length >= 10 ? closes.slice(-10).reduce((a, b) => a + b, 0) / 10 : null;

  return (
    <div className="view-enter">
      <button className="btn btn-line mb-5" style={{ minHeight: 36 }} onClick={() => go("markets")}>
        ← All markets
      </button>

      {/* price header */}
      <Panel className="mb-4">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-3">
              <h1 className="display text-[34px] leading-none">{symbol.replace("-USD", "")}</h1>
              {meta && <Pill>{meta.sector}</Pill>}
              <button
                onClick={() =>
                  setWatchlist(starred ? watchlist.filter((s) => s !== symbol) : [...watchlist, symbol])
                }
                aria-label={starred ? "Remove from watchlist" : "Add to watchlist"}
                style={{ color: starred ? "var(--gold)" : "var(--ink-3)" }}
                className="transition-transform active:scale-90"
              >
                <Star size={18} fill={starred ? "var(--gold)" : "none"} />
              </button>
            </div>
            <div className="mt-1.5 text-[14px]" style={{ color: "var(--ink-2)" }}>
              {symbolName(symbol)} {symbol.endsWith("-USD") && "· 24/7 market"}
            </div>
          </div>
          <div className="text-right">
            <div className="data text-[40px] leading-none tracking-tight">{q ? priceFmt(q.price) : "—"}</div>
            <div className="mt-2 flex justify-end">{q ? <Delta value={q.changePct || 0} /> : <span className="label">loading live quote…</span>}</div>
          </div>
        </div>

        <div className="mt-6 flex items-center justify-between">
          <div className="flex gap-1.5">
            {(["1M", "3M"] as const).map((r) => (
              <button
                key={r}
                onClick={() => setRange(r)}
                className="rounded-lg px-3.5 py-1.5 text-[12.5px] font-medium transition-all"
                style={{
                  background: range === r ? "var(--panel-3)" : "transparent",
                  color: range === r ? "var(--ink)" : "var(--ink-3)",
                  border: `1px solid ${range === r ? "var(--line)" : "transparent"}`,
                }}
              >
                {r}
              </button>
            ))}
          </div>
          <span className="label">JEXI native chart · daily closes</span>
        </div>
        <div className="mt-2">
          <AreaChart data={closes} height={250} fmt={(v) => `$${priceFmt(v)}`} />
        </div>

        <div className="mt-5 grid grid-cols-2 gap-4 border-t pt-4 sm:grid-cols-4" style={{ borderColor: "var(--line-soft)" }}>
          <Stat label="Prev close" value={q?.prevClose ? priceFmt(q.prevClose) : "—"} />
          <Stat label={`Period high (${range})`} value={periodHigh ? priceFmt(periodHigh) : "—"} />
          <Stat label={`Period low (${range})`} value={periodLow ? priceFmt(periodLow) : "—"} />
          <Stat label="10-day average" value={sma10 ? priceFmt(sma10) : "—"} sub={sma10 && q ? (q.price > sma10 ? "price above — trend support" : "price below — trend pressure") : undefined} />
        </div>
      </Panel>

      {/* thesis + analysts */}
      <div className="grid gap-4 lg:grid-cols-[1.2fr_1fr]">
        <Panel>
          <div className="flex items-center justify-between">
            <SectionTitle sub="demo research format">JEXI thesis</SectionTitle>
            <Pill tone="brand">Demo</Pill>
          </div>
          <div className="flex flex-wrap items-center gap-6">
            <ConvictionDial value={thesis.conviction} />
            <div>
              <div
                className="display text-[28px]"
                style={{
                  color:
                    thesis.stance === "Bullish" ? "var(--up)" : thesis.stance === "Cautious" ? "var(--down)" : "var(--sand)",
                }}
              >
                {thesis.stance}
              </div>
              <div className="text-[13px]" style={{ color: "var(--ink-3)" }}>
                on {symbol.replace("-USD", "")} · verifier-checked format
              </div>
            </div>
          </div>
          <div className="mt-5 grid gap-4 sm:grid-cols-3">
            <ThesisList title="Drivers" tone="up" items={thesis.drivers} />
            <ThesisList title="Risks" tone="down" items={thesis.risks} />
            <ThesisList title="Catalysts" tone="brand" items={thesis.catalysts} />
          </div>
        </Panel>

        <Panel>
          <SectionTitle sub="each desk, one line">Analyst pipeline</SectionTitle>
          <div className="flex flex-col gap-2.5">
            {[
              { r: "RESEARCH ANALYST", d: "Fundamentals, valuation and quality of the business" },
              { r: "TECHNICAL ANALYST", d: "Trend, momentum and where price sits vs. its averages" },
              { r: "MACRO ANALYST", d: "Rates, liquidity and the regime the tape is trading in" },
              { r: "RISK ANALYST", d: "What can go wrong, sized in dollars, with exit lines drawn" },
              { r: "NEWS ANALYST", d: "Events and catalysts that can move price, with timing" },
              { r: "VERIFIER", d: "Separates data, analysis and interpretation before publishing" },
            ].map((a) => (
              <div key={a.r} className="panel-2 flex items-center justify-between gap-3 px-3.5 py-3">
                <div>
                  <div className="text-[11.5px] font-semibold tracking-[0.08em]" style={{ color: "var(--peach)" }}>
                    {a.r}
                  </div>
                  <div className="mt-0.5 text-[12.5px]" style={{ color: "var(--ink-2)" }}>
                    {a.d}
                  </div>
                </div>
                <Pill tone="neutral">ready</Pill>
              </div>
            ))}
          </div>
          <p className="mt-4 text-[12px] leading-relaxed" style={{ color: "var(--ink-3)" }}>
            Connect your AI key in Settings to run this pipeline live with your own model. JEXI never
            presents generated content as market fact.
          </p>
        </Panel>
      </div>
    </div>
  );
}

function ThesisList({ title, items, tone }: { title: string; items: string[]; tone: "up" | "down" | "brand" }) {
  const color = tone === "up" ? "var(--up)" : tone === "down" ? "var(--down)" : "var(--ember)";
  return (
    <div className="panel-2 p-4">
      <div className="label mb-2.5" style={{ color }}>
        {title}
      </div>
      <ul className="flex flex-col gap-2">
        {items.map((it) => (
          <li key={it} className="text-[12.5px] leading-relaxed" style={{ color: "var(--ink-2)" }}>
            • {it}
          </li>
        ))}
      </ul>
    </div>
  );
}
