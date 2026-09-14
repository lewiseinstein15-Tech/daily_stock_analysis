import { getStore } from "@/lib/store";
import { ok, authFrom } from "@/lib/api";

export async function GET(req: Request) {
  const auth = authFrom(req);
  if (!auth) return Response.json({ error: "Not logged in." }, { status: 401 });
  const store = getStore();
  return ok({ events: await store.listFeed(auth.uid, 30) });
}
