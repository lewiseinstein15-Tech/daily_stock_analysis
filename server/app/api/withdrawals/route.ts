import { getStore } from "@/lib/store";
import { getQuotes } from "@/lib/prices";
import { ok, bad, authFrom, readJson } from "@/lib/api";

interface Body {
  amount?: number;
  method?: string;
  destination?: string;
}

const WITHDRAW_LIMIT_PCT = 0.5; // can withdraw up to 50% of equity per request

export async function GET(req: Request) {
  const auth = authFrom(req);
  if (!auth) return bad("Not logged in.", 401);
  const store = getStore();
  return ok({ withdrawals: await store.listWithdrawals(auth.uid) });
}

export async function POST(req: Request) {
  const auth = authFrom(req);
  if (!auth) return bad("Not logged in.", 401);
  const body = await readJson<Body>(req);
  const amount = Number(body?.amount || 0);
  const method = (body?.method || "bank").trim();
  const destination = (body?.destination || "").trim();

  if (!Number.isFinite(amount) || amount < 1) return bad("Enter an amount of at least $1.");
  if (!destination) return bad("Add where the money should go (e.g. bank or wallet).");

  const store = getStore();
  const account = await store.getAccount(auth.uid);
  if (!account) return bad("No account found.", 404);

  const positions = await store.getPositions(auth.uid);
  const symbols = positions.map((p) => p.symbol);
  const quotes = symbols.length ? await getQuotes(symbols) : {};
  const positionsValue = positions.reduce((a, p) => a + p.qty * (quotes[p.symbol]?.price || p.last_price), 0);
  const equity = account.cash + positionsValue;
  const limit = equity * WITHDRAW_LIMIT_PCT;

  if (amount > limit) {
    return bad(
      `You can withdraw up to $${limit.toFixed(2)} right now (limit is ${(WITHDRAW_LIMIT_PCT * 100).toFixed(0)}% of your $${equity.toFixed(2)} equity to keep enough margin for open trades).`
    );
  }
  if (amount > account.cash) {
    return bad(`Not enough free cash. You have $${account.cash.toFixed(2)} not tied up in trades.`);
  }

  await store.insertWithdrawal(auth.uid, amount, method, destination);
  await store.setCash(auth.uid, account.cash - amount);
  await store.insertFeed(
    auth.uid,
    "money",
    `Withdrawal of $${amount.toFixed(2)} approved via ${method}. It will arrive with your next payout cycle. Your remaining balance is $${(account.cash - amount).toFixed(2)}.`
  );
  return ok({ approved: true, amount, remainingCash: Math.round((account.cash - amount) * 100) / 100 }, 201);
}
