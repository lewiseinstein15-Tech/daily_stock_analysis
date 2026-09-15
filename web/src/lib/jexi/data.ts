"use client";

// JEXI Market data layer: formatters, symbol universe, live-server client, hooks.
import { useCallback, useEffect, useRef, useState } from "react";

// ---------------- server connection ----------------

export const DEFAULT_SERVER = "https://jexi-server.vercel.app";

export function getServerUrl(): string {
  if (typeof window === "undefined") return DEFAULT_SERVER;
  return localStorage.getItem("jexi.serverUrl") || DEFAULT_SERVER;
}

export function setServerUrl(url: string) {
  if (typeof window === "undefined") return;
  if (url.trim()) localStorage.setItem("jexi.serverUrl", url.trim().replace(/\/$/, ""));
  else localStorage.removeItem("jexi.serverUrl");
}

export interface JexiUser {
  id: number;
  email: string;
  name: string;
  role?: string;
}

function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("jexi.token");
}
function setToken(t: string | null) {
  if (typeof window === "undefined") return;
  if (t) localStorage.setItem("jexi.token", t);
  else localStorage.removeItem("jexi.token");
}

export async function api<T = Record<string, unknown>>(
  path: string,
  opts: { method?: string; body?: unknown; token?: string | null } = {}
): Promise<T> {
  const res = await fetch(`${getServerUrl()}${path}`, {
    method: opts.method || "GET",
    headers: {
      "Content-Type": "application/json",
      ...(opts.token ? { Authorization: `Bearer ${opts.token}` } : {}),
    },
    body: opts.body ? JSON.stringify(opts.body) : undefined,
    signal: AbortSignal.timeout(15000),
  });
  const json = await res.json().catch(() => ({ ok: false, error: `HTTP ${res.status}` }));
  // Session expired or revoked: let the auth layer sign the user out cleanly
  // instead of showing broken member UI forever.
  if (res.status === 401 && opts.token) {
    if (typeof window !== "undefined") window.dispatchEvent(new Event("jexi.unauthorized"));
  }
  if (!res.ok || json.ok === false) throw new Error(json.error || `HTTP ${res.status}`);
  return json as T;
}

// ---------------- types ----------------

export interface Quote {
  price: number;
  prevClose?: number;
  changePct?: number;
  closes?: number[];
}
export type Quotes = Record<string, Quote>;

export interface Position {
  symbol: string;
  qty: number;
  avgPrice: number;
  lastPrice: number;
  value: number;
  pnl: number;
  openedAt: string;
}
export interface AccountInfo {
  cash: number;
  equity: number;
  startingBalance: number;
  pnl: number;
  pnlPct: number;
  mode: string;
  pendingDeposits?: number;
  positions: Position[];
}
export interface Trade {
  id: number;
  symbol: string;
  side: string;
  qty: number;
  price: number;
  amount: number;
  pnl: number;
  reason: string;
  status: string;
  created_at: string;
}
export interface FeedEvent {
  id: number;
  kind: string;
  message: string;
  created_at: string;
}
export interface Profits {
  totalPnl: number;
  todayPnl: number;
  trades: number;
  wins: number;
  losses: number;
  winRate: number;
  bestTrade: { symbol: string; pnl: number } | null;
  worstTrade: { symbol: string; pnl: number } | null;
  equityCurve: { created_at: string; equity: number }[];
}
export interface AdminOverview {
  totals: { users: number; equity: number; cash: number; positions: number; trades: number; openPositions: number };
  users: {
    id: number;
    email: string;
    name: string;
    isAdmin: boolean;
    cash: number;
    positionValue: number;
    equity: number;
    pnl: number;
    tradesCount: number;
    positionsCount: number;
    lastTradeAt: string | null;
    createdAt: string;
  }[];
  recentTrades: { id: number; email: string; symbol: string; side: string; qty: number; price: number; pnl: number; createdAt: string }[];
  withdrawals: { id: number; email: string; amount: number; method: string; status: string; createdAt: string }[];
  deposits: { id: number; email: string; amount: number; method: string; status: string; createdAt: string }[];
}

// ---------------- app version + updates ----------------
// The site is always current (it IS the live web app), so there is no
// blocking update screen here. The Android shell reports its own version
// through window.jexiNative (see MainActivity), and app updates live in
// Settings -> "App update" (shellVersion + checkAppUpdate below).

export function shellVersion(): string | null {
  if (typeof window === "undefined") return null;
  const n = (window as unknown as { jexiNative?: { appVersion?: () => string } }).jexiNative;
  try {
    const v = n?.appVersion?.();
    return v ? String(v) : null;
  } catch {
    return null;
  }
}

export interface AppUpdateInfo {
  latest: string;
  notes: string;
  url: string;
}

export async function checkAppUpdate(): Promise<{ shell: string | null; update: AppUpdateInfo | null }> {
  const shell = shellVersion();
  try {
    const r = await api<{ ok: boolean; latest: string; notes: string; url: string }>("/api/version");
    const update = r.latest && shell && compareVersions(shell, r.latest) < 0
      ? { latest: r.latest, notes: r.notes, url: r.url }
      : null;
    return { shell, update };
  } catch {
    return { shell, update: null };
  }
}

export function compareVersions(a: string, b: string): number {
  const pa = a.split(".").map(Number);
  const pb = b.split(".").map(Number);
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const d = (pa[i] || 0) - (pb[i] || 0);
    if (d !== 0) return d;
  }
  return 0;
}

export function installAppUpdate(url: string): void {
  const w = window as unknown as { jexiNative?: { installUpdate?: (u: string) => void } };
  if (w.jexiNative?.installUpdate) {
    // Inside the Android app: download in-app with a progress bar, then install.
    w.jexiNative.installUpdate(url);
  } else {
    // Browser or old shell: hand the APK to the normal download flow.
    window.location.assign(url);
  }
}

// ---------------- real market wire (guest activity, computed from live quotes) ----------------

export function marketWire(quotes: Quotes): FeedEvent[] {
  const entries = Object.entries(quotes).filter(([, q]) => Number.isFinite(q.changePct || NaN));
  if (!entries.length) return [];
  const sorted = [...entries].sort((a, b) => (b[1].changePct || 0) - (a[1].changePct || 0));
  const top = sorted[0];
  const bottom = sorted[sorted.length - 1];
  const spy = quotes["SPY"];
  const btc = quotes["BTC-USD"];
  const wire: FeedEvent[] = [];
  let id = -1;
  const push = (kind: string, message: string) => wire.push({ id: id--, kind, message, created_at: new Date().toISOString() });
  if (top && (top[1].changePct || 0) > 0.05) {
    push(
      "info",
      `${top[0].replace("-USD", "")} leads the watch universe at ${priceFmt(top[1].price)} (${pct(top[1].changePct || 0)} today).`
    );
  }
  if (bottom && top[0] !== bottom[0] && (bottom[1].changePct || 0) < -0.05) {
    push(
      "warn",
      `${bottom[0].replace("-USD", "")} is the weakest at ${priceFmt(bottom[1].price)} (${pct(bottom[1].changePct || 0)} today).`
    );
  }
  if (spy) {
    push(
      "info",
      `S&P 500 proxy (SPY) trades at ${priceFmt(spy.price)}, ${pct(spy.changePct || 0)} on the session.`
    );
  }
  if (btc) {
    push("info", `Bitcoin changes hands at ${priceFmt(btc.price)} (${pct(btc.changePct || 0)}), 24/7 market.`);
  }
  push("info", "Sign in and this wire becomes your personal trading log — every buy, sell and safety line, in plain English.");
  return wire;
}

// ---------------- data-driven brief hook (replaces demo theses) ----------------

export interface DeskBrief {
  key: string;
  label: string;
  status: string;
  line: string;
  points: string[];
}

export interface AnalysisResult {
  symbol: string;
  price: number;
  changePct: number | null;
  stance: "Bullish" | "Cautious" | "Neutral";
  stanceTone: "up" | "down" | "neutral";
  conviction: number;
  metrics: {
    closes: number;
    sma10: number | null;
    sma20: number | null;
    sma50: number | null;
    high90: number;
    low90: number;
    rangePos: number;
    ret10: number | null;
    ret30: number | null;
    volAnn: number;
    maxDrawdown: number;
    upDays30: number;
    spyCorrelation: number | null;
  };
  desks: DeskBrief[];
  watch: { label: string; value: number }[];
  news: { title: string; publisher: string; link: string }[];
  conflicts: string[];
  method: string;
  disclaimer: string;
  asOf: string;
}

export function useAnalysis(symbol: string, pollMs = 60_000): {
  analysis: AnalysisResult | null;
  loading: boolean;
  error: string | null;
} {
  const [analysis, setAnalysis] = useState<AnalysisResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!symbol) return;
    let alive = true;
    setLoading(true);
    setError(null);
    const load = () =>
      api<AnalysisResult & { ok: boolean }>(`/api/analysis?symbol=${encodeURIComponent(symbol)}`)
        .then((r) => {
          if (!alive) return;
          setAnalysis(r);
          setLoading(false);
        })
        .catch((e) => {
          if (!alive) return;
          setError((e as Error).message);
          setLoading(false);
        });
    load();
    const id = setInterval(load, pollMs);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, [symbol, pollMs]);
  return { analysis, loading, error };
}

// ---------------- symbol universe ----------------

export interface SymbolMeta {
  s: string;
  name: string;
  sector: string;
}

export const UNIVERSE: SymbolMeta[] = [
  { s: "AAPL", name: "Apple", sector: "Technology" },
  { s: "MSFT", name: "Microsoft", sector: "Technology" },
  { s: "NVDA", name: "NVIDIA", sector: "Semiconductors" },
  { s: "AMZN", name: "Amazon", sector: "Consumer" },
  { s: "META", name: "Meta Platforms", sector: "Technology" },
  { s: "GOOGL", name: "Alphabet", sector: "Technology" },
  { s: "TSLA", name: "Tesla", sector: "Automotive" },
  { s: "AMD", name: "AMD", sector: "Semiconductors" },
  { s: "NFLX", name: "Netflix", sector: "Media" },
  { s: "JPM", name: "JPMorgan Chase", sector: "Financials" },
  { s: "V", name: "Visa", sector: "Financials" },
  { s: "XOM", name: "Exxon Mobil", sector: "Energy" },
  { s: "KO", name: "Coca-Cola", sector: "Consumer" },
  { s: "DIS", name: "Disney", sector: "Media" },
  { s: "BA", name: "Boeing", sector: "Industrials" },
  { s: "SPY", name: "S&P 500 ETF", sector: "Index" },
  { s: "QQQ", name: "Nasdaq 100 ETF", sector: "Index" },
  { s: "BTC-USD", name: "Bitcoin", sector: "Crypto" },
  { s: "ETH-USD", name: "Ethereum", sector: "Crypto" },
];

export const INDEX_SYMBOLS = ["SPY", "QQQ", "BTC-USD"];
export const TICKER_SYMBOLS = ["AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "TSLA", "SPY", "QQQ", "BTC-USD"];

export function symbolName(s: string): string {
  return UNIVERSE.find((u) => u.s === s)?.name || s;
}

// ---------------- formatters ----------------

export const money = (n: number, frac = 2) =>
  (n < 0 ? "-$" : "$") +
  Math.abs(n).toLocaleString("en-US", { minimumFractionDigits: frac, maximumFractionDigits: frac });

export const moneyCompact = (n: number) =>
  (n < 0 ? "-$" : "$") +
  Math.abs(n).toLocaleString("en-US", { notation: "compact", maximumFractionDigits: 1 });

export const pct = (n: number) => `${n > 0 ? "+" : ""}${n.toFixed(2)}%`;

export const priceFmt = (n: number) =>
  n >= 1000 ? n.toLocaleString("en-US", { maximumFractionDigits: 2 }) : n.toFixed(2);

export function timeAgo(iso: string): string {
  const then = Date.parse(iso.includes("T") ? iso : iso.replace(" ", "T") + "Z");
  const s = Math.max(0, Math.floor((Date.now() - then) / 1000));
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

// ---------------- providers ----------------

let providersCache: { email: boolean; google: boolean } | null = null;
export function useProviders() {
  const [providers, setProviders] = useState(providersCache || { email: true, google: false });
  useEffect(() => {
    if (providersCache) return;
    api<{ providers: { email: boolean; google: boolean } }>("/api/auth/providers")
      .then((r) => {
        providersCache = r.providers;
        setProviders(r.providers);
      })
      .catch(() => {});
  }, []);
  return providers;
}

// ---------------- auth hook ----------------

export function useAuth() {
  const [user, setUser] = useState<JexiUser | null>(null);
  const [token, setTok] = useState<string | null>(null);
  const [ready, setReady] = useState(false);
  const userRef = useRef<JexiUser | null>(null);

  const applySession = useCallback((t: string, u: JexiUser) => {
    setToken(t);
    localStorage.setItem("jexi.user", JSON.stringify(u));
    userRef.current = u;
    setTok(t);
    setUser(u);
  }, []);

  useEffect(() => {
    // Hydrate the session from localStorage: this is a legitimate one-time
    // sync between an external system and React state.
     
    const hydrate = () => {
      const t = getToken();
      const raw = localStorage.getItem("jexi.user");
      if (t && raw) {
        try {
          const u = JSON.parse(raw) as JexiUser;
          userRef.current = u;
          setTok(t);
          setUser(u);
        } catch {}
      }
      setReady(true);
    };
    hydrate();
    // Full-page Google sign-in (the Android app shell runs OAuth in the same
    // window, so no popup/opener exists): the server bounces back here with
    // #gt=<token>. Turn it into a normal session, then clean the address bar.
    const gt = window.location.hash.match(/[#&]gt=([^&]+)/);
    if (gt) {
      history.replaceState(null, "", location.pathname + location.search);
      const t = decodeURIComponent(gt[1]);
      api<{ ok: true; user: JexiUser }>("/api/auth/me", { token: t })
        .then((r) => {
          applySession(t, r.user);
        })
        .catch(() => {});
    }
    const onMsg = (e: MessageEvent) => {
      if (e.data?.type === "jexi-google-auth" && e.data.token) {
        applySession(e.data.token, e.data.user);
      }
    };
    // Server rejected our session (401): wipe it and fall back to guest view.
    const onUnauthorized = () => {
      localStorage.removeItem("jexi.token");
      localStorage.removeItem("jexi.user");
      userRef.current = null;
      setTok(null);
      setUser(null);
    };
    window.addEventListener("message", onMsg);
    window.addEventListener("jexi.unauthorized", onUnauthorized);
    return () => {
      window.removeEventListener("message", onMsg);
      window.removeEventListener("jexi.unauthorized", onUnauthorized);
    };
  }, [applySession]);

  const signOut = useCallback(() => {
    setToken(null);
    localStorage.removeItem("jexi.user");
    userRef.current = null;
    setTok(null);
    setUser(null);
  }, []);

  const signIn = useCallback(async (email: string, password: string) => {
    const r = await api<{ token: string; user: JexiUser }>("/api/auth/login", {
      method: "POST",
      body: { email, password },
    });
    applySession(r.token, r.user);
    return r.user;
  }, []);

  const signUp = useCallback(async (email: string, password: string, name: string) => {
    const r = await api<{ token: string; user: JexiUser }>("/api/auth/register", {
      method: "POST",
      body: { email, password, name },
    });
    applySession(r.token, r.user);
    return r.user;
  }, []);

  const { google } = useProviders();
  const startGoogle = useCallback(() => {
    window.open(
      `${getServerUrl()}/api/auth/google/start?origin=${encodeURIComponent(window.location.origin)}`,
      "jexi-google",
      "width=460,height=640"
    );
  }, []);

  return { user, token, ready, signIn, signUp, signOut, startGoogle, googleEnabled: google, isAdmin: user?.role === "admin" };
}

// ---------------- market data hook ----------------

export function useQuotes(symbols: string[], pollMs = 20000): { quotes: Quotes; loading: boolean; error: string | null } {
  const [quotes, setQuotes] = useState<Quotes>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const key = symbols.join(",");

  const load = useCallback(async () => {
    try {
      const r = await api<{ quotes: Quotes }>(`/api/market?symbols=${encodeURIComponent(key)}&closes=1`);
      setQuotes(r.quotes);
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [key]);

  useEffect(() => {
    if (!key) return;
    setLoading(true);
    load();
    const id = setInterval(load, pollMs);
    return () => clearInterval(id);
  }, [key, pollMs, load]);

  return { quotes, loading, error };
}

// ---------------- account hooks ----------------

export function useAccount(token: string | null, pollMs = 12000) {
  const [account, setAccount] = useState<AccountInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(Boolean(token));

  const load = useCallback(async () => {
    if (!token) return;
    try {
      const r = await api<AccountInfo>("/api/account", { token });
      setAccount(r);
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    if (!token) {
      setAccount(null);
      setLoading(false);
      return;
    }
    load();
    const id = setInterval(load, pollMs);
    // deposits / mode switches dispatch this to refresh immediately
    const onChanged = () => load();
    window.addEventListener("jexi.account-changed", onChanged);
    return () => {
      clearInterval(id);
      window.removeEventListener("jexi.account-changed", onChanged);
    };
  }, [token, pollMs, load]);

  return { account, error, loading, reload: load };
}

export function useFeed(token: string | null, pollMs = 15000, limit = 30) {
  const [events, setEvents] = useState<FeedEvent[]>([]);
  useEffect(() => {
    if (!token) return;
    let alive = true;
    const load = () =>
      api<{ events: FeedEvent[] }>(`/api/feed?limit=${limit}`, { token })
        .then((r) => alive && setEvents(r.events))
        .catch(() => {});
    load();
    const id = setInterval(load, pollMs);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, [token, pollMs, limit]);
  return events;
}

// ---------------- notifications (in-app, replaces ntfy) ----------------
// Every Jexi event — engine trades, deposits, withdrawals, the daily runner
// report — lands in the feed. The bell shows how many you have not seen.

const FEED_SEEN_KEY = "jexi.feedSeenId";

export function useNotifications(token: string | null, pollMs = 12000) {
  const events = useFeed(token, pollMs, 60);
  const [seenId, setSeenId] = useState(0);

  useEffect(() => {
    // One-time hydration of the last-seen marker (external system -> state).
    const raw = Number(localStorage.getItem(FEED_SEEN_KEY) || 0);
    if (Number.isFinite(raw)) setSeenId(raw);
  }, []);

  const unread = events.filter((e) => e.id > seenId).length;

  const markAllRead = useCallback(() => {
    const top = events.reduce((m, e) => Math.max(m, e.id), 0);
    if (top > 0) {
      localStorage.setItem(FEED_SEEN_KEY, String(top));
      setSeenId(top);
    }
  }, [events]);

  return { events, unread, markAllRead };
}

export function useProfits(token: string | null, pollMs = 30000) {
  const [profits, setProfits] = useState<Profits | null>(null);
  useEffect(() => {
    if (!token) return;
    let alive = true;
    const load = () =>
      api<Profits>("/api/profits", { token })
        .then((r) => alive && setProfits(r))
        .catch(() => {});
    load();
    const id = setInterval(load, pollMs);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, [token, pollMs]);
  return profits;
}

export function useAdmin(token: string | null, enabled: boolean) {
  const [overview, setOverview] = useState<AdminOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const load = useCallback(() => {
    if (!token || !enabled) return;
    setLoading(true);
    api<AdminOverview>("/api/admin/overview", { token })
      .then((r) => {
        setOverview(r);
        setError(null);
      })
      .catch((e) => setError((e as Error).message))
      .finally(() => setLoading(false));
  }, [token, enabled]);
  useEffect(() => {
    load();
  }, [load]);
  return { overview, error, loading, reload: load };
}

// ---------------- actions ----------------

export async function saveKeys(
  token: string,
  data: { aiProvider: string; aiKey: string; brokerName: string; brokerKey: string; brokerSecret?: string }
) {
  return api("/api/keys", { method: "POST", body: data, token });
}

export async function requestWithdrawal(token: string, amount: number, method: string, destination: string) {
  return api("/api/withdrawals", { method: "POST", body: { amount, method, destination }, token });
}

// ---------------- trading mode + deposits ----------------

export async function setTradingMode(token: string, mode: "paper" | "live") {
  return api<{ mode: string; changed: boolean; cash?: number }>("/api/account/mode", {
    method: "POST",
    body: { mode },
    token,
  });
}

export async function requestDeposit(token: string, amount: number, method: string, destination: string) {
  return api<{ status: string; amount: number; newCash?: number }>("/api/account/deposit", {
    method: "POST",
    body: { amount, method, destination },
    token,
  });
}

export interface DepositRow {
  id: number;
  amount: number;
  method: string;
  destination: string;
  status: string;
  created_at: string;
}

export async function fetchDeposits(token: string) {
  return api<{ deposits: DepositRow[] }>("/api/account/deposit", { token });
}

// Admin: approve / reject pending live deposits and withdrawals.
export async function adminDecide(
  token: string,
  kind: "deposits" | "withdrawals",
  id: number,
  action: "approve" | "reject"
) {
  return api(`/api/admin/${kind}`, { method: "POST", body: { id, action }, token });
}

export async function fetchKeys(token: string) {
  return api<{
    set: boolean;
    aiProvider?: string;
    aiKeyMasked?: string;
    brokerName?: string;
    brokerKeySet?: boolean;
  }>("/api/keys", { token });
}

export async function serverHealth(): Promise<boolean> {
  try {
    await api("/api/health");
    return true;
  } catch {
    return false;
  }
}

// ---------------- local persisted lists ----------------

export function useLocalList<T>(storageKey: string, initial: T[]) {
  const [items, setItems] = useState<T[]>(initial);
  const [hydrated, setHydrated] = useState(false);
  useEffect(() => {
    // One-time hydration from localStorage (external system -> React state).
    // eslint-disable-next-line react-hooks/set-state-in-effect
    const raw = localStorage.getItem(storageKey);
    if (raw) {
      try {
        setItems(JSON.parse(raw));
      } catch {}
    }
    setHydrated(true);
     
  }, []);
  useEffect(() => {
    if (hydrated) localStorage.setItem(storageKey, JSON.stringify(items));
  }, [items, hydrated, storageKey]);
  return [items, setItems] as const;
}

// ---------------- legal content ----------------

export const LEGAL_UPDATED = "September 15, 2026";

export function briefingFromQuotes(quotes: Quotes): {
  regime: string;
  regimeDetail: string;
  lines: string[];
} {
  const entries = Object.entries(quotes).filter(([, q]) => Number.isFinite(q.changePct || NaN));
  if (!entries.length) {
    return {
      regime: "Standing by",
      regimeDetail: "Waiting for live prices",
      lines: ["Market data is loading — the briefing updates the moment prices land."],
    };
  }
  const ups = entries.filter(([, q]) => (q.changePct || 0) > 0.15).length;
  const downs = entries.filter(([, q]) => (q.changePct || 0) < -0.15).length;
  const sorted = [...entries].sort((a, b) => (b[1].changePct || 0) - (a[1].changePct || 0));
  const top = sorted[0];
  const bottom = sorted[sorted.length - 1];
  const spy = quotes["SPY"];

  let regime = "Mixed tape";
  if (spy && (spy.changePct || 0) >= 0.3 && ups > downs) regime = "Risk-on";
  else if (spy && (spy.changePct || 0) <= -0.3 && downs > ups) regime = "Risk-off";

  return {
    regime,
    regimeDetail: `${ups} up · ${downs} down across the watch universe`,
    lines: [
      `${top[0]} leads with ${pct(top[1].changePct || 0)} at ${priceFmt(top[1].price)}.`,
      `${bottom[0]} is the weakest at ${pct(bottom[1].changePct || 0)}.`,
      spy
        ? `The index proxy (SPY) is ${pct(spy.changePct || 0)} — ${
            regime === "Risk-on"
              ? "drawdowns are being bought"
              : regime === "Risk-off"
                ? "sellers still control the tape"
                : "no clear trend leadership today"
          }.`
        : "",
      regime === "Risk-off"
        ? "JEXI keeps position sizes small and honors every safety line in this regime."
        : "JEXI keeps entries selective: only uptrends above the 10-day average qualify.",
    ].filter(Boolean),
  };
}
