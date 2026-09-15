// JEXI update gate for the mobile app.
//
// The app checks the JEXI server on startup: if the server says the running
// version is below `minRequired`, the UI must show a full-screen
// "Update your app" gate. If it is below `latest` only, show a soft banner.
//
// Usage (in src/app/_layout.tsx once the lib store exists):
//   const update = useUpdateGate();
//   if (update.status === 'required') return <UpdateGate info={update.info} />;
//   // and render <SoftUpdateBanner ... /> inside your home header when optional.
//
// APP_VERSION below must be bumped with every release (keep in sync with app.json).

import { useCallback, useEffect, useState } from 'react';

// Keep in sync with the web app's DEFAULT_SERVER and the app's settings screen.
export const DEFAULT_SERVER = 'https://jexi-server.vercel.app';

export const APP_VERSION = '1.3.0';

export interface VersionInfo {
  latest: string;
  minRequired: string;
  notes: string;
  url: string;
}

export type UpdateStatus = 'checking' | 'ok' | 'optional' | 'required' | 'offline';

export function compareSemver(a: string, b: string): number {
  const pa = a.split('.').map(Number);
  const pb = b.split('.').map(Number);
  for (let i = 0; i < 3; i++) {
    const d = (pa[i] || 0) - (pb[i] || 0);
    if (d !== 0) return d;
  }
  return 0;
}

export function useUpdateGate(pollMs = 30 * 60_000): {
  status: UpdateStatus;
  info: VersionInfo | null;
  recheck: () => void;
} {
  const [status, setStatus] = useState<UpdateStatus>('checking');
  const [info, setInfo] = useState<VersionInfo | null>(null);

  const check = useCallback(() => {
    fetch(`${DEFAULT_SERVER}/api/version`)
      .then((r) => r.json())
      .then((j) => {
        const v = j as VersionInfo;
        if (!v || !v.latest) throw new Error('bad payload');
        setInfo({ latest: v.latest, minRequired: v.minRequired, notes: v.notes, url: v.url });
        if (compareSemver(APP_VERSION, v.minRequired) < 0) setStatus('required');
        else if (compareSemver(APP_VERSION, v.latest) < 0) setStatus('optional');
        else setStatus('ok');
      })
      .catch(() => setStatus((s) => (s === 'required' ? s : 'offline')));
  }, []);

  useEffect(() => {
    check();
    const id = setInterval(check, pollMs);
    return () => clearInterval(id);
  }, [check, pollMs]);

  return { status, info, recheck: check };
}
