import { encryptSecret, maskKey } from "@/lib/crypto";
import { getStore } from "@/lib/store";
import { ok, bad, authFrom, readJson } from "@/lib/api";

interface Body {
  aiProvider?: string;
  aiKey?: string;
  brokerName?: string;
  brokerKey?: string;
  brokerSecret?: string;
}

export async function GET(req: Request) {
  const auth = authFrom(req);
  if (!auth) return bad("Not logged in.", 401);
  const store = getStore();
  const keys = await store.getKeys(auth.uid);
  if (!keys) return ok({ set: false });
  // Show only masked values — the real keys never leave the server again
  return ok({
    set: true,
    aiProvider: keys.ai_provider,
    aiKeyMasked: maskKey(keys.ai_key_enc ? "saved" : ""),
    brokerName: keys.broker_name,
    brokerKeySet: Boolean(keys.broker_key_enc),
  });
}

export async function POST(req: Request) {
  const auth = authFrom(req);
  if (!auth) return bad("Not logged in.", 401);
  const body = await readJson<Body>(req);
  if (!body) return bad("Send JSON.");

  const aiProvider = (body.aiProvider || "").trim();
  const aiKey = (body.aiKey || "").trim();
  const brokerName = (body.brokerName || "").trim();
  const brokerKey = (body.brokerKey || "").trim();
  const brokerSecret = (body.brokerSecret || "").trim();

  if (!aiProvider || !aiKey) return bad("Both the AI provider name and its API key are needed.");
  if (!brokerName || !brokerKey) return bad("Both the broker name and its API key are needed.");

  const store = getStore();
  const existing = await store.getKeys(auth.uid);
  await store.setKeys(auth.uid, {
    ai_provider: aiProvider,
    ai_key_enc: encryptSecret(aiKey),
    broker_name: brokerName,
    broker_key_enc: encryptSecret(brokerKey),
    broker_secret_enc: brokerSecret ? encryptSecret(brokerSecret) : existing?.broker_secret_enc || "",
  });
  await store.insertFeed(
    auth.uid,
    "info",
    `Keys saved: your AI brain is ${aiProvider}, your broker is ${brokerName}. They are encrypted and stored only for your account.`
  );
  return ok({ saved: true });
}
