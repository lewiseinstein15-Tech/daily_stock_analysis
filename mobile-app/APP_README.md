# Jexi App — What This Is

**Jexi** is a real native app (iPhone + Android) for the Jexi trading AI.

- Built with **React Native + Expo** — one codebase, both phones.
- **Demo mode right now**: the money and trades you see are simulated, so you can try everything safely.
- **Nothing is uploaded to GitHub.** Your keys never touch GitHub either.

## What the app does (already working in this build)

1. **Welcome + easy setup** — 3 short slides, then your name.
2. **Your two keys, entered in the app** (never in GitHub):
   - Key 1: AI brain — Gemini, OpenAI, Claude, Groq or other.
   - Key 2: trading account — Alpaca, Binance, Pocket Option, MT5 or Paper practice.
   - Keys are stored encrypted on the device only (Expo SecureStore).
3. **Home** — full balance, today's profit, live chart, open positions, updates every 2 seconds.
4. **Trades** — every buy and sell, tap any trade to see *why* Jexi did it, in plain English.
5. **Profit** — total profit, win rate, 6-month chart, best trade.
6. **Jexi feed** — Jexi explains what it did in plain words. Big **Pause** and **STOP everything** buttons.
7. **Withdraw** — take money out in 4 taps: amount → where → check → done. Min $20, cannot exceed available cash.
8. **Settings** — see/change your keys (masked), notifications, pause, erase everything.

## Try it on your phone later (real native)

```bash
cd jexi-app
npm install
npx expo start
```

Then install **Expo Go** on your phone and scan the QR code. That runs the real native app.

## What comes next (needs your OK + the database)

The database is **designed but NOT built** (as you asked). Plan:

**Phase 1 — user database + real accounts**
- Tables: `users`, `user_keys` (encrypted), `accounts`, `trades`, `positions`, `withdrawals`, `notifications`, `sessions`.
- Each user = own profile, own keys, own money. Login with email.
- Jexi backend (Python, already built: 5 brokers, 15 strategies, risk gates, kill-switch) connects behind an API.

**Phase 2 — real money**
- Keys in the app talk to the real broker through the Jexi backend.
- Withdrawals call the broker payout API. Balance/trades/profit come live over WebSocket.

**Phase 3 — app stores**
- Expo EAS build → Apple App Store + Google Play.

## Safety rules Jexi follows (already in the engine)

- Every trade gets a stop-loss the moment it is bought.
- Confidence gates + position sizing + daily loss limits + drawdown circuit breaker.
- You can pause or kill all trading from the app, instantly.
