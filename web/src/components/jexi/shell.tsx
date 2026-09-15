"use client";

// JEXI Market shell: hash routing, top nav, mobile tab bar, ⌘K palette, update gate.
import { useCallback, useEffect, useMemo, useState } from "react";
import { Bell, ChartCandlestick, LayoutDashboard, LineChart, PieChart, RefreshCw, Search, Settings, Wallet, X } from "lucide-react";
import { JexiMark, Wordmark } from "@/components/jexi/brand";
import { Pill } from "@/components/jexi/bits";
import { AuthView, Landing } from "@/components/jexi/views-public";
import { AssetView, CommandView, MarketsView } from "@/components/jexi/views-app";
import { AlertsView, IntelligenceView, PortfolioView, SettingsView } from "@/components/jexi/views-app2";
import { PrivacyView, TermsView } from "@/components/jexi/views-legal";
import { UNIVERSE, useAccount, useAuth, useFeed, useNotifications, useProfits, acceptTerms, api } from "@/lib/jexi/data";
import type { JexiUser } from "@/lib/jexi/data";
import { NotificationsView } from "@/components/jexi/views-app2";

type View = "landing" | "auth" | "command" | "markets" | "asset" | "portfolio" | "intelligence" | "alerts" | "notifications" | "settings" | "legal";

const NAV: { id: View; label: string; icon: React.ReactNode }[] = [
  { id: "command", label: "Command", icon: <LayoutDashboard size={17} /> },
  { id: "markets", label: "Markets", icon: <ChartCandlestick size={17} /> },
  { id: "portfolio", label: "Portfolio", icon: <PieChart size={17} /> },
  { id: "intelligence", label: "Intelligence", icon: <LineChart size={17} /> },
  { id: "alerts", label: "Alerts", icon: <Bell size={17} /> },
];

function parseHash(): { view: View; symbol?: string; doc?: string } {
  const h = window.location.hash.replace(/^#\/?/, "");
  if (!h) return { view: "landing" };
  const [head, tail] = h.split("/");
  switch (head) {
    case "auth":
      return { view: "auth" };
    case "command":
      return { view: "command" };
    case "markets":
      return { view: "markets" };
    case "asset":
      return { view: "asset", symbol: (tail || "AAPL").toUpperCase() };
    case "portfolio":
      return { view: "portfolio" };
    case "intelligence":
      return { view: "intelligence" };
    case "alerts":
      return { view: "alerts" };
    case "notifications":
      return { view: "notifications" };
    case "settings":
      return { view: "settings" };
    case "legal":
      return { view: "legal", doc: tail === "privacy" ? "privacy" : "terms" };
    default:
      return { view: "landing" };
  }
}

export function JexiApp() {
  const [{ view, symbol, doc }, setRoute] = useState<{ view: View; symbol?: string; doc?: string }>({ view: "landing" });
  const { user, token, ready, isAdmin, signOut } = useAuth();
  const { account } = useAccount(token);
  const liveFeed = useFeed(token);
  const { unread } = useNotifications(token);
  const profits = useProfits(token);
  const [paletteOpen, setPaletteOpen] = useState(false);

  useEffect(() => {
    // defer the first hash read so we never setState synchronously inside the effect
    const t = setTimeout(() => setRoute(parseHash()), 0);
    const onHash = () => setRoute(parseHash());
    window.addEventListener("hashchange", onHash);
    return () => {
      clearTimeout(t);
      window.removeEventListener("hashchange", onHash);
    };
  }, []);

  const go = useCallback((v: string, s?: string) => {
    window.location.hash = `#/${v}${s ? `/${s}` : ""}`;
    setRoute({ view: v as View, symbol: s?.toUpperCase() });
    setPaletteOpen(false);
    window.scrollTo({ top: 0, behavior: "instant" as ScrollBehavior });
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPaletteOpen((o) => !o);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const connected = Boolean(token);
  const feed = liveFeed;

  // Terms & Policies check — one server look-up per session. The gate only
  // shows when the server CONFIRMED the user has not accepted the current
  // version (a network failure never locks anyone out).
  const [terms, setTerms] = useState<{ checked: boolean; current: boolean }>({ checked: false, current: true });
  useEffect(() => {
    if (!token) {
      setTerms({ checked: false, current: true });
      return;
    }
    let alive = true;
    api<{ ok: true; user: JexiUser }>("/api/auth/me", { token })
      .then((r) => {
        if (alive) setTerms({ checked: true, current: r.user.terms_current === true });
      })
      .catch(() => {
        if (alive) setTerms({ checked: false, current: true });
      });
    return () => {
      alive = false;
    };
  }, [token, user?.terms_accepted_at]);
  const needsTerms = connected && terms.checked && !terms.current;

  const nav = (v: string, s?: string) => go(v, s);

  const content = useMemo(() => {
    if (!ready) return <div className="p-10" />;
    if (view === "landing") return <Landing go={nav} />;
    if (view === "auth") return user ? <CommandView go={nav} token={token} account={account} feed={feed} isDemo={!connected} /> : <AuthView go={nav} />;
    if (view === "legal") return doc === "privacy" ? <PrivacyView go={nav} /> : <TermsView go={nav} />;
    // Everyone signs in: members-only views bounce to the sign-in page.
    if (!connected) return <AuthView go={nav} />;

    const shared = { go: nav, token, account, feed, isDemo: !connected };
    switch (view) {
      case "notifications":
        return <NotificationsView token={token} isDemo={!connected} />;
      case "command":
        return <CommandView {...shared} />;
      case "markets":
        return <MarketsView go={nav} />;
      case "asset":
        return <AssetView symbol={symbol || "AAPL"} go={nav} />;
      case "portfolio":
        return <PortfolioView go={nav} token={token} account={account} profits={profits} isDemo={!connected} />;
      case "intelligence":
        return <IntelligenceView go={nav} />;
      case "alerts":
        return <AlertsView go={nav} />;
      case "settings":
        return <SettingsView go={nav} token={token} user={user} isAdmin={isAdmin} signOut={signOut} />;
      default:
        return <Landing go={nav} />;
    }
  }, [ready, view, symbol, doc, user, token, account, feed, profits, connected, isAdmin, nav, signOut]);

  return (
    <div className="min-h-screen">
      <div className="jexi-glow" />

      {/* top nav */}
      <header
        className="sticky top-0 z-40 border-b backdrop-blur-md"
        style={{ borderColor: "var(--line-soft)", background: "color-mix(in srgb, var(--bg) 82%, transparent)" }}
      >
        <div className="mx-auto flex h-[64px] max-w-6xl items-center justify-between gap-4 px-5">
          <button className="flex items-center gap-2.5" onClick={() => go("landing")} aria-label="JEXI Market home">
            <JexiMark size={30} />
            <Wordmark />
          </button>

          <nav className="hidden items-center gap-1 md:flex">
            {NAV.map((n) => (
              <button
                key={n.id}
                onClick={() => go(n.id)}
                className="flex items-center gap-2 rounded-lg px-3.5 py-2 text-[13.5px] font-medium transition-all"
                style={{
                  color: view === n.id ? "var(--ink)" : "var(--ink-2)",
                  background: view === n.id ? "var(--panel-2)" : "transparent",
                }}
              >
                {n.label}
              </button>
            ))}
          </nav>

          <div className="flex items-center gap-2.5">
            <button
              className="flex items-center gap-2 rounded-lg px-3 py-2 text-[13px] transition-colors"
              style={{ background: "var(--panel-2)", border: "1px solid var(--line)", color: "var(--ink-3)" }}
              onClick={() => setPaletteOpen(true)}
            >
              <Search size={14} />
              <span className="hidden sm:inline">Search</span>
              <span className="data hidden text-[11px] sm:inline">⌘K</span>
            </button>
            {connected && (
              <button
                className="relative flex h-9 w-9 items-center justify-center rounded-lg"
                style={{ background: "var(--panel-2)", border: "1px solid var(--line)", color: "var(--ink-2)" }}
                onClick={() => go("notifications")}
                aria-label={`Notifications${unread ? ` (${unread} new)` : ""}`}
                title="Notifications — everything Jexi does lands here"
              >
                <Bell size={15} />
                {unread > 0 && (
                  <span
                    className="absolute -right-1 -top-1 flex h-[17px] min-w-[17px] items-center justify-center rounded-full px-1 text-[10px] font-bold"
                    style={{ background: "var(--ember)", color: "#180f08" }}
                  >
                    {unread > 9 ? "9+" : unread}
                  </span>
                )}
              </button>
            )}
            {connected ? (
              <button className="flex items-center gap-2" onClick={() => go("settings")} aria-label="Settings">
                <span
                  className="flex h-9 w-9 items-center justify-center rounded-full text-[13px] font-semibold"
                  style={{ background: "linear-gradient(135deg, var(--ember), var(--coral))", color: "#180f08" }}
                >
                  {(user?.name || user?.email || "J").slice(0, 1).toUpperCase()}
                </span>
              </button>
            ) : (
              <button className="btn btn-primary" style={{ minHeight: 38 }} onClick={() => go("auth")}>
                Sign in
              </button>
            )}
          </div>
        </div>
      </header>

      <main className="relative mx-auto w-full max-w-6xl px-5 pb-28 pt-6 md:pb-14">{content}</main>

      {/* mobile tab bar */}
      {view !== "landing" && view !== "auth" && view !== "legal" && (
        <nav
          className="fixed inset-x-0 bottom-0 z-40 flex items-center justify-around border-t px-2 pb-[env(safe-area-inset-bottom)] backdrop-blur-md md:hidden"
          style={{ borderColor: "var(--line-soft)", background: "color-mix(in srgb, var(--bg) 90%, transparent)" }}
        >
          {NAV.map((n) => (
            <button
              key={n.id}
              onClick={() => go(n.id)}
              className="flex min-h-[52px] w-full flex-col items-center justify-center gap-1 py-1.5"
              style={{ color: view === n.id ? "var(--ember)" : "var(--ink-3)" }}
            >
              {n.icon}
              <span className="text-[10.5px]">{n.label}</span>
            </button>
          ))}
        </nav>
      )}

      {paletteOpen && <Palette onClose={() => setPaletteOpen(false)} go={go} />}

      {needsTerms && (
        <TermsGate
          token={token}
          onAccepted={() => setTerms({ checked: true, current: true })}
          onDecline={() => {
            signOut();
            go("landing");
          }}
          go={go}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Terms & Policies acceptance gate — every account must accept the current
// version before using the app. Decline = sign out.
// ---------------------------------------------------------------------------
function TermsGate({
  token,
  onAccepted,
  onDecline,
  go,
}: {
  token: string | null;
  onAccepted: () => void;
  onDecline: () => void;
  go: (v: string, s?: string) => void;
}) {
  const [agreed, setAgreed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const accept = async () => {
    setBusy(true);
    setError(null);
    try {
      await acceptTerms(token);
      onAccepted();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Could not record acceptance — try again.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center px-4"
      style={{ background: "rgba(8,7,5,.78)", backdropFilter: "blur(6px)" }}
      role="dialog"
      aria-modal="true"
      aria-label="Accept the Terms & Policies"
    >
      <div
        className="panel w-full max-w-lg"
        style={{ animation: "jexi-rise 180ms var(--ease) both" }}
      >
        <div className="flex items-center gap-3 border-b px-5 py-4" style={{ borderColor: "var(--line-soft)" }}>
          <span
            className="flex h-9 w-9 items-center justify-center rounded-lg text-[15px] font-bold"
            style={{ background: "linear-gradient(135deg, var(--ember), var(--coral))", color: "#180f08" }}
          >
            J
          </span>
          <div>
            <div className="text-[15.5px] font-semibold">Before you continue</div>
            <div className="text-[12px]" style={{ color: "var(--ink-3)" }}>
              Jexi Terms &amp; Policies — updated 16 Sep 2026
            </div>
          </div>
        </div>

        <div className="space-y-2.5 px-5 py-4 text-[13.5px] leading-relaxed" style={{ color: "var(--ink-2)" }}>
          <p>To keep Jexi safe for everyone, please accept the house rules:</p>
          <ul className="ml-4 list-disc space-y-1.5">
            <li>
              <b style={{ color: "var(--ink)" }}>Real money, real risk.</b> Jexi can trade a live brokerage
              account with real funds. Prices move fast and losses are real — never deposit money you
              cannot afford to lose.
            </li>
            <li>
              <b style={{ color: "var(--ink)" }}>No advice, no promises.</b> Jexi is software that follows
              your rules. Nothing it says is investment advice, and past results never guarantee future ones.
            </li>
            <li>
              <b style={{ color: "var(--ink)" }}>You stay in charge.</b> Keys you save are yours, encrypted;
              live mode is capped and can be paused or halted from the app at any time.
            </li>
            <li>
              <b style={{ color: "var(--ink)" }}>Fair use &amp; privacy.</b> One account per person, no abuse
              of the service, and your data is handled per the Privacy Policy.
            </li>
          </ul>
          <p className="text-[12.5px]" style={{ color: "var(--ink-3)" }}>
            Read the full documents:{" "}
            <button className="underline" style={{ color: "var(--ember)" }} onClick={() => go("legal", "terms")}>
              Terms of Service
            </button>{" "}
            ·{" "}
            <button className="underline" style={{ color: "var(--ember)" }} onClick={() => go("legal", "privacy")}>
              Privacy Policy
            </button>
          </p>
        </div>

        <div className="space-y-3 border-t px-5 py-4" style={{ borderColor: "var(--line-soft)" }}>
          <label className="flex cursor-pointer items-start gap-2.5 text-[13.5px]" style={{ color: "var(--ink)" }}>
            <input
              type="checkbox"
              checked={agreed}
              onChange={(e) => setAgreed(e.target.checked)}
              className="mt-0.5 h-4 w-4 accent-[var(--ember)]"
            />
            <span>
              I have read and accept the Jexi Terms of Service and Privacy Policy, and I understand that
              live trading involves real financial risk.
            </span>
          </label>
          {error && (
            <div className="text-[12.5px]" style={{ color: "var(--coral, #ff6b6b)" }}>
              {error}
            </div>
          )}
          <div className="flex items-center gap-2.5">
            <button className="btn btn-primary flex-1" disabled={!agreed || busy} style={{ opacity: !agreed || busy ? 0.5 : 1 }} onClick={accept}>
              {busy ? "Saving…" : "Accept and continue"}
            </button>
            <button className="btn" onClick={onDecline} style={{ color: "var(--ink-3)" }}>
              Decline
            </button>
          </div>
          <div className="text-[11.5px]" style={{ color: "var(--ink-3)" }}>
            Declining signs you out. You can come back any time.
          </div>
        </div>
      </div>
    </div>
  );
}

function Palette({ onClose, go }: { onClose: () => void; go: (v: string, s?: string) => void }) {
  const [q, setQ] = useState("");
  const results = useMemo(() => {
    const views = NAV.concat([{ id: "settings" as View, label: "Settings", icon: <Settings size={17} /> }]).filter((v) =>
      v.label.toLowerCase().includes(q.toLowerCase())
    );
    const syms = UNIVERSE.filter(
      (u) => u.s.toLowerCase().includes(q.toLowerCase()) || u.name.toLowerCase().includes(q.toLowerCase())
    ).slice(0, 6);
    return { views, syms };
  }, [q]);

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center pt-[12vh]" style={{ background: "rgba(8,7,5,.6)" }} onClick={onClose}>
      <div
        className="panel w-full max-w-lg overflow-hidden"
        style={{ animation: "jexi-rise 180ms var(--ease) both" }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-3 border-b px-4 py-3.5" style={{ borderColor: "var(--line-soft)" }}>
          <Search size={16} style={{ color: "var(--ink-3)" }} />
          <input
            autoFocus
            className="w-full bg-transparent text-[15px] outline-none placeholder:text-[var(--ink-3)]"
            placeholder="Jump to a symbol or page…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Escape") onClose();
              if (e.key === "Enter") {
                if (results.syms.length) go("asset", results.syms[0].s);
                else if (results.views.length) go(results.views[0].id);
              }
            }}
          />
          <button onClick={onClose} style={{ color: "var(--ink-3)" }} aria-label="Close search">
            <X size={16} />
          </button>
        </div>
        <div className="max-h-[320px] overflow-y-auto p-2">
          {results.views.length > 0 && (
            <>
              <div className="label px-3 pb-1.5 pt-2">Pages</div>
              {results.views.map((v) => (
                <button key={v.id} className="row-link flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left text-[14px]" onClick={() => go(v.id)}>
                  <span style={{ color: "var(--ink-3)" }}>{v.icon}</span> {v.label}
                </button>
              ))}
            </>
          )}
          {results.syms.length > 0 && (
            <>
              <div className="label px-3 pb-1.5 pt-3">Symbols</div>
              {results.syms.map((u) => (
                <button key={u.s} className="row-link flex w-full items-center justify-between rounded-lg px-3 py-2.5 text-left" onClick={() => go("asset", u.s)}>
                  <span className="flex items-center gap-3">
                    <span className="data text-[13.5px]">{u.s.replace("-USD", "")}</span>
                    <span className="text-[13px]" style={{ color: "var(--ink-2)" }}>
                      {u.name}
                    </span>
                  </span>
                  <Pill>{u.sector}</Pill>
                </button>
              ))}
            </>
          )}
          {!results.views.length && !results.syms.length && (
            <div className="px-4 py-8 text-center text-[13px]" style={{ color: "var(--ink-3)" }}>
              Nothing matches “{q}”.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
