"use client";

// JEXI Market brand: original logo mark, wordmark, and the Core identity object.

export function JexiMark({ size = 34 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" fill="none" aria-label="JEXI Market">
      <rect width="64" height="64" rx="15" fill="url(#jexi-tile)" />
      <rect x="0.5" y="0.5" width="63" height="63" rx="14.5" stroke="#3a3226" />
      <path
        d="M18 14 L18 38 Q18 50 29 50 Q37 50 40.5 44"
        stroke="url(#jexi-j)"
        strokeWidth="5.5"
        strokeLinecap="round"
        fill="none"
      />
      <path
        d="M34 40 L41 33 L46 37 L54 24"
        stroke="#FFB88C"
        strokeWidth="3.4"
        strokeLinecap="round"
        strokeLinejoin="round"
        fill="none"
      />
      <circle cx="54" cy="24" r="3.4" fill="#FF6B5E" />
      <defs>
        <linearGradient id="jexi-tile" x1="0" y1="0" x2="64" y2="64">
          <stop stopColor="#1a1712" />
          <stop offset="1" stopColor="#12100c" />
        </linearGradient>
        <linearGradient id="jexi-j" x1="18" y1="14" x2="41" y2="50">
          <stop stopColor="#FF7A3D" />
          <stop offset="1" stopColor="#FF6B5E" />
        </linearGradient>
      </defs>
    </svg>
  );
}

export function Wordmark({ compact = false }: { compact?: boolean }) {
  return (
    <span className="inline-flex items-baseline gap-[7px] select-none">
      <span className="display text-[20px] leading-none tracking-tight" style={{ color: "var(--ink)" }}>
        JEXI
      </span>
      {!compact && (
        <span className="label" style={{ letterSpacing: "0.22em", color: "var(--ink-3)" }}>
          MARKET
        </span>
      )}
    </span>
  );
}

/**
 * The JEXI Core — the product's identity object.
 * A layered system of warm metal rings, slowly rotating at different speeds,
 * with an orbiting spark. Pure SVG/CSS; pauses under prefers-reduced-motion.
 */
export function CoreOrb({ size = 420 }: { size?: number }) {
  return (
    <div
      className="relative select-none"
      style={{ width: size, height: size }}
      role="img"
      aria-label="The JEXI Core"
    >
      {/* warm halo */}
      <div
        className="absolute inset-0 rounded-full"
        style={{
          background:
            "radial-gradient(closest-side, color-mix(in srgb, var(--ember) 16%, transparent), transparent 72%)",
        }}
      />
      <svg viewBox="0 0 400 400" width={size} height={size} style={{ position: "relative" }}>
        <defs>
          <linearGradient id="core-ring-a" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="#FF7A3D" />
            <stop offset="0.55" stopColor="#8a4a2c" />
            <stop offset="1" stopColor="#241f19" />
          </linearGradient>
          <linearGradient id="core-ring-b" x1="1" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="#FFB88C" />
            <stop offset="0.5" stopColor="#7a5638" />
            <stop offset="1" stopColor="#241f19" />
          </linearGradient>
          <linearGradient id="core-ring-c" x1="0" y1="1" x2="1" y2="0">
            <stop offset="0" stopColor="#FF6B5E" stopOpacity="0.9" />
            <stop offset="1" stopColor="#2c241c" stopOpacity="0.2" />
          </linearGradient>
          <radialGradient id="core-center" cx="0.38" cy="0.32" r="0.9">
            <stop offset="0" stopColor="#3a2f22" />
            <stop offset="0.6" stopColor="#1c1813" />
            <stop offset="1" stopColor="#12100c" />
          </radialGradient>
        </defs>

        {/* center sphere */}
        <circle cx="200" cy="200" r="118" fill="url(#core-center)" stroke="#35291d" strokeWidth="1.5" />

        {/* latitude arcs */}
        <g stroke="#4a3a28" strokeWidth="1" fill="none" opacity="0.75">
          <ellipse cx="200" cy="200" rx="118" ry="44" />
          <ellipse cx="200" cy="200" rx="118" ry="86" opacity="0.55" />
          <ellipse cx="200" cy="200" rx="86" ry="118" opacity="0.35" />
        </g>

        {/* rotating outer rings */}
        <g style={{ transformOrigin: "200px 200px", animation: "jexi-spin-slow 26s linear infinite" }}>
          <circle cx="200" cy="200" r="168" stroke="url(#core-ring-a)" strokeWidth="10" fill="none"
            strokeDasharray="620 160" strokeLinecap="round" opacity="0.9" />
        </g>
        <g style={{ transformOrigin: "200px 200px", animation: "jexi-spin-slow 40s linear infinite reverse" }}>
          <circle cx="200" cy="200" r="146" stroke="url(#core-ring-b)" strokeWidth="4" fill="none"
            strokeDasharray="120 500" strokeLinecap="round" opacity="0.85" />
        </g>
        <g style={{ transformOrigin: "200px 200px", animation: "jexi-spin-slow 60s linear infinite" }}>
          <circle cx="200" cy="200" r="186" stroke="url(#core-ring-c)" strokeWidth="1.6" fill="none"
            strokeDasharray="300 900" opacity="0.7" />
        </g>

        {/* orbiting spark */}
        <g style={{ transformOrigin: "200px 200px", animation: "jexi-spin-slow 12s linear infinite" }}>
          <circle cx="200" cy="14" r="5" fill="#FFB88C">
            <animate attributeName="opacity" values="1;0.4;1" dur="2.4s" repeatCount="indefinite" />
          </circle>
        </g>

        {/* inner J monogram — the identity inside the identity */}
        <path
          d="M172 158 L172 226 Q172 258 199 258 Q221 258 231 241"
          stroke="url(#jexi-j)"
          strokeWidth="10"
          strokeLinecap="round"
          fill="none"
          opacity="0.95"
        />
        <path d="M214 236 L232 214 L246 224 L266 196" stroke="#FFB88C" strokeWidth="4.5"
          strokeLinecap="round" strokeLinejoin="round" fill="none" />
        <circle cx="266" cy="196" r="5" fill="#FF6B5E" />
      </svg>
    </div>
  );
}
