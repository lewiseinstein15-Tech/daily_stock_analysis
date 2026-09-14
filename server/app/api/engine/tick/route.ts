import { getStore } from "@/lib/store";
import { runTick } from "@/lib/engine";
import { ok, bad, checkCronSecret } from "@/lib/api";

// Vercel Cron hits this with GET; manual runs use POST with the secret.
async function handle(req: Request): Promise<Response> {
  if (!checkCronSecret(req)) {
    return bad("Unauthorized. Set the CRON_SECRET header (x-cron-secret) or run from Vercel Cron.", 401);
  }
  const store = getStore();
  const result = await runTick(store);
  return ok({ ranAt: new Date().toISOString(), ...result });
}

export async function GET(req: Request) {
  return handle(req);
}

export async function POST(req: Request) {
  return handle(req);
}
