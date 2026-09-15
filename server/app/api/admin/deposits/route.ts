import { getStore } from "@/lib/store";
import { ok, bad, authFrom, readJson } from "@/lib/api";

interface Body {
  id?: number;
  action?: string; // "approve" | "reject"
}

// Admin approves or rejects pending LIVE deposits. Approving credits the
// user's live balance (real money was confirmed received outside the app).
export async function GET(req: Request) {
  const auth = authFrom(req);
  if (!auth) return bad("Not logged in.", 401);
  const store = getStore();
  const me = await store.getUserById(auth.uid);
  if (!me || !me.is_admin) return bad("Admin access required.", 403);
  return ok({ deposits: await store.listDepositsAll(100) });
}

export async function POST(req: Request) {
  const auth = authFrom(req);
  if (!auth) return bad("Not logged in.", 401);
  const store = getStore();
  const me = await store.getUserById(auth.uid);
  if (!me || !me.is_admin) return bad("Admin access required.", 403);

  const body = await readJson<Body>(req);
  const id = Number(body?.id || 0);
  const action = (body?.action || "").trim().toLowerCase();
  if (!id || !["approve", "reject"].includes(action)) return bad("Send the deposit id and action: approve or reject.");

  const deposit = await store.getDeposit(id);
  if (!deposit) return bad("Deposit not found.", 404);
  if (deposit.status !== "pending") return bad(`This deposit is already ${deposit.status}.`);

  if (action === "reject") {
    await store.setDepositStatus(id, "rejected");
    await store.insertFeed(
      deposit.user_id,
      "warn",
      `Your live deposit of $${Number(deposit.amount).toFixed(2)} (${deposit.method}) could not be confirmed and was rejected. If you already sent the money, reply in the app and the team will look again.`
    );
    return ok({ id, status: "rejected" });
  }

  // approve: money confirmed -> credit the LIVE book
  const account = await store.getAccount(deposit.user_id);
  if (!account) return bad("That user has no account.", 404);
  await store.setDepositStatus(id, "approved");
  if (account.mode === "live") {
    await store.setCash(deposit.user_id, account.cash + Number(deposit.amount));
  } else {
    // user is on the paper book right now; park the credit in the live slot
    await store.switchMode(deposit.user_id, "live").catch(() => null);
    const fresh = await store.getAccount(deposit.user_id);
    // if the user was on live when depositing they were switched back;
    // safest path: put the money in the live slot via a temporary switch
    if (fresh && fresh.mode === "live") {
      await store.setCash(deposit.user_id, fresh.cash + Number(deposit.amount));
      await store.switchMode(deposit.user_id, "paper");
    } else {
      // last resort: record approval without touching balances
      await store.insertFeed(
        deposit.user_id,
        "warn",
        `Live deposit of $${Number(deposit.amount).toFixed(2)} was approved — switch to Live mode in Settings to see it in your live balance.`
      );
      return ok({ id, status: "approved", note: "credited to parked live book" });
    }
  }
  await store.insertFeed(
    deposit.user_id,
    "money",
    `Live deposit of $${Number(deposit.amount).toFixed(2)} confirmed and added to your live balance. Jexi can now put it to work.`
  );
  return ok({ id, status: "approved" });
}
