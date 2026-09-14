import { getStore } from "@/lib/store";
import { ok, bad, authFrom } from "@/lib/api";

// Admin-only: live view of every account on the server
export async function GET(req: Request) {
  const auth = authFrom(req);
  if (!auth) return bad("Not logged in.", 401);
  const store = getStore();

  const me = await store.getUserById(auth.uid);
  if (!me || !me.is_admin) return bad("Admin access required.", 403);

  const [users, recentTrades, withdrawals] = await Promise.all([
    store.listUsersWithAccounts(200),
    store.listRecentTradesAll(20),
    store.listWithdrawalsAll(20),
  ]);

  const totals = users.reduce(
    (acc, u) => {
      acc.equity += u.cash + u.position_value;
      acc.cash += u.cash;
      acc.positions += u.position_value;
      return acc;
    },
    { equity: 0, cash: 0, positions: 0 }
  );

  return ok({
    totals: {
      users: users.length,
      equity: Math.round(totals.equity * 100) / 100,
      cash: Math.round(totals.cash * 100) / 100,
      positions: Math.round(totals.positions * 100) / 100,
    },
    users: users.map((u) => ({
      id: u.id,
      email: u.email,
      name: u.name,
      isAdmin: Boolean(u.is_admin),
      cash: Math.round(u.cash * 100) / 100,
      positionValue: Math.round(u.position_value * 100) / 100,
      equity: Math.round((u.cash + u.position_value) * 100) / 100,
      pnl: Math.round((u.cash + u.position_value - u.starting_balance) * 100) / 100,
      createdAt: u.created_at,
    })),
    recentTrades: recentTrades.map((t) => ({
      id: t.id,
      email: (t as { email?: string }).email || "",
      symbol: t.symbol,
      side: t.side,
      qty: t.qty,
      price: t.price,
      pnl: t.pnl,
      createdAt: t.created_at,
    })),
    withdrawals: withdrawals.map((w) => ({
      id: w.id,
      email: (w as { email?: string }).email || "",
      amount: w.amount,
      method: w.method,
      status: w.status,
      createdAt: w.created_at,
    })),
  });
}
