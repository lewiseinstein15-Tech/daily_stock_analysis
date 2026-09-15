-- Jexi database schema (Cloudflare D1 / SQLite)
-- Run this once: D1 console -> Console -> paste -> Run

CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL,
  name TEXT DEFAULT '',
  is_admin INTEGER DEFAULT 0,
  terms_version TEXT,
  terms_accepted_at TEXT,
  created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS api_keys (
  user_id INTEGER PRIMARY KEY REFERENCES users(id),
  ai_provider TEXT DEFAULT '',
  ai_key_enc TEXT DEFAULT '',
  broker_name TEXT DEFAULT '',
  broker_key_enc TEXT DEFAULT '',
  broker_secret_enc TEXT DEFAULT '',
  updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS accounts (
  user_id INTEGER PRIMARY KEY REFERENCES users(id),
  cash REAL NOT NULL DEFAULT 10000,
  starting_balance REAL NOT NULL DEFAULT 10000,
  mode TEXT NOT NULL DEFAULT 'paper',
  last_tick TEXT DEFAULT '',
  paper_cash REAL,
  paper_starting REAL,
  live_cash REAL DEFAULT 0,
  live_starting REAL DEFAULT 0,
  updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS positions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id),
  symbol TEXT NOT NULL,
  qty REAL NOT NULL,
  avg_price REAL NOT NULL,
  last_price REAL NOT NULL DEFAULT 0,
  opened_at TEXT DEFAULT (datetime('now')),
  mode TEXT NOT NULL DEFAULT 'paper',
  UNIQUE(user_id, symbol, mode)
);

CREATE TABLE IF NOT EXISTS trades (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id),
  symbol TEXT NOT NULL,
  side TEXT NOT NULL,
  qty REAL NOT NULL,
  price REAL NOT NULL,
  amount REAL NOT NULL,
  pnl REAL NOT NULL DEFAULT 0,
  reason TEXT DEFAULT '',
  status TEXT NOT NULL DEFAULT 'filled',
  mode TEXT NOT NULL DEFAULT 'paper',
  created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS withdrawals (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id),
  amount REAL NOT NULL,
  method TEXT DEFAULT 'bank',
  destination TEXT DEFAULT '',
  status TEXT NOT NULL DEFAULT 'approved',
  mode TEXT NOT NULL DEFAULT 'paper',
  created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS deposits (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id),
  amount REAL NOT NULL,
  method TEXT DEFAULT 'm-pesa',
  destination TEXT DEFAULT '',
  status TEXT NOT NULL DEFAULT 'approved',
  mode TEXT NOT NULL DEFAULT 'paper',
  created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS equity_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id),
  equity REAL NOT NULL,
  mode TEXT NOT NULL DEFAULT 'paper',
  created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS feed_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id),
  kind TEXT DEFAULT 'info',
  message TEXT NOT NULL,
  created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_trades_user ON trades(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_feed_user ON feed_events(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_equity_user ON equity_snapshots(user_id, created_at DESC);
