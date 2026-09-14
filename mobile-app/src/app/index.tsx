import React from 'react';
import { View, Text, StyleSheet, ScrollView, TouchableOpacity } from 'react-native';
import { useRouter } from 'expo-router';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useJexi } from '../lib/store';
import { C } from '../lib/theme';
import { Btn, Orb, Sub } from '../components/ui';

export default function Welcome() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { onboarded, booted } = useJexi();

  const enter = () => {
    if (onboarded) router.replace('/home');
    else router.push('/onboarding');
  };

  if (!booted) return <View style={s.fill} />;

  return (
    <ScrollView
      style={s.fill}
      contentContainerStyle={[s.wrap, { paddingTop: insets.top + 24, paddingBottom: insets.bottom + 24 }]}
    >
      <View style={s.hero}>
        <Orb size={84} />
        <Text style={s.title}>Meet Jexi</Text>
        <Text style={s.subtitle}>Your trading helper. It watches the market, trades carefully, and explains everything in simple words.</Text>
      </View>

      <View style={s.points}>
        {[
          ['🔐', 'Your keys stay yours', 'Put your two keys in the app. They are saved only on your device — never on GitHub.'],
          ['📈', 'See everything live', 'Balance, trades and profit update in real time. No spreadsheets.'],
          ['💸', 'Take money out anytime', 'Withdraw straight from the app in a few taps.'],
          ['🛑', 'You are the boss', 'Pause or stop Jexi with one button. It obeys instantly.'],
        ].map(([icon, t, d]) => (
          <View key={t} style={s.point}>
            <Text style={s.pointIcon}>{icon}</Text>
            <View style={s.pointBody}>
              <Text style={s.pointTitle}>{t}</Text>
              <Text style={s.pointDesc}>{d}</Text>
            </View>
          </View>
        ))}
      </View>

      <View style={s.spacer} />
      <Btn label={onboarded ? 'Open my app' : 'Get started'} onPress={enter} />
      <TouchableOpacity onPress={() => router.replace('/home')}>
        <Sub style={s.demoLink}>Look around in demo mode first</Sub>
      </TouchableOpacity>
      <Sub style={s.foot}>Demo preview · demo money only · nothing is pushed to GitHub</Sub>
    </ScrollView>
  );
}

const s = StyleSheet.create({
  fill: { flex: 1, backgroundColor: C.bg },
  wrap: { paddingHorizontal: 24, flexGrow: 1 },
  hero: { alignItems: 'center', marginTop: 40 },
  title: { color: C.text, fontSize: 34, fontWeight: '900', marginTop: 20 },
  subtitle: { color: C.sub, fontSize: 15, textAlign: 'center', marginTop: 10, lineHeight: 22 },
  points: { marginTop: 34, gap: 14 },
  point: { flexDirection: 'row', gap: 14, backgroundColor: C.card, borderRadius: 16, borderWidth: 1, borderColor: C.border, padding: 14 },
  pointIcon: { fontSize: 24 },
  pointBody: { flex: 1 },
  pointTitle: { color: C.text, fontSize: 15, fontWeight: '800' },
  pointDesc: { color: C.sub, fontSize: 13, marginTop: 3, lineHeight: 19 },
  spacer: { flex: 1, minHeight: 24 },
  demoLink: { textAlign: 'center', marginTop: 16, color: C.brand, fontWeight: '700' },
  foot: { textAlign: 'center', marginTop: 10, fontSize: 11, color: C.faint },
});
