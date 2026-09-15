import { getStore } from "@/lib/store";
import { ok, bad, checkAgentSecret } from "@/lib/api";

// The JEXI runner reads the account it should trade for: current mode
// (paper/live), cash and open positions of the active book.
export async function GET(req: Request) {
  if (!checkAgentSecret(req)) return bad("Unauthorized agent.", 401);

  const url = new URL(req.url);
  const email = (url.searchParams.get("email") || "").trim().toLowerCase();
  if (!email) return bad("Add the account email: /api/agent/state?email=you@example.com");

  const store = getStore();
  const user = await store.getUserByEmail(email);
  if (!user) return bad(`No Jexi account found for ${email}.`, 404);

  const account = await store.getAccount(user.id);
  if (!account) return bad("No account found for this user.", 404);

  const positions = await store.getPositions(user.id, account.mode);
  const keys = await store.getKeys(user.id);

  return ok({
    email: user.email,
    mode: account.mode,
    cash: account.cash,
    startingBalance: account.starting_balance,
    brokerName: keys?.broker_name || "",
    brokerSet: Boolean(keys?.broker_key_enc),
    positions: positions.map((p) => ({
      symbol: p.symbol,
      qty: p.qty,
      avgPrice: p.avg_price,
      lastPrice: p.last_price,
    })),
  });
}
