"use client";

// App views part 2: Portfolio, Intelligence, Alerts, Settings (+admin).
import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, Bell, Check, KeyRound, LogOut, Plug, ShieldCheck, Sparkles, TrendingUp } from "lucide-react";
import { AreaChart, CHART_COLORS, ConvictionDial, Donut } from "@/components/jexi/charts";
import { Delta, EmptyState, KindDot, Panel, Pill, SectionTitle, Stat } from "@/components/jexi/bits";
import {
  AccountInfo,
  AdminOverview,
  Profits,
  UNIVERSE,
  demoThesis,
  fetchKeys,
  money,
  moneyCompact,
  priceFmt,
  requestWithdrawal,
  saveKeys,
  serverHealth,
  setServerUrl,
  symbolName,
  timeAgo,
  useLocalList,
  useQuotes,
} from "@/lib/jexi/data";

type Go = (view: string, symbol?: string) => void;

// ---------------- Portfolio ----------------

export function PortfolioView({ go, token, account, profits, isDemo }: {
  go: Go;
  token: string | null;
  account: AccountInfo | null;
  profits: Profits | null;
  isDemo: boolean;
}) {
  const positions = account?.positions || [];
  const slices = positions
    .map((p, i) => ({ label: p.symbol, value: p.value, color: CHART_COLORS[i % CHART_COLORS.length] }))
    .concat(positions.length ? [{ label: "Cash", value: account?.cash || 0, color: "#35302a" }] : []);

  return (
    <div className="view-enter">
      <SectionTitle sub={isDemo ? "demo data — sign in for the real thing" : `paper account · ${account?.mode || "paper"}`}>
        Portfolio
      </SectionTitle>

      <div className="grid gap-4 lg:grid-cols-[1.5fr_1fr]">
        <Panel>
          <div className="flex flex-wrap items-end justify-between gap-4">
            <div>
              <div className="label">Total equity</div>
              <div className="mt-1 flex items-baseline gap-3">
                <span className="data text-[40px] leading-none tracking-tight">{money(account?.equity ?? 10000)}</span>
                {account && <Delta value={account.pnlPct} size={15} />}
              </div>
              <div className="mt-1.5 text-[13px]" style={{ color: "var(--ink-3)" }}>
                {account ? `${money(account.pnl)} since you started (${money(account.startingBalance, 0)} baseline)` : "Demo baseline $10,000"}
              </div>
            </div>
            {!isDemo && profits && (
              <div className="flex gap-6">
                <Stat label="Total P&L" value={<span style={{ color: profits.totalPnl >= 0 ? "var(--up)" : "var(--down)" }}>{money(profits.totalPnl)}</span>} />
                <Stat label="Win rate" value={`${profits.winRate}%`} sub={`${profits.wins}W · ${profits.losses}L`} />
              </div>
            )}
          </div>
          <div className="mt-5">
            {profits?.equityCurve && profits.equityCurve.length > 3 ? (
              <AreaChart data={profits.equityCurve.map((p) => p.equity)} height={220} fmt={(v) => money(v)} />
            ) : (
              <div className="flex items-center justify-center" style={{ height: 220 }}>
                <div className="text-center">
                  <Pill tone="brand">Demo</Pill>
                  <p className="mx-auto mt-3 max-w-[380px] text-[13px] leading-relaxed" style={{ color: "var(--ink-3)" }}>
                    The equity curve draws from your account&apos;s real snapshots. Sign in and let the
                    engine run for a day — this panel fills with your history.
                  </p>
                </div>
              </div>
            )}
          </div>
        </Panel>

        <div className="flex flex-col gap-4">
          <Panel>
            <div className="label mb-3">Allocation</div>
            {positions.length ? (
              <div className="flex items-center gap-5">
                <Donut slices={slices} />
                <div className="flex flex-col gap-1.5">
                  {slices.map((s) => (
                    <div key={s.label} className="flex items-center gap-2 text-[12.5px]">
                      <span className="h-2.5 w-2.5 rounded-[3px]" style={{ background: s.color }} />
                      <span className="data" style={{ color: "var(--ink)" }}>
                        {s.label.replace("-USD", "")}
                      </span>
                      <span style={{ color: "var(--ink-3)" }}>{moneyCompact(s.value)}</span>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <EmptyState title="Nothing allocated" body="When JEXI opens positions, your allocation by symbol appears here." />
            )}
          </Panel>

          <WithdrawCard token={token} account={account} isDemo={isDemo} />
        </div>
      </div>

      <Panel className="mt-4" pad={false}>
        <div className="flex items-center justify-between px-5 py-4">
          <SectionTitle sub={isDemo ? "demo" : "live"}>Holdings</SectionTitle>
        </div>
        {positions.length ? (
          <div className="flex flex-col px-2 pb-2">
            {positions.map((p) => (
              <button key={p.symbol} className="row-link flex items-center justify-between rounded-xl px-3 py-3 text-left" onClick={() => go("asset", p.symbol)}>
                <div>
                  <div className="data text-[14px]">{p.symbol}</div>
                  <div className="text-[12px]" style={{ color: "var(--ink-3)" }}>
                    {symbolName(p.symbol)} · {p.qty} @ {priceFmt(p.avgPrice)}
                  </div>
                </div>
                <div className="flex items-center gap-6">
                  <div className="text-right">
                    <div className="data text-[14px]">{money(p.value)}</div>
                    <div className="text-[11.5px]" style={{ color: "var(--ink-3)" }}>
                      now {priceFmt(p.lastPrice)}
                    </div>
                  </div>
                  <div className="w-[90px] text-right">
                    <Delta value={((p.lastPrice - p.avgPrice) / p.avgPrice) * 100} />
                    <div className="data mt-0.5 text-[12px]" style={{ color: p.pnl >= 0 ? "var(--up)" : "var(--down)" }}>
                      {p.pnl >= 0 ? "+" : ""}
                      {money(p.pnl)}
                    </div>
                  </div>
                </div>
              </button>
            ))}
          </div>
        ) : (
          <div className="px-5 pb-6">
            <EmptyState
              title={isDemo ? "Demo has no holdings" : "No open positions yet"}
              body="JEXI buys only uptrends above the 10-day average, caps exposure at 6 positions, and draws a safety line under every trade."
              action={
                <button className="btn btn-ghost" onClick={() => go(isDemo ? "auth" : "markets")}>
                  {isDemo ? "Create your account" : "Explore markets"}
                </button>
              }
            />
          </div>
        )}
      </Panel>
    </div>
  );
}

function WithdrawCard({ token, account, isDemo }: { token: string | null; account: AccountInfo | null; isDemo: boolean }) {
  const [amount, setAmount] = useState("");
  const [dest, setDest] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setMsg(null);
    setBusy(true);
    try {
      const r = await requestWithdrawal(token!, Number(amount), "bank", dest);
      setMsg({ ok: true, text: `Approved. Remaining cash: $${(r as { remainingCash: number }).remainingCash?.toFixed(2) ?? "—"}` });
      setAmount("");
      setDest("");
    } catch (e) {
      setMsg({ ok: false, text: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Panel>
      <div className="label mb-3 flex items-center gap-2">
        <Sparkles size={13} style={{ color: "var(--gold)" }} /> Withdrawals
      </div>
      {isDemo ? (
        <p className="text-[13px] leading-relaxed" style={{ color: "var(--ink-3)" }}>
          Sign in to withdraw from your real paper balance — up to 50% of equity per request, straight from the app.
        </p>
      ) : (
        <div className="flex flex-col gap-2.5">
          <div className="grid grid-cols-2 gap-2.5">
            <input className="input" placeholder="Amount ($)" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} />
            <input className="input" placeholder="Destination (bank/wallet)" value={dest} onChange={(e) => setDest(e.target.value)} />
          </div>
          <button className="btn btn-primary" onClick={submit} disabled={busy || !amount || !dest}>
            {busy ? "Sending…" : "Request withdrawal"}
          </button>
          <div className="text-[11.5px]" style={{ color: "var(--ink-3)" }}>
            Limit: 50% of equity ({money((account?.equity || 0) * 0.5)}) · free cash: {money(account?.cash || 0)}
          </div>
          {msg && (
            <div
              className="rounded-lg px-3 py-2 text-[12.5px]"
              style={{
                background: `color-mix(in srgb, ${msg.ok ? "var(--up)" : "var(--down)"} 9%, transparent)`,
                color: msg.ok ? "var(--up)" : "var(--down)",
              }}
            >
              {msg.text}
            </div>
          )}
        </div>
      )}
    </Panel>
  );
}

// ---------------- Intelligence ----------------

const PIPELINE = [
  { r: "RESEARCH ANALYST", role: "Fundamental analysis", pts: ["Business quality and moat", "Valuation vs. growth", "Balance-sheet strength"] },
  { r: "TECHNICAL ANALYST", role: "Price and momentum", pts: ["Trend vs. 10-day average", "Volume confirmation", "Support and resistance map"] },
  { r: "MACRO ANALYST", role: "Environment", pts: ["Rate path sensitivity", "Sector rotation context", "Liquidity conditions"] },
  { r: "RISK ANALYST", role: "Downside first", pts: ["Worst case in dollars", "Correlation to holdings", "Exit lines drawn pre-entry"] },
  { r: "NEWS ANALYST", role: "Events and catalysts", pts: ["Earnings timing", "Product and policy events", "Sentiment shifts"] },
  { r: "VERIFIER", role: "Evidence check", pts: ["Data vs. interpretation split", "Conflicting evidence surfaced", "Confidence calibrated"] },
];

export function IntelligenceView({ go }: { go: Go }) {
  const [watchlist] = useLocalList<string[]>("jexi.watchlist", ["NVDA", "AAPL", "MSFT", "TSLA"]);
  const [symbol, setSymbol] = useState(watchlist[0] || "NVDA");
  const thesis = demoThesis(symbol);

  return (
    <div className="view-enter">
      <SectionTitle sub="research → analysis → evidence → thesis">AI market intelligence</SectionTitle>

      <div className="mb-4 flex flex-wrap gap-2">
        {watchlist.map((s) => (
          <button
            key={s}
            onClick={() => setSymbol(s)}
            className="rounded-lg px-3.5 py-2 text-[13px] font-medium transition-all"
            style={{
              background: symbol === s ? "var(--panel-3)" : "var(--panel)",
              border: `1px solid ${symbol === s ? "var(--line)" : "var(--line-soft)"}`,
              color: symbol === s ? "var(--ink)" : "var(--ink-2)",
            }}
          >
            {s.replace("-USD", "")}
          </button>
        ))}
        <button className="btn btn-line" style={{ minHeight: 38 }} onClick={() => go("markets")}>
          + more
        </button>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="flex flex-col gap-3 lg:col-span-2">
          <div className="grid gap-3 sm:grid-cols-2">
            {PIPELINE.map((a, i) => (
              <Panel key={a.r} className="p-4">
                <div className="flex items-center justify-between">
                  <span className="text-[11px] font-semibold tracking-[0.1em]" style={{ color: "var(--peach)" }}>
                    {a.r}
                  </span>
                  <Pill tone="up">
                    <Check size={11} /> done
                  </Pill>
                </div>
                <div className="mt-1 text-[12px]" style={{ color: "var(--ink-3)" }}>
                  {a.role}
                </div>
                <ul className="mt-2.5 flex flex-col gap-1.5">
                  {a.pts.map((p) => (
                    <li key={p} className="text-[12.5px]" style={{ color: "var(--ink-2)" }}>
                      · {p}
                    </li>
                  ))}
                </ul>
                <div className="mt-3 flex items-center gap-2">
                  <div className="h-1 flex-1 overflow-hidden rounded-full" style={{ background: "var(--panel-3)" }}>
                    <div className="h-full rounded-full" style={{ width: `${88 + ((i * 7) % 12)}%`, background: "linear-gradient(90deg, var(--ember), var(--peach))" }} />
                  </div>
                  <span className="text-[10.5px]" style={{ color: "var(--ink-3)" }}>
                    step {i + 1}/6
                  </span>
                </div>
              </Panel>
            ))}
          </div>

          {/* thesis */}
          <Panel>
            <div className="flex items-center justify-between">
              <SectionTitle sub={`on ${symbolName(symbol)}`}>Final thesis</SectionTitle>
              <Pill tone="brand">Demo</Pill>
            </div>
            <div className="flex flex-wrap items-center gap-6">
              <ConvictionDial value={thesis.conviction} size={110} />
              <div className="min-w-[180px]">
                <div className="label">Stance</div>
                <div
                  className="display text-[30px]"
                  style={{ color: thesis.stance === "Bullish" ? "var(--up)" : thesis.stance === "Cautious" ? "var(--down)" : "var(--sand)" }}
                >
                  {thesis.stance}
                </div>
                <div className="mt-1 text-[12.5px]" style={{ color: "var(--ink-3)" }}>
                  Last verified format demo · analysts involved: 6
                </div>
              </div>
            </div>
            <div className="mt-5 grid gap-3 sm:grid-cols-3">
              {[
                { t: "Drivers", tone: "up", items: thesis.drivers },
                { t: "Risks", tone: "down", items: thesis.risks },
                { t: "Catalysts", tone: "brand", items: thesis.catalysts },
              ].map((g) => (
                <div key={g.t} className="panel-2 p-4">
                  <div className="label mb-2" style={{ color: g.tone === "up" ? "var(--up)" : g.tone === "down" ? "var(--down)" : "var(--ember)" }}>
                    {g.t}
                  </div>
                  <ul className="flex flex-col gap-1.5">
                    {g.items.map((it) => (
                      <li key={it} className="text-[12.5px] leading-relaxed" style={{ color: "var(--ink-2)" }}>
                        • {it}
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          </Panel>
        </div>

        {/* evidence + data honesty */}
        <div className="flex flex-col gap-4">
          <Panel>
            <div className="label mb-3">Evidence ledger</div>
            <div className="flex flex-col gap-3">
              {[
                { k: "DATA", v: "Daily closes from the live server quote chain (Yahoo → Stooq fallback)", tone: "var(--up)" },
                { k: "ANALYSIS", v: "Trend vs. 10-day average; regime from index proxy breadth", tone: "var(--peach)" },
                { k: "INTERPRETATION", v: "Thesis stance and conviction — clearly separated from raw data", tone: "var(--ember)" },
                { k: "CONFLICTS", v: "Bull vs. bear evidence shown side by side; nothing hidden", tone: "var(--gold)" },
              ].map((e) => (
                <div key={e.k} className="panel-2 px-3.5 py-3">
                  <div className="text-[10.5px] font-semibold tracking-[0.12em]" style={{ color: e.tone }}>
                    {e.k}
                  </div>
                  <div className="mt-1 text-[12.5px] leading-relaxed" style={{ color: "var(--ink-2)" }}>
                    {e.v}
                  </div>
                </div>
              ))}
            </div>
          </Panel>
          <Panel>
            <div className="label mb-2 flex items-center gap-2">
              <ShieldCheck size={13} style={{ color: "var(--up)" }} /> Data honesty
            </div>
            <p className="text-[12.5px] leading-relaxed" style={{ color: "var(--ink-2)" }}>
              Theses in this view demonstrate the format. Connect your AI key in Settings and JEXI
              generates live, model-driven research for your watchlist — with the same structure,
              the same evidence split, and no fabricated numbers.
            </p>
            <button className="btn btn-ghost mt-4 w-full" onClick={() => go("settings")}>
              <KeyRound size={15} /> Connect your AI key
            </button>
          </Panel>
        </div>
      </div>
    </div>
  );
}

// ---------------- Alerts ----------------

interface Alert {
  id: number;
  symbol: string;
  op: ">" | "<";
  price: number;
  triggeredAt?: string;
}

export function AlertsView({ go }: { go: Go }) {
  const symbols = useMemo(() => UNIVERSE.map((u) => u.s), []);
  const { quotes } = useQuotes(symbols, 25000);
  const [alerts, setAlerts] = useLocalList<Alert[]>("jexi.alerts", []);
  const [symbol, setSymbol] = useState("AAPL");
  const [op, setOp] = useState<">" | "<">(">");
  const [price, setPrice] = useState("");

  useEffect(() => {
    // evaluate triggers on each quotes refresh
    setAlerts((list) =>
      list.map((a) => {
        const p = quotes[a.symbol]?.price;
        if (p === undefined || a.triggeredAt) return a;
        const hit = a.op === ">" ? p >= a.price : p <= a.price;
        return hit ? { ...a, triggeredAt: new Date().toISOString() } : a;
      })
    );
     
  }, [quotes]);

  const add = () => {
    const p = Number(price);
    if (!Number.isFinite(p) || p <= 0) return;
    setAlerts([{ id: Date.now(), symbol, op, price: p }, ...alerts]);
    setPrice("");
  };

  return (
    <div className="view-enter">
      <SectionTitle sub="checked against live prices every 25s">Price alerts</SectionTitle>

      <Panel className="mb-4">
        <div className="flex flex-wrap items-end gap-2.5">
          <div className="min-w-[130px] flex-1">
            <div className="label mb-1.5">Symbol</div>
            <select className="input" value={symbol} onChange={(e) => setSymbol(e.target.value)}>
              {UNIVERSE.map((u) => (
                <option key={u.s} value={u.s}>
                  {u.s} — {u.name}
                </option>
              ))}
            </select>
          </div>
          <div>
            <div className="label mb-1.5">When</div>
            <select className="input" value={op} onChange={(e) => setOp(e.target.value as ">" | "<")}>
              <option value=">">price rises above</option>
              <option value="<">price falls below</option>
            </select>
          </div>
          <div className="w-[130px]">
            <div className="label mb-1.5">Price ($)</div>
            <input className="input" inputMode="decimal" placeholder="0.00" value={price} onChange={(e) => setPrice(e.target.value)} />
          </div>
          <button className="btn btn-primary" onClick={add} disabled={!price}>
            <Bell size={15} /> Create alert
          </button>
        </div>
      </Panel>

      {alerts.length === 0 ? (
        <Panel>
          <EmptyState
            icon={<Bell size={18} />}
            title="No alerts yet"
            body="Alerts run locally against live server prices — for example: NVDA rises above $240, or BTC-USD falls below $90,000."
          />
        </Panel>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2">
          {alerts.map((a) => {
            const p = quotes[a.symbol]?.price;
            const live = a.triggeredAt || (p !== undefined && (a.op === ">" ? p >= a.price : p <= a.price));
            return (
              <Panel key={a.id} className="flex items-center justify-between p-4">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="data text-[14.5px]">{a.symbol.replace("-USD", "")}</span>
                    {live && <Pill tone="gold">triggered</Pill>}
                  </div>
                  <div className="mt-1 text-[13px]" style={{ color: "var(--ink-2)" }}>
                    {a.op === ">" ? "rises above" : "falls below"} <span className="data">{priceFmt(a.price)}</span>
                    {p !== undefined && (
                      <span style={{ color: "var(--ink-3)" }}>
                        {" "}
                        · now {priceFmt(p)}
                      </span>
                    )}
                  </div>
                  {a.triggeredAt && (
                    <div className="mt-1 text-[11.5px]" style={{ color: "var(--gold)" }}>
                      fired {timeAgo(a.triggeredAt)}
                    </div>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  <button className="btn btn-line" style={{ minHeight: 36 }} onClick={() => go("asset", a.symbol)}>
                    Open
                  </button>
                  <button
                    className="btn btn-line"
                    style={{ minHeight: 36, color: "var(--down)" }}
                    onClick={() => setAlerts(alerts.filter((x) => x.id !== a.id))}
                  >
                    ✕
                  </button>
                </div>
              </Panel>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ---------------- Settings (+ admin) ----------------

export function SettingsView({ go, token, user, isAdmin, signOut }: {
  go: Go;
  token: string | null;
  user: { id: number; email: string; name: string; role?: string } | null;
  isAdmin: boolean;
  signOut: () => void;
}) {
  const [url, setUrl] = useState("");
  const [health, setHealth] = useState<"unknown" | "checking" | "ok" | "fail">("unknown");
  const [keys, setKeys] = useState<{ set: boolean; aiProvider?: string; aiKeyMasked?: string; brokerName?: string; brokerKeySet?: boolean } | null>(null);
  const [aiProvider, setAiProvider] = useState("gemini");
  const [aiKey, setAiKey] = useState("");
  const [brokerName, setBrokerName] = useState("alpaca");
  const [brokerKey, setBrokerKey] = useState("");
  const [brokerSecret, setBrokerSecret] = useState("");
  const [keysMsg, setKeysMsg] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => {
    import("@/lib/jexi/data").then((m) => setUrl(m.getServerUrl()));
    if (token) fetchKeys(token).then(setKeys).catch(() => {});
  }, [token]);

  const check = async () => {
    setHealth("checking");
    setServerUrl(url);
    await new Promise((r) => setTimeout(r, 150));
    const ok = await serverHealth();
    setHealth(ok ? "ok" : "fail");
  };

  const submitKeys = async () => {
    setKeysMsg(null);
    try {
      await saveKeys(token!, { aiProvider, aiKey, brokerName, brokerKey, brokerSecret });
      setKeysMsg({ ok: true, text: "Keys saved — encrypted with AES-256 and stored only for your account." });
      setAiKey("");
      setBrokerKey("");
      setBrokerSecret("");
      fetchKeys(token!).then(setKeys).catch(() => {});
    } catch (e) {
      setKeysMsg({ ok: false, text: (e as Error).message });
    }
  };

  return (
    <div className="view-enter">
      <SectionTitle sub="account, connection, keys">Settings</SectionTitle>
      <div className="grid gap-4 lg:grid-cols-2">
        {/* profile */}
        <Panel>
          <div className="label mb-3">Profile</div>
          {user ? (
            <div className="flex items-center justify-between">
              <div>
                <div className="text-[16px] font-semibold">{user.name || "Jexi user"}</div>
                <div className="text-[13px]" style={{ color: "var(--ink-3)" }}>
                  {user.email}
                </div>
              </div>
              <div className="flex items-center gap-2.5">
                {isAdmin && <Pill tone="gold"><ShieldCheck size={11} /> admin</Pill>}
                <Pill tone="up">signed in</Pill>
              </div>
            </div>
          ) : (
            <div className="flex items-center justify-between">
              <div className="text-[13.5px]" style={{ color: "var(--ink-2)" }}>
                Browsing as guest — data is demo-only.
              </div>
              <button className="btn btn-primary" style={{ minHeight: 38 }} onClick={() => go("auth")}>
                Sign in
              </button>
            </div>
          )}
          {user && (
            <button className="btn btn-line mt-4 w-full" onClick={signOut}>
              <LogOut size={14} /> Sign out
            </button>
          )}
        </Panel>

        {/* server connection */}
        <Panel>
          <div className="label mb-3 flex items-center gap-2">
            <Plug size={13} /> Server connection
          </div>
          <div className="flex gap-2.5">
            <input className="input" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://jexi-server.vercel.app" />
            <button className="btn btn-ghost" onClick={check} disabled={health === "checking"}>
              {health === "checking" ? "…" : "Test"}
            </button>
          </div>
          <div className="mt-3 flex items-center gap-2 text-[13px]">
            {health === "ok" && <Pill tone="up"><Check size={11} /> connected — D1 database live</Pill>}
            {health === "fail" && <Pill tone="down"><AlertTriangle size={11} /> unreachable</Pill>}
            {health === "unknown" && <span style={{ color: "var(--ink-3)" }}>Default: the deployed Jexi server.</span>}
            {health === "checking" && <span style={{ color: "var(--ink-3)" }}>Checking…</span>}
          </div>
        </Panel>

        {/* keys */}
        <Panel className="lg:col-span-2">
          <div className="label mb-1 flex items-center gap-2">
            <KeyRound size={13} /> Your two keys
          </div>
          <p className="mb-4 text-[12.5px]" style={{ color: "var(--ink-3)" }}>
            {keys?.set
              ? `Saved: AI brain ${keys.aiProvider} (${keys.aiKeyMasked}) · broker ${keys.brokerName}${keys.brokerKeySet ? " (key set)" : ""}. Keys never leave the server unmasked.`
              : "JEXI needs an AI brain and a broker to trade for you. Keys are AES-256 encrypted at rest and shown masked forever."}
          </p>
          {token ? (
            <>
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="panel-2 p-4">
                  <div className="label mb-2.5">AI model key (Gemini or any)</div>
                  <select className="input mb-2.5" value={aiProvider} onChange={(e) => setAiProvider(e.target.value)}>
                    {["gemini", "openai", "anthropic", "groq", "deepseek", "openrouter"].map((p) => (
                      <option key={p} value={p}>
                        {p}
                      </option>
                    ))}
                  </select>
                  <input className="input" type="password" placeholder="AI API key" value={aiKey} onChange={(e) => setAiKey(e.target.value)} />
                </div>
                <div className="panel-2 p-4">
                  <div className="label mb-2.5">Trading account key (broker)</div>
                  <select className="input mb-2.5" value={brokerName} onChange={(e) => setBrokerName(e.target.value)}>
                    {["alpaca", "binance", "paper", "interactive-brokers", "td-ameritrade"].map((p) => (
                      <option key={p} value={p}>
                        {p}
                      </option>
                    ))}
                  </select>
                  <div className="grid gap-2">
                    <input className="input" type="password" placeholder="Broker API key" value={brokerKey} onChange={(e) => setBrokerKey(e.target.value)} />
                    <input className="input" type="password" placeholder="Broker secret (optional)" value={brokerSecret} onChange={(e) => setBrokerSecret(e.target.value)} />
                  </div>
                </div>
              </div>
              <div className="mt-4 flex items-center gap-3">
                <button className="btn btn-primary" onClick={submitKeys} disabled={!aiKey || !brokerKey}>
                  Save keys (encrypted)
                </button>
                {keysMsg && (
                  <span className="text-[12.5px]" style={{ color: keysMsg.ok ? "var(--up)" : "var(--down)" }}>
                    {keysMsg.text}
                  </span>
                )}
              </div>
            </>
          ) : (
            <button className="btn btn-ghost" onClick={() => go("auth")}>
              Sign in to manage keys
            </button>
          )}
        </Panel>
      </div>

      {isAdmin && <AdminPanel token={token} />}
    </div>
  );
}

function AdminPanel({ token }: { token: string | null }) {
  const [overview, setOverview] = useState<AdminOverview | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [tab, setTab] = useState<"users" | "trades" | "withdrawals">("users");

  useEffect(() => {
    if (!token) return;
    import("@/lib/jexi/data").then((m) =>
      m.api<AdminOverview>("/api/admin/overview", { token }).then(setOverview).catch((e) => setErr(e.message))
    );
  }, [token]);

  if (!token) return null;
  return (
    <Panel className="mt-4" pad={false}>
      <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-4">
        <div className="flex items-center gap-2.5">
          <Pill tone="gold"><ShieldCheck size={11} /> admin</Pill>
          <span className="text-[14px] font-semibold">Server control room</span>
        </div>
        <div className="flex gap-1.5">
          {(["users", "trades", "withdrawals"] as const).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className="rounded-lg px-3 py-1.5 text-[12.5px] capitalize"
              style={{
                background: tab === t ? "var(--panel-3)" : "transparent",
                color: tab === t ? "var(--ink)" : "var(--ink-3)",
                border: `1px solid ${tab === t ? "var(--line)" : "transparent"}`,
              }}
            >
              {t}
            </button>
          ))}
        </div>
      </div>

      {err && (
        <div className="px-5 pb-4 text-[13px]" style={{ color: "var(--down)" }}>
          {err}
        </div>
      )}

      {overview && (
        <>
          <div className="grid grid-cols-2 gap-4 border-t px-5 py-4 sm:grid-cols-4" style={{ borderColor: "var(--line-soft)" }}>
            <Stat label="Users" value={overview.totals.users} />
            <Stat label="Total equity" value={money(overview.totals.equity)} />
            <Stat label="Cash on server" value={money(overview.totals.cash)} />
            <Stat label="In positions" value={money(overview.totals.positions)} />
          </div>

          <div className="border-t px-2 pb-2" style={{ borderColor: "var(--line-soft)" }}>
            {tab === "users" && (
              <div className="flex flex-col">
                {overview.users.map((u) => (
                  <div key={u.id} className="row-link flex items-center justify-between rounded-xl px-3 py-2.5">
                    <div className="flex items-center gap-3">
                      <span className="data text-[13.5px]">{u.email}</span>
                      {u.isAdmin && <Pill tone="gold">admin</Pill>}
                    </div>
                    <div className="flex items-center gap-6 text-right">
                      <span className="data text-[13.5px]">{money(u.equity)}</span>
                      <span className="data w-[86px] text-[13px]" style={{ color: u.pnl >= 0 ? "var(--up)" : "var(--down)" }}>
                        {u.pnl >= 0 ? "+" : ""}
                        {money(u.pnl)}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            )}
            {tab === "trades" && (
              <div className="flex flex-col">
                {overview.recentTrades.map((t) => (
                  <div key={t.id} className="row-link flex items-center justify-between rounded-xl px-3 py-2.5">
                    <div className="flex items-center gap-3">
                      <Pill tone={t.side === "BUY" ? "up" : "down"}>{t.side}</Pill>
                      <span className="data text-[13.5px]">{t.symbol}</span>
                      <span className="text-[12px]" style={{ color: "var(--ink-3)" }}>
                        {t.email}
                      </span>
                    </div>
                    <div className="flex items-center gap-5">
                      <span className="data text-[13px]">
                        {t.qty} @ {priceFmt(t.price)}
                      </span>
                      <span className="text-[11.5px]" style={{ color: "var(--ink-3)" }}>
                        {timeAgo(t.createdAt)}
                      </span>
                    </div>
                  </div>
                ))}
                {!overview.recentTrades.length && <div className="px-4 py-6 text-center text-[13px]" style={{ color: "var(--ink-3)" }}>No trades yet.</div>}
              </div>
            )}
            {tab === "withdrawals" && (
              <div className="flex flex-col">
                {overview.withdrawals.map((w) => (
                  <div key={w.id} className="row-link flex items-center justify-between rounded-xl px-3 py-2.5">
                    <div className="flex items-center gap-3">
                      <Pill tone="gold">{w.status}</Pill>
                      <span className="text-[13px]" style={{ color: "var(--ink-2)" }}>
                        {w.email}
                      </span>
                    </div>
                    <div className="flex items-center gap-5">
                      <span className="data text-[13.5px]">{money(w.amount)}</span>
                      <span className="text-[11.5px]" style={{ color: "var(--ink-3)" }}>
                        {timeAgo(w.createdAt)}
                      </span>
                    </div>
                  </div>
                ))}
                {!overview.withdrawals.length && <div className="px-4 py-6 text-center text-[13px]" style={{ color: "var(--ink-3)" }}>No withdrawals yet.</div>}
              </div>
            )}
          </div>
        </>
      )}
      {!overview && !err && (
        <div className="flex items-center gap-2 px-5 pb-5 text-[13px]" style={{ color: "var(--ink-3)" }}>
          <TrendingUp size={14} /> Loading control room…
        </div>
      )}
    </Panel>
  );
}
