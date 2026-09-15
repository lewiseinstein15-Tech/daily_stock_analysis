import { getStore } from "@/lib/store";
import { getQuotes } from "@/lib/prices";
import { tickUser } from "@/lib/engine";
import { ok, bad, authFrom } from "@/lib/api";

const TICK_EVERY_MS = 3 * 60 * 1000; // re-evaluate the account at most every 3 minutes

export async function GET(req: Request) {
  const auth = authFrom(req);
  if (!auth) return bad("Not logged in.", 401);
  const store = getStore();

  const account = await store.getAccount(auth.uid);
  if (!account) {
    // Valid token but no user row = revoked/deleted session: tell the client
    // to sign out (401), not merely "missing data" (404).
    const user = await store.getUserById(auth.uid);
    if (!user) return bad("Session no longer valid — please sign in again.", 401);
    return bad("No account found.", 404);
  }

  // Keep Jexi working even without cron: if the last evaluation is stale,
  // run one now (bounded by prices cache + 3 minute gate).
  const last = Date.parse(account.last_tick.replace(" ", "T") + "Z");
  if (!account.last_tick || Number.isNaN(last) || Date.now() - last > TICK_EVERY_MS) {
    try {
      await tickUser(store, auth.uid);
      await store.setLastTick(auth.uid, new Date().toISOString().slice(0, 19).replace("T", " "));
    } catch {
      // never fail the read because of engine trouble
    }
  }

  const fresh = (await store.getAccount(auth.uid)) || account;
  const positions = await store.getPositions(auth.uid);

  // refresh prices for held symbols so the app shows live value
  const symbols = positions.map((p) => p.symbol);
  const quotes = symbols.length ? await getQuotes(symbols) : {};
  let positionsValue = 0;
  for (const p of positions) {
    const live = quotes[p.symbol]?.price || p.last_price || p.avg_price;
    p.last_price = live;
    positionsValue += p.qty * live;
  }
  const equity = fresh.cash + positionsValue;
  const pnl = equity - fresh.starting_balance;

  return ok({
    cash: Math.round(fresh.cash * 100) / 100,
    equity: Math.round(equity * 100) / 100,
    startingBalance: fresh.starting_balance,
    pnl: Math.round(pnl * 100) / 100,
    pnlPct: Math.round((pnl / fresh.starting_balance) * 10000) / 100,
    mode: fresh.mode,
    positions: positions.map((p) => ({
      symbol: p.symbol,
      qty: p.qty,
      avgPrice: p.avg_price,
      lastPrice: p.last_price,
      value: Math.round(p.qty * p.last_price * 100) / 100,
      pnl: Math.round((p.last_price - p.avg_price) * p.qty * 100) / 100,
      openedAt: p.opened_at,
    })),
  });
}
