import { getStore } from "@/lib/store";
import { ok, bad, checkAgentSecret, readJson } from "@/lib/api";

interface Body {
  email?: string;
  kind?: string;
  message?: string;
  title?: string;
}

// The JEXI runner pushes its plain-English reports here; they land in the
// user's notifications feed inside the Jexi app. No ntfy, no external app.
export async function POST(req: Request) {
  if (!checkAgentSecret(req)) return bad("Unauthorized agent.", 401);

  const body = await readJson<Body>(req);
  if (!body) return bad("Send JSON.");

  const email = (body.email || "").trim().toLowerCase();
  const message = (body.message || "").trim();
  const title = (body.title || "").trim();
  const kindRaw = (body.kind || "info").trim().toLowerCase();
  const allowed = new Set(["info", "win", "loss", "warn", "money", "plan"]);
  const kind = allowed.has(kindRaw) ? kindRaw : "info";

  if (!email) return bad("Add the account email.");
  if (!message) return bad("Add a message.");

  const store = getStore();
  const user = await store.getUserByEmail(email);
  if (!user) return bad(`No Jexi account found for ${email}.`, 404);

  // Long bot reports are fine — cap them so the feed stays readable.
  const full = title ? `${title}\n${message}` : message;
  const clipped = full.length > 4000 ? `${full.slice(0, 3990)}…` : full;
  await store.insertFeed(user.id, kind, clipped);
  return ok({ delivered: true }, 201);
}
