// Terms & Policies versioning.
//
// Every user must accept the current version before using the app.
// Bump CURRENT_TERMS_VERSION whenever the legal text changes; every
// existing user will then see the accept gate once more on next launch.

export const CURRENT_TERMS_VERSION = "2026-09-16";

export function termsCurrent(user: {
  terms_version?: string | null;
  terms_accepted_at?: string | null;
}): boolean {
  return Boolean(user?.terms_accepted_at) && user?.terms_version === CURRENT_TERMS_VERSION;
}
