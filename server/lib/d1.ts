// Minimal Cloudflare D1 REST client (works from Vercel, no SDK needed)
const API = "https://api.cloudflare.com/client/v4";

export interface D1Meta {
  last_row_id?: number;
  changes?: number;
}

export interface D1Result<T> {
  rows: T[];
  meta: D1Meta;
}

export function d1Configured(): boolean {
  return Boolean(
    process.env.CLOUDFLARE_API_TOKEN &&
      process.env.CLOUDFLARE_ACCOUNT_ID &&
      process.env.CLOUDFLARE_D1_ID
  );
}

export async function d1Query<T = Record<string, unknown>>(
  sql: string,
  params: (string | number | null)[] = []
): Promise<D1Result<T>> {
  const token = process.env.CLOUDFLARE_API_TOKEN!;
  const accountId = process.env.CLOUDFLARE_ACCOUNT_ID!;
  const dbId = process.env.CLOUDFLARE_D1_ID!;

  const res = await fetch(
    `${API}/accounts/${accountId}/d1/database/${dbId}/query`,
    {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ sql, params }),
      signal: AbortSignal.timeout(15000),
      cache: "no-store",
    }
  );

  const body = (await res.json()) as {
    success: boolean;
    errors?: { code: number; message: string }[];
    result?: { results?: T[]; meta?: D1Meta }[];
  };

  if (!body.success || !body.result) {
    const msg = (body.errors || []).map((e) => e.message).join("; ") || `D1 HTTP ${res.status}`;
    throw new Error(`D1 error: ${msg}`);
  }
  const first = body.result[0] || {};
  return { rows: (first.results || []) as T[], meta: first.meta || {} };
}
