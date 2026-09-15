// Minimal Alpaca trading client (paper + live) — no SDK, plain REST.
// Used by the engine when the account is in LIVE mode: real orders go
// through the user's own saved broker keys.
import { decryptSecret } from "./crypto";
import type { KeysRow } from "./store";

export interface BrokerCreds {
  baseUrl: string;
  dataUrl: string;
  key: string;
  secret: string;
}

// broker_name conventions:
//   alpaca-paper (or legacy "alpaca") -> paper endpoint
//   alpaca-live                       -> live (real money) endpoint
export function alpacaCredsFromKeys(keys: KeysRow | null): BrokerCreds | null {
  if (!keys || !keys.broker_key_enc) return null;
  const name = (keys.broker_name || "").trim().toLowerCase();
  if (!name.startsWith("alpaca")) return null;
  const live = name === "alpaca-live";
  const key = decryptSecret(keys.broker_key_enc);
  const secret = decryptSecret(keys.broker_secret_enc || "");
  if (!key || !secret) return null;
  return {
    baseUrl: live ? "https://api.alpaca.markets" : "https://paper-api.alpaca.markets",
    dataUrl: "https://data.alpaca.markets",
    key,
    secret,
  };
}

async function alpacaFetch(creds: BrokerCreds, path: string, init?: RequestInit): Promise<Response> {
  return fetch(`${creds.baseUrl}${path}`, {
    ...init,
    headers: {
      "APCA-API-KEY-ID": creds.key,
      "APCA-API-SECRET-KEY": creds.secret,
      "Content-Type": "application/json",
      ...(init?.headers || {}),
    },
    signal: AbortSignal.timeout(12000),
    cache: "no-store",
  });
}

// Verify the keys work and the account can trade. Returns an error string
// or null when everything is fine.
export async function alpacaCheck(creds: BrokerCreds): Promise<string | null> {
  try {
    const res = await alpacaFetch(creds, "/v2/account");
    if (res.status === 401 || res.status === 403) return "your broker rejected the keys — double-check them in Settings → Keys";
    if (!res.ok) return `your broker answered HTTP ${res.status}`;
    const acct = (await res.json()) as { trading_blocked?: boolean; account_blocked?: boolean };
    if (acct.trading_blocked || acct.account_blocked) return "your broker account is blocked from trading";
    return null;
  } catch {
    return "could not reach your broker right now";
  }
}

// Market order. Returns the broker order id, or throws with a plain message.
export async function alpacaMarketOrder(
  creds: BrokerCreds,
  symbol: string,
  qty: number,
  side: "buy" | "sell"
): Promise<string> {
  const res = await alpacaFetch(creds, "/v2/orders", {
    method: "POST",
    body: JSON.stringify({
      symbol,
      qty: String(qty),
      side,
      type: "market",
      time_in_force: "day",
    }),
  });
  const body = (await res.json().catch(() => ({}))) as { id?: string; message?: string; code?: number };
  if (!res.ok) {
    const why = body.message || `HTTP ${res.status}`;
    throw new Error(why);
  }
  return String(body.id || "accepted");
}
