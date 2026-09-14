import { verifyState, signToken } from "@/lib/crypto";
import { getStore, startingBalance } from "@/lib/store";

function decodeIdToken(idToken: string): { email?: string; name?: string; email_verified?: boolean } | null {
  try {
    const part = idToken.split(".")[1];
    if (!part) return null;
    const json = Buffer.from(part.replace(/-/g, "+").replace(/_/g, "/"), "base64").toString("utf8");
    return JSON.parse(json);
  } catch {
    return null;
  }
}

function page(title: string, body: string): Response {
  return new Response(
    `<!doctype html><html><head><meta charset="utf-8"><title>${title}</title>
     <meta name="viewport" content="width=device-width, initial-scale=1">
     <style>body{font-family:system-ui;background:#14120f;color:#f5f1ea;display:grid;place-items:center;min-height:100vh;margin:0}
     .card{max-width:420px;padding:28px;border-radius:16px;background:#1d1a15;border:1px solid #35302a;text-align:center}
     code{word-break:break-all;font-size:11px;color:#ffb88c}</style></head>
     <body><div class="card"><h2 style="margin:0 0 8px">${title}</h2><p style="color:#a89f92;line-height:1.5">${body}</p></div></body></html>`,
    { headers: { "content-type": "text/html; charset=utf-8" } }
  );
}

export async function GET(req: Request) {
  const url = new URL(req.url);
  const code = url.searchParams.get("code");
  const stateRaw = url.searchParams.get("state") || "";
  const error = url.searchParams.get("error");

  if (error) return page("Sign-in cancelled", "You can close this window and try email sign-in instead.");
  if (!code) return page("Missing code", "Google did not return an authorization code. Please try again.");

  const state = verifyState(stateRaw);
  if (!state) return page("Bad state", "The sign-in state could not be verified. Please try again.");

  const clientId = process.env.GOOGLE_CLIENT_ID;
  const clientSecret = process.env.GOOGLE_CLIENT_SECRET;
  if (!clientId || !clientSecret) return page("Not configured", "Google sign-in is not configured on the server.");

  try {
    const tokenRes = await fetch("https://oauth2.googleapis.com/token", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({
        code,
        client_id: clientId,
        client_secret: clientSecret,
        redirect_uri: `${url.origin}/api/auth/google/callback`,
        grant_type: "authorization_code",
      }),
      signal: AbortSignal.timeout(15000),
    });
    if (!tokenRes.ok) return page("Google error", "Could not exchange the code with Google. Please try again.");
    const tokens = (await tokenRes.json()) as { id_token?: string };
    const claims = tokens.id_token ? decodeIdToken(tokens.id_token) : null;
    if (!claims?.email) return page("No email", "Google did not share an email address. Please use email sign-in.");

    const email = claims.email.toLowerCase();
    const store = getStore();
    let user = await store.getUserByEmail(email);
    if (!user) {
      const isAdmin = process.env.ADMIN_EMAIL && email === process.env.ADMIN_EMAIL.trim().toLowerCase() ? 1 : 0;
      user = await store.createUser(email, `google:${crypto.randomUUID()}`, claims.name || "", isAdmin);
      const account = await store.ensureAccount(user.id, startingBalance());
      await store.insertFeed(
        user.id,
        "info",
        `Welcome! Your account is ready with $${account.cash.toFixed(2)} trading balance (signed in with Google).`
      );
    } else if (process.env.ADMIN_EMAIL && email === process.env.ADMIN_EMAIL.trim().toLowerCase() && !user.is_admin) {
      await store.promoteToAdmin(email);
      user.is_admin = 1;
    }

    const token = signToken({ uid: user.id, email: user.email });
    const targetOrigin = typeof state.origin === "string" && state.origin.startsWith("http") ? state.origin : url.origin;

    return new Response(
      `<!doctype html><html><head><meta charset="utf-8"><title>Signed in</title></head><body>
       <script>
         try {
           if (window.opener) {
             window.opener.postMessage({ type: "jexi-google-auth", token: ${JSON.stringify(token)},
               user: ${JSON.stringify({ id: user.id, email: user.email, name: user.name, role: user.is_admin ? "admin" : "user" })} }, "*");
             window.close();
           }
         } catch (e) {}
         document.body.style.cssText = "font-family:system-ui;background:#14120f;color:#f5f1ea;display:grid;place-items:center;min-height:100vh;margin:0";
         document.body.innerHTML = "<div style='text-align:center'><h2>You are signed in</h2><p style='color:#a89f92'>Copy this sign-in code into the Jexi app if the window did not close:</p><code style='color:#ffb88c;word-break:break-all'>${token}</code></div>";
       </script></body></html>`,
      { headers: { "content-type": "text/html; charset=utf-8" } }
    );
  } catch (e) {
    return page("Sign-in failed", "Something went wrong talking to Google. Please try again or use email sign-in.");
  }
}
