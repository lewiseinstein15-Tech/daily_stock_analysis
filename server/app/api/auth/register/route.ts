import { hashPassword, signToken } from "@/lib/crypto";
import { getStore, startingBalance } from "@/lib/store";
import { ok, bad, readJson } from "@/lib/api";

interface Body {
  email?: string;
  password?: string;
  name?: string;
}

export async function POST(req: Request) {
  const body = await readJson<Body>(req);
  const email = (body?.email || "").trim().toLowerCase();
  const password = body?.password || "";
  const name = (body?.name || "").trim();

  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) return bad("Enter a valid email address.");
  if (password.length < 6) return bad("Password must be at least 6 characters.");

  const store = getStore();
  if (await store.getUserByEmail(email)) return bad("An account with this email already exists. Try logging in.", 409);

  const user = await store.createUser(email, hashPassword(password), name);
  const account = await store.ensureAccount(user.id, startingBalance());
  await store.insertFeed(
    user.id,
    "info",
    `Welcome! Your account is ready with $${account.cash.toFixed(2)} trading balance. Add your two keys in Settings, then I start watching the market for you.`
  );

  const token = signToken({ uid: user.id, email: user.email });
  return ok({ token, user: { id: user.id, email: user.email, name: user.name }, account }, 201);
}
