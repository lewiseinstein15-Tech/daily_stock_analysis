import { ok } from "@/lib/api";

// Tells the app which sign-in methods are available
export async function GET() {
  const google = Boolean(process.env.GOOGLE_CLIENT_ID && process.env.GOOGLE_CLIENT_SECRET);
  return ok({
    providers: {
      email: true,
      google,
    },
    adminEmailConfigured: Boolean(process.env.ADMIN_EMAIL),
  });
}
