import { d1Query, d1Configured } from "./d1";

// ---------------- shared types ----------------
export interface User {
  id: number;
  email: string;
  name: string;
  password_hash: string;
  is_admin?: number;
  terms_version?: string | null;
  terms_accepted_at?: string | null;
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
  // Per-mode ledgers. `cash` / `starting_balance` above always mirror the
  // CURRENT mode so every existing reader keeps working untouched.
  paper_cash?: number;
  paper_starting?: number;
  live_cash?: number;
  live_starting?: number;
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
  mode?: string;
}
export interface Withdrawal {
  id: number;
  user_id: number;
  amount: number;
  method: string;
  destination: string;
  status: string;
  created_at: string;
  mode?: string;
}
export interface Deposit {
  id: number;
  user_id: number;
  amount: number;
  method: string;
  destination: string;
  status: string;
  created_at: string;
  mode?: string;
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
  mode?: string;
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

const normMode = (m?: string) => (m === "live" ? "live" : "paper");

// ================= memory driver (local dev + tests) =================
class MemoryStore {
  driver = "memory" as const;
  private users: (User & { created_at: string })[] = [];
  private accounts = new Map<number, Account>();
  private positions: (Position & { user_id: number; id: number; mode: string })[] = [];
  private trades: (Trade & { user_id: number })[] = [];
  private withdrawals: (Withdrawal & { user_id: number })[] = [];
  private deposits: (Deposit & { user_id: number })[] = [];
  private events: (FeedEvent & { user_id: number })[] = [];
  private equity: { user_id: number; equity: number; created_at: string; id: number; mode: string }[] = [];
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
  async acceptTerms(id: number, version: string, acceptedAt: string) {
    const u = this.users.find((x) => x.id === id);
    if (u) {
      u.terms_version = version;
      u.terms_accepted_at = acceptedAt;
    }
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
      acc = {
        user_id: userId,
        cash: starting,
        starting_balance: starting,
        mode: "paper",
        last_tick: "",
        paper_cash: starting,
        paper_starting: starting,
        live_cash: 0,
        live_starting: 0,
      };
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
    if (acc) {
      acc.cash = cash;
      if (acc.mode === "live") acc.live_cash = cash;
      else acc.paper_cash = cash;
    }
  }
  // Swap the active book: park the current cash/starting into its mode slot
  // and promote the other mode's slot into the live fields.
  async switchMode(userId: number, newMode: string): Promise<Account | null> {
    const acc = this.accounts.get(userId);
    if (!acc) return null;
    const cur = normMode(acc.mode);
    const target = normMode(newMode);
    if (cur === target) return acc;
    if (cur === "paper") {
      acc.paper_cash = acc.cash;
      acc.paper_starting = acc.starting_balance;
      acc.cash = acc.live_cash ?? 0;
      acc.starting_balance = acc.live_starting ?? 0;
    } else {
      acc.live_cash = acc.cash;
      acc.live_starting = acc.starting_balance;
      acc.cash = acc.paper_cash ?? startingBalance();
      acc.starting_balance = acc.paper_starting ?? startingBalance();
    }
    acc.mode = target;
    return acc;
  }
  async getPositions(userId: number, mode = "paper"): Promise<Position[]> {
    return this.positions
      .filter((p) => p.user_id === userId && p.mode === normMode(mode))
      .map(({ user_id, id, mode: _m, ...p }) => p);
  }
  async upsertPosition(p: {
    user_id: number;
    symbol: string;
    qty: number;
    avg_price: number;
    last_price: number;
    mode?: string;
  }) {
    const mode = normMode(p.mode);
    const existing = this.positions.find(
      (x) => x.user_id === p.user_id && x.symbol === p.symbol && x.mode === mode
    );
    if (existing) {
      existing.qty = p.qty;
      existing.avg_price = p.avg_price;
      existing.last_price = p.last_price;
    } else {
      this.positions.push({ id: this.nextId(), ...p, mode, opened_at: nowSql() });
    }
  }
  async updatePositionPrice(userId: number, symbol: string, lastPrice: number, mode = "paper") {
    const p = this.positions.find(
      (x) => x.user_id === userId && x.symbol === symbol && x.mode === normMode(mode)
    );
    if (p) p.last_price = lastPrice;
  }
  async deletePosition(userId: number, symbol: string, mode = "paper") {
    this.positions = this.positions.filter(
      (x) => !(x.user_id === userId && x.symbol === symbol && x.mode === normMode(mode))
    );
  }
  async recordTrade(t: NewTrade) {
    this.trades.push({ id: this.nextId(), status: "filled", created_at: nowSql(), mode: normMode(t.mode), ...t });
  }
  async listTrades(userId: number, limit: number, mode?: string): Promise<Trade[]> {
    let rows = this.trades.filter((t) => t.user_id === userId);
    if (mode) rows = rows.filter((t) => t.mode === normMode(mode));
    return rows.slice(-limit).reverse();
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
  async insertWithdrawal(
    userId: number,
    amount: number,
    method: string,
    destination: string,
    mode = "paper",
    status = "approved"
  ) {
    this.withdrawals.push({
      id: this.nextId(),
      user_id: userId,
      amount,
      method,
      destination,
      status,
      mode: normMode(mode),
      created_at: nowSql(),
    });
  }
  async listWithdrawals(userId: number, mode?: string): Promise<Withdrawal[]> {
    let rows = this.withdrawals.filter((w) => w.user_id === userId);
    if (mode) rows = rows.filter((w) => w.mode === normMode(mode));
    return rows.reverse();
  }
  async listWithdrawalsAll(limit: number) {
    return this.withdrawals.slice(-limit).reverse();
  }
  async setWithdrawalStatus(id: number, status: string) {
    const w = this.withdrawals.find((x) => x.id === id);
    if (w) w.status = status;
  }
  async getWithdrawal(id: number) {
    return this.withdrawals.find((x) => x.id === id) || null;
  }
  async insertDeposit(
    userId: number,
    amount: number,
    method: string,
    destination: string,
    mode = "paper",
    status = "approved"
  ) {
    const d: Deposit & { user_id: number } = {
      id: this.nextId(),
      user_id: userId,
      amount,
      method,
      destination,
      status,
      mode: normMode(mode),
      created_at: nowSql(),
    };
    this.deposits.push(d);
    return d;
  }
  async listDeposits(userId: number, mode?: string): Promise<Deposit[]> {
    let rows = this.deposits.filter((d) => d.user_id === userId);
    if (mode) rows = rows.filter((d) => d.mode === normMode(mode));
    return rows.reverse();
  }
  async listDepositsAll(limit: number) {
    return this.deposits.slice(-limit).reverse();
  }
  async getDeposit(id: number) {
    return this.deposits.find((x) => x.id === id) || null;
  }
  async setDepositStatus(id: number, status: string) {
    const d = this.deposits.find((x) => x.id === id);
    if (d) d.status = status;
  }
  async insertEquity(userId: number, equity: number, mode = "paper") {
    this.equity.push({ id: this.nextId(), user_id: userId, equity, created_at: nowSql(), mode: normMode(mode) });
  }
  async listEquity(userId: number, limit: number, mode = "paper") {
    return this.equity
      .filter((e) => e.user_id === userId && e.mode === normMode(mode))
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
const ACC_SELECT = `SELECT user_id, cash, starting_balance, mode, last_tick,
  COALESCE(paper_cash, cash) AS paper_cash,
  COALESCE(paper_starting, starting_balance) AS paper_starting,
  COALESCE(live_cash, 0) AS live_cash,
  COALESCE(live_starting, 0) AS live_starting
  FROM accounts WHERE user_id = ? LIMIT 1`;

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
  async acceptTerms(id: number, version: string, acceptedAt: string) {
    await d1Query(
      "UPDATE users SET terms_version = ?, terms_accepted_at = ? WHERE id = ?",
      [version, acceptedAt, id]
    );
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
      `INSERT OR IGNORE INTO accounts (user_id, cash, starting_balance, mode, last_tick,
        paper_cash, paper_starting, live_cash, live_starting)
       VALUES (?, ?, ?, 'paper', '', ?, ?, 0, 0)`,
      [userId, starting, starting, starting, starting]
    );
    const r = await d1Query<Account>(ACC_SELECT, [userId]);
    return (
      r.rows[0] || {
        user_id: userId,
        cash: starting,
        starting_balance: starting,
        mode: "paper",
        last_tick: "",
      }
    );
  }
  async getAccount(userId: number) {
    const r = await d1Query<Account>(ACC_SELECT, [userId]);
    return r.rows[0] || null;
  }
  async setLastTick(userId: number, ts: string) {
    await d1Query("UPDATE accounts SET last_tick = ?, updated_at = ? WHERE user_id = ?", [ts, nowSql(), userId]);
  }
  async setCash(userId: number, cash: number) {
    // Keep the mirror + the active mode's slot in sync in one statement.
    await d1Query(
      `UPDATE accounts SET cash = ?,
        paper_cash = CASE WHEN mode = 'paper' THEN ? ELSE paper_cash END,
        live_cash  = CASE WHEN mode = 'live'  THEN ? ELSE live_cash  END,
        updated_at = ? WHERE user_id = ?`,
      [cash, cash, cash, nowSql(), userId]
    );
  }
  async switchMode(userId: number, newMode: string): Promise<Account | null> {
    const acc = await this.getAccount(userId);
    if (!acc) return null;
    const cur = normMode(acc.mode);
    const target = normMode(newMode);
    if (cur === target) return acc;
    if (cur === "paper") {
      await d1Query(
        `UPDATE accounts SET
           paper_cash = cash, paper_starting = starting_balance,
           cash = COALESCE(live_cash, 0), starting_balance = COALESCE(live_starting, 0),
           mode = 'live', updated_at = ?
         WHERE user_id = ?`,
        [nowSql(), userId]
      );
    } else {
      await d1Query(
        `UPDATE accounts SET
           live_cash = cash, live_starting = starting_balance,
           cash = COALESCE(paper_cash, ?), starting_balance = COALESCE(paper_starting, ?),
           mode = 'paper', updated_at = ?
         WHERE user_id = ?`,
        [startingBalance(), startingBalance(), nowSql(), userId]
      );
    }
    return this.getAccount(userId);
  }
  async getPositions(userId: number, mode = "paper"): Promise<Position[]> {
    const r = await d1Query<Position>(
      "SELECT symbol, qty, avg_price, last_price, opened_at FROM positions WHERE user_id = ? AND mode = ? ORDER BY symbol",
      [userId, normMode(mode)]
    );
    return r.rows;
  }
  async upsertPosition(p: {
    user_id: number;
    symbol: string;
    qty: number;
    avg_price: number;
    last_price: number;
    mode?: string;
  }) {
    await d1Query(
      `INSERT INTO positions (user_id, symbol, qty, avg_price, last_price, opened_at, mode) VALUES (?, ?, ?, ?, ?, ?, ?)
       ON CONFLICT(user_id, symbol, mode) DO UPDATE SET qty = excluded.qty, avg_price = excluded.avg_price, last_price = excluded.last_price`,
      [p.user_id, p.symbol, p.qty, p.avg_price, p.last_price, nowSql(), normMode(p.mode)]
    );
  }
  async updatePositionPrice(userId: number, symbol: string, lastPrice: number, mode = "paper") {
    await d1Query("UPDATE positions SET last_price = ? WHERE user_id = ? AND symbol = ? AND mode = ?", [
      lastPrice,
      userId,
      symbol,
      normMode(mode),
    ]);
  }
  async deletePosition(userId: number, symbol: string, mode = "paper") {
    await d1Query("DELETE FROM positions WHERE user_id = ? AND symbol = ? AND mode = ?", [
      userId,
      symbol,
      normMode(mode),
    ]);
  }
  async recordTrade(t: NewTrade) {
    await d1Query(
      "INSERT INTO trades (user_id, symbol, side, qty, price, amount, pnl, reason, status, mode) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'filled', ?)",
      [t.user_id, t.symbol, t.side, t.qty, t.price, t.amount, t.pnl, t.reason, normMode(t.mode)]
    );
  }
  async listTrades(userId: number, limit: number, mode?: string): Promise<Trade[]> {
    const sql = mode
      ? "SELECT * FROM trades WHERE user_id = ? AND mode = ? ORDER BY id DESC LIMIT ?"
      : "SELECT * FROM trades WHERE user_id = ? ORDER BY id DESC LIMIT ?";
    const r = await d1Query<Trade>(sql, mode ? [userId, normMode(mode), limit] : [userId, limit]);
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
  async insertWithdrawal(
    userId: number,
    amount: number,
    method: string,
    destination: string,
    mode = "paper",
    status = "approved"
  ) {
    await d1Query(
      "INSERT INTO withdrawals (user_id, amount, method, destination, status, mode) VALUES (?, ?, ?, ?, ?, ?)",
      [userId, amount, method, destination, status, normMode(mode)]
    );
  }
  async listWithdrawals(userId: number, mode?: string): Promise<Withdrawal[]> {
    const sql = mode
      ? "SELECT * FROM withdrawals WHERE user_id = ? AND mode = ? ORDER BY id DESC LIMIT 100"
      : "SELECT * FROM withdrawals WHERE user_id = ? ORDER BY id DESC LIMIT 100";
    const r = await d1Query<Withdrawal>(sql, mode ? [userId, normMode(mode)] : [userId]);
    return r.rows;
  }
  async listWithdrawalsAll(limit: number): Promise<(Withdrawal & { email?: string })[]> {
    const r = await d1Query<Withdrawal & { email?: string }>(
      "SELECT w.*, u.email FROM withdrawals w JOIN users u ON u.id = w.user_id ORDER BY w.id DESC LIMIT ?",
      [limit]
    );
    return r.rows;
  }
  async getWithdrawal(id: number) {
    const r = await d1Query<Withdrawal>("SELECT * FROM withdrawals WHERE id = ? LIMIT 1", [id]);
    return r.rows[0] || null;
  }
  async setWithdrawalStatus(id: number, status: string) {
    await d1Query("UPDATE withdrawals SET status = ? WHERE id = ?", [status, id]);
  }
  async insertDeposit(
    userId: number,
    amount: number,
    method: string,
    destination: string,
    mode = "paper",
    status = "approved"
  ) {
    const ins = await d1Query(
      "INSERT INTO deposits (user_id, amount, method, destination, status, mode) VALUES (?, ?, ?, ?, ?, ?)",
      [userId, amount, method, destination, status, normMode(mode)]
    );
    const id = Number(ins.meta.last_row_id);
    const r = await d1Query<Deposit>("SELECT * FROM deposits WHERE id = ? LIMIT 1", [id]);
    return r.rows[0];
  }
  async listDeposits(userId: number, mode?: string): Promise<Deposit[]> {
    const sql = mode
      ? "SELECT * FROM deposits WHERE user_id = ? AND mode = ? ORDER BY id DESC LIMIT 50"
      : "SELECT * FROM deposits WHERE user_id = ? ORDER BY id DESC LIMIT 50";
    const r = await d1Query<Deposit>(sql, mode ? [userId, normMode(mode)] : [userId]);
    return r.rows;
  }
  async listDepositsAll(limit: number): Promise<(Deposit & { email?: string })[]> {
    const r = await d1Query<Deposit & { email?: string }>(
      "SELECT d.*, u.email FROM deposits d JOIN users u ON u.id = d.user_id ORDER BY d.id DESC LIMIT ?",
      [limit]
    );
    return r.rows;
  }
  async getDeposit(id: number) {
    const r = await d1Query<Deposit>("SELECT * FROM deposits WHERE id = ? LIMIT 1", [id]);
    return r.rows[0] || null;
  }
  async setDepositStatus(id: number, status: string) {
    await d1Query("UPDATE deposits SET status = ? WHERE id = ?", [status, id]);
  }
  async insertEquity(userId: number, equity: number, mode = "paper") {
    await d1Query("INSERT INTO equity_snapshots (user_id, equity, mode) VALUES (?, ?, ?)", [userId, equity, normMode(mode)]);
  }
  async listEquity(userId: number, limit: number, mode = "paper") {
    const r = await d1Query<{ created_at: string; equity: number }>(
      "SELECT created_at, equity FROM equity_snapshots WHERE user_id = ? AND mode = ? ORDER BY id DESC LIMIT ?",
      [userId, normMode(mode), limit]
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
      "SELECT user_id, COUNT(*) AS n FROM positions GROUP BY user_id, mode"
    );
    const trades: Record<string, { n: number; lastAt: string }> = {};
    for (const row of t.rows) trades[String(row.user_id)] = { n: Number(row.n), lastAt: String(row.lastAt) };
    const positions: Record<string, number> = {};
    for (const row of p.rows) positions[String(row.user_id)] = (positions[String(row.user_id)] || 0) + Number(row.n);
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
