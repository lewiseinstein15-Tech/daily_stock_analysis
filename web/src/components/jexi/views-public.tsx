"use client";

// Landing + Auth views — the public face of JEXI Market.
import { useState } from "react";
import { ArrowRight, BarChart3, BrainCircuit, KeyRound, LineChart, ShieldCheck, Sparkles } from "lucide-react";
import { CoreOrb, JexiMark, Wordmark } from "@/components/jexi/brand";
import { Delta, Panel, Pill, SectionTitle, Stat, TickerStrip, LiveDot } from "@/components/jexi/bits";
import {
  TICKER_SYMBOLS,
  priceFmt,
  useQuotes,
  useAuth,
  money,
} from "@/lib/jexi/data";

type Go = (view: string, symbol?: string) => void;

export function Landing({ go }: { go: Go }) {
  const { quotes } = useQuotes(TICKER_SYMBOLS, 25000);
  const { user } = useAuth();
  const nvda = quotes["NVDA"];
  const spy = quotes["SPY"];

  return (
    <div className="view-enter">
      {/* hero */}
      <section className="relative mx-auto flex max-w-6xl flex-col items-center px-5 pb-14 pt-10 text-center md:pt-16">
        <div className="mb-6">
          <Pill tone="brand">
            <LiveDot /> live prices · {Object.keys(quotes).length || "…"} markets
          </Pill>
        </div>
        <h1 className="display max-w-3xl text-[44px] leading-[1.04] md:text-[68px]">
          The market,{" "}
          <span
            style={{
              background: "linear-gradient(100deg, var(--ember), var(--peach))",
              WebkitBackgroundClip: "text",
              backgroundClip: "text",
              color: "transparent",
            }}
          >
            explained
          </span>
          .
        </h1>
        <p className="mt-5 max-w-[560px] text-[15.5px] leading-relaxed" style={{ color: "var(--ink-2)" }}>
          JEXI Market is a financial-intelligence terminal. It watches the tape, runs a
          six-analyst research pipeline, and trades with a safety-first engine that
          explains every move in plain English.
        </p>
        <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
          <button className="btn btn-primary" onClick={() => go(user ? "command" : "auth")}>
            {user ? "Open Command Center" : "Start with your email"} <ArrowRight size={16} />
          </button>
          <button className="btn btn-line" onClick={() => go("intelligence")}>
            See how JEXI thinks
          </button>
        </div>

        <div className="mt-10 flex items-end justify-center">
          <div style={{ filter: "drop-shadow(0 30px 60px rgba(255,122,61,.12))" }}>
            <CoreOrb size={330} />
          </div>
        </div>

        {quotes && Object.keys(quotes).length > 0 && (
          <div className="mt-8 w-full max-w-5xl">
            <TickerStrip quotes={quotes} onSelect={(s) => go("asset", s)} />
          </div>
        )}
      </section>

      {/* live proof strip */}
      <section className="mx-auto max-w-6xl px-5 py-8">
        <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
          <Panel raised>
            <Stat
              label="S&P 500 · SPY"
              value={spy ? priceFmt(spy.price) : "—"}
              sub={spy ? <Delta value={spy.changePct || 0} /> : "loading live quote"}
            />
          </Panel>
          <Panel raised>
            <Stat
              label="NVIDIA · NVDA"
              value={nvda ? priceFmt(nvda.price) : "—"}
              sub={nvda ? <Delta value={nvda.changePct || 0} /> : "loading live quote"}
            />
          </Panel>
          <Panel raised>
            <Stat label="Analyst pipeline" value="6 + verifier" sub="fundamental → thesis, with evidence" />
          </Panel>
          <Panel raised>
            <Stat label="Engine rules" value="Safety first" sub="7% safety line · 18% take profit · 6 positions max" />
          </Panel>
        </div>
      </section>

      {/* how JEXI thinks */}
      <section className="mx-auto max-w-6xl px-5 py-14">
        <SectionTitle sub="no black boxes">How JEXI thinks</SectionTitle>
        <div className="grid gap-4 md:grid-cols-3">
          {[
            {
              icon: <BarChart3 size={18} />,
              title: "Research analysts",
              body: "Fundamental, technical, macro, risk and news analysts each examine the market from their own desk — and show their key evidence.",
            },
            {
              icon: <ShieldCheck size={18} />,
              title: "Verifier before thesis",
              body: "A verifier separates data, analysis and interpretation. Only then does JEXI publish a thesis with conviction, drivers and risks.",
            },
            {
              icon: <LineChart size={18} />,
              title: "Engine that explains itself",
              body: "Trades carry a plain-English reason. Safety lines protect capital. Every buy, sell and withdrawal lands in your feed.",
            },
          ].map((f) => (
            <Panel key={f.title} className="flex flex-col gap-3">
              <div
                className="flex h-10 w-10 items-center justify-center rounded-xl"
                style={{ background: "var(--panel-2)", border: "1px solid var(--line)", color: "var(--ember)" }}
              >
                {f.icon}
              </div>
              <div className="font-semibold" style={{ color: "var(--ink)" }}>
                {f.title}
              </div>
              <p className="text-[13.5px] leading-relaxed" style={{ color: "var(--ink-2)" }}>
                {f.body}
              </p>
            </Panel>
          ))}
        </div>
      </section>

      {/* thesis preview */}
      <section className="mx-auto max-w-6xl px-5 pb-14">
        <Panel className="grid gap-8 md:grid-cols-[1.1fr_1fr]">
          <div>
            <Pill tone="brand">Thesis preview</Pill>
            <h3 className="display mt-4 text-[30px] leading-tight">NVDA — Bullish</h3>
            <p className="mt-3 max-w-[440px] text-[14px] leading-relaxed" style={{ color: "var(--ink-2)" }}>
              An example of the JEXI thesis format: a stance, a conviction level, and the
              evidence split into drivers, risks and catalysts. Connect your own AI key to
              generate live theses for your watchlist.
            </p>
            <div className="mt-5 flex flex-wrap gap-2">
              {["Revenue growth", "AI infrastructure demand", "Margin trajectory"].map((d) => (
                <span
                  key={d}
                  className="rounded-lg px-2.5 py-1.5 text-[12.5px]"
                  style={{ background: "var(--panel-2)", border: "1px solid var(--line-soft)", color: "var(--ink-2)" }}
                >
                  {d}
                </span>
              ))}
            </div>
            <button className="btn btn-ghost mt-7" onClick={() => go("asset", "NVDA")}>
              Open the NVDA page <ArrowRight size={15} />
            </button>
          </div>
          <div className="grid grid-cols-3 gap-3 self-center">
            {[
              { k: "Drivers", v: "3", d: "evidence-backed" },
              { k: "Risks", v: "3", d: "ranked by impact" },
              { k: "Catalysts", v: "3", d: "with time horizons" },
            ].map((x) => (
              <div key={x.k} className="panel-2 p-4 text-center">
                <div className="data text-[26px]" style={{ color: "var(--peach)" }}>
                  {x.v}
                </div>
                <div className="label mt-1">{x.k}</div>
                <div className="mt-0.5 text-[11px]" style={{ color: "var(--ink-3)" }}>
                  {x.d}
                </div>
              </div>
            ))}
          </div>
        </Panel>
      </section>

      {/* what you get */}
      <section className="mx-auto max-w-6xl px-5 pb-16">
        <SectionTitle sub="everything included">What you get</SectionTitle>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {[
            { icon: <BrainCircuit size={18} />, t: "AI research desk", b: "Six analysts, a verifier, and theses you can interrogate." },
            { icon: <LineChart size={18} />, t: "Native market charts", b: "Warm, readable, JEXI-drawn charts — not an embed." },
            { icon: <KeyRound size={18} />, t: "Your keys, encrypted", b: "AI and broker keys live server-side, AES-256 encrypted, masked forever." },
            { icon: <Sparkles size={18} />, t: "Plain-English feed", b: "Every trade and withdrawal explained like a colleague would." },
          ].map((x) => (
            <Panel key={x.t} className="flex flex-col gap-2.5">
              <div style={{ color: "var(--ember)" }}>{x.icon}</div>
              <div className="font-semibold" style={{ color: "var(--ink)" }}>
                {x.t}
              </div>
              <p className="text-[13px] leading-relaxed" style={{ color: "var(--ink-2)" }}>
                {x.b}
              </p>
            </Panel>
          ))}
        </div>
      </section>

      {/* closing */}
      <section className="mx-auto max-w-6xl px-5 pb-20 text-center">
        <div className="panel relative overflow-hidden px-6 py-12">
          <div
            className="pointer-events-none absolute inset-0"
            style={{
              background:
                "radial-gradient(520px 220px at 50% 0%, color-mix(in srgb, var(--ember) 10%, transparent), transparent 70%)",
            }}
          />
          <h2 className="display relative text-[32px] leading-tight md:text-[40px]">
            Your capital deserves a research desk.
          </h2>
          <p className="relative mx-auto mt-3 max-w-[480px] text-[14.5px]" style={{ color: "var(--ink-2)" }}>
            Create an account with email or Google — you start with a {money(10000, 0)} paper
            account, your own keys, and JEXI watching the market for you.
          </p>
          <button className="btn btn-primary relative mt-7" onClick={() => go(user ? "command" : "auth")}>
            {user ? "Go to your account" : "Create your account"} <ArrowRight size={16} />
          </button>
        </div>
        <Footer />
      </section>
    </div>
  );
}

export function Footer() {
  return (
    <footer className="mt-14 flex flex-col items-center gap-3 border-t pt-8" style={{ borderColor: "var(--line-soft)" }}>
      <div className="flex items-center gap-2.5">
        <JexiMark size={26} />
        <Wordmark />
      </div>
      <p className="text-[12px]" style={{ color: "var(--ink-3)" }}>
        JEXI Market trades paper money by default. Nothing here is financial advice. © {new Date().getFullYear()} JEXI.
      </p>
    </footer>
  );
}

export function AuthView({ go }: { go: Go }) {
  const { signIn, signUp, startGoogle, googleEnabled } = useAuth();
  const [mode, setMode] = useState<"in" | "up">("in");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setErr(null);
    setBusy(true);
    try {
      if (mode === "in") await signIn(email, password);
      else await signUp(email, password, name);
      go("command");
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="view-enter mx-auto grid min-h-[calc(100vh-140px)] max-w-5xl items-center gap-10 px-5 py-10 md:grid-cols-[1fr_420px]">
      <div className="hidden md:block">
        <CoreOrb size={300} />
      </div>

      <Panel className="p-7">
        <div className="mb-6 flex items-center gap-2.5">
          <JexiMark size={30} />
          <Wordmark />
        </div>
        <h1 className="display text-[26px]">{mode === "in" ? "Welcome back" : "Create your account"}</h1>
        <p className="mt-1.5 text-[13.5px]" style={{ color: "var(--ink-2)" }}>
          {mode === "in"
            ? "Sign in to your JEXI Market account."
            : "You start with a $10,000 paper account and your own encrypted keys."}
        </p>

        <div className="mt-6 flex flex-col gap-3">
          {mode === "up" && (
            <input className="input" placeholder="Your name" value={name} onChange={(e) => setName(e.target.value)} />
          )}
          <input
            className="input"
            placeholder="Email address"
            type="email"
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
          <input
            className="input"
            placeholder="Password (min 6 characters)"
            type="password"
            autoComplete={mode === "in" ? "current-password" : "new-password"}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && submit()}
          />
          {err && (
            <div
              className="rounded-lg px-3 py-2.5 text-[13px]"
              style={{ background: "color-mix(in srgb, var(--down) 9%, transparent)", color: "var(--down)", border: "1px solid color-mix(in srgb, var(--down) 25%, transparent)" }}
            >
              {err}
            </div>
          )}
          <button className="btn btn-primary" onClick={submit} disabled={busy}>
            {busy ? "One moment…" : mode === "in" ? "Sign in" : "Create account"}
          </button>

          <div className="my-1 flex items-center gap-3">
            <div className="h-px flex-1" style={{ background: "var(--line)" }} />
            <span className="label">or</span>
            <div className="h-px flex-1" style={{ background: "var(--line)" }} />
          </div>

          <button className="btn btn-ghost" onClick={startGoogle} disabled={!googleEnabled}>
            <GoogleG /> Continue with Google
          </button>
          {!googleEnabled && (
            <p className="text-center text-[11.5px]" style={{ color: "var(--ink-3)" }}>
              Google sign-in activates once GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET are set on the server.
            </p>
          )}

          <button
            className="mt-2 text-[13px]"
            style={{ color: "var(--ink-2)" }}
            onClick={() => {
              setMode(mode === "in" ? "up" : "in");
              setErr(null);
            }}
          >
            {mode === "in" ? "New here? Create an account" : "Already have an account? Sign in"}
          </button>
        </div>
      </Panel>
    </div>
  );
}

export function GoogleG() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" aria-hidden>
      <path fill="#EA4335" d="M12 10.2v3.9h5.4c-.2 1.4-1.7 4.2-5.4 4.2-3.3 0-6-2.7-6-6.1s2.7-6.1 6-6.1c1.9 0 3.1.8 3.9 1.5l2.7-2.6C16.9 3.3 14.7 2.3 12 2.3 6.6 2.3 2.3 6.6 2.3 12s4.3 9.7 9.7 9.7c5.6 0 9.3-3.9 9.3-9.4 0-.6-.1-1.1-.2-1.6H12z" />
    </svg>
  );
}
