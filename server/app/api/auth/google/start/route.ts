import { signState } from "@/lib/crypto";

// Starts the Google OAuth flow. The web/app client opens this in a popup:
//   window.open("https://<server>/api/auth/google/start?origin=" + encodeURIComponent(location.origin))
export async function GET(req: Request) {
  const clientId = process.env.GOOGLE_CLIENT_ID;
  const clientSecret = process.env.GOOGLE_CLIENT_SECRET;
  if (!clientId || !clientSecret) {
    return Response.json(
      { ok: false, error: "Google sign-in is not configured yet. Add GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET." },
      { status: 400 }
    );
  }

  const url = new URL(req.url);
  const origin = url.searchParams.get("origin") || "";
  const state = signState({ origin, nonce: crypto.randomUUID(), t: Date.now() });

  const redirectUri = `${url.origin}/api/auth/google/callback`;
  const auth = new URL("https://accounts.google.com/o/oauth2/v2/auth");
  auth.searchParams.set("client_id", clientId);
  auth.searchParams.set("redirect_uri", redirectUri);
  auth.searchParams.set("response_type", "code");
  auth.searchParams.set("scope", "openid email profile");
  auth.searchParams.set("access_type", "online");
  auth.searchParams.set("prompt", "select_account");
  auth.searchParams.set("state", state);

  return Response.redirect(auth.toString(), 302);
}
