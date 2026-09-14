import React, { useState } from 'react';
import { View, Text, StyleSheet, Dimensions } from 'react-native';
import { useRouter } from 'expo-router';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { C } from '../lib/theme';
import { Btn, Sub } from '../components/ui';

const SLIDES: Array<{ emoji: string; title: string; body: string }> = [
  {
    emoji: '🔑',
    title: 'Connect two keys',
    body: 'Key 1: your AI model key (Gemini or any other). Key 2: your trading account key (Alpaca, Binance, Pocket Option, MT5 and more). You put them inside the app — never in GitHub, never in code.',
  },
  {
    emoji: '👾',
    title: 'Jexi trades for you',
    body: 'It checks your account, plans the day, and only buys when the time is right. Every trade has a safety line so a bad day can never hurt your money badly.',
  },
  {
    emoji: '👀',
    title: 'Watch it work live',
    body: 'Balance, every trade, every dollar of profit — all live in this app. And Jexi talks like a human: “I bought 2 shares of Apple. Here is why.”',
  },
];

export default function Onboarding() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const [i, setI] = useState(0);
  const slide = SLIDES[i];

  return (
    <View style={[s.fill, { paddingTop: insets.top + 12, paddingBottom: insets.bottom + 24 }]}>
      <View style={s.dotsRow}>
        {SLIDES.map((_, d) => (
          <View key={d} style={[s.dot, d === i && s.dotOn]} />
        ))}
      </View>

      <View style={s.body}>
        <Text style={s.emoji}>{slide.emoji}</Text>
        <Text style={s.title}>{slide.title}</Text>
        <Text style={s.text}>{slide.body}</Text>
      </View>

      <View style={s.foot}>
        <Sub>Step {i + 1} of {SLIDES.length}</Sub>
        <View style={s.footBtns}>
          {i > 0 && <Btn tone="ghost" label="Back" small onPress={() => setI(i - 1)} />}
          <Btn
            label={i === SLIDES.length - 1 ? 'Continue' : 'Next'}
            onPress={() => (i === SLIDES.length - 1 ? router.push('/signup') : setI(i + 1))}
          />
        </View>
      </View>
    </View>
  );
}

const W = Dimensions.get('window').width;

const s = StyleSheet.create({
  fill: { flex: 1, backgroundColor: C.bg, paddingHorizontal: 24 },
  dotsRow: { flexDirection: 'row', gap: 8, alignSelf: 'center', marginTop: 8 },
  dot: { width: 8, height: 8, borderRadius: 4, backgroundColor: C.border },
  dotOn: { backgroundColor: C.brand, width: 22 },
  body: { flex: 1, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 8, maxWidth: W },
  emoji: { fontSize: 64, marginBottom: 18 },
  title: { color: C.text, fontSize: 30, fontWeight: '900', textAlign: 'center' },
  text: { color: C.sub, fontSize: 16, lineHeight: 25, textAlign: 'center', marginTop: 14 },
  foot: { gap: 14 },
  footBtns: { flexDirection: 'row', gap: 10, alignItems: 'center', justifyContent: 'flex-end' },
});
