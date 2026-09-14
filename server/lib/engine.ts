// JEXI trading engine: one tick evaluates exits first, then entries.
// Paper trading on live prices; every action lands in the feed in plain English.
import { getQuotes, Quote } from "./prices";

const WATCHLIST = ["AAPL", "MSFT", "NVDA", "AMZN", "META", "GOOGL", "TSLA", "SPY", "QQQ"];
const MAX_POSITIONS = 6;
const SAFETY_LINE = 0.93; // sell if price falls 7% below average cost
const TAKE_PROFIT = 1.18; // sell if price rises 18% above average cost

export interface TickResult {
  userId?: number;
  skipped?: boolean;
  note?: string;
  trades?: number;
  buys?: number;
  sells?: number;
  details?: string[];
}

export async function tickUser(store: any, userId: number): Promise<TickResult> {
  const account = await store.getAccount(userId);
  if (!account) return { skipped: true, note: "no account for user" };

  const quotes: Record<string, Quote> = await getQuotes(WATCHLIST);
  const tradable = Object.keys(quotes).filter(
    (s) => Number.isFinite(quotes[s].price) && quotes[s].price > 0
  );
  if (!tradable.length) {
    return {
      skipped: true,
      note: "no price data available right now - will check again on the next tick",
    };
  }

  const positions: any[] = await store.getPositions(userId);
  const held = new Set(positions.map((p: any) => p.symbol));
  const soldThisTick = new Set<string>();
  const details: string[] = [];
  let buys = 0;
  let sells = 0;

  // 1) manage open positions first
  for (const p of positions) {
    const quote = quotes[p.symbol];
    if (!quote || !(quote.price > 0)) continue;
    const price = quote.price;
    const stop = p.avg_price * SAFETY_LINE;
    const target = p.avg_price * TAKE_PROFIT;

    if (price <= stop || price >= target) {
      const pnl = (price - p.avg_price) * p.qty;
      const reason =
        price <= stop
          ? `Safety line hit: ${p.symbol} fell to $${price.toFixed(2)} (bought at $${p.avg_price.toFixed(2)}). Sold to protect your money.`
          : `Take profit: ${p.symbol} reached $${price.toFixed(2)} (bought at $${p.avg_price.toFixed(2)}). Sold to lock in the gain.`;
      await store.recordTrade({
        user_id: userId,
        symbol: p.symbol,
        side: "SELL",
        qty: p.qty,
        price,
        amount: price * p.qty,
        pnl,
        reason,
      });
      await store.deletePosition(userId, p.symbol);
      soldThisTick.add(p.symbol);
      sells++;
      details.push(`SELL ${p.symbol}`);
      await store.insertFeed(
        userId,
        pnl >= 0 ? "win" : "loss",
        pnl >= 0
          ? `Sold ${p.qty} ${p.symbol} at $${price.toFixed(2)} for a gain of $${pnl.toFixed(2)}. Reason: ${reason}`
          : `Sold ${p.qty} ${p.symbol} at $${price.toFixed(2)} for a loss of $${Math.abs(pnl).toFixed(2)}. Reason: ${reason}`
      );
    } else {
      await store.updatePositionPrice(userId, p.symbol, price);
    }
  }

  // 2) look for new entries
  let fresh = await store.getAccount(userId);
  let cash = fresh ? fresh.cash : 0;
  const openCount = positions.length - sells;

  for (const symbol of tradable) {
    if (held.has(symbol) || soldThisTick.has(symbol)) continue;
    if (openCount + buys >= MAX_POSITIONS) break;

    const quote = quotes[symbol];
    const closes = quote.closes || [];
    if (closes.length < 12) continue;

    const window = closes.slice(-10);
    const sma10 = window.reduce((a, b) => a + b, 0) / window.length;
    const rising = closes[closes.length - 1] > closes[closes.length - 6];
    if (!(quote.price > sma10 && rising)) continue;

    const spend = Math.min(cash * 0.25, 5000);
    const qty = Math.floor(spend / quote.price);
    if (qty < 1) continue;
    const cost = qty * quote.price;
    if (cost > cash || cost <= 0) continue;

    await store.recordTrade({
      user_id: userId,
      symbol,
      side: "BUY",
      qty,
      price: quote.price,
      amount: cost,
      pnl: 0,
      reason: `Uptrend: ${symbol} is trading above its 10-day average ($${sma10.toFixed(2)}) and still climbing.`,
    });
    await store.upsertPosition({
      user_id: userId,
      symbol,
      qty,
      avg_price: quote.price,
      last_price: quote.price,
    });
    await store.setCash(userId, cash - cost);
    cash -= cost;
    buys++;
    details.push(`BUY ${symbol}`);
    await store.insertFeed(
      userId,
      "info",
      `Bought ${qty} ${symbol} at $${quote.price.toFixed(2)} (about $${cost.toFixed(2)}). Reason: trading above its 10-day average and still climbing.`
    );
  }

  // 3) snapshot equity
  const finalAccount = await store.getAccount(userId);
  if (finalAccount) {
    const pos: any[] = await store.getPositions(userId);
    if (pos.length) {
      const freshQuotes = await getQuotes(pos.map((p: any) => p.symbol));
      const value = pos.reduce(
        (a: number, p: any) => a + p.qty * (freshQuotes[p.symbol]?.price || p.last_price || p.avg_price),
        0
      );
      await store.insertEquity(userId, finalAccount.cash + value);
    } else {
      await store.insertEquity(userId, finalAccount.cash);
    }
  }

  return { userId, trades: buys + sells, buys, sells, details };
}

export async function runTick(store: any): Promise<Record<string, unknown>> {
  const userIds = await store.listAccountUserIds();
  let trades = 0;
  const perUser: Record<string, unknown>[] = [];
  for (const uid of userIds) {
    try {
      const result = await tickUser(store, uid);
      trades += result.trades || 0;
      perUser.push({ ...result });
    } catch (e) {
      perUser.push({ userId: uid, error: String(e) });
    }
  }
  return { users: userIds.length, trades, perUser };
}
