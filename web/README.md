# JEXI Market — Web

The JEXI Market web terminal (design system: see `docs/jexi-market-design-system.md`,
research: `docs/jexi-market-design-research.md`).

- Live at: https://jexi-web.vercel.app (when deployed)
- Talks to the API server in `../server` (deployed at https://jexi-server.vercel.app)
- Real prices from the server's `/api/market` (Yahoo → Stooq fallback, cached 60s)
- Email + Google sign-in, encrypted per-user keys, paper trading feed, admin control
  room for ADMIN_EMAIL accounts.

## Run locally

```bash
cd web
npm install
npm run dev   # http://localhost:3000
```

## Deploy to Vercel

```bash
cd web
npx vercel link --project jexi-web
npx vercel deploy --prod
```

No environment variables required (the server URL is configurable in-app, Settings →
Server connection).
