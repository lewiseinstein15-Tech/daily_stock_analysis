// Auth + encryption helpers (zero external deps)
import {
  createCipheriv,
  createDecipheriv,
  createHash,
  createHmac,
  randomBytes,
  scryptSync,
  timingSafeEqual,
} from "crypto";

function encKey(): Buffer {
  return createHash("sha256")
    .update(process.env.ENCRYPTION_KEY || "jexi-dev-key-change-me")
    .digest();
}

function jwtSecret(): string {
  return process.env.JWT_SECRET || "jexi-dev-jwt-change-me";
}

// ---------------- passwords (scrypt) ----------------

export function hashPassword(pw: string): string {
  const salt = randomBytes(16).toString("hex");
  const hash = scryptSync(pw, salt, 64).toString("hex");
  return `${salt}:${hash}`;
}

export function verifyPassword(pw: string, stored: string): boolean {
  const [salt, hash] = String(stored || "").split(":");
  if (!salt || !hash) return false;
  const test = scryptSync(pw, salt, 64);
  const orig = Buffer.from(hash, "hex");
  return orig.length === test.length && timingSafeEqual(orig, test);
}

// ---------------- secrets at rest (AES-256-GCM) ----------------

export function encryptSecret(plain: string): string {
  const iv = randomBytes(12);
  const cipher = createCipheriv("aes-256-gcm", encKey(), iv);
  const ct = Buffer.concat([cipher.update(String(plain), "utf8"), cipher.final()]);
  return [iv.toString("base64"), cipher.getAuthTag().toString("base64"), ct.toString("base64")].join(":");
}

export function decryptSecret(blob: string): string {
  try {
    const [ivB64, tagB64, ctB64] = String(blob || "").split(":");
    if (!ivB64 || !tagB64 || !ctB64) return "";
    const decipher = createDecipheriv("aes-256-gcm", encKey(), Buffer.from(ivB64, "base64"));
    decipher.setAuthTag(Buffer.from(tagB64, "base64"));
    return Buffer.concat([decipher.update(Buffer.from(ctB64, "base64")), decipher.final()]).toString("utf8");
  } catch {
    return "";
  }
}

export function maskKey(v: string): string {
  return v ? "••••••" : "";
}

// ---------------- tokens (HMAC-SHA256 JWT, no deps) ----------------

function b64url(input: Buffer | string): string {
  return Buffer.from(input).toString("base64").replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function b64urlJson(obj: unknown): string {
  return b64url(JSON.stringify(obj));
}

function fromB64url(s: string): Buffer {
  return Buffer.from(s.replace(/-/g, "+").replace(/_/g, "/"), "base64");
}

export function signToken(payload: Record<string, unknown>, days = 30): string {
  const header = b64urlJson({ alg: "HS256", typ: "JWT" });
  const body = b64urlJson({
    ...payload,
    iat: Math.floor(Date.now() / 1000),
    exp: Math.floor(Date.now() / 1000) + days * 24 * 60 * 60,
  });
  const sig = b64url(createHmac("sha256", jwtSecret()).update(`${header}.${body}`).digest());
  return `${header}.${body}.${sig}`;
}

export function verifyToken(token: string): Record<string, unknown> | null {
  try {
    const [header, body, sig] = String(token || "").split(".");
    if (!header || !body || !sig) return null;
    const expected = createHmac("sha256", jwtSecret()).update(`${header}.${body}`).digest();
    const got = fromB64url(sig);
    if (expected.length !== got.length || !timingSafeEqual(expected, got)) return null;
    const payload = JSON.parse(fromB64url(body).toString("utf8"));
    if (typeof payload.exp === "number" && payload.exp < Math.floor(Date.now() / 1000)) return null;
    return payload;
  } catch {
    return null;
  }
}

export function signState(data: Record<string, unknown>): string {
  const body = b64urlJson(data);
  const sig = b64url(createHmac("sha256", jwtSecret()).update(body).digest());
  return `${body}.${sig}`;
}

export function verifyState(state: string): Record<string, unknown> | null {
  try {
    const [body, sig] = String(state || "").split(".");
    if (!body || !sig) return null;
    const expected = createHmac("sha256", jwtSecret()).update(body).digest();
    const got = fromB64url(sig);
    if (expected.length !== got.length || !timingSafeEqual(expected, got)) return null;
    return JSON.parse(fromB64url(body).toString("utf8"));
  } catch {
    return null;
  }
}
