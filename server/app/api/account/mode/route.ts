import { getStore } from "@/lib/store";
import { alpacaCredsFromKeys, alpacaCheck } from "@/lib/broker";
import { ok, bad, authFrom, readJson } from "@/lib/api";

interface Body {
  mode?: string;
}

// Switch the account between the paper book and the live book.
// Each mode keeps its own cash, positions and history; switching parks the
// current numbers and brings up the other book exactly where you left it.
export async function POST(req: Request) {
  const auth = authFrom(req);
  if (!auth) return bad("Not logged in.", 401);
  const body = await readJson<Body>(req);
  const target = (body?.mode || "").trim().toLowerCase();
  if (target !== "paper" && target !== "live") return bad("Mode must be paper or live.");

  const store = getStore();
  const account = await store.getAccount(auth.uid);
  if (!account) return bad("No account found.", 404);
  const current = account.mode === "live" ? "live" : "paper";
  if (current === target) return ok({ mode: target, changed: false });

  if (target === "live") {
    // Going live requires a real broker connection saved in the account.
    const keys = await store.getKeys(auth.uid);
    const creds = alpacaCredsFromKeys(keys);
    if (!creds) {
      return bad(
        "Live trading needs your broker keys first. Open Settings → Keys, choose Alpaca paper or Alpaca live, and save your API key + secret."
      );
    }
    const problem = await alpacaCheck(creds);
    if (problem) return bad(`Jexi checked your broker and ${problem}. Nothing was switched.`);
    if (!creds.baseUrl.includes("live")) {
      await store.insertFeed(
        auth.uid,
        "info",
        "You are now trading live on your Alpaca PAPER broker keys — real orders flow, but through Alpaca's practice exchange. When your LIVE keys are in, switch the broker type to Alpaca live in Settings → Keys."
      );
    }
  }

  const switched = await store.switchMode(auth.uid, target);
  const cash = switched ? switched.cash : 0;
  await store.insertFeed(
    auth.uid,
    target === "live" ? "money" : "info",
    target === "live"
      ? `Live mode is ON. Jexi now trades your real broker account with the keys saved in Settings. Live balance starts at $${cash.toFixed(2)} — make a deposit from Portfolio → Deposit when ready.`
      : "Back to paper mode. Your live book is parked safe — switch back anytime and it is exactly as you left it."
  );
  return ok({ mode: target, changed: true, cash: Math.round(cash * 100) / 100 });
}
