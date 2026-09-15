import React from 'react';
import {
  StyleProp,
  Text,
  TextStyle,
  TouchableOpacity,
  View,
  ViewStyle,
  StyleSheet,
} from 'react-native';
import Svg, { Rect, Path, Circle, Defs, LinearGradient as Grad, Stop } from 'react-native-svg';
import { C, F, R } from '../lib/theme';

/** The JEXI Market logo mark — exact port of the web's JexiMark SVG. */
export function JexiMark({ size = 34 }: { size?: number }) {
  return (
    <Svg width={size} height={size} viewBox="0 0 64 64" fill="none">
      <Defs>
        <Grad id="jexi-tile-m" x1="0" y1="0" x2="64" y2="64">
          <Stop offset="0" stopColor="#1a1712" />
          <Stop offset="1" stopColor="#12100c" />
        </Grad>
        <Grad id="jexi-j-m" x1="18" y1="14" x2="41" y2="50">
          <Stop offset="0" stopColor="#FF7A3D" />
          <Stop offset="1" stopColor="#FF6B5E" />
        </Grad>
      </Defs>
      <Rect width="64" height="64" rx="15" fill="url(#jexi-tile-m)" />
      <Rect x="0.5" y="0.5" width="63" height="63" rx="14.5" stroke="#3a3226" />
      <Path
        d="M18 14 L18 38 Q18 50 29 50 Q37 50 40.5 44"
        stroke="url(#jexi-j-m)"
        strokeWidth="5.5"
        strokeLinecap="round"
        fill="none"
      />
      <Path
        d="M34 40 L41 33 L46 37 L54 24"
        stroke="#FFB88C"
        strokeWidth="3.4"
        strokeLinecap="round"
        strokeLinejoin="round"
        fill="none"
      />
      <Circle cx="54" cy="24" r="3.4" fill="#FF6B5E" />
    </Svg>
  );
}

/** "JEXI MARKET" wordmark — serif JEXI + letter-spaced MARKET, as on the web. */
export function Wordmark({ compact = false, size = 20 }: { compact?: boolean; size?: number }) {
  return (
    <View style={{ flexDirection: 'row', alignItems: 'baseline', gap: 7 }}>
      <Text
        style={{
          fontFamily: F.display,
          fontSize: size,
          lineHeight: size + 2,
          letterSpacing: -0.3,
          fontWeight: '600',
          color: C.text,
        }}
      >
        JEXI
      </Text>
      {!compact && (
        <Text style={{ fontSize: 11, letterSpacing: 4.4, color: C.faint, fontWeight: '500' }}>
          MARKET
        </Text>
      )}
    </View>
  );
}

export function Card({ style, children }: { style?: StyleProp<ViewStyle>; children: React.ReactNode }) {
  return <View style={[s.card, style]}>{children}</View>;
}

export function Pill({
  tone = 'sub',
  label,
}: {
  tone?: 'green' | 'red' | 'sub' | 'brand' | 'amber';
  label: string;
}) {
  const map = {
    green: [C.greenSoft, C.green],
    red: [C.redSoft, C.red],
    brand: [C.brandSoft, C.brand],
    amber: [C.amberSoft, C.amber],
    sub: ['rgba(139,149,165,0.14)', C.sub],
  } as const;
  const [bg, fg] = map[tone];
  return (
    <View style={[s.pill, { backgroundColor: bg }]}>
      <Text style={[s.pillText, { color: fg }]}>{label}</Text>
    </View>
  );
}

/** Eyebrow label: "● LIVE PRICES · 10 MARKETS" style — dot, caps, hairline border. */
export function LivePill({
  dot = C.green,
  label,
  color = C.sub,
}: {
  dot?: string;
  label: string;
  color?: string;
}) {
  return (
    <View style={[s.livePill, { borderColor: C.border }]}>
      <View style={[s.livePillDot, { backgroundColor: dot }]} />
      <Text style={[s.livePillText, { color }]}>{label}</Text>
    </View>
  );
}

export function LiveDot({ tone = C.green }: { tone?: string }) {
  return (
    <View style={s.liveWrap}>
      <View style={[s.liveDot, { backgroundColor: tone }]} />
      <View style={[s.liveHalo, { borderColor: tone }]} />
    </View>
  );
}

export function Btn({
  label,
  onPress,
  tone = 'brand',
  disabled,
  style,
  small,
}: {
  label: string;
  onPress: () => void;
  tone?: 'brand' | 'ghost' | 'danger' | 'green';
  disabled?: boolean;
  style?: ViewStyle | ViewStyle[];
  small?: boolean;
}) {
  const isGhost = tone === 'ghost';
  const isBrand = tone === 'brand';
  const flatBg = tone === 'danger' ? C.red : tone === 'green' ? C.green : 'transparent';
  return (
    <TouchableOpacity
      onPress={onPress}
      disabled={disabled}
      activeOpacity={0.85}
      style={[s.btnOuter, disabled && { opacity: 0.4 }, style]}
    >
      {isBrand ? (
        // .btn-primary: linear-gradient(135deg, ember, coral) with dark ink text
        <View style={[s.btnFill, small && s.btnSmall]}>
          <Svg width="100%" height="100%" style={StyleSheet.absoluteFill}>
            <Defs>
              <Grad id="jexi-btn-m" x1="0" y1="0" x2="1" y2="1">
                <Stop offset="0" stopColor={C.brand} />
                <Stop offset="1" stopColor={C.coral} />
              </Grad>
            </Defs>
            <Rect width="100%" height="100%" rx={small ? 10 : 10} fill="url(#jexi-btn-m)" />
          </Svg>
          <Text style={[s.btnText, small && s.btnTextSmall, { color: '#180f08' }]}>{label}</Text>
        </View>
      ) : (
        <View
          style={[
            s.btnFill,
            small && s.btnSmall,
            !isGhost && { backgroundColor: flatBg },
            isGhost && { backgroundColor: C.card2, borderWidth: 1, borderColor: C.border },
          ]}
        >
          <Text style={[s.btnText, small && s.btnTextSmall, { color: isGhost ? C.text : '#FFFFFF' }]}>
            {label}
          </Text>
        </View>
      )}
    </TouchableOpacity>
  );
}

/** Brand avatar: solid ember circle with the user's initial (as in the header). */
export function Avatar({ initial, size = 34 }: { initial: string; size?: number }) {
  return (
    <View style={{ width: size, height: size, borderRadius: size / 2, overflow: 'hidden' }}>
      <Svg width={size} height={size}>
        <Defs>
          <Grad id="jexi-av-m" x1="0" y1="0" x2="1" y2="1">
            <Stop offset="0" stopColor={C.brand} />
            <Stop offset="1" stopColor={C.coral} />
          </Grad>
        </Defs>
        <Rect width={size} height={size} fill="url(#jexi-av-m)" />
      </Svg>
      <View style={StyleSheet.absoluteFill && { position: 'absolute', width: '100%', height: '100%', alignItems: 'center', justifyContent: 'center' }}>
        <Text style={{ color: '#180f08', fontWeight: '800', fontSize: size * 0.42, fontFamily: F.ui }}>
          {(initial || 'J').toUpperCase()}
        </Text>
      </View>
    </View>
  );
}

/** Kept for compatibility — now renders the real JEXI mark. */
export function Orb({ size = 40 }: { size?: number }) {
  return <JexiMark size={size} />;
}

export function SectionTitle({ children, right }: { children: React.ReactNode; right?: React.ReactNode }) {
  return (
    <View style={s.rowBetween}>
      <Text style={s.sectionTitle}>{children}</Text>
      {right}
    </View>
  );
}

export function Row({ children, style }: { children: React.ReactNode; style?: ViewStyle | ViewStyle[] }) {
  return <View style={[s.row, style]}>{children}</View>;
}

export function Sub({ children, style }: { children: React.ReactNode; style?: TextStyle | TextStyle[] }) {
  return <Text style={[s.sub, style]}>{children}</Text>;
}

const s = StyleSheet.create({
  card: {
    backgroundColor: C.card,
    borderRadius: R,
    borderWidth: 1,
    borderColor: C.border,
    padding: 16,
  },
  pill: { paddingHorizontal: 10, paddingVertical: 5, borderRadius: 999, alignSelf: 'flex-start' },
  pillText: { fontSize: 12, fontWeight: '600', fontFamily: F.ui },
  livePill: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    alignSelf: 'center',
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 14,
    paddingVertical: 7,
    backgroundColor: 'rgba(255,122,61,0.05)',
  },
  livePillDot: { width: 7, height: 7, borderRadius: 4 },
  livePillText: { fontSize: 11.5, letterSpacing: 2.2, fontWeight: '600', fontFamily: F.ui },
  liveWrap: { width: 12, height: 12, alignItems: 'center', justifyContent: 'center' },
  liveDot: { width: 7, height: 7, borderRadius: 4 },
  liveHalo: { position: 'absolute', width: 12, height: 12, borderRadius: 6, borderWidth: 1.5, opacity: 0.5 },
  btnOuter: { borderRadius: 10 },
  btnFill: {
    borderRadius: 10,
    minHeight: 46,
    paddingHorizontal: 18,
    alignItems: 'center',
    justifyContent: 'center',
    width: '100%',
  },
  btnSmall: { minHeight: 36, paddingHorizontal: 14, alignSelf: 'flex-start', borderRadius: 10 },
  btnText: { fontSize: 14.5, fontWeight: '650', fontFamily: F.ui, letterSpacing: 0.1 },
  btnTextSmall: { fontSize: 13 },
  sectionTitle: {
    color: C.text,
    fontFamily: F.display,
    fontSize: 18,
    fontWeight: '600',
    letterSpacing: -0.2,
  },
  row: { flexDirection: 'row', alignItems: 'center' },
  sub: { color: C.sub, fontSize: 13, fontFamily: F.ui },
});
