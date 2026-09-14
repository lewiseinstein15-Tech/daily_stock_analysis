/**
 * Engine test with simulated prices (no network needed).
 * Scenario 1: uptrend in AAPL -> engine buys.
 * Scenario 2: price crashes -> engine sells at the safety line.
 * Scenario 3: no price data -> honest skip, no crash.
 * Run: bun scripts/test_engine.ts  (from server/)
 */
let SCENARIO_PRICES: Record<string, number[]> = {};

function fakeChartJson(closes: number[]) {
  return {
    chart: { result: [{ indicators: { quote: [{ close: closes }] } }] },
  };
}

function series(start: number, drift: number, n = 30): number[] {
  const out: number[] = [];
  let p = start;
  for (let i = 0; i < n; i++) {
    out.push(Math.round(p * 100) / 100);
    p *= 1 + drift;
  }
  return out;
}

// Install fake fetch BEFORE importing the engine's prices module
globalThis.fetch = (async (url: any) => {
  const u = String(url instanceof URL ? url : url?.url || url);
  const m = u.match(/chart\/([A-Za-z0-9.]+)/);
  if (u.includes("stooq.com")) throw new Error("blocked");
  if (m && SCENARIO_PRICES[m[1].toUpperCase()]) {
    return { ok: true, json: async () => fakeChartJson(SCENARIO_PRICES[m[1].toUpperCase()]) } as any;
  }
  return { ok: false, status: 429, json: async () => ({}) } as any;
}) as any;

import { tickUser } from "../lib/engine";
import { getStore } from "../lib/store";
import { resetPriceCache } from "../lib/prices";

async function main() {
  const store = getStore();

  // ---------- scenario 1: uptrend -> BUY ----------
  SCENARIO_PRICES = { AAPL: series(200, 0.01), MSFT: series(400, -0.002) };
  const user = await store.createUser("engine@test.app", "x", "Engine Test");
  await store.ensureAccount(user.id, 10000);
  const r1 = await tickUser(store, user.id);
  const trades1 = await store.listTrades(user.id, 10);
  console.log("S1 tick:", JSON.stringify(r1));
  console.log("S1 trades:", trades1.map((t) => `${t.side} ${t.qty} ${t.symbol} @ ${t.price}`));
  if (!(trades1.length === 1 && trades1[0].side === "BUY" && trades1[0].symbol === "AAPL")) {
    console.error("FAIL: expected exactly one BUY of AAPL");
    process.exit(1);
  }

  // ---------- scenario 2: crash -> SELL at safety line ----------
  resetPriceCache();
  SCENARIO_PRICES = { AAPL: series(200, 0.01).slice(0, 25).concat([150, 149]), MSFT: series(400, -0.002) };
  const r2 = await tickUser(store, user.id);
  const trades2 = await store.listTrades(user.id, 10);
  const sell = trades2.find((t) => t.side === "SELL");
  const feed = await store.listFeed(user.id, 10);
  console.log("S2 tick:", JSON.stringify(r2));
  console.log("S2 sell:", sell ? `SELL ${sell.qty} ${sell.symbol} @ ${sell.price} pnl=${sell.pnl}` : "NONE");
  console.log("S2 feed:", feed.map((f) => f.message.slice(0, 90)));
  if (!sell || sell.pnl >= 0) {
    console.error("FAIL: expected a loss-selling SELL after the crash");
    process.exit(1);
  }
  const account = await store.getAccount(user.id);
  console.log("S2 cash after:", account?.cash);

  // ---------- scenario 3: no data anywhere -> honest skip ----------
  resetPriceCache();
  SCENARIO_PRICES = {};
  const r3 = await tickUser(store, user.id);
  console.log("S3 tick:", JSON.stringify(r3));
  if (!r3.skipped || !String(r3.note).includes("no price data")) {
    console.error("FAIL: expected honest 'no price data' skip");
    process.exit(1);
  }

  console.log("ENGINE_TEST_OK");
}

main().catch((e) => {
  console.error("ENGINE_TEST_ERROR", e);
  process.exit(1);
});
