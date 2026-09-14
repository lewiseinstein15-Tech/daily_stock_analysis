import React from 'react';
import Svg, { Path, Rect, Defs, LinearGradient, Stop, Circle } from 'react-native-svg';
import { C } from '../lib/theme';

export function AreaChart({ data, height = 150 }: { data: number[]; height?: number }) {
  const W = 320;
  const H = height;
  if (data.length < 2) return null;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const span = max - min || 1;
  const pad = 8;
  const pts = data.map((v, i) => {
    const x = (i / (data.length - 1)) * W;
    const y = pad + (1 - (v - min) / span) * (H - pad * 2);
    return [x, y] as const;
  });
  const line = pts.map(([x, y], i) => `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`).join(' ');
  const fill = `${line} L${W},${H} L0,${H} Z`;
  const last = pts[pts.length - 1];
  const up = data[data.length - 1] >= data[0];
  const color = up ? C.green : C.red;
  return (
    <Svg width="100%" height={H} viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none">
      <Defs>
        <LinearGradient id="jexiFill" x1="0" y1="0" x2="0" y2="1">
          <Stop offset="0" stopColor={color} stopOpacity="0.28" />
          <Stop offset="1" stopColor={color} stopOpacity="0" />
        </LinearGradient>
      </Defs>
      <Path d={fill} fill="url(#jexiFill)" />
      <Path d={line} fill="none" stroke={color} strokeWidth={2.5} strokeLinejoin="round" strokeLinecap="round" />
      <Circle cx={last[0]} cy={last[1]} r={4} fill={color} />
      <Circle cx={last[0]} cy={last[1]} r={8} fill={color} opacity={0.25} />
    </Svg>
  );
}

export function Bars({ data }: { data: number[] }) {
  const W = 320;
  const H = 140;
  const max = Math.max(...data.map((d) => Math.abs(d))) || 1;
  const zero = H / 2;
  const gap = W / data.length;
  const bw = gap * 0.55;
  return (
    <Svg width="100%" height={H} viewBox={`0 0 ${W} ${H}`}>
      <Rect x={0} y={zero - 0.5} width={W} height={1} fill={C.border} />
      {data.map((v, i) => {
        const h = (Math.abs(v) / max) * (H / 2 - 14);
        const x = i * gap + (gap - bw) / 2;
        const y = v >= 0 ? zero - h : zero;
        return (
          <Rect
            key={i}
            x={x}
            y={y}
            width={bw}
            height={Math.max(h, 3)}
            rx={4}
            fill={v >= 0 ? C.green : C.red}
            opacity={0.9}
          />
        );
      })}
    </Svg>
  );
}
