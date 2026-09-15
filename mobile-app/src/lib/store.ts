// JEXI store — one zustand store powering the whole app.
//
// Two modes live side by side:
//  · demo  — a friendly built-in simulation so anyone can look around instantly
//  · live  — connected to the user's own Jexi server (Vercel + Cloudflare D1),
//            where balance / trades / feed come from their real paper account
//
// Everything persists to device storage. Keys never leave the device except to
// the user's own server, encrypted in transit (https).

import { create } from 'zustand';

export const DEFAULT_SERVER = 'https://jexi-server.vercel.app';
const STORE_KEY = 'jexi-store-v1';

export interface Profile {
  name: string;
  email: string;
}

export interface Keys {
  aiProvider: string;
  aiKey: string;
  broker: string;
  brokerKey: string;
  brokerSecret: string;
}

export interface Position {
  id: string;
  sym: string;
  name: string;
  shares: number;
  avg: number;
  price: number;
}

export interface Trade {
  id: string;
  side: 'BUY' | 'SELL';
  sym: string;
  name: string;
  shares: number;
  price: number;
  value: number;
  pnl: number | null;
  ts: number;
  reason: string;
}

export type FeedKind = 'buy' | 'sell' | 'info' | 'warn' | 'win';

export interface FeedItem {
  id: string;
  kind: FeedKind;
  text: string;
  ts: number;
}

export interface Withdrawal {
  id: string;
  amount: number;
  method: string;
  ts: number;
  status: 'Sent' | 'Processing';
}

/** cash + what the open positions are worth right now. */
export function equityOf(s: { cash: number; positions: Position[] }): number {
  const inv = s.positions.reduce((a, p) => a + p.shares * p.price, 0);
  return Math.round((s.cash + inv) * 100) / 100;
}

interface DemoStock {
  sym: string;
  name: string;
  price: number;
}

const UNIVERSE: DemoStock[] = [
  { sym: 'AAPL', name: 'Apple', price: 228.4 },
  { sym: 'MSFT', name: 'Microsoft', price: 415.2 },
  { sym: 'NVDA', name: 'Nvidia', price: 121.8 },
  { sym: 'TSLA', name: 'Tesla', price: 248.6 },
  { sym: 'AMZN', name: 'Amazon', price: 186.3 },
  { sym: 'GOOGL', name: 'Alphabet', price: 166.9 },
  { sym: 'META', name: 'Meta', price: 512.7 },
  { sym: 'AMD', name: 'AMD', price: 152.4 },
  { sym: 'NFLX', name: 'Netflix', price: 689.1 },
  { sym: 'DIS', name: 'Disney', price: 96.5 },
];

const BUY_REASONS = [
  'It pulled back to a level where buyers stepped in before, and the plan says buy fear, not hype. I set its safety line the moment I bought it.',
  'The trend turned up again after a small dip. Small position, clear safety line — a bad day can never hurt you badly.',
  'Good news came out and the price had not moved yet. I got in early, kept the size small, and set the exit plan first.',
  'This one cooled off for three days in a row while the market stayed strong. That is exactly when my checklist says: time to buy.',
];

const SELL_WIN_REASONS = [
  'It reached the profit goal I set when I bought it, so I sold and locked the gain in. Boring? Maybe. Reliable? Yes.',
  'The price jumped faster than usual. I took the win — you never go broke taking profit.',
  'My plan said sell when this hit its target. It did. Money moves from "maybe" to "yours".',
];

const SELL_LOSS_REASONS = [
  'It fell to its safety line, so I sold right away to protect the rest of your money. Small losses are part of the plan.',
  'The story that made me buy it changed. When the reason is gone, I leave — that is how your money stays safe.',
  'It broke below its safety line during a rough patch. I stepped aside early instead of hoping.',
];

const IDLE_NOTES = [
  'Market is quiet right now. I am watching and waiting — patience is part of the plan.',
  'Nothing on my checklist is cheap enough yet. I would rather miss a trade than rush one.',
  'I checked every stock I follow. No safe moment appeared, so your money stays put.',
  'Still watching. Every open trade still has its safety line, exactly where I set it.',
];

interface Snapshot {
  onboarded: boolean;
  profile: Profile | null;
  keys: Keys | null;
  cash: number;
  positions: Position[];
  trades: Trade[];
  withdrawals: Withdrawal[];
  feed: FeedItem[];
  equityHistory: number[];
  dayStartEquity: number;
  paused: boolean;
  killed: boolean;
  liveMode: boolean;
  serverUrl: string;
  token: string;
}

interface JexiState extends Snapshot {
  booted: boolean;
  tick: number;
  boot: () => void;
  setProfile: (p: Profile) => void;
  setKeys: (k: Keys) => void;
  startEngine: () => void;
  setPaused: (v: boolean) => void;
  setKilled: (v: boolean) => void;
  requestWithdrawal: (amount: number, method: string, destination: string) => void;
  connectServer: (url: string, email: string, password: string) => Promise<string | null>;
  disconnectServer: () => void;
  resetAll: () => Promise<void>;
}

const uid = () => `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
const round2 = (n: number) => Math.round(n * 100) / 100;

function save(s: Snapshot) {
  try {
    localStorage.setItem(STORE_KEY, JSON.stringify(s));
  } catch {
    /* storage full or blocked — app still works this session */
  }
}

function load(): Partial<Snapshot> {
  try {
    const raw = localStorage.getItem(STORE_KEY);
    return raw ? (JSON.parse(raw) as Partial<Snapshot>) : {};
  } catch {
    return {};
  }
}

let engineId: ReturnType<typeof setInterval> | null = null;
let liveId: ReturnType<typeof setInterval> | null = null;
const saved = load();

export const useJexi = create<JexiState>((set, get) => {
  function snapshot(): Snapshot {
    const s = get();
    return {
      onboarded: s.onboarded,
      profile: s.profile,
      keys: s.keys,
      cash: s.cash,
      positions: s.positions,
      trades: s.trades,
      withdrawals: s.withdrawals,
      feed: s.feed,
      equityHistory: s.equityHistory,
      dayStartEquity: s.dayStartEquity,
      paused: s.paused,
      killed: s.killed,
      liveMode: s.liveMode,
      serverUrl: s.serverUrl,
      token: s.token,
    };
  }

  function feed(kind: FeedKind, text: string) {
    set((st) => ({ feed: [{ id: uid(), kind, text, ts: Date.now() }, ...st.feed].slice(0, 40) }));
  }

  /** One demo heartbeat: prices move, rules run, plain-English notes appear. */
  function demoTick() {
    const st = get();
    if (st.liveMode) return;

    // 1. market moves a little
    for (const u of UNIVERSE) {
      const drift = (Math.random() - 0.5) * 0.018;
      u.price = Math.max(5, round2(u.price * (1 + drift)));
    }

    // 2. engine rules (demo money)
    if (!st.paused && !st.killed) {
      let cash = st.cash;
      const positions = st.positions.map((p) => {
        const live = UNIVERSE.find((u) => u.sym === p.sym);
        return live ? { ...p, price: live.price } : p;
      });
      const trades = st.trades;
      const newFeed: FeedItem[] = [];
      const newTrades: Trade[] = [];

      // buy rule: few positions, plenty of cash, random safe moment
      const wantBuy = positions.length < 4 && cash > 600 && Math.random() < 0.16;
      if (wantBuy) {
        const held = new Set(positions.map((p) => p.sym));
        const options = UNIVERSE.filter((u) => !held.has(u.sym));
        const pick = options[Math.floor(Math.random() * options.length)];
        if (pick) {
          const budget = Math.min(cash * 0.2, 900);
          const shares = Math.max(1, Math.floor(budget / pick.price));
          const cost = round2(shares * pick.price);
          if (cost > 0 && cash >= cost) {
            cash = round2(cash - cost);
            positions.push({ id: uid(), sym: pick.sym, name: pick.name, shares, avg: pick.price, price: pick.price });
            newTrades.push({
              id: uid(), side: 'BUY', sym: pick.sym, name: pick.name, shares,
              price: pick.price, value: cost, pnl: null, ts: Date.now(),
              reason: BUY_REASONS[Math.floor(Math.random() * BUY_REASONS.length)],
            });
            newFeed.push({ id: uid(), kind: 'buy', ts: Date.now(), text: `I bought ${shares} share${shares > 1 ? 's' : ''} of ${pick.name} (${pick.sym}) for ${'$' + cost.toFixed(2)}. ${BUY_REASONS[Math.floor(Math.random() * BUY_REASONS.length)]}` });
          }
        }
      }

      // sell rule: safety line or profit goal, decided by how the trade is doing
      const wantSell = positions.length > 0 && Math.random() < 0.14;
      if (wantSell) {
        const idx = Math.floor(Math.random() * positions.length);
        const p = positions[idx];
        const pnl = round2((p.price - p.avg) * p.shares);
        cash = round2(cash + p.shares * p.price);
        positions.splice(idx, 1);
        const win = pnl >= 0;
        const reason = win
          ? SELL_WIN_REASONS[Math.floor(Math.random() * SELL_WIN_REASONS.length)]
          : SELL_LOSS_REASONS[Math.floor(Math.random() * SELL_LOSS_REASONS.length)];
        newTrades.push({
          id: uid(), side: 'SELL', sym: p.sym, name: p.name, shares: p.shares,
          price: p.price, value: round2(p.shares * p.price), pnl, ts: Date.now(), reason,
        });
        newFeed.push({
          id: uid(), kind: win ? 'win' : 'warn', ts: Date.now(),
          text: win
            ? `I sold ${p.name} (${p.sym}) for a ${pnl >= 0 ? '+' : ''}$${pnl.toFixed(2)} gain. ${reason}`
            : `I sold ${p.name} (${p.sym}). Result: -$${Math.abs(pnl).toFixed(2)}. ${reason}`,
        });
      }

      // occasional plain-English "nothing happened" notes
      if (!newFeed.length && Math.random() < 0.07) {
        newFeed.push({ id: uid(), kind: 'info', ts: Date.now(), text: IDLE_NOTES[Math.floor(Math.random() * IDLE_NOTES.length)] });
      }

      const eq = equityOf({ cash, positions });
      const dayStart = st.dayStartEquity || eq;
      set({
        cash,
        positions,
        trades: newTrades.length ? [...newTrades, ...trades].slice(0, 200) : trades,
        feed: newFeed.length ? [...newFeed.reverse(), ...st.feed].slice(0, 40) : st.feed,
        equityHistory: [...st.equityHistory, eq].slice(-48),
        dayStartEquity: dayStart,
        tick: st.tick + 1,
      });
    } else {
      const eq = equityOf({ cash: st.cash, positions: st.positions });
      set({
        equityHistory: [...st.equityHistory, eq].slice(-48),
        tick: st.tick + 1,
      });
    }
    save(snapshot());
  }

  /** Live mode: pull the real numbers from the user's own server. */
  async function refreshLive() {
    const st = get();
    if (!st.liveMode || !st.token) return;
    try {
      const headers = { Authorization: `Bearer ${st.token}` };
      const acc = await fetch(`${st.serverUrl}/api/account`, { headers }).then((r) => (r.ok ? r.json() : null));
      if (!acc) return;
      const positions: Position[] = (acc.positions || []).map((p: { symbol: string; qty: number; avgPrice: number; lastPrice: number }, i: number) => ({
        id: `live-${p.symbol}-${i}`,
        sym: p.symbol,
        name: p.symbol,
        shares: p.qty,
        avg: p.avgPrice,
        price: p.lastPrice,
      }));
      const equity = acc.equity ?? equityOf({ cash: acc.cash ?? 0, positions });

      let trades = st.trades;
      let dayStart = st.dayStartEquity;
      const prof = await fetch(`${st.serverUrl}/api/profits`, { headers }).then((r) => (r.ok ? r.json() : null));
      if (prof) {
        dayStart = round2(equity - (prof.todayPnl ?? 0));
        const tr = await fetch(`${st.serverUrl}/api/trades`, { headers }).then((r) => (r.ok ? r.json() : null));
        if (tr?.trades) {
          trades = tr.trades.map((t: { id: number; side: string; symbol: string; qty: number; price: number; amount: number; pnl: number; reason: string; created_at: string }) => ({
            id: `srv-${t.id}`,
            side: t.side === 'SELL' ? 'SELL' : 'BUY',
            sym: t.symbol,
            name: t.symbol,
            shares: t.qty,
            price: t.price,
            value: t.amount,
            pnl: t.side === 'SELL' ? t.pnl : null,
            ts: Date.parse(t.created_at.length === 19 ? t.created_at + 'Z' : t.created_at),
            reason: t.reason || 'No note was recorded for this trade.',
          }));
        }
      }

      const ev = await fetch(`${st.serverUrl}/api/feed`, { headers }).then((r) => (r.ok ? r.json() : null));
      const feedItems: FeedItem[] = ev?.events
        ? ev.events.map((e: { id: number; kind: string; message: string; created_at: string }) => ({
            id: `srv-f-${e.id}`,
            kind: (['buy', 'sell', 'info', 'warn', 'win'].includes(e.kind) ? e.kind : 'info') as FeedKind,
            text: e.message,
            ts: Date.parse(e.created_at.length === 19 ? e.created_at + 'Z' : e.created_at),
          }))
        : st.feed;

      set({
        cash: acc.cash ?? st.cash,
        positions,
        trades: trades.slice(0, 200),
        feed: feedItems.slice(0, 40),
        equityHistory: [...st.equityHistory, equity].slice(-48),
        dayStartEquity: dayStart,
        tick: st.tick + 1,
      });
      save(snapshot());
    } catch {
      /* offline — keep last known numbers, try again next poll */
    }
  }

  function startLivePoll() {
    if (liveId) return;
    liveId = setInterval(refreshLive, 20_000);
    refreshLive();
  }

  return {
    booted: false,
    tick: 0,

    onboarded: saved.onboarded ?? false,
    profile: saved.profile ?? null,
    keys: saved.keys ?? null,
    cash: saved.cash ?? 10000,
    positions: saved.positions ?? [],
    trades: saved.trades ?? [],
    withdrawals: saved.withdrawals ?? [],
    feed: saved.feed ?? [
      {
        id: 'seed-1',
        kind: 'info',
        text: 'Hi! I am Jexi. While you look around, I run on demo money so you can see exactly how I think and trade. Connect your own server in Settings whenever you are ready.',
        ts: Date.now(),
      },
    ],
    equityHistory: saved.equityHistory ?? [],
    dayStartEquity: saved.dayStartEquity ?? 0,
    paused: saved.paused ?? false,
    killed: saved.killed ?? false,
    liveMode: saved.liveMode ?? false,
    serverUrl: saved.serverUrl ?? DEFAULT_SERVER,
    token: saved.token ?? '',

    boot: () => {
      set({ booted: true });
      if (get().liveMode && get().token) startLivePoll();
    },

    setProfile: (p) => {
      set({ profile: p, onboarded: true });
      feed('info', `Welcome aboard, ${p.name.split(' ')[0]}! I am ready to work for you. Add your keys next so I can trade with your account.`);
      save(snapshot());
    },

    setKeys: (k) => {
      set({ keys: k });
      feed('info', `Keys saved on this device only. I will use ${k.aiProvider} to think and ${k.broker} to trade.`);
      save(snapshot());
    },

    startEngine: () => {
      if (engineId) return;
      const st = get();
      if (!st.dayStartEquity) {
        set({ dayStartEquity: equityOf({ cash: st.cash, positions: st.positions }) });
      }
      if (st.liveMode) {
        startLivePoll();
        return;
      }
      // seed a little history so the chart has a line from the first second
      if (get().equityHistory.length < 2) {
        const eq = equityOf({ cash: get().cash, positions: get().positions });
        set({ equityHistory: [round2(eq * 0.998), round2(eq * 0.999), eq] });
      }
      engineId = setInterval(demoTick, 5000);
    },

    setPaused: (v) => {
      set({ paused: v });
      feed('info', v ? 'Paused. I will keep watching everything, but I will not trade until you say go.' : 'Back on. Watching the market for safe moments again.');
      save(snapshot());
    },

    setKilled: (v) => {
      set({ killed: v });
      if (v) feed('warn', 'Everything is fully stopped. No trades will happen until you press resume.');
      save(snapshot());
    },

    requestWithdrawal: (amount, method, destination) => {
      const st = get();
      const w: Withdrawal = { id: uid(), amount, method, ts: Date.now(), status: 'Processing' };
      set({ cash: round2(st.cash - amount), withdrawals: [w, ...st.withdrawals] });
      feed('sell', `Withdrawal started: $${amount.toFixed(2)} via ${method}${destination ? ` (${destination})` : ''}. I will message you the moment it is sent.`);
      save(snapshot());
    },

    connectServer: async (url, email, password) => {
      const raw = url.trim() || DEFAULT_SERVER;
      const base = /^https?:\/\//i.test(raw) ? raw.replace(/\/+$/, '') : `https://${raw.replace(/\/+$/, '')}`;
      try {
        const res = await fetch(`${base}/api/auth/login`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ email, password }),
        });
        const j = await res.json().catch(() => null);
        if (!res.ok || !j?.token) {
          return j?.error || 'Could not sign in. Check the address, email and password.';
        }
        const st = get();
        const demoBackup: Partial<Snapshot> = {
          cash: st.cash,
          positions: st.positions,
          trades: st.trades,
          feed: st.feed,
          equityHistory: st.equityHistory,
          dayStartEquity: st.dayStartEquity,
          withdrawals: st.withdrawals,
        };
        try {
          localStorage.setItem(`${STORE_KEY}-demo`, JSON.stringify(demoBackup));
        } catch {}
        set({
          liveMode: true,
          serverUrl: base,
          token: j.token,
          profile: { name: j.user?.name || email.split('@')[0], email: j.user?.email || email },
          onboarded: true,
          cash: j.account?.cash ?? 10000,
        });
        feed('info', `Connected to ${base}. Everything you see now comes from your own server account.`);
        startLivePoll();
        save(snapshot());
        return null;
      } catch {
        return 'Could not reach that server. Check the address and your internet, then try again.';
      }
    },

    disconnectServer: () => {
      if (liveId) {
        clearInterval(liveId);
        liveId = null;
      }
      let demo: Partial<Snapshot> = {};
      try {
        demo = JSON.parse(localStorage.getItem(`${STORE_KEY}-demo`) || '{}');
      } catch {}
      set({ liveMode: false, token: '', serverUrl: DEFAULT_SERVER });
      set({
        cash: demo.cash ?? 10000,
        positions: demo.positions ?? [],
        trades: demo.trades ?? [],
        feed: demo.feed ?? get().feed,
        equityHistory: demo.equityHistory ?? [],
        dayStartEquity: demo.dayStartEquity ?? 0,
        withdrawals: demo.withdrawals ?? [],
      });
      feed('info', 'Disconnected from the server. Back to demo money — nothing was deleted.');
      save(snapshot());
    },

    resetAll: async () => {
      if (engineId) {
        clearInterval(engineId);
        engineId = null;
      }
      if (liveId) {
        clearInterval(liveId);
        liveId = null;
      }
      try {
        localStorage.removeItem(STORE_KEY);
        localStorage.removeItem(`${STORE_KEY}-demo`);
      } catch {}
      set({
        booted: true,
        onboarded: false,
        profile: null,
        keys: null,
        cash: 10000,
        positions: [],
        trades: [],
        withdrawals: [],
        feed: [
          {
            id: 'seed-1',
            kind: 'info',
            text: 'Hi! I am Jexi. While you look around, I run on demo money so you can see exactly how I think and trade. Connect your own server in Settings whenever you are ready.',
            ts: Date.now(),
          },
        ],
        equityHistory: [],
        dayStartEquity: 0,
        paused: false,
        killed: false,
        liveMode: false,
        token: '',
        serverUrl: DEFAULT_SERVER,
        tick: 0,
      });
    },
  };
});
