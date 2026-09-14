// Small response/auth helpers shared by every route
import { verifyToken } from "./crypto";

export function ok(data: Record<string, unknown>, status = 200): Response {
  return Response.json({ ok: true, ...data }, { status });
}

export function bad(error: string, status = 400): Response {
  return Response.json({ ok: false, error }, { status });
}

export async function readJson<T>(req: Request): Promise<T | null> {
  try {
    return (await req.json()) as T;
  } catch {
    return null;
  }
}

export function authFrom(req: Request): { uid: number; email: string } | null {
  const header = req.headers.get("authorization") || "";
  const match = header.match(/^Bearer\s+(.+)$/i);
  if (!match) return null;
  const payload = verifyToken(match[1]);
  if (!payload || payload.uid === undefined) return null;
  return { uid: Number(payload.uid), email: String(payload.email || "") };
}

// Vercel Cron sends the x-vercel-cron header; manual runs use the shared secret.
export function checkCronSecret(req: Request): boolean {
  if (req.headers.get("x-vercel-cron")) return true;
  const secret = process.env.CRON_SECRET || "";
  if (!secret) return false;
  if (req.headers.get("x-cron-secret") === secret) return true;
  if (req.headers.get("authorization") === `Bearer ${secret}`) return true;
  return false;
}
