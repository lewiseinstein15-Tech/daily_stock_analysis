// Small money / percent / time helpers used across every screen.

/** $1,234.56 — signed=true puts a + in front of gains. */
export function money(v: number, signed = false): string {
  const n = Number.isFinite(v) ? v : 0;
  const sign = n < 0 ? '-' : signed && n > 0 ? '+' : '';
  const abs = Math.abs(n);
  const body = abs.toLocaleString('en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return `${sign}$${body}`;
}

/** +1.23% — always shows its direction. */
export function pct(v: number, signed = true): string {
  const n = Number.isFinite(v) ? v : 0;
  const sign = n > 0 ? '+' : n < 0 ? '-' : '';
  const body = Math.abs(n).toLocaleString('en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return signed ? `${sign}${body}%` : `${body}%`;
}

/** "just now" · "5m ago" · "3h ago" · "2d ago" */
export function ago(ts: number | string): string {
  const t = typeof ts === 'string' ? Date.parse(ts.length === 19 ? ts + 'Z' : ts) : ts;
  if (Number.isNaN(t)) return 'just now';
  const s = Math.max(0, Math.floor((Date.now() - t) / 1000));
  if (s < 60) return 'just now';
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  return `${d}d ago`;
}

/** "14:32" clock time for feed stamps. */
export function clock(ts: number | string): string {
  const t = typeof ts === 'string' ? Date.parse(ts.length === 19 ? ts + 'Z' : ts) : ts;
  const d = Number.isNaN(t) ? new Date() : new Date(t);
  return d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false });
}
