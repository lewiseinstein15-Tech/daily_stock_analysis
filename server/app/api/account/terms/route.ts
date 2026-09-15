import { getStore } from "@/lib/store";
import { ok, bad, authFrom, readJson } from "@/lib/api";
import { CURRENT_TERMS_VERSION, termsCurrent } from "@/lib/terms";

// POST /api/account/terms — record acceptance of the Terms & Policies.
// Body: {} (or {accepted:true}); the server pins the version itself so a
// tampered client cannot claim acceptance of a version that does not exist.
export async function POST(req: Request) {
  const auth = authFrom(req);
  if (!auth) return bad("Not logged in.", 401);
  const body = await readJson<{ accepted?: boolean }>(req);
  if (body && body.accepted === false) return bad("Terms were not accepted.");

  const store = getStore();
  const user = await store.getUserById(auth.uid);
  if (!user) return bad("Session no longer valid — please sign in again.", 401);

  const acceptedAt = new Date().toISOString().slice(0, 19).replace("T", " ");
  await store.acceptTerms(auth.uid, CURRENT_TERMS_VERSION, acceptedAt);
  return ok({
    terms_version: CURRENT_TERMS_VERSION,
    terms_accepted_at: acceptedAt,
    terms_current: true,
  });
}

// GET /api/account/terms — current acceptance status.
export async function GET(req: Request) {
  const auth = authFrom(req);
  if (!auth) return bad("Not logged in.", 401);
  const store = getStore();
  const user = await store.getUserById(auth.uid);
  if (!user) return bad("Session no longer valid — please sign in again.", 401);
  return ok({
    current_version: CURRENT_TERMS_VERSION,
    terms_version: user.terms_version || null,
    terms_accepted_at: user.terms_accepted_at || null,
    terms_current: termsCurrent(user),
  });
}
