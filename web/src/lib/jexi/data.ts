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
  totals: { users: number; equity: number; cash: number; positions: number };
  users: {
    id: number;
    email: string;
    name: string;
    isAdmin: boolean;
    cash: number;
    positionValue: number;
    equity: number;
    pnl: number;
    createdAt: string;
  }[];
  recentTrades: { id: number; email: string; symbol: string; side: string; qty: number; price: number; pnl: number; createdAt: string }[];
  withdrawals: { id: number; email: string; amount: number; method: string; status: string; createdAt: string }[];
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
    const onMsg = (e: MessageEvent) => {
      if (e.data?.type === "jexi-google-auth" && e.data.token) {
        applySession(e.data.token, e.data.user);
      }
    };
    window.addEventListener("message", onMsg);
    return () => window.removeEventListener("message", onMsg);
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
    return () => clearInterval(id);
  }, [token, pollMs, load]);

  return { account, error, loading, reload: load };
}

export function useFeed(token: string | null, pollMs = 15000) {
  const [events, setEvents] = useState<FeedEvent[]>([]);
  useEffect(() => {
    if (!token) return;
    let alive = true;
    const load = () =>
      api<{ events: FeedEvent[] }>("/api/feed", { token })
        .then((r) => alive && setEvents(r.events))
        .catch(() => {});
    load();
    const id = setInterval(load, pollMs);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, [token, pollMs]);
  return events;
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
  useEffect(() => {
    if (!token || !enabled) return;
    api<AdminOverview>("/api/admin/overview", { token })
      .then(setOverview)
      .catch((e) => setError((e as Error).message));
  }, [token, enabled]);
  return { overview, error };
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

// ---------------- demo content (labeled Demo in UI) ----------------

export const DEMO_FEED: FeedEvent[] = [
  {
    id: -3,
    kind: "info",
    message:
      "Demo feed: this is what JEXI's plain-English trading log looks like. Sign in to make it real.",
    created_at: new Date(Date.now() - 9 * 60000).toISOString(),
  },
  {
    id: -2,
    kind: "win",
    message:
      "Sold 12 NVDA at $218.40 for a gain of $410.20. Reason: take profit reached (bought at $184.20).",
    created_at: new Date(Date.now() - 52 * 60000).toISOString(),
  },
  {
    id: -1,
    kind: "info",
    message:
      "Bought 7 AAPL at $332.10 (about $2,324.70). Reason: trading above its 10-day average and still climbing.",
    created_at: new Date(Date.now() - 140 * 60000).toISOString(),
  },
];

export const DEMO_POSITIONS: Position[] = [
  { symbol: "AAPL", qty: 7, avgPrice: 332.1, lastPrice: 333.08, value: 2331.56, pnl: 6.86, openedAt: "" },
  { symbol: "MSFT", qty: 4, avgPrice: 508.4, lastPrice: 505.2, value: 2020.8, pnl: -12.8, openedAt: "" },
];

export interface ThesisContent {
  stance: "Bullish" | "Cautious" | "Neutral";
  conviction: number;
  drivers: string[];
  risks: string[];
  catalysts: string[];
}

export function demoThesis(symbol: string): ThesisContent {
  const specific: Record<string, ThesisContent> = {
    NVDA: {
      stance: "Bullish",
      conviction: 78,
      drivers: [
        "Data-center revenue trajectory remains the strongest in mega-cap tech",
        "Accelerated-compute demand from AI infrastructure buildouts",
        "Software ecosystem lock-in widens the moat each quarter",
      ],
      risks: [
        "Valuation already prices in years of flawless execution",
        "Custom silicon from hyperscalers competes at the high end",
        "Export controls create revenue concentration risk",
      ],
      catalysts: ["Quarterly earnings", "Next-gen product ramp", "Hyperscaler capex guides"],
    },
    AAPL: {
      stance: "Neutral",
      conviction: 62,
      drivers: ["Services margin expansion", "Install-base loyalty", "Capital return program"],
      risks: ["Hardware cycle saturation in mature markets", "China demand swings"],
      catalysts: ["Product launches", "Earnings", "Services disclosures"],
    },
    TSLA: {
      stance: "Cautious",
      conviction: 58,
      drivers: ["Energy storage growth", "Full-self-driving optionality"],
      risks: ["Margin compression from price cuts", "Demand elasticity at scale", "Key-person risk"],
      catalysts: ["Delivery numbers", "Margin updates", "Autonomy milestones"],
    },
  };
  return (
    specific[symbol] || {
      stance: "Neutral",
      conviction: 55,
      drivers: ["Sector momentum", "Balance-sheet quality", "Liquidity profile"],
      risks: ["Multiple expansion vs. growth", "Macro rate sensitivity"],
      catalysts: ["Quarterly earnings", "Sector policy shifts"],
    }
  );
}

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
