# JEXI Market — Design System (implemented)

The code in `src/components/jexi/` is the source of truth. This document maps it.

## 1. Color tokens (CSS custom properties, `globals.css`)

| Token | Value | Use |
|---|---|---|
| `--bg` | `#0C0B09` | app background (warm near-black) |
| `--panel` | `#15130F` | cards, panels |
| `--panel-2` | `#1C1915` | raised panels, inputs |
| `--line` | `#282318` | hairline borders |
| `--line-soft` | `#201C15` | dividers inside panels |
| `--ink` | `#F3EEE6` | primary text (warm white) |
| `--ink-2` | `#A99F90` | secondary text |
| `--ink-3` | `#7A7163` | muted text, labels |
| `--ember` | `#FF7A3D` | brand primary (actions, focus, brand marks) |
| `--coral` | `#FF6B5E` | brand secondary |
| `--peach` | `#FFB88C` | brand tertiary, chart line |
| `--sand` | `#E8D9C4` | display-serif accent text |
| `--up` | `#4CC38A` | positive deltas only |
| `--down` | `#FF5D5D` | negative deltas only |
| `--gold` | `#E5B567` | admin badge, "pro" marks |

Rules: brand family (ember/coral/peach) = identity + actions. `--up`/`--down` are
reserved for financial deltas and chart direction — never decoration. No blue, no
purple, no neon.

## 2. Typography

- **Display**: Fraunces (variable, serif) — hero, section claims, big thesis words.
- **UI**: Inter (variable) — everything else; `-0.01em` tracking on labels.
- **Data**: JetBrains Mono (variable) — prices, percentages, tickers, timestamps;
  `font-variant-numeric: tabular-nums` everywhere numbers move.

Scale: hero 56–72 · h1 34 · h2 24 · h3 18 · body 15 · label 12 (uppercase,
letter-spaced 0.08em) · micro 11. Loaded locally via `next/font/local`
(`public/fonts/*.woff2`), zero runtime font requests.

## 3. Surfaces & depth

- Panels: `--panel` fill, 1px `--line` border, radius 14–16, **no drop shadows** —
  depth comes from a slightly raised fill (`--panel-2`) and border contrast.
- Page glow: one fixed radial warm glow (top, ~6% opacity) per view. Never on data.
- The JEXI Core (brand.tsx) is the only immersive object; landing + auth only.

## 4. Components (`src/components/jexi/`)

brand.tsx: `JexiMark` (original logo — J descender becomes an ascending market line
on a warm tile), `Wordmark`, `CoreOrb` (layered rotating warm ring system, pauses on
reduced-motion), `FaviconMark`.

charts.tsx (native SVG, no chart library): `Sparkline` (90×28), `AreaChart`
(gradient fill, draw-in animation, hover crosshair + price flag, baseline dot),
`ConvictionDial` (0–100 ring), `Donut` (allocation), `HeatCell`.

bits.tsx: `Delta` (up/down chip, mono), `Stat` (label + mono value), `Panel`,
`SectionTitle`, `TickerStrip` (live marquee), `Skeleton`, `EmptyState`, `Pill`.

app-views.tsx / views.tsx: Landing, Auth, Command (market command center), Markets,
Asset, Portfolio, Intelligence (analyst pipeline + thesis), Alerts, Settings (+admin).

shell.tsx: `JexiApp` — hash router (`#/command`, `#/asset/AAPL`, …), top nav,
mobile tab bar, ⌘K command palette, auth gate, connection state.

## 5. Motion (Phase/Framer-derived rules)

- Durations: 150ms (micro) / 220ms (view) / 400ms (charts draw-in). Ease: cubic-bezier(.22,.61,.36,1).
- View change: crossfade + 8px rise. Numbers: 220ms fade-slide on change.
- Hover: rows lift 1px, buttons brighten 4%; focus rings 2px `--ember` at 40%.
- `prefers-reduced-motion`: all animation off, charts render final state.

## 6. Interaction states (every control)

default / hover (+4% lightness) / active (scale .98) / focus-visible (ember ring) /
disabled (40% ink, no hover). Inputs: warm dark fill, `--line` border, ember focus.

## 7. Data honesty

Real prices come from the live JEXI server (`/api/market`). Anything simulated is
labeled **Demo** (Pill) — thesis previews, demo portfolio, demo feed. The interface
never presents generated content as market fact.

## 8. Responsive

Breakpoints: <640 mobile (bottom tabs, single column, 44px targets), 640–1024
(2-col), >1024 (3–4 col, full nav). Tables become stacked cards on mobile; the
command palette fills the screen; charts keep ≥120px height.
