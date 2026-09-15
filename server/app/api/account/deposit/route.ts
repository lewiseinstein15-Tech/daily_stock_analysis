import { getStore } from "@/lib/store";
import { ok, bad, authFrom, readJson } from "@/lib/api";

interface Body {
  amount?: number;
  method?: string;
  destination?: string;
}

const METHODS = new Set(["m-pesa", "bank", "card", "crypto"]);

// GET: the deposit history for the current mode's book.
export async function GET(req: Request) {
  const auth = authFrom(req);
  if (!auth) return bad("Not logged in.", 401);
  const store = getStore();
  const account = await store.getAccount(auth.uid);
  const mode = account?.mode === "live" ? "live" : "paper";
  return ok({ deposits: await store.listDeposits(auth.uid, mode) });
}

// POST: add money to the active book.
//   paper -> credited instantly (practice money).
//   live  -> recorded as a pending deposit; the Jexi team confirms it in the
//            control room once the money actually arrived, then it lands.
export async function POST(req: Request) {
  const auth = authFrom(req);
  if (!auth) return bad("Not logged in.", 401);
  const body = await readJson<Body>(req);
  const amount = Number(body?.amount || 0);
  const method = (body?.method || "m-pesa").trim().toLowerCase();
  const destination = (body?.destination || "").trim();

  if (!Number.isFinite(amount) || amount < 1) return bad("Enter an amount of at least $1.");
  if (amount > 1_000_000) return bad("For deposits above $1,000,000 please talk to the Jexi team directly.");
  if (!METHODS.has(method)) return bad("Choose a method: m-pesa, bank, card or crypto.");

  const store = getStore();
  const account = await store.getAccount(auth.uid);
  if (!account) return bad("No account found.", 404);
  const mode = account.mode === "live" ? "live" : "paper";

  if (mode === "paper") {
    await store.insertDeposit(auth.uid, amount, method, destination || method, mode, "approved");
    await store.setCash(auth.uid, account.cash + amount);
    await store.insertFeed(
      auth.uid,
      "money",
      `Deposit of $${amount.toFixed(2)} added to your paper account via ${method}. New practice balance: $${(account.cash + amount).toFixed(2)}.`
    );
    return ok(
      { status: "approved", amount, newCash: Math.round((account.cash + amount) * 100) / 100 },
      201
    );
  }

  // live: pending until a human confirms the money arrived.
  await store.insertDeposit(auth.uid, amount, method, destination || method, mode, "pending");
  await store.insertFeed(
    auth.uid,
    "money",
    `Deposit request for $${amount.toFixed(2)} (${method}) received. Jexi confirms live deposits before they land in your balance — usually within a day. You will get a notification here the moment it is in.`
  );
  return ok({ status: "pending", amount }, 201);
}
