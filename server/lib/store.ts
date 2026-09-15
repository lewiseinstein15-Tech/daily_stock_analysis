import { d1Query, d1Configured } from "./d1";

// ---------------- shared types ----------------
export interface User {
  id: number;
  email: string;
  name: string;
  password_hash: string;
  is_admin?: number;
}
export interface KeysRow {
  ai_provider: string;
  ai_key_enc: string;
  broker_name: string;
  broker_key_enc: string;
  broker_secret_enc: string;
}
export interface Account {
  user_id: number;
  cash: number;
  starting_balance: number;
  mode: string;
  last_tick: string;
}
export interface Position {
  symbol: string;
  qty: number;
  avg_price: number;
  last_price: number;
  opened_at: string;
}
export interface Trade {
  id: number;
  user_id: number;
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
export interface Withdrawal {
  id: number;
  user_id: number;
  amount: number;
  method: string;
  destination: string;
  status: string;
  created_at: string;
}
export interface FeedEvent {
  id: number;
  user_id: number;
  kind: string;
  message: string;
  created_at: string;
}
export interface NewTrade {
  user_id: number;
  symbol: string;
  side: string;
  qty: number;
  price: number;
  amount: number;
  pnl: number;
  reason: string;
}

export interface AdminUserRow {
  id: number;
  email: string;
  name: string;
  is_admin: number;
  created_at: string;
  cash: number;
  starting_balance: number;
  position_value: number;
}

// Per-user activity aggregates for the admin control room.
export interface AdminActivity {
  trades: Record<string, { n: number; lastAt: string }>;
  positions: Record<string, number>;
}

export function startingBalance(): number {
  const n = Number(process.env.STARTING_BALANCE || 10000);
  return Number.isFinite(n) && n > 0 ? n : 10000;
}

const nowSql = () => new Date().toISOString().slice(0, 19).replace("T", " ");

// ================= memory driver (local dev + tests) =================
class MemoryStore {
  driver = "memory" as const;
  private users: (User & { created_at: string })[] = [];
  private accounts = new Map<number, Account>();
  private positions: (Position & { user_id: number; id: number })[] = [];
  private trades: (Trade & { user_id: number })[] = [];
  private withdrawals: (Withdrawal & { user_id: number })[] = [];
  private events: (FeedEvent & { user_id: number })[] = [];
  private equity: { user_id: number; equity: number; created_at: string; id: number }[] = [];
  private keys = new Map<number, KeysRow>();
  private seq = 1;

  private nextId() {
    return this.seq++;
  }

  async getUserByEmail(email: string) {
    return this.users.find((u) => u.email === email.toLowerCase()) || null;
  }
  async getUserById(id: number) {
    return this.users.find((u) => u.id === id) || null;
  }
  async createUser(email: string, passwordHash: string, name: string, isAdmin = 0): Promise<User> {
    const user: User & { created_at: string } = {
      id: this.nextId(),
      email: email.toLowerCase(),
      name: name || "",
      password_hash: passwordHash,
      is_admin: isAdmin,
      created_at: nowSql(),
    };
    this.users.push(user);
    return user;
  }
  async promoteToAdmin(email: string) {
    const u = this.users.find((x) => x.email === email.toLowerCase());
    if (u) u.is_admin = 1;
  }
  async ensureAccount(userId: number, starting: number): Promise<Account> {
    let acc = this.accounts.get(userId);
    if (!acc) {
      acc = { user_id: userId, cash: starting, starting_balance: starting, mode: "paper", last_tick: "" };
      this.accounts.set(userId, acc);
    }
    return acc;
  }
  async getAccount(userId: number) {
    return this.accounts.get(userId) || null;
  }
  async setLastTick(userId: number, ts: string) {
    const acc = this.accounts.get(userId);
    if (acc) acc.last_tick = ts;
  }
  async setCash(userId: number, cash: number) {
    const acc = this.accounts.get(userId);
    if (acc) acc.cash = cash;
  }
  async getPositions(userId: number): Promise<Position[]> {
    return this.positions
      .filter((p) => p.user_id === userId)
      .map(({ user_id, id, ...p }) => p);
  }
  async upsertPosition(p: { user_id: number; symbol: string; qty: number; avg_price: number; last_price: number }) {
    const existing = this.positions.find((x) => x.user_id === p.user_id && x.symbol === p.symbol);
    if (existing) {
      existing.qty = p.qty;
      existing.avg_price = p.avg_price;
      existing.last_price = p.last_price;
    } else {
      this.positions.push({ id: this.nextId(), ...p, opened_at: nowSql() });
    }
  }
  async updatePositionPrice(userId: number, symbol: string, lastPrice: number) {
    const p = this.positions.find((x) => x.user_id === userId && x.symbol === symbol);
    if (p) p.last_price = lastPrice;
  }
  async deletePosition(userId: number, symbol: string) {
    this.positions = this.positions.filter((x) => !(x.user_id === userId && x.symbol === symbol));
  }
  async recordTrade(t: NewTrade) {
    this.trades.push({ id: this.nextId(), status: "filled", created_at: nowSql(), ...t });
  }
  async listTrades(userId: number, limit: number): Promise<Trade[]> {
    return this.trades
      .filter((t) => t.user_id === userId)
      .slice(-limit)
      .reverse();
  }
  async listRecentTradesAll(limit: number) {
    return this.trades.slice(-limit).reverse();
  }
  async insertFeed(userId: number, kind: string, message: string) {
    this.events.push({ id: this.nextId(), user_id: userId, kind, message, created_at: nowSql() });
  }
  async listFeed(userId: number, limit: number): Promise<FeedEvent[]> {
    return this.events
      .filter((e) => e.user_id === userId)
      .slice(-limit)
      .reverse();
  }
  async getKeys(userId: number) {
    return this.keys.get(userId) || null;
  }
  async setKeys(userId: number, row: KeysRow) {
    this.keys.set(userId, row);
  }
  async insertWithdrawal(userId: number, amount: number, method: string, destination: string) {
    this.withdrawals.push({
      id: this.nextId(),
      user_id: userId,
      amount,
      method,
      destination,
      status: "approved",
      created_at: nowSql(),
    });
  }
  async listWithdrawals(userId: number): Promise<Withdrawal[]> {
    return this.withdrawals.filter((w) => w.user_id === userId).reverse();
  }
  async listWithdrawalsAll(limit: number) {
    return this.withdrawals.slice(-limit).reverse();
  }
  async insertEquity(userId: number, equity: number) {
    this.equity.push({ id: this.nextId(), user_id: userId, equity, created_at: nowSql() });
  }
  async listEquity(userId: number, limit: number) {
    return this.equity
      .filter((e) => e.user_id === userId)
      .slice(-limit)
      .map((e) => ({ created_at: e.created_at, equity: e.equity }));
  }
  async listAccountUserIds(): Promise<number[]> {
    return [...this.accounts.keys()];
  }
  async adminActivity(): Promise<AdminActivity> {
    const trades: Record<string, { n: number; lastAt: string }> = {};
    for (const t of this.trades) {
      const cur = trades[String(t.user_id)];
      if (!cur) trades[String(t.user_id)] = { n: 1, lastAt: t.created_at };
      else {
        cur.n += 1;
        if (t.created_at > cur.lastAt) cur.lastAt = t.created_at;
      }
    }
    const positions: Record<string, number> = {};
    for (const p of this.positions) {
      positions[String(p.user_id)] = (positions[String(p.user_id)] || 0) + 1;
    }
    return { trades, positions };
  }
  async listUsersWithAccounts(limit = 200): Promise<AdminUserRow[]> {
    const posValue = new Map<number, number>();
    for (const p of this.positions) {
      posValue.set(p.user_id, (posValue.get(p.user_id) || 0) + p.qty * p.last_price);
    }
    return this.users.slice(-limit).reverse().map((u) => {
      const acc = this.accounts.get(u.id);
      return {
        id: u.id,
        email: u.email,
        name: u.name,
        is_admin: u.is_admin || 0,
        created_at: u.created_at,
        cash: acc ? acc.cash : 0,
        starting_balance: acc ? acc.starting_balance : 0,
        position_value: posValue.get(u.id) || 0,
      };
    });
  }
}

// ================= D1 driver (production) =================
class D1Store {
  driver = "d1" as const;

  async getUserByEmail(email: string) {
    const r = await d1Query<User>("SELECT * FROM users WHERE email = ? LIMIT 1", [email.toLowerCase()]);
    return r.rows[0] || null;
  }
  async getUserById(id: number) {
    const r = await d1Query<User>("SELECT * FROM users WHERE id = ? LIMIT 1", [id]);
    return r.rows[0] || null;
  }
  async createUser(email: string, passwordHash: string, name: string, isAdmin = 0): Promise<User> {
    const ins = await d1Query(
      "INSERT INTO users (email, password_hash, name, is_admin) VALUES (?, ?, ?, ?)",
      [email.toLowerCase(), passwordHash, name || "", isAdmin]
    );
    const id = Number(ins.meta.last_row_id);
    const r = await d1Query<User>("SELECT * FROM users WHERE id = ?", [id]);
    return r.rows[0] || { id, email: email.toLowerCase(), name: name || "", password_hash: "", is_admin: isAdmin };
  }
  async promoteToAdmin(email: string) {
    await d1Query("UPDATE users SET is_admin = 1 WHERE email = ?", [email.toLowerCase()]);
  }
  async ensureAccount(userId: number, starting: number): Promise<Account> {
    await d1Query(
      "INSERT OR IGNORE INTO accounts (user_id, cash, starting_balance, mode, last_tick) VALUES (?, ?, ?, 'paper', '')",
      [userId, starting, starting]
    );
    const r = await d1Query<Account>("SELECT * FROM accounts WHERE user_id = ? LIMIT 1", [userId]);
    return r.rows[0] || { user_id: userId, cash: starting, starting_balance: starting, mode: "paper", last_tick: "" };
  }
  async getAccount(userId: number) {
    const r = await d1Query<Account>("SELECT * FROM accounts WHERE user_id = ? LIMIT 1", [userId]);
    return r.rows[0] || null;
  }
  async setLastTick(userId: number, ts: string) {
    await d1Query("UPDATE accounts SET last_tick = ?, updated_at = ? WHERE user_id = ?", [ts, nowSql(), userId]);
  }
  async setCash(userId: number, cash: number) {
    await d1Query("UPDATE accounts SET cash = ?, updated_at = ? WHERE user_id = ?", [cash, nowSql(), userId]);
  }
  async getPositions(userId: number): Promise<Position[]> {
    const r = await d1Query<Position>(
      "SELECT symbol, qty, avg_price, last_price, opened_at FROM positions WHERE user_id = ? ORDER BY symbol",
      [userId]
    );
    return r.rows;
  }
  async upsertPosition(p: { user_id: number; symbol: string; qty: number; avg_price: number; last_price: number }) {
    await d1Query(
      `INSERT INTO positions (user_id, symbol, qty, avg_price, last_price, opened_at) VALUES (?, ?, ?, ?, ?, ?)
       ON CONFLICT(user_id, symbol) DO UPDATE SET qty = excluded.qty, avg_price = excluded.avg_price, last_price = excluded.last_price`,
      [p.user_id, p.symbol, p.qty, p.avg_price, p.last_price, nowSql()]
    );
  }
  async updatePositionPrice(userId: number, symbol: string, lastPrice: number) {
    await d1Query("UPDATE positions SET last_price = ? WHERE user_id = ? AND symbol = ?", [lastPrice, userId, symbol]);
  }
  async deletePosition(userId: number, symbol: string) {
    await d1Query("DELETE FROM positions WHERE user_id = ? AND symbol = ?", [userId, symbol]);
  }
  async recordTrade(t: NewTrade) {
    await d1Query(
      "INSERT INTO trades (user_id, symbol, side, qty, price, amount, pnl, reason, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'filled')",
      [t.user_id, t.symbol, t.side, t.qty, t.price, t.amount, t.pnl, t.reason]
    );
  }
  async listTrades(userId: number, limit: number): Promise<Trade[]> {
    const r = await d1Query<Trade>(
      "SELECT * FROM trades WHERE user_id = ? ORDER BY id DESC LIMIT ?",
      [userId, limit]
    );
    return r.rows;
  }
  async listRecentTradesAll(limit: number): Promise<(Trade & { email?: string })[]> {
    const r = await d1Query<Trade & { email?: string }>(
      "SELECT t.*, u.email FROM trades t JOIN users u ON u.id = t.user_id ORDER BY t.id DESC LIMIT ?",
      [limit]
    );
    return r.rows;
  }
  async insertFeed(userId: number, kind: string, message: string) {
    await d1Query("INSERT INTO feed_events (user_id, kind, message) VALUES (?, ?, ?)", [userId, kind, message]);
  }
  async listFeed(userId: number, limit: number): Promise<FeedEvent[]> {
    const r = await d1Query<FeedEvent>(
      "SELECT * FROM feed_events WHERE user_id = ? ORDER BY id DESC LIMIT ?",
      [userId, limit]
    );
    return r.rows;
  }
  async getKeys(userId: number) {
    const r = await d1Query<KeysRow>(
      "SELECT ai_provider, ai_key_enc, broker_name, broker_key_enc, broker_secret_enc FROM api_keys WHERE user_id = ? LIMIT 1",
      [userId]
    );
    return r.rows[0] || null;
  }
  async setKeys(userId: number, row: KeysRow) {
    await d1Query(
      `INSERT INTO api_keys (user_id, ai_provider, ai_key_enc, broker_name, broker_key_enc, broker_secret_enc, updated_at)
       VALUES (?, ?, ?, ?, ?, ?, ?)
       ON CONFLICT(user_id) DO UPDATE SET ai_provider = excluded.ai_provider, ai_key_enc = excluded.ai_key_enc,
         broker_name = excluded.broker_name, broker_key_enc = excluded.broker_key_enc,
         broker_secret_enc = excluded.broker_secret_enc, updated_at = excluded.updated_at`,
      [userId, row.ai_provider, row.ai_key_enc, row.broker_name, row.broker_key_enc, row.broker_secret_enc, nowSql()]
    );
  }
  async insertWithdrawal(userId: number, amount: number, method: string, destination: string) {
    await d1Query(
      "INSERT INTO withdrawals (user_id, amount, method, destination, status) VALUES (?, ?, ?, ?, 'approved')",
      [userId, amount, method, destination]
    );
  }
  async listWithdrawals(userId: number): Promise<Withdrawal[]> {
    const r = await d1Query<Withdrawal>(
      "SELECT * FROM withdrawals WHERE user_id = ? ORDER BY id DESC LIMIT 100",
      [userId]
    );
    return r.rows;
  }
  async listWithdrawalsAll(limit: number): Promise<(Withdrawal & { email?: string })[]> {
    const r = await d1Query<Withdrawal & { email?: string }>(
      "SELECT w.*, u.email FROM withdrawals w JOIN users u ON u.id = w.user_id ORDER BY w.id DESC LIMIT ?",
      [limit]
    );
    return r.rows;
  }
  async insertEquity(userId: number, equity: number) {
    await d1Query("INSERT INTO equity_snapshots (user_id, equity) VALUES (?, ?)", [userId, equity]);
  }
  async listEquity(userId: number, limit: number) {
    const r = await d1Query<{ created_at: string; equity: number }>(
      "SELECT created_at, equity FROM equity_snapshots WHERE user_id = ? ORDER BY id DESC LIMIT ?",
      [userId, limit]
    );
    return r.rows.reverse();
  }
  async listAccountUserIds(): Promise<number[]> {
    const r = await d1Query<{ user_id: number }>("SELECT user_id FROM accounts ORDER BY user_id LIMIT 500");
    return r.rows.map((row) => Number(row.user_id));
  }
  async adminActivity(): Promise<AdminActivity> {
    const t = await d1Query<{ user_id: number; n: number; lastAt: string }>(
      "SELECT user_id, COUNT(*) AS n, MAX(created_at) AS lastAt FROM trades GROUP BY user_id"
    );
    const p = await d1Query<{ user_id: number; n: number }>(
      "SELECT user_id, COUNT(*) AS n FROM positions GROUP BY user_id"
    );
    const trades: Record<string, { n: number; lastAt: string }> = {};
    for (const row of t.rows) trades[String(row.user_id)] = { n: Number(row.n), lastAt: String(row.lastAt) };
    const positions: Record<string, number> = {};
    for (const row of p.rows) positions[String(row.user_id)] = Number(row.n);
    return { trades, positions };
  }
  async listUsersWithAccounts(limit = 200): Promise<AdminUserRow[]> {
    const r = await d1Query<AdminUserRow>(
      `SELECT u.id, u.email, u.name, COALESCE(u.is_admin, 0) AS is_admin, u.created_at,
              COALESCE(a.cash, 0) AS cash, COALESCE(a.starting_balance, 0) AS starting_balance, 0 AS position_value
       FROM users u LEFT JOIN accounts a ON a.user_id = u.id
       ORDER BY u.id DESC LIMIT ?`,
      [limit]
    );
    const pv = await d1Query<{ user_id: number; v: number }>(
      "SELECT user_id, SUM(qty * last_price) AS v FROM positions GROUP BY user_id"
    );
    const map = new Map(pv.rows.map((row) => [Number(row.user_id), Number(row.v) || 0]));
    return r.rows.map((row) => ({ ...row, position_value: map.get(Number(row.id)) || 0 }));
  }
}

// ---------------- singleton ----------------
let memorySingleton: MemoryStore | null = null;
let d1Singleton: D1Store | null = null;

export function getStore(): MemoryStore | D1Store {
  if (d1Configured()) {
    if (!d1Singleton) d1Singleton = new D1Store();
    return d1Singleton;
  }
  if (!memorySingleton) memorySingleton = new MemoryStore();
  return memorySingleton;
}
