import { getStore } from "@/lib/store";
import { ok, authFrom } from "@/lib/api";

export async function GET(req: Request) {
  const auth = authFrom(req);
  if (!auth) return Response.json({ error: "Not logged in." }, { status: 401 });
  const store = getStore();
  const limitRaw = Number(new URL(req.url).searchParams.get("limit") || 30);
  const limit = Math.min(Math.max(Number.isFinite(limitRaw) ? limitRaw : 30, 1), 100);
  return ok({ events: await store.listFeed(auth.uid, limit) });
}
