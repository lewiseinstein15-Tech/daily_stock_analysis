import { verifyPassword, signToken } from "@/lib/crypto";
import { getStore } from "@/lib/store";
import { ok, bad, readJson } from "@/lib/api";

interface Body {
  email?: string;
  password?: string;
}

export async function POST(req: Request) {
  const body = await readJson<Body>(req);
  const email = (body?.email || "").trim().toLowerCase();
  const password = body?.password || "";

  const store = getStore();
  const user = await store.getUserByEmail(email);
  if (!user || !verifyPassword(password, user.password_hash)) {
    return bad("Wrong email or password.", 401);
  }
  const account = await store.ensureAccount(user.id, 10000);
  const token = signToken({ uid: user.id, email: user.email });
  return ok({ token, user: { id: user.id, email: user.email, name: user.name }, account });
}
