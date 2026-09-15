import { getStore } from "@/lib/store";
import { ok, bad, authFrom, readJson } from "@/lib/api";

interface Body {
  id?: number;
  action?: string; // "approve" | "reject"
}

// Admin approves or rejects pending LIVE withdrawals.
// Approve = the money actually went out, deduct it from the live book.
export async function POST(req: Request) {
  const auth = authFrom(req);
  if (!auth) return bad("Not logged in.", 401);
  const store = getStore();
  const me = await store.getUserById(auth.uid);
  if (!me || !me.is_admin) return bad("Admin access required.", 403);

  const body = await readJson<Body>(req);
  const id = Number(body?.id || 0);
  const action = (body?.action || "").trim().toLowerCase();
  if (!id || !["approve", "reject"].includes(action)) return bad("Send the withdrawal id and action: approve or reject.");

  const wd = await store.getWithdrawal(id);
  if (!wd) return bad("Withdrawal not found.", 404);
  if (wd.status !== "pending") return bad(`This withdrawal is already ${wd.status}.`);

  if (action === "reject") {
    await store.setWithdrawalStatus(id, "rejected");
    await store.insertFeed(
      wd.user_id,
      "warn",
      `Your withdrawal request for $${Number(wd.amount).toFixed(2)} was not approved this time. Nothing left your balance — reach out in the app if that looks wrong.`
    );
    return ok({ id, status: "rejected" });
  }

  const account = await store.getAccount(wd.user_id);
  if (!account) return bad("That user has no account.", 404);
  await store.setWithdrawalStatus(id, "approved");
  if (account.mode === "live") {
    await store.setCash(wd.user_id, account.cash - Number(wd.amount));
  }
  await store.insertFeed(
    wd.user_id,
    "money",
    `Withdrawal of $${Number(wd.amount).toFixed(2)} via ${wd.method} is on its way to ${wd.destination || "your account"}. It can take 1–2 business days to arrive.`
  );
  return ok({ id, status: "approved" });
}
