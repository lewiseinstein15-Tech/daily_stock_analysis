"use client";

// Shared JEXI primitives — every screen composes from these.
import { ReactNode } from "react";
import { pct as fmtPct } from "@/lib/jexi/data";

export function Delta({ value, size = 13, showPill = true }: { value: number; size?: number; showPill?: boolean }) {
  const up = value >= 0;
  return (
    <span
      className="data inline-flex items-center gap-1"
      style={{
        color: up ? "var(--up)" : "var(--down)",
        fontSize: size,
        ...(showPill
          ? {
              background: `color-mix(in srgb, ${up ? "var(--up)" : "var(--down)"} 10%, transparent)`,
              border: `1px solid color-mix(in srgb, ${up ? "var(--up)" : "var(--down)"} 22%, transparent)`,
              borderRadius: 8,
              padding: "2px 7px",
            }
          : {}),
      }}
    >
      {up ? "▲" : "▼"} {fmtPct(Math.abs(value)).replace("+", "")}
    </span>
  );
}

export function Stat({
  label,
  value,
  sub,
  mono = true,
}: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  mono?: boolean;
}) {
  return (
    <div>
      <div className="label mb-1.5">{label}</div>
      <div className={mono ? "data text-[17px]" : "text-[17px] font-semibold"} style={{ color: "var(--ink)" }}>
        {value}
      </div>
      {sub && (
        <div className="mt-0.5 text-[12px]" style={{ color: "var(--ink-3)" }}>
          {sub}
        </div>
      )}
    </div>
  );
}

export function Panel({
  children,
  className = "",
  pad = true,
  raised = false,
}: {
  children: ReactNode;
  className?: string;
  pad?: boolean;
  raised?: boolean;
}) {
  return (
    <div className={`${raised ? "panel-2" : "panel"} ${pad ? "p-5" : ""} ${className}`}>{children}</div>
  );
}

export function SectionTitle({ children, sub }: { children: ReactNode; sub?: string }) {
  return (
    <div className="mb-4 flex items-end justify-between gap-4">
      <h2 className="display text-[22px] leading-tight" style={{ color: "var(--ink)" }}>
        {children}
      </h2>
      {sub && (
        <span className="text-[12.5px] pb-0.5" style={{ color: "var(--ink-3)" }}>
          {sub}
        </span>
      )}
    </div>
  );
}

export function Pill({ children, tone = "neutral" }: { children: ReactNode; tone?: "neutral" | "brand" | "up" | "down" | "gold" }) {
  const map = {
    neutral: { c: "var(--ink-2)", b: "var(--line)" },
    brand: { c: "var(--ember)", b: "color-mix(in srgb, var(--ember) 35%, transparent)" },
    up: { c: "var(--up)", b: "color-mix(in srgb, var(--up) 30%, transparent)" },
    down: { c: "var(--down)", b: "color-mix(in srgb, var(--down) 30%, transparent)" },
    gold: { c: "var(--gold)", b: "color-mix(in srgb, var(--gold) 35%, transparent)" },
  }[tone];
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-[3px] text-[11px] font-medium uppercase tracking-[0.08em]"
      style={{ color: map.c, border: `1px solid ${map.b}`, background: "color-mix(in srgb, var(--bg) 40%, transparent)" }}
    >
      {children}
    </span>
  );
}

export function LiveDot() {
  return <span className="live-dot inline-block h-[7px] w-[7px] rounded-full" style={{ background: "var(--up)" }} />;
}

export function Skeleton({ h = 16, w }: { h?: number; w?: number | string }) {
  return <div className="skeleton" style={{ height: h, width: w ?? "100%" }} />;
}

export function EmptyState({ icon, title, body, action }: { icon?: ReactNode; title: string; body: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 py-10 text-center">
      {icon && (
        <div
          className="mb-1 flex h-11 w-11 items-center justify-center rounded-xl"
          style={{ background: "var(--panel-2)", border: "1px solid var(--line)", color: "var(--ink-3)" }}
        >
          {icon}
        </div>
      )}
      <div className="font-medium" style={{ color: "var(--ink)" }}>
        {title}
      </div>
      <p className="max-w-[360px] text-[13px] leading-relaxed" style={{ color: "var(--ink-3)" }}>
        {body}
      </p>
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}

export function TickerStrip({
  quotes,
  onSelect,
}: {
  quotes: Record<string, { price: number; changePct?: number }>;
  onSelect?: (symbol: string) => void;
}) {
  const entries = Object.entries(quotes);
  if (!entries.length) return null;
  const doubled = [...entries, ...entries];
  return (
    <div className="overflow-hidden" style={{ borderTop: "1px solid var(--line-soft)", borderBottom: "1px solid var(--line-soft)" }}>
      <div className="ticker-track flex w-max items-center gap-9 py-2.5">
        {doubled.map(([symbol, q], i) => (
          <button
            key={`${symbol}-${i}`}
            onClick={() => onSelect?.(symbol)}
            className="flex items-center gap-2 text-[13px] transition-colors"
            style={{ color: "var(--ink-2)" }}
          >
            <span className="data font-medium" style={{ color: "var(--ink)" }}>
              {symbol.replace("-USD", "")}
            </span>
            <span className="data">{q.price.toLocaleString("en-US", { maximumFractionDigits: 2 })}</span>
            <span className="data" style={{ color: (q.changePct || 0) >= 0 ? "var(--up)" : "var(--down)" }}>
              {(q.changePct || 0) > 0 ? "▲" : "▼"} {Math.abs(q.changePct || 0).toFixed(2)}%
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}

export function KindDot({ kind }: { kind: string }) {
  const color =
    kind === "win" ? "var(--up)" : kind === "loss" ? "var(--down)" : kind === "money" ? "var(--gold)" : "var(--ember)";
  return <span className="mt-[7px] inline-block h-2 w-2 shrink-0 rounded-full" style={{ background: color }} />;
}
