import { getStore } from "@/lib/store";

export async function GET() {
  const store = getStore();
  return Response.json({ ok: true, driver: store.driver, time: new Date().toISOString() });
}
