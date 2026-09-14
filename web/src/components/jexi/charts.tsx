"use client";

// JEXI-native charts: warm SVG, tabular data, draw-in animation, hover crosshair.
import { useMemo, useRef, useState } from "react";

function smoothPath(values: number[], w: number, h: number, pad = 2): string {
  if (values.length < 2) return "";
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const x = (i: number) => pad + (i / (values.length - 1)) * (w - pad * 2);
  const y = (v: number) => h - pad - ((v - min) / range) * (h - pad * 2);
  const pts = values.map((v, i) => [x(i), y(v)] as const);

  let d = `M ${pts[0][0]} ${pts[0][1]}`;
  for (let i = 1; i < pts.length; i++) {
    const [x0, y0] = pts[i - 1];
    const [x1, y1] = pts[i];
    const mx = (x0 + x1) / 2;
    d += ` C ${mx} ${y0}, ${mx} ${y1}, ${x1} ${y1}`;
  }
  return d;
}

export function AreaChart({
  data,
  height = 260,
  showAxis = true,
  fmt = (v: number) => v.toFixed(2),
}: {
  data: number[];
  height?: number;
  showAxis?: boolean;
  fmt?: (v: number) => string;
}) {
  const ref = useRef<SVGSVGElement>(null);
  const [hover, setHover] = useState<number | null>(null);
  const W = 640;
  const H = height;
  const id = useMemo(() => `ac${Math.random().toString(36).slice(2, 8)}`, []);

  if (!data || data.length < 2) {
    return (
      <div className="flex items-center justify-center" style={{ height: H }}>
        <span className="label">Not enough history yet</span>
      </div>
    );
  }

  const min = Math.min(...data);
  const max = Math.max(...data);
  const line = smoothPath(data, W, H);
  const area = `${line} L ${W - 2} ${H} L 2 ${H} Z`;
  const up = data[data.length - 1] >= data[0];
  const stroke = up ? "var(--peach)" : "var(--down)";

  const onMove = (e: React.MouseEvent) => {
    const rect = ref.current?.getBoundingClientRect();
    if (!rect) return;
    const ratio = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width));
    setHover(Math.round(ratio * (data.length - 1)));
  };

  const hoverX = hover !== null ? 2 + (hover / (data.length - 1)) * (W - 4) : 0;
  const hoverY = hover !== null ? H - 2 - ((data[hover] - min) / (max - min || 1)) * (H - 4) : 0;

  return (
    <div className="relative w-full" style={{ height: H }}>
      <svg
        ref={ref}
        viewBox={`0 0 ${W} ${H}`}
        width="100%"
        height={H}
        preserveAspectRatio="none"
        onMouseMove={onMove}
        onMouseLeave={() => setHover(null)}
      >
        <defs>
          <linearGradient id={`${id}-fill`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor={stroke} stopOpacity="0.22" />
            <stop offset="1" stopColor={stroke} stopOpacity="0" />
          </linearGradient>
        </defs>
        {showAxis && (
          <g stroke="var(--line-soft)" strokeWidth="1">
            <line x1="0" y1={H * 0.25} x2={W} y2={H * 0.25} />
            <line x1="0" y1={H * 0.5} x2={W} y2={H * 0.5} />
            <line x1="0" y1={H * 0.75} x2={W} y2={H * 0.75} />
          </g>
        )}
        <path d={area} fill={`url(#${id}-fill)`} />
        <path
          d={line}
          stroke={stroke}
          strokeWidth="2.2"
          fill="none"
          strokeLinecap="round"
          style={{
            strokeDasharray: 2400,
            animation: "jexi-draw 700ms cubic-bezier(.22,.61,.36,1) both",
            ["--draw" as string]: 2400,
          }}
        />
        <circle cx={W - 2} cy={H - 2 - ((data[data.length - 1] - min) / (max - min || 1)) * (H - 4)} r="3.4" fill={stroke} />
        {hover !== null && (
          <g>
            <line x1={hoverX} y1="0" x2={hoverX} y2={H} stroke="var(--ink-3)" strokeWidth="1" strokeDasharray="3 4" />
            <circle cx={hoverX} cy={hoverY} r="4.2" fill={stroke} stroke="var(--bg)" strokeWidth="2" />
          </g>
        )}
      </svg>
      {hover !== null && (
        <div
          className="panel-2 absolute px-2.5 py-1.5 pointer-events-none"
          style={{
            left: `min(calc(100% - 92px), ${(hover / (data.length - 1)) * 100}%)`,
            top: 8,
            transform: "translateX(-50%)",
          }}
        >
          <span className="data text-[12px]" style={{ color: "var(--ink)" }}>
            {fmt(data[hover])}
          </span>
        </div>
      )}
    </div>
  );
}

export function Sparkline({ data, w = 92, h = 30 }: { data: number[]; w?: number; h?: number }) {
  if (!data || data.length < 2) return <div style={{ width: w, height: h }} />;
  const up = data[data.length - 1] >= data[0];
  const stroke = up ? "var(--up)" : "var(--down)";
  const line = smoothPath(data, w, h, 2);
  return (
    <svg viewBox={`0 0 ${w} ${h}`} width={w} height={h} aria-hidden>
      <path d={line} stroke={stroke} strokeWidth="1.6" fill="none" strokeLinecap="round" />
    </svg>
  );
}

export function ConvictionDial({ value, size = 96 }: { value: number; size?: number }) {
  const r = 40;
  const circ = 2 * Math.PI * r;
  const filled = (Math.min(100, Math.max(0, value)) / 100) * circ;
  return (
    <svg viewBox="0 0 100 100" width={size} height={size} role="img" aria-label={`Conviction ${value}%`}>
      <defs>
        <linearGradient id="conv-grad" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#FF7A3D" />
          <stop offset="1" stopColor="#FF6B5E" />
        </linearGradient>
      </defs>
      <circle cx="50" cy="50" r={r} stroke="var(--panel-3)" strokeWidth="8" fill="none" />
      <circle
        cx="50"
        cy="50"
        r={r}
        stroke="url(#conv-grad)"
        strokeWidth="8"
        fill="none"
        strokeLinecap="round"
        strokeDasharray={`${filled} ${circ}`}
        transform="rotate(-90 50 50)"
        style={{ transition: "stroke-dasharray 600ms var(--ease)" }}
      />
      <text
        x="50"
        y="47"
        textAnchor="middle"
        fill="var(--ink)"
        fontSize="19"
        fontWeight="600"
        fontFamily="var(--font-data), monospace"
      >
        {value}%
      </text>
      <text x="50" y="62" textAnchor="middle" fill="var(--ink-3)" fontSize="8.5" letterSpacing="1.5">
        CONVICTION
      </text>
    </svg>
  );
}

export function Donut({ slices, size = 150 }: { slices: { label: string; value: number; color: string }[]; size?: number }) {
  const total = slices.reduce((a, s) => a + s.value, 0) || 1;
  const r = 56;
  const circ = 2 * Math.PI * r;
  // precompute arc offsets before render (pure, no accumulator mutation)
  const arcs = slices.reduce<{ label: string; value: number; color: string; dash: number; offset: number }[]>(
    (list, s) => {
      const prev = list[list.length - 1];
      const start = prev ? prev.offset + prev.dash : 0;
      const dash = Math.max(0, (s.value / total) * circ - 2);
      list.push({ ...s, dash, offset: -start });
      return list;
    },
    []
  );
  return (
    <svg viewBox="0 0 140 140" width={size} height={size} role="img" aria-label="Allocation">
      {arcs.map((a, i) => (
        <circle
          key={i}
          cx="70"
          cy="70"
          r={r}
          fill="none"
          stroke={a.color}
          strokeWidth="14"
          strokeDasharray={`${a.dash} ${circ - a.dash}`}
          strokeDashoffset={a.offset}
          transform="rotate(-90 70 70)"
        />
      ))}
      <circle cx="70" cy="70" r="40" fill="var(--panel)" />
    </svg>
  );
}

export const CHART_COLORS = ["#FF7A3D", "#FFB88C", "#FF6B5E", "#E5B567", "#4CC38A", "#A99F90", "#8a5a3a", "#c98a5a"];
