// JEXI warm theme — matches the web app's globals.css tokens exactly.
// Warm charcoal surfaces, ember orange brand, honest green/red for money.

export const C = {
  bg: '#0c0b09',
  card: '#15130f',
  card2: '#1c1915',
  card3: '#241f19',
  border: '#282318',

  text: '#f3eee6',
  sub: '#a99f90',
  faint: '#7a7163',

  brand: '#ff7a3d',
  brandSoft: 'rgba(255,122,61,0.14)',

  coral: '#ff6b5e',
  peach: '#ffb88c',
  sand: '#e8d9c4',

  green: '#4cc38a',
  greenSoft: 'rgba(76,195,138,0.14)',
  red: '#ff5d5d',
  redSoft: 'rgba(255,93,93,0.14)',
  amber: '#e5b567',
  amberSoft: 'rgba(229,181,103,0.16)',
} as const;

/** Global corner radius (matches --radius on the web). */
export const R = 14;

/** Font families — the same variable fonts the JEXI Market web app uses. */
export const F = {
  display: 'Fraunces',      // serif headlines ("The market, explained.")
  ui: 'Inter',              // everything else
  data: 'JetBrains Mono',   // numbers, tickers
} as const;

/** Brand gradient for primary buttons (matches .btn-primary on the web). */
export const GRAD = ['#ff7a3d', '#ff6b5e'] as const;
