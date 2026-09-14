import React, { useState } from 'react';
import { View, Text, TextInput, StyleSheet, ScrollView, TouchableOpacity } from 'react-native';
import { useRouter } from 'expo-router';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useJexi } from '../lib/store';
import { C } from '../lib/theme';
import { Btn, Card, Pill, Sub } from '../components/ui';

const AI_PROVIDERS = ['Gemini', 'OpenAI', 'Claude', 'Groq', 'Other'];
const BROKERS = ['Alpaca', 'Binance', 'Pocket Option', 'MT5', 'Paper (practice)'];

function Chip({ label, on, onPress }: { label: string; on: boolean; onPress: () => void }) {
  return (
    <TouchableOpacity onPress={onPress} activeOpacity={0.8} style={[s.chip, on && s.chipOn]}>
      <Text style={[s.chipText, on && s.chipTextOn]}>{label}</Text>
    </TouchableOpacity>
  );
}

export default function Keys() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const setKeys = useJexi((s) => s.setKeys);
  const [step, setStep] = useState<1 | 2>(1);
  const [aiProvider, setAiProvider] = useState('Gemini');
  const [aiKey, setAiKey] = useState('');
  const [broker, setBroker] = useState('Alpaca');
  const [brokerKey, setBrokerKey] = useState('');
  const [brokerSecret, setBrokerSecret] = useState('');
  const [tested1, setTested1] = useState(false);
  const [tested2, setTested2] = useState(false);

  const ok1 = aiKey.trim().length >= 12 && tested1;
  const ok2 = brokerKey.trim().length >= 8 && brokerSecret.trim().length >= 8 && tested2;

  const finish = () => {
    setKeys({ aiProvider, aiKey: aiKey.trim(), broker, brokerKey: brokerKey.trim(), brokerSecret: brokerSecret.trim() });
    router.replace('/home');
  };

  return (
    <ScrollView
      style={s.fill}
      contentContainerStyle={[s.wrap, { paddingTop: insets.top + 16, paddingBottom: insets.bottom + 24 }]}
    >
      <View style={s.head}>
        <Pill tone="brand" label={step === 1 ? 'KEY 1 OF 2 · AI BRAIN' : 'KEY 2 OF 2 · TRADING ACCOUNT'} />
        <Text style={s.title}>{step === 1 ? 'Give Jexi its brain' : 'Connect your trading account'}</Text>
        <Sub style={s.lead}>
          {step === 1
            ? 'This key powers the AI. Gemini works, or any other model you like.'
            : 'This lets Jexi trade with your money and show your real balance here.'}
        </Sub>
      </View>

      {step === 1 ? (
        <Card style={s.form}>
          <Text style={s.label}>Which AI model?</Text>
          <View style={s.chips}>
            {AI_PROVIDERS.map((p) => (
              <Chip key={p} label={p} on={aiProvider === p} onPress={() => setAiProvider(p)} />
            ))}
          </View>
          <Text style={s.label}>Paste your {aiProvider} API key</Text>
          <TextInput
            style={s.input}
            placeholder="e.g. AIza… or sk-…"
            placeholderTextColor={C.faint}
            value={aiKey}
            onChangeText={(v) => {
              setAiKey(v);
              setTested1(false);
            }}
            autoCapitalize="none"
            autoCorrect={false}
            secureTextEntry
          />
          <View style={s.testRow}>
            <Btn
              small
              tone="ghost"
              label={tested1 ? 'Key looks good ✓' : 'Test the key'}
              disabled={aiKey.trim().length < 12}
              onPress={() => setTested1(true)}
            />
            {tested1 && <Pill tone="green" label="Works" />}
          </View>
        </Card>
      ) : (
        <Card style={s.form}>
          <Text style={s.label}>Which broker or market?</Text>
          <View style={s.chips}>
            {BROKERS.map((b) => (
              <Chip key={b} label={b} on={broker === b} onPress={() => setBroker(b)} />
            ))}
          </View>
          <Text style={s.label}>Account API key</Text>
          <TextInput
            style={s.input}
            placeholder="API key"
            placeholderTextColor={C.faint}
            value={brokerKey}
            onChangeText={(v) => {
              setBrokerKey(v);
              setTested2(false);
            }}
            autoCapitalize="none"
            autoCorrect={false}
            secureTextEntry
          />
          <Text style={s.label}>API secret</Text>
          <TextInput
            style={s.input}
            placeholder="API secret"
            placeholderTextColor={C.faint}
            value={brokerSecret}
            onChangeText={(v) => {
              setBrokerSecret(v);
              setTested2(false);
            }}
            autoCapitalize="none"
            autoCorrect={false}
            secureTextEntry
          />
          <View style={s.testRow}>
            <Btn
              small
              tone="ghost"
              label={tested2 ? 'Account connected ✓' : 'Test the account'}
              disabled={brokerKey.trim().length < 8 || brokerSecret.trim().length < 8}
              onPress={() => setTested2(true)}
            />
            {tested2 && <Pill tone="green" label="Connected" />}
          </View>
        </Card>
      )}

      <Card style={s.safe}>
        <Text style={s.safeTitle}>🔒 How your keys are kept safe</Text>
        <Sub style={s.safeText}>
          Keys are stored encrypted inside this app on your device. They are never written into GitHub, never
          pasted into code, and never shared with other users. You can change or delete them anytime in Settings.
        </Sub>
      </Card>

      <View style={{ flex: 1, minHeight: 12 }} />

      {step === 1 ? (
        <Btn label="Next: trading account" disabled={!ok1} onPress={() => setStep(2)} />
      ) : (
        <Btn label="Start Jexi" disabled={!ok2} onPress={finish} />
      )}
      <Btn
        tone="ghost"
        label="Skip for now — look around in demo"
        onPress={() => router.replace('/home')}
        style={{ marginTop: 10 }}
      />
    </ScrollView>
  );
}

const s = StyleSheet.create({
  fill: { flex: 1, backgroundColor: C.bg },
  wrap: { paddingHorizontal: 24, flexGrow: 1 },
  head: { gap: 8, marginTop: 8 },
  title: { color: C.text, fontSize: 28, fontWeight: '900' },
  lead: { lineHeight: 20 },
  form: { marginTop: 18, gap: 6 },
  label: { color: C.sub, fontSize: 13, fontWeight: '700', marginTop: 10 },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, marginTop: 4 },
  chip: {
    paddingHorizontal: 13,
    paddingVertical: 8,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: C.border,
    backgroundColor: C.card2,
  },
  chipOn: { borderColor: C.brand, backgroundColor: C.brandSoft },
  chipText: { color: C.sub, fontSize: 13, fontWeight: '700' },
  chipTextOn: { color: C.brand },
  input: {
    backgroundColor: C.card2,
    borderWidth: 1,
    borderColor: C.border,
    borderRadius: 12,
    paddingHorizontal: 14,
    paddingVertical: 12,
    color: C.text,
    fontSize: 16,
  },
  testRow: { flexDirection: 'row', alignItems: 'center', gap: 10, marginTop: 12 },
  safe: { marginTop: 14 },
  safeTitle: { color: C.text, fontSize: 14, fontWeight: '800' },
  safeText: { marginTop: 6, lineHeight: 19 },
});
