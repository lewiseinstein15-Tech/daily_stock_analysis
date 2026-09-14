# JEXI Market — Design Research

Date: 2026-09-15 · Author: Design + Frontend Lead (JEXI)

## Why this document exists

JEXI Market must stop looking like "a trading dashboard" and start looking like
**JEXI Market** — an original, premium financial-intelligence product. This document
records what was studied, the principles extracted from each reference, what JEXI
adopts, what JEXI explicitly rejects, and why the final result is original rather
than a copy.

Studied: **Relume, Magic Patterns, Framer, Readdy, Phase, Marcelo Design X (MDX)**.
Method: live study of their public sites and product surfaces (HTML/text capture of
marketing + product pages, noting structure, hierarchy, motion and language), plus
long familiarity with each product's documented design approach. No assets, code,
or layouts were copied from any of them.

---

## 1. Relume — component systems and page composition

What was studied: relume.io marketing site and the public Figma library surface.

What Relume is exceptionally good at:

- **Systems before screens.** Every page is assembled from a small set of
  well-named, reusable components. Nothing is drawn "just this once".
- **Page composition as rhythm.** Sections alternate dense/airy, and every section
  has one obvious job (promise, proof, feature, conversion).
- **Sane responsive defaults.** Components collapse in predictable, boring-in-a-good-
  way ways: 3-col → 2-col → 1-col, tables become cards, nav becomes a sheet.
- **Typography scale discipline.** Few sizes, huge jumps, consistent weights.

What JEXI adopts:

- A named component inventory (`Stat`, `Delta`, `Panel`, `Sparkline`, `AnalystCard`,
  `ThesisCard`, `TickerStrip`, `HeatCell`, …) that every screen composes from.
- One job per screen region; information hierarchy over information quantity.
- Explicit mobile collapse rules (documented in the design-system doc).

What JEXI rejects: Relume's marketing-site section tropes (logo walls, testimonial
carousels) — JEXI is a product, not an agency site.

## 2. Magic Patterns — modern application UI and data hierarchy

What was studied: magicpatterns.com product pages and its gallery of generated
application UIs.

What Magic Patterns is good at:

- **Information hierarchy in dense tools.** Primary metric huge, supporting metrics
  quiet, controls tucked away until needed.
- **Component composition over chrome.** Dense data lives in calm containers; the
  container is quiet so the data can shout.
- **AI-assisted interfaces that expose their reasoning.** The best AI product UIs
  show state (thinking → done), inputs (what the AI saw) and outputs (what it
  concluded) as first-class UI, not a chat log.

What JEXI adopts:

- The "one hero number per view" rule (price on the asset page, equity on portfolio).
- AI states rendered as UI: each JEXI analyst shows status + key evidence, and the
  thesis is a distinct, final artifact — never a chat bubble.
- Quiet containers: warm charcoal panels, hairline borders, no nesting-in-nesting.

What JEXI rejects: generic "AI dashboard" aesthetics — purple gradients, neon-on-
black glow, floating glass cards everywhere.

## 3. Framer — premium typography, motion, storytelling

What was studied: framer.com marketing and docs surfaces.

What Framer is good at:

- **Type as identity.** One display face used with extreme size contrast carries the
  whole brand; body text stays almost invisible in its competence.
- **Motion with purpose.** Entrances are short (150–250ms), ease-out, and always
  communicate hierarchy (primary content settles first, decorations last).
- **Storytelling scroll.** The page is a narrative: claim → proof → mechanism →
  invitation. Each scroll viewport answers one question.

What JEXI adopts:

- A distinctive display serif (warm, editorial) used at large sizes for hero and
  section claims, paired with a workhorse UI sans and a mono for data.
- Motion rules: every animation earns its place; page/view transitions are crossfade
  + 8px rise; numbers animate on change; charts draw in once; `prefers-reduced-motion`
  disables all of it.
- Landing as narrative: "the market, explained" → who JEXI is → how JEXI thinks →
  what you get → start.

What JEXI rejects: scroll-jacking, heavy parallax, gratuitous 3D everywhere.

## 4. Readdy — complete product layouts and structure

What was studied: readdy.ai marketing site and template structure.

What Readdy is good at:

- **Complete, coherent layouts** — header, hero, feature grid, tables, footer all
  feel like one family.
- **Feature grids that scan** — icon + claim + one line, in a strict grid.
- **Trust through structure** — comparison tables and structured pricing read cleanly.

What JEXI adopts:

- The idea that EVERY screen is designed, not just the hero: auth, empty states,
  loading states, errors, and settings get the same care as the dashboard.
- Strict feature-grid scanning patterns for the landing "what you get" section.

What JEXI rejects: template-y sameness; SaaS-blue button and badge language.

## 5. Phase — micro-interactions and interface states

What was studied: phase.com (app-shell only rendered — service is invite-gated), plus
Phase's widely documented interaction model (Figma plugin / design-token workflow).

What Phase is known for:

- **Micro-interactions that confirm state** — every press, toggle and commit gives a
  small, physical response.
- **Interaction states designed as a set**: default/hover/active/focus/disabled all
  exist for every control, with consistent timing and easing.
- **Design tokens as the single source of truth** — color/spacing/radius defined once
  and referenced everywhere.

What JEXI adopts:

- Full interaction-state matrix for buttons, inputs, rows, tabs, cards (documented).
- Micro-feedback: watchlist star fill, copy-key flash, tab slide, palette open scale.
- Tokens-first CSS custom properties; no ad-hoc hex values in components.

What JEXI rejects: springy overshoot everywhere; animation for decoration's sake.

## 6. Marcelo Design X — immersive, award-level presentation

What was studied: mdx.so home/bio pages ("Turn Your Vision Into an Experience That
Lasts", "Design That Feels. Experiences That Resonate.", award-winning studio
positioning, dark immersive presentation, 3D studio services).

What MDX is good at:

- **Immersive hero objects** — one memorable, slowly-alive visual identity element
  that anchors the whole page.
- **Dark, warm, premium palettes** with generous negative space.
- **Confidence through restraint** — few elements, each large and precisely placed.

What JEXI adopts:

- The **JEXI Core**: an original identity object — a layered warm-metal ring system
  (SVG/CSS, slow rotation, subtle depth) used exactly twice: landing hero and auth.
  It is decoration with meaning (the market as a system you can see into), never a
  data container.
- Warm-dark premium palette (deep charcoal, ember, coral, peach) instead of neon.
- Restraint: at most one immersive element per screen; data always stays readable.

What JEXI rejects: turning the product into a 3D experiment; WebGL cost; heavy
canvas loops. The Core is pure SVG/CSS and pauses under reduced-motion.

---

## What JEXI Market will be

**Positioning:** an executive financial-intelligence terminal — calm, warm, serious.
Feels less like a trading app and more like a research desk that happens to trade.

**Identity words:** Intelligent · Premium · Financial · Calm · Powerful · Modern ·
Trustworthy · Technical · Executive.

**Design language in one line:** warm charcoal surfaces, an ember/coral/peach brand
family, an editorial serif for claims, mono for numbers, native warm charts, one
living identity object, and motion that only ever explains state.

## Originality statement

- The logo (JexiMark: a "J" whose descender resolves into an ascending market line,
  inside a warm charcoal tile) is drawn from scratch for JEXI.
- The palette is JEXI's own warm family; no reference uses it.
- The analyst pipeline / thesis UI is designed from JEXI's actual agent architecture
  (research → technical → macro → risk → news → verifier → thesis).
- All charts are JEXI-native SVG (no third-party chart skin), sharing the palette and
  animation language.
- No reference site's layout, copy, assets, or distinctive designs were copied.
