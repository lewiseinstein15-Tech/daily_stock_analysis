import { verifyToken } from "@/lib/crypto";
import { getStore } from "@/lib/store";
import { termsCurrent } from "@/lib/terms";

// GET /api/auth/me — Bearer-token profile lookup.
// Used by the Android app shell (and any non-browser client) to turn a signed
// token into the user object after a full-page Google sign-in redirect.
export async function GET(req: Request) {
  const auth = req.headers.get("authorization") || "";
  const token = auth.startsWith("Bearer ") ? auth.slice(7).trim() : "";
  if (!token) {
    return Response.json({ ok: false, error: "Missing token" }, { status: 401 });
  }
  const claims = verifyToken(token);
  const uid = typeof claims?.uid === "number" ? claims.uid : null;
  if (!uid) {
    return Response.json({ ok: false, error: "Invalid token" }, { status: 401 });
  }
  const store = getStore();
  const user = await store.getUserById(uid);
  if (!user) {
    return Response.json({ ok: false, error: "User not found" }, { status: 401 });
  }
  return Response.json({
    ok: true,
    user: {
      id: user.id,
      email: user.email,
      name: user.name,
      role: user.is_admin ? "admin" : "user",
      terms_version: user.terms_version || null,
      terms_accepted_at: user.terms_accepted_at || null,
      terms_current: termsCurrent(user),
    },
  });
}
