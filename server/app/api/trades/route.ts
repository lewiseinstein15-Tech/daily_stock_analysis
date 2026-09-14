import { getStore } from "@/lib/store";
import { ok, bad, authFrom } from "@/lib/api";

export async function GET(req: Request) {
  const auth = authFrom(req);
  if (!auth) return bad("Not logged in.", 401);
  const store = getStore();
  const trades = await store.listTrades(auth.uid, 200);
  return ok({ trades });
}
