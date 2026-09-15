import { getStore } from "@/lib/store";
import { decryptSecret } from "@/lib/crypto";
import { ok, bad, checkAgentSecret } from "@/lib/api";

// The JEXI runner (trading bot) calls this to pull the broker + AI keys
// the user saved in their Jexi account. Keys travel decrypted ONLY over
// this authenticated server-to-server call; GitHub never stores them.
export async function GET(req: Request) {
  if (!checkAgentSecret(req)) return bad("Unauthorized agent.", 401);

  const url = new URL(req.url);
  const email = (url.searchParams.get("email") || "").trim().toLowerCase();
  if (!email) return bad("Add the account email: /api/agent/keys?email=you@example.com");

  const store = getStore();
  const user = await store.getUserByEmail(email);
  if (!user) return bad(`No Jexi account found for ${email}.`, 404);

  const keys = await store.getKeys(user.id);
  const account = await store.getAccount(user.id);
  if (!keys || !keys.broker_key_enc) {
    return ok({
      set: false,
      mode: account?.mode || "paper",
      note: "This account has no broker keys yet — they are saved in the Jexi app under Settings -> Keys.",
    });
  }

  return ok({
    set: true,
    mode: account?.mode || "paper",
    aiProvider: keys.ai_provider,
    aiKey: decryptSecret(keys.ai_key_enc),
    brokerName: keys.broker_name,
    brokerKey: decryptSecret(keys.broker_key_enc),
    brokerSecret: decryptSecret(keys.broker_secret_enc || ""),
  });
}
