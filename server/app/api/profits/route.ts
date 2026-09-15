import { getStore } from "@/lib/store";
import { ok, authFrom } from "@/lib/api";

export async function GET(req: Request) {
  const auth = authFrom(req);
  if (!auth) return Response.json({ error: "Not logged in." }, { status: 401 });
  const store = getStore();

  // Profits always describe the CURRENT book (paper or live), so switching
  // modes never mixes the two track records.
  const account = await store.getAccount(auth.uid);
  const mode = account?.mode === "live" ? "live" : "paper";

  const trades = await store.listTrades(auth.uid, 500, mode);
  const closed = trades.filter((t) => t.side === "SELL");
  const totalPnl = closed.reduce((a, t) => a + t.pnl, 0);
  const wins = closed.filter((t) => t.pnl > 0).length;
  const losses = closed.filter((t) => t.pnl <= 0).length;

  const today = new Date().toISOString().slice(0, 10);
  const todayPnl = closed.filter((t) => t.created_at.slice(0, 10) === today).reduce((a, t) => a + t.pnl, 0);

  const best = closed.reduce((b, t) => (!b || t.pnl > b.pnl ? t : b), null as null | { pnl: number; symbol: string });
  const worst = closed.reduce((w, t) => (!w || t.pnl < w.pnl ? t : w), null as null | { pnl: number; symbol: string });

  const equityCurve = await store.listEquity(auth.uid, 60, mode);

  return ok({
    totalPnl: Math.round(totalPnl * 100) / 100,
    todayPnl: Math.round(todayPnl * 100) / 100,
    trades: closed.length,
    wins,
    losses,
    winRate: wins + losses > 0 ? Math.round((wins / (wins + losses)) * 100) : 0,
    bestTrade: best ? { symbol: best.symbol, pnl: Math.round(best.pnl * 100) / 100 } : null,
    worstTrade: worst ? { symbol: worst.symbol, pnl: Math.round(worst.pnl * 100) / 100 } : null,
    equityCurve,
  });
}
