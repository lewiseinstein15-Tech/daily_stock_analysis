"use client";

// App views part 2: Portfolio, Intelligence, Alerts, Settings (+admin).
import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, ArrowRight, Bell, Bitcoin, Check, CheckCircle2, CreditCard, Inbox, KeyRound, Landmark, LogOut, Plug, RefreshCw, Search, ShieldCheck, Smartphone, Sparkles, TrendingDown, TrendingUp, Wallet, X, XCircle } from "lucide-react";
import { AreaChart, CHART_COLORS, ConvictionDial, Donut } from "@/components/jexi/charts";
import { Delta, EmptyState, LiveDot, Panel, Pill, SectionTitle, Stat } from "@/components/jexi/bits";
import {
  AccountInfo,
  DepositRow,
  Profits,
  UNIVERSE,
  adminDecide,
  checkAppUpdate,
  fetchDeposits,
  fetchKeys,
  installAppUpdate,
  money,
  moneyCompact,
  priceFmt,
  requestDeposit,
  requestWithdrawal,
  saveKeys,
  serverHealth,
  setServerUrl,
  setTradingMode,
  symbolName,
  timeAgo,
  useAdmin,
  useAnalysis,
  useLocalList,
  useNotifications,
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
      <SectionTitle sub={isDemo ? "your account lives behind sign-in" : `${account?.mode === "live" ? "LIVE" : "paper"} account · real market prices`}>
        Portfolio
      </SectionTitle>

      <div className="grid gap-4 lg:grid-cols-[1.5fr_1fr]">
        <Panel>
          {isDemo ? (
            <div className="flex min-h-[280px] flex-col items-start justify-center">
              <div className="label">Total equity</div>
              <div className="display mt-2 text-[28px] leading-snug">Your $10,000 paper account is one sign-in away</div>
              <p className="mt-3 max-w-[440px] text-[13.5px] leading-relaxed" style={{ color: "var(--ink-2)" }}>
                Create a free account with email or Google and JEXI opens a real paper account
                instantly — equity curve, allocation, holdings and withdrawals all come from it,
                live. No fake numbers here, just your data once it exists.
              </p>
              <button className="btn btn-primary mt-5" onClick={() => go("auth")}>
                Create your account <ArrowRight size={15} />
              </button>
            </div>
          ) : (
            <>
              <div className="flex flex-wrap items-end justify-between gap-4">
                <div>
                  <div className="label">Total equity</div>
                  <div className="mt-1 flex items-baseline gap-3">
                    <span className="data text-[40px] leading-none tracking-tight">{money(account?.equity ?? 0)}</span>
                    {account && <Delta value={account.pnlPct} size={15} />}
                  </div>
                  <div className="mt-1.5 text-[13px]" style={{ color: "var(--ink-3)" }}>
                    {account
                      ? `${money(account.pnl)} since you started (${money(account.startingBalance, 0)} baseline)`
                      : "Syncing your account…"}
                  </div>
                </div>
                {profits && (
                  <div className="flex gap-6">
                    <Stat label="Total P&L" value={<span style={{ color: profits.totalPnl >= 0 ? "var(--up)" : "var(--down)", fontSize: "15px" }}>{money(profits.totalPnl)}</span>} />
                    <Stat label="Win rate" value={<span style={{ fontSize: "15px" }}>{`${profits.winRate}%`}</span>} sub={`${profits.wins}W · ${profits.losses}L`} />
                  </div>
                )}
              </div>
              <div className="mt-5">
                {profits?.equityCurve && profits.equityCurve.length > 3 ? (
                  <AreaChart data={profits.equityCurve.map((p) => p.equity)} height={220} fmt={(v) => money(v)} />
                ) : (
                  <div className="flex items-center justify-center" style={{ height: 220 }}>
                    <div className="text-center">
                      <p className="mx-auto mt-3 max-w-[380px] text-[13px] leading-relaxed" style={{ color: "var(--ink-3)" }}>
                        The equity curve draws from your account&apos;s real snapshots. Let the
                        engine run for a day — this panel fills with your history.
                      </p>
                    </div>
                  </div>
                )}
              </div>
            </>
          )}
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

          <TradingModeCard token={token} account={account} isDemo={isDemo} />
          <DepositCard token={token} account={account} isDemo={isDemo} />
          <WithdrawCard token={token} account={account} isDemo={isDemo} />
        </div>
      </div>

      <Panel className="mt-4" pad={false}>
        <div className="flex items-center justify-between px-5 py-4">
          <SectionTitle sub={isDemo ? "members only" : "live"}>Holdings</SectionTitle>
        </div>
        {isDemo ? (
          <div className="px-5 pb-6">
            <EmptyState
              title="Holdings belong to your account"
              body="Sign in and every position the engine opens for you appears here with live P&L."
              action={
                <button className="btn btn-ghost" onClick={() => go("auth")}>
                  Create your account
                </button>
              }
            />
          </div>
        ) : positions.length ? (
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
              title="No open positions yet"
              body="JEXI buys only uptrends above the 10-day average, caps exposure at 6 positions, and draws a safety line under every trade."
              action={
                <button className="btn btn-ghost" onClick={() => go("markets")}>
                  Explore markets
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

// ---------------- Trading mode (paper <-> live) ----------------

function TradingModeCard({ token, account, isDemo }: { token: string | null; account: AccountInfo | null; isDemo: boolean }) {
  const mode = account?.mode === "live" ? "live" : "paper";
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  const switchTo = async (target: "paper" | "live") => {
    setMsg(null);
    setBusy(true);
    setConfirming(false);
    try {
      await setTradingMode(token!, target);
      setMsg({
        ok: true,
        text:
          target === "live"
            ? "Live mode is on. Jexi now trades your real broker account with the keys saved in Settings."
            : "Back to paper. Your live book is parked and stays exactly as you left it.",
      });
      // nudge the parent data to refresh
      window.dispatchEvent(new Event("jexi.account-changed"));
      setReloadKey((k) => k + 1);
    } catch (e) {
      setMsg({ ok: false, text: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Panel>
      <div className="label mb-3 flex items-center gap-2">
        <Landmark size={13} /> Trading mode
      </div>
      {isDemo ? (
        <p className="text-[13px] leading-relaxed" style={{ color: "var(--ink-3)" }}>
          Sign in to choose how Jexi trades for you: a free paper account, or live mode through your own broker.
        </p>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-2">
            <button
              className="rounded-xl px-3 py-2.5 text-[13px] font-medium"
              style={{
                border: `1px solid ${mode === "paper" ? "var(--up)" : "var(--line)"}`,
                background: mode === "paper" ? "color-mix(in srgb, var(--up) 10%, transparent)" : "transparent",
                color: mode === "paper" ? "var(--up)" : "var(--ink-2)",
              }}
              onClick={() => mode !== "paper" && switchTo("paper")}
              disabled={busy || mode === "paper"}
            >
              Paper{mode === "paper" ? " · active" : ""}
            </button>
            <button
              className="rounded-xl px-3 py-2.5 text-[13px] font-medium"
              style={{
                border: `1px solid ${mode === "live" ? "var(--ember)" : "var(--line)"}`,
                background: mode === "live" ? "color-mix(in srgb, var(--ember) 12%, transparent)" : "transparent",
                color: mode === "live" ? "var(--ember)" : "var(--ink-2)",
              }}
              onClick={() => mode !== "live" && setConfirming(true)}
              disabled={busy || mode === "live"}
            >
              Live{mode === "live" ? " · active" : ""}
            </button>
          </div>

          {confirming && (
            <div className="mt-3 rounded-xl p-3.5" style={{ border: "1px solid var(--ember)", background: "color-mix(in srgb, var(--ember) 7%, transparent)" }}>
              <div className="text-[13px] font-semibold" style={{ color: "var(--ember)" }}>
                Switch to live trading?
              </div>
              <p className="mt-1.5 text-[12.5px] leading-relaxed" style={{ color: "var(--ink-2)" }}>
                Jexi will place real orders through the broker keys saved in Settings → Keys. Your live balance starts
                from your live deposits. Paper practice stays saved and separate.
              </p>
              <div className="mt-3 flex gap-2">
                <button className="btn btn-primary" style={{ minHeight: 36 }} disabled={busy} onClick={() => switchTo("live")}>
                  {busy ? "Switching…" : "Yes, go live"}
                </button>
                <button className="btn btn-line" style={{ minHeight: 36 }} onClick={() => setConfirming(false)} disabled={busy}>
                  <X size={13} /> Cancel
                </button>
              </div>
            </div>
          )}

          <p className="mt-3 text-[11.5px] leading-relaxed" style={{ color: "var(--ink-3)" }} key={reloadKey}>
            {mode === "live"
              ? `Live balance: ${money(account?.cash || 0)}${account?.pendingDeposits ? ` · ${money(account.pendingDeposits)} deposit on the way` : ""}`
              : "Paper is practice money — same engine, same rules, zero risk."}
          </p>

          {msg && (
            <div
              className="mt-2 rounded-lg px-3 py-2 text-[12.5px]"
              style={{
                background: `color-mix(in srgb, ${msg.ok ? "var(--up)" : "var(--down)"} 9%, transparent)`,
                color: msg.ok ? "var(--up)" : "var(--down)",
              }}
            >
              {msg.text}
            </div>
          )}
        </>
      )}
    </Panel>
  );
}

// ---------------- Deposits ----------------

const DEPOSIT_METHODS: { id: string; label: string; icon: React.ReactNode; hint: string }[] = [
  { id: "m-pesa", label: "M-Pesa", icon: <Smartphone size={13} />, hint: "your Safaricom number" },
  { id: "bank", label: "Bank", icon: <Landmark size={13} />, hint: "account or IBAN" },
  { id: "card", label: "Card", icon: <CreditCard size={13} />, hint: "visa/mastercard" },
  { id: "crypto", label: "Crypto", icon: <Bitcoin size={13} />, hint: "wallet address" },
];

function DepositCard({ token, account, isDemo }: { token: string | null; account: AccountInfo | null; isDemo: boolean }) {
  const mode = account?.mode === "live" ? "live" : "paper";
  const [amount, setAmount] = useState("");
  const [method, setMethod] = useState("m-pesa");
  const [dest, setDest] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [history, setHistory] = useState<DepositRow[]>([]);

  const loadHistory = () => {
    if (token) fetchDeposits(token).then((r) => setHistory(r.deposits.slice(0, 4))).catch(() => {});
  };
  useEffect(() => {
    loadHistory();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  const submit = async () => {
    setMsg(null);
    setBusy(true);
    try {
      const r = await requestDeposit(token!, Number(amount), method, dest);
      if (r.status === "approved") {
        setMsg({ ok: true, text: `Done — $${Number(amount).toFixed(2)} added to your ${mode} balance.` });
        window.dispatchEvent(new Event("jexi.account-changed"));
      } else {
        setMsg({ ok: true, text: "Deposit received. Jexi confirms live deposits before they land — you will get a notification here." });
      }
      setAmount("");
      setDest("");
      loadHistory();
    } catch (e) {
      setMsg({ ok: false, text: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Panel>
      <div className="label mb-3 flex items-center gap-2">
        <Wallet size={13} style={{ color: "var(--gold)" }} /> Deposit
      </div>
      {isDemo ? (
        <p className="text-[13px] leading-relaxed" style={{ color: "var(--ink-3)" }}>
          Sign in to deposit into your account — M-Pesa, bank, card or crypto — right here in Jexi. No other app needed.
        </p>
      ) : (
        <>
          <div className="flex flex-col gap-2.5">
            <div className="grid grid-cols-2 gap-2.5">
              <input className="input" placeholder="Amount ($)" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} />
              <select className="input" value={method} onChange={(e) => setMethod(e.target.value)}>
                {DEPOSIT_METHODS.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.label}
                  </option>
                ))}
              </select>
            </div>
            <input
              className="input"
              placeholder={DEPOSIT_METHODS.find((m) => m.id === method)?.hint || "Destination"}
              value={dest}
              onChange={(e) => setDest(e.target.value)}
            />
            <button className="btn btn-primary" onClick={submit} disabled={busy || !amount}>
              {busy ? "Sending…" : mode === "live" ? "Request live deposit" : "Add to paper balance"}
            </button>
            {mode === "live" && (
              <div className="text-[11.5px] leading-relaxed" style={{ color: "var(--ink-3)" }}>
                Live deposits are confirmed by the Jexi team before they land in your balance{account?.pendingDeposits ? ` — ${money(account.pendingDeposits)} pending now` : ""}.
              </div>
            )}
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
            {history.length > 0 && (
              <div className="mt-1 border-t pt-2" style={{ borderColor: "var(--line-soft)" }}>
                {history.map((d) => (
                  <div key={d.id} className="flex items-center justify-between py-1.5 text-[12px]">
                    <span style={{ color: "var(--ink-2)" }}>
                      {money(d.amount)} · {d.method}
                    </span>
                    <span className="flex items-center gap-2">
                      <Pill tone={d.status === "approved" ? "up" : d.status === "pending" ? "gold" : "down"}>{d.status}</Pill>
                      <span style={{ color: "var(--ink-3)" }}>{timeAgo(d.created_at)}</span>
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </>
      )}
    </Panel>
  );
}

// ---------------- Notifications (in-app center — replaces ntfy) ----------------

const KIND_STYLE: Record<string, { icon: React.ReactNode; color: string }> = {
  win: { icon: <TrendingUp size={15} />, color: "var(--up)" },
  loss: { icon: <TrendingDown size={15} />, color: "var(--down)" },
  warn: { icon: <AlertTriangle size={15} />, color: "var(--gold)" },
  money: { icon: <Wallet size={15} />, color: "var(--gold)" },
  plan: { icon: <Sparkles size={15} />, color: "var(--ink-2)" },
  info: { icon: <Bell size={15} />, color: "var(--ink-3)" },
};

export function NotificationsView({ token, isDemo }: { token: string | null; isDemo: boolean }) {
  const { events, markAllRead } = useNotifications(token);
  const [refresh, setRefresh] = useState(0);

  useEffect(() => {
    if (!token) return;
    // mark everything as read shortly after opening so the badge clears
    const t = setTimeout(markAllRead, 900);
    return () => clearTimeout(t);
  }, [token, markAllRead, refresh]);

  if (isDemo || !token) {
    return (
      <div className="view-enter">
        <SectionTitle sub="everything Jexi does, in one place">Notifications</SectionTitle>
        <Panel>
          <EmptyState
            icon={<Inbox size={18} />}
            title="Your notifications live here"
            body="Sign in and every trade, deposit, withdrawal and daily report Jexi produces arrives in this feed — in plain English, inside the app. Nothing goes to outside services anymore."
            action={
              <button className="btn btn-primary" onClick={() => (window.location.hash = "#/auth")}>
                Sign in
              </button>
            }
          />
        </Panel>
      </div>
    );
  }

  return (
    <div className="view-enter">
      <SectionTitle sub="trades, deposits, withdrawals, reports — all in plain English">Notifications</SectionTitle>
      <Panel pad={false}>
        <div className="flex items-center justify-between px-5 py-4">
          <div className="flex items-center gap-2.5">
            <LiveDot />
            <span className="text-[13px]" style={{ color: "var(--ink-3)" }}>
              updates every few seconds
            </span>
          </div>
          <button
            className="btn btn-line"
            style={{ minHeight: 32, paddingInline: 10 }}
            onClick={() => setRefresh((r) => r + 1)}
            aria-label="Refresh notifications"
            title="Refresh"
          >
            <RefreshCw size={13} />
          </button>
        </div>
        {events.length ? (
          <div className="flex flex-col border-t px-2 pb-2" style={{ borderColor: "var(--line-soft)" }}>
            {events.map((e) => {
              const s = KIND_STYLE[e.kind] || KIND_STYLE.info;
              return (
                <div key={e.id} className="flex gap-3 rounded-xl px-3 py-3">
                  <span
                    className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg"
                    style={{ background: `color-mix(in srgb, ${s.color} 12%, transparent)`, color: s.color }}
                  >
                    {s.icon}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="whitespace-pre-line text-[13.5px] leading-relaxed" style={{ color: "var(--ink)" }}>
                      {e.message}
                    </div>
                    <div className="mt-1 text-[11.5px]" style={{ color: "var(--ink-3)" }}>
                      {timeAgo(e.created_at)}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          <div className="border-t px-5 pb-6" style={{ borderColor: "var(--line-soft)" }}>
            <EmptyState
              icon={<Inbox size={18} />}
              title="Nothing yet"
              body="The moment Jexi trades, receives a deposit or finishes a daily run, the report shows up here."
            />
          </div>
        )}
      </Panel>
    </div>
  );
}

// ---------------- Intelligence ----------------

const DESK_ROLES: Record<string, string> = {
  research: "Price structure and range",
  technical: "Trend and momentum",
  macro: "Market environment",
  risk: "Downside, sized in numbers",
  news: "Live headlines",
  verifier: "Evidence check",
};

export function IntelligenceView({ go }: { go: Go }) {
  const [watchlist] = useLocalList<string>("jexi.watchlist", ["NVDA", "AAPL", "MSFT", "TSLA"]);
  const [symbol, setSymbol] = useState(watchlist[0] || "NVDA");
  const { analysis, loading, error } = useAnalysis(symbol);

  return (
    <div className="view-enter">
      <SectionTitle sub="data → analysis → evidence → thesis · all computed live">Data intelligence</SectionTitle>

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
            {(analysis?.desks || []).map((a, i) => (
              <Panel key={a.label} className="p-4">
                <div className="flex items-center justify-between">
                  <span className="text-[11px] font-semibold tracking-[0.1em]" style={{ color: "var(--peach)" }}>
                    {a.label}
                  </span>
                  <Pill tone={a.status === "ok" ? "up" : a.status === "flag" ? "gold" : "neutral"}>
                    {a.status === "ok" ? <><Check size={11} /> done</> : a.status === "flag" ? "caveat" : "unavailable"}
                  </Pill>
                </div>
                <div className="mt-1 text-[12px]" style={{ color: "var(--ink-3)" }}>
                  {DESK_ROLES[a.key] || ""}
                </div>
                <div className="mt-2.5 text-[12.5px] font-medium leading-relaxed" style={{ color: "var(--ink)" }}>
                  {a.line}
                </div>
                <ul className="mt-2 flex flex-col gap-1.5">
                  {a.points.slice(0, 3).map((p) => (
                    <li key={p} className="text-[12px] leading-relaxed" style={{ color: "var(--ink-2)" }}>
                      · {p}
                    </li>
                  ))}
                </ul>
                <div className="mt-3 flex items-center gap-2">
                  <div className="h-1 flex-1 overflow-hidden rounded-full" style={{ background: "var(--panel-3)" }}>
                    <div className="h-full rounded-full" style={{ width: a.status === "ok" ? "100%" : "70%", background: "linear-gradient(90deg, var(--ember), var(--peach))" }} />
                  </div>
                  <span className="text-[10.5px]" style={{ color: "var(--ink-3)" }}>
                    desk {i + 1}/6
                  </span>
                </div>
              </Panel>
            ))}
            {loading && !analysis &&
              [0, 1, 2, 3, 4, 5].map((i) => <Panel key={i} className="p-4"><div className="skeleton h-[110px] w-full" /></Panel>)}
          </div>
          {error && !analysis && (
            <Panel>
              <EmptyState title="Desks could not run" body={error} />
            </Panel>
          )}

          {/* thesis — computed live */}
          {analysis && (
            <Panel>
              <div className="flex items-center justify-between">
                <SectionTitle sub={`on ${symbolName(symbol)} · ${analysis.metrics.closes} sessions analyzed`}>Data brief</SectionTitle>
                <Pill tone="brand"><LiveDot /> live</Pill>
              </div>
              <div className="flex flex-wrap items-center gap-6">
                <ConvictionDial value={analysis.conviction} size={110} />
                <div className="min-w-[180px]">
                  <div className="label">Stance</div>
                  <div
                    className="display text-[30px]"
                    style={{ color: analysis.stance === "Bullish" ? "var(--up)" : analysis.stance === "Cautious" ? "var(--down)" : "var(--sand)" }}
                  >
                    {analysis.stance}
                  </div>
                  <div className="mt-1 text-[12.5px]" style={{ color: "var(--ink-3)" }}>
                    Conviction {analysis.conviction}/100 · 6 desks + verifier
                  </div>
                </div>
              </div>
              <div className="mt-5 grid gap-3 sm:grid-cols-3">
                {[
                  {
                    t: "Supporting evidence",
                    tone: "up",
                    items: analysis.desks.filter((d) => d.key === "technical" || d.key === "research").flatMap((d) => d.points).slice(0, 3),
                  },
                  {
                    t: "Opposing evidence",
                    tone: "down",
                    items: [...analysis.conflicts, ...analysis.desks.filter((d) => d.key === "risk").flatMap((d) => d.points)].slice(0, 3),
                  },
                  { t: "Levels to watch", tone: "brand", items: analysis.watch.map((w) => `${w.label}: ${priceFmt(w.value)}`) },
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
              {analysis.news.length > 0 && (
                <div className="mt-4">
                  <div className="label mb-2">Latest headlines</div>
                  <div className="flex flex-col gap-2">
                    {analysis.news.slice(0, 3).map((h) => (
                      <a
                        key={h.link}
                        href={h.link}
                        target="_blank"
                        rel="noreferrer"
                        className="panel-2 row-link px-3.5 py-2.5 text-[12.5px] leading-snug"
                        style={{ color: "var(--ink-2)" }}
                      >
                        <span style={{ color: "var(--ember)" }}>{h.publisher}</span> — {h.title}
                      </a>
                    ))}
                  </div>
                </div>
              )}
              <p className="mt-4 text-[11.5px] leading-relaxed" style={{ color: "var(--ink-3)" }}>
                {analysis.disclaimer}
              </p>
            </Panel>
          )}
        </div>

        {/* evidence ledger + data honesty — real values */}
        <div className="flex flex-col gap-4">
          <Panel>
            <div className="label mb-3">Evidence ledger</div>
            <div className="flex flex-col gap-3">
              {[
                {
                  k: "DATA",
                  v: analysis
                    ? `${analysis.metrics.closes} daily closes from the live quote chain (Yahoo → Stooq fallback), latest ${priceFmt(analysis.price)}.`
                    : "Waiting for the live quote chain…",
                  tone: "var(--up)",
                },
                {
                  k: "ANALYSIS",
                  v: analysis
                    ? `Trend: price ${analysis.metrics.sma10 !== null && analysis.price > analysis.metrics.sma10 ? "above" : "below"} 10-day average; ${analysis.metrics.upDays30} of last 30 sessions closed higher; ${analysis.metrics.ret30 !== null ? `30-session move ${analysis.metrics.ret30 > 0 ? "+" : ""}${analysis.metrics.ret30}%` : "momentum window warming up"}.`
                    : "Computing from live closes…",
                  tone: "var(--peach)",
                },
                {
                  k: "INTERPRETATION",
                  v: analysis
                    ? `Stance ${analysis.stance} at conviction ${analysis.conviction}/100 — a transparent score, not a secret model.`
                    : "Stance forms once data lands.",
                  tone: "var(--ember)",
                },
                {
                  k: "CONFLICTS",
                  v: analysis
                    ? analysis.conflicts.length
                      ? analysis.conflicts.join(" ")
                      : "Verifier found no contradictions across desks."
                    : "Checked after desks report.",
                  tone: "var(--gold)",
                },
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
              {analysis
                ? analysis.method
                : "Every desk computes from real market data. Nothing here is mocked — when a feed is down, the desk says so instead of inventing numbers."}
            </p>
            <p className="mt-2 text-[12.5px] leading-relaxed" style={{ color: "var(--ink-2)" }}>
              Want model-driven interpretation on top of this data? Connect your AI key in Settings
              and JEXI adds it to the same evidence structure — clearly marked as generated.
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
  const [alerts, setAlerts] = useLocalList<Alert>("jexi.alerts", []);
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
  const [appUpd, setAppUpd] = useState<{ shell: string | null; update: { latest: string; notes: string; url: string } | null } | null>(null);

  useEffect(() => {
    import("@/lib/jexi/data").then((m) => setUrl(m.getServerUrl()));
    if (token) fetchKeys(token).then(setKeys).catch(() => {});
    checkAppUpdate().then(setAppUpd).catch(() => {});
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
                Browsing as guest — sign in to see your real account.
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

        {/* legal + app version */}
        <Panel>
          <div className="label mb-3 flex items-center gap-2">
            <ShieldCheck size={13} /> Legal &amp; app
          </div>
          <div className="flex flex-col gap-2">
            <button className="row-link flex items-center justify-between rounded-lg px-1 py-1.5 text-[13.5px]" onClick={() => go("legal", "terms")}>
              <span style={{ color: "var(--ink-2)" }}>Terms of Service</span>
              <ArrowRight size={14} style={{ color: "var(--ink-3)" }} />
            </button>
            <button className="row-link flex items-center justify-between rounded-lg px-1 py-1.5 text-[13.5px]" onClick={() => go("legal", "privacy")}>
              <span style={{ color: "var(--ink-2)" }}>Privacy Policy</span>
              <ArrowRight size={14} style={{ color: "var(--ink-3)" }} />
            </button>
          </div>
          <div className="mt-3 flex items-center justify-between gap-3 border-t pt-3 text-[12.5px]" style={{ borderColor: "var(--line-soft)" }}>
            <span style={{ color: "var(--ink-3)" }}>
              App version <b className="data" style={{ color: "var(--ink-2)" }}>{appUpd?.shell || "web"}</b>
              {appUpd?.shell && appUpd?.update && <span> · {appUpd.update.latest} ready</span>}
            </span>
            {appUpd?.shell && appUpd?.update ? (
              <button className="btn btn-primary" style={{ minHeight: 34 }} onClick={() => installAppUpdate(appUpd.update!.url)}>
                <RefreshCw size={13} /> Update app
              </button>
            ) : (
              <Pill tone="up">up to date</Pill>
            )}
          </div>
          <p className="mt-2 text-[11.5px] leading-relaxed" style={{ color: "var(--ink-3)" }}>
            No update screens at startup — the app always opens straight into JEXI. Updates live here:
            tap &ldquo;Update app&rdquo; and the app downloads the new version itself, shows a progress bar, then
            Android asks you to install it. On the web you are always current.
          </p>
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
                    {["alpaca-paper", "alpaca-live", "pocketoption", "pocketoption-live", "binance", "paper"].map((p) => (
                      <option key={p} value={p}>
                        {p}
                      </option>
                    ))}
                  </select>
                  <div className="grid gap-2">
                    <input className="input" type="password" placeholder={brokerName.startsWith("pocketoption") ? "Pocket Option SSID session string" : "Broker API key"} value={brokerKey} onChange={(e) => setBrokerKey(e.target.value)} />
                    <input className="input" type="password" placeholder="Broker secret (optional)" value={brokerSecret} onChange={(e) => setBrokerSecret(e.target.value)} />
                  </div>
                  <p className="mt-2 text-[11px] leading-relaxed" style={{ color: "var(--ink-3)" }}>
                    alpaca-paper = practice broker · alpaca-live = real money · pocketoption = Pocket Option (Pocket Broker) demo
                    · pocketoption-live = Pocket Option real money — paste the SSID session string as the key. Jexi pulls these keys itself when it
                    trades for you — they never sit on GitHub or any outside service.
                  </p>
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
  const { overview, error: err, loading, reload } = useAdminSafe(token);
  const [tab, setTab] = useState<"users" | "trades" | "deposits" | "withdrawals" | "activity">("users");
  const [q, setQ] = useState("");
  const [busyId, setBusyId] = useState<number | null>(null);

  const filteredUsers = (overview?.users || []).filter(
    (u) => !q || u.email.toLowerCase().includes(q.toLowerCase()) || (u.name || "").toLowerCase().includes(q.toLowerCase())
  );

  const decide = async (kind: "deposits" | "withdrawals", id: number, action: "approve" | "reject") => {
    setBusyId(id);
    try {
      await adminDecide(token!, kind, id, action);
      reload();
    } catch {
      reload();
    } finally {
      setBusyId(null);
    }
  };

  if (!token) return null;
  return (
    <Panel className="mt-4" pad={false}>
      <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-4">
        <div className="flex items-center gap-2.5">
          <Pill tone="gold"><ShieldCheck size={11} /> admin</Pill>
          <span className="text-[14px] font-semibold">Server control room</span>
          <span className="text-[12px]" style={{ color: "var(--ink-3)" }}>
            live from the database
          </span>
        </div>
        <div className="flex items-center gap-2">
          <button
            className="btn btn-line"
            style={{ minHeight: 32, paddingInline: 10 }}
            onClick={reload}
            aria-label="Refresh admin data"
            title="Refresh"
          >
            <RefreshCw size={13} className={loading ? "animate-spin" : ""} />
          </button>
          <div className="flex gap-1.5">
            {(["users", "trades", "deposits", "withdrawals"] as const).map((t) => (
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
      </div>

      {err && (
        <div className="px-5 pb-4 text-[13px]" style={{ color: "var(--down)" }}>
          {err}
        </div>
      )}

      {overview && (
        <>
          <div className="grid grid-cols-2 gap-4 border-t px-5 py-4 sm:grid-cols-3 lg:grid-cols-6" style={{ borderColor: "var(--line-soft)" }}>
            <Stat label="Users" value={overview.totals.users} />
            <Stat label="Total equity" value={money(overview.totals.equity)} />
            <Stat label="Cash on server" value={money(overview.totals.cash)} />
            <Stat label="In positions" value={money(overview.totals.positions)} />
            <Stat label="All-time trades" value={overview.totals.trades} />
            <Stat label="Open positions" value={overview.totals.openPositions} />
          </div>

          <div className="border-t px-2 pb-2" style={{ borderColor: "var(--line-soft)" }}>
            {tab === "users" && (
              <div>
                <div className="flex items-center gap-2.5 px-3 py-2.5">
                  <Search size={14} style={{ color: "var(--ink-3)" }} />
                  <input
                    className="w-full bg-transparent text-[13.5px] outline-none placeholder:text-[var(--ink-3)]"
                    placeholder={`Filter ${overview.totals.users} users by email or name…`}
                    value={q}
                    onChange={(e) => setQ(e.target.value)}
                  />
                </div>
                <div className="flex flex-col">
                  {filteredUsers.map((u) => (
                    <div key={u.id} className="row-link flex flex-wrap items-center justify-between gap-x-4 gap-y-1 rounded-xl px-3 py-2.5">
                      <div className="min-w-[180px]">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="data text-[13.5px]">{u.email}</span>
                          {u.isAdmin && <Pill tone="gold">admin</Pill>}
                        </div>
                        <div className="text-[11.5px]" style={{ color: "var(--ink-3)" }}>
                          {u.name || "—"} · joined {timeAgo(u.createdAt)}
                        </div>
                      </div>
                      <div className="flex flex-wrap items-center gap-x-6 gap-y-1 text-right">
                        <span className="text-[11.5px]" style={{ color: "var(--ink-3)" }}>
                          {u.positionsCount} pos · {u.tradesCount} trade{u.tradesCount === 1 ? "" : "s"}
                          {u.lastTradeAt ? ` · last ${timeAgo(u.lastTradeAt)}` : ""}
                        </span>
                        <span className="data w-[86px] text-[13.5px]">{money(u.equity)}</span>
                        <span className="data w-[86px] text-[13px]" style={{ color: u.pnl >= 0 ? "var(--up)" : "var(--down)" }}>
                          {u.pnl >= 0 ? "+" : ""}
                          {money(u.pnl)}
                        </span>
                      </div>
                    </div>
                  ))}
                  {!filteredUsers.length && (
                    <div className="px-4 py-6 text-center text-[13px]" style={{ color: "var(--ink-3)" }}>
                      No users match “{q}”.
                    </div>
                  )}
                </div>
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
                      {Number.isFinite(t.pnl) && t.pnl !== 0 && (
                        <span className="data text-[12.5px]" style={{ color: t.pnl >= 0 ? "var(--up)" : "var(--down)" }}>
                          {t.pnl >= 0 ? "+" : ""}
                          {money(t.pnl)}
                        </span>
                      )}
                      <span className="text-[11.5px]" style={{ color: "var(--ink-3)" }}>
                        {timeAgo(t.createdAt)}
                      </span>
                    </div>
                  </div>
                ))}
                {!overview.recentTrades.length && <div className="px-4 py-6 text-center text-[13px]" style={{ color: "var(--ink-3)" }}>No trades yet.</div>}
              </div>
            )}
            {tab === "deposits" && (
              <div className="flex flex-col">
                {overview.deposits.map((d) => (
                  <div key={d.id} className="row-link flex items-center justify-between rounded-xl px-3 py-2.5">
                    <div className="flex items-center gap-3">
                      <Pill tone={d.status === "approved" ? "up" : d.status === "pending" ? "gold" : "down"}>{d.status}</Pill>
                      <span className="text-[13px]" style={{ color: "var(--ink-2)" }}>
                        {d.email}
                      </span>
                      <span className="text-[12px]" style={{ color: "var(--ink-3)" }}>
                        via {d.method}
                      </span>
                    </div>
                    <div className="flex items-center gap-4">
                      <span className="data text-[13.5px]">{money(d.amount)}</span>
                      <span className="text-[11.5px]" style={{ color: "var(--ink-3)" }}>
                        {timeAgo(d.createdAt)}
                      </span>
                      {d.status === "pending" && (
                        <span className="flex items-center gap-1.5">
                          <button
                            className="btn btn-primary"
                            style={{ minHeight: 30, paddingInline: 10, fontSize: 12 }}
                            disabled={busyId === d.id}
                            onClick={() => decide("deposits", d.id, "approve")}
                          >
                            <CheckCircle2 size={12} /> Confirm
                          </button>
                          <button
                            className="btn btn-line"
                            style={{ minHeight: 30, paddingInline: 10, fontSize: 12, color: "var(--down)" }}
                            disabled={busyId === d.id}
                            onClick={() => decide("deposits", d.id, "reject")}
                          >
                            <XCircle size={12} /> Reject
                          </button>
                        </span>
                      )}
                    </div>
                  </div>
                ))}
                {!overview.deposits.length && <div className="px-4 py-6 text-center text-[13px]" style={{ color: "var(--ink-3)" }}>No deposits yet.</div>}
              </div>
            )}
            {tab === "withdrawals" && (
              <div className="flex flex-col">
                {overview.withdrawals.map((w) => (
                  <div key={w.id} className="row-link flex items-center justify-between rounded-xl px-3 py-2.5">
                    <div className="flex items-center gap-3">
                      <Pill tone={w.status === "approved" ? "up" : w.status === "pending" ? "gold" : "down"}>{w.status}</Pill>
                      <span className="text-[13px]" style={{ color: "var(--ink-2)" }}>
                        {w.email}
                      </span>
                      <span className="text-[12px]" style={{ color: "var(--ink-3)" }}>
                        via {w.method}
                      </span>
                    </div>
                    <div className="flex items-center gap-4">
                      <span className="data text-[13.5px]">{money(w.amount)}</span>
                      <span className="text-[11.5px]" style={{ color: "var(--ink-3)" }}>
                        {timeAgo(w.createdAt)}
                      </span>
                      {w.status === "pending" && (
                        <span className="flex items-center gap-1.5">
                          <button
                            className="btn btn-primary"
                            style={{ minHeight: 30, paddingInline: 10, fontSize: 12 }}
                            disabled={busyId === w.id}
                            onClick={() => decide("withdrawals", w.id, "approve")}
                          >
                            <CheckCircle2 size={12} /> Pay out
                          </button>
                          <button
                            className="btn btn-line"
                            style={{ minHeight: 30, paddingInline: 10, fontSize: 12, color: "var(--down)" }}
                            disabled={busyId === w.id}
                            onClick={() => decide("withdrawals", w.id, "reject")}
                          >
                            <XCircle size={12} /> Reject
                          </button>
                        </span>
                      )}
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
          <TrendingUp size={14} /> Loading control room from the live database…
        </div>
      )}
    </Panel>
  );
}

// thin wrapper so the admin panel can live inside SettingsView without prop drilling
function useAdminSafe(token: string | null) {
  return useAdmin(token, Boolean(token));
}
