import React from 'react';
import { StyleProp, Text, TextStyle, TouchableOpacity, View, ViewStyle, StyleSheet } from 'react-native';
import { C, R } from '../lib/theme';

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
  const bg =
    tone === 'brand' ? C.brand : tone === 'danger' ? C.red : tone === 'green' ? C.green : 'transparent';
  const fg = tone === 'ghost' ? C.text : tone === 'brand' ? '#06251C' : '#FFFFFF';
  return (
    <TouchableOpacity
      onPress={onPress}
      disabled={disabled}
      activeOpacity={0.8}
      style={[
        s.btn,
        small && s.btnSmall,
        { backgroundColor: bg },
        tone === 'ghost' && { borderWidth: 1, borderColor: C.border },
        disabled && { opacity: 0.4 },
        style,
      ]}
    >
      <Text style={[s.btnText, small && s.btnTextSmall, { color: disabled ? C.sub : fg }]}>{label}</Text>
    </TouchableOpacity>
  );
}

export function Orb({ size = 40 }: { size?: number }) {
  return (
    <View style={[s.orb, { width: size, height: size, borderRadius: size / 2 }]}>
      <Text style={[s.orbText, { fontSize: size * 0.42 }]}>J</Text>
    </View>
  );
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
  pillText: { fontSize: 12, fontWeight: '700' },
  liveWrap: { width: 12, height: 12, alignItems: 'center', justifyContent: 'center' },
  liveDot: { width: 7, height: 7, borderRadius: 4 },
  liveHalo: { position: 'absolute', width: 12, height: 12, borderRadius: 6, borderWidth: 1.5, opacity: 0.5 },
  btn: { borderRadius: 14, paddingVertical: 15, alignItems: 'center', justifyContent: 'center' },
  btnSmall: { paddingVertical: 10, paddingHorizontal: 14, borderRadius: 12, alignSelf: 'flex-start' },
  btnText: { fontSize: 16, fontWeight: '800' },
  btnTextSmall: { fontSize: 13 },
  orb: {
    backgroundColor: C.brand,
    alignItems: 'center',
    justifyContent: 'center',
    shadowColor: C.brand,
    shadowOpacity: 0.5,
    shadowRadius: 12,
    shadowOffset: { width: 0, height: 0 },
  },
  orbText: { color: '#06251C', fontWeight: '900' },
  rowBetween: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  sectionTitle: { color: C.text, fontSize: 17, fontWeight: '900' },
  row: { flexDirection: 'row', alignItems: 'center' },
  sub: { color: C.sub, fontSize: 13 },
});
