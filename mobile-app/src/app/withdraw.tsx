import React, { useState } from 'react';
import { View, Text, TextInput, StyleSheet, ScrollView, TouchableOpacity } from 'react-native';
import { useRouter } from 'expo-router';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useJexi, equityOf } from '../lib/store';
import { C } from '../lib/theme';
import { money, ago } from '../lib/format';
import { Btn, Card, Pill, Row, Sub } from '../components/ui';

const METHODS = [
  ['🏦', 'Bank transfer', 'Arrives in 1–2 days', 'Account ending ••88'],
  ['📈', 'Broker payout', 'Arrives same day', 'Same account Jexi trades in'],
  ['🪙', 'Crypto (USDC)', 'Arrives in minutes', 'Wallet 0x71…3a9f'],
] as const;

export default function Withdraw() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { cash, positions, withdrawals, requestWithdrawal } = useJexi();
  const [step, setStep] = useState(1);
  const [amount, setAmount] = useState('');
  const [method, setMethod] = useState<(typeof METHODS)[number][1] | null>(null);

  const available = cash; // only settled cash can leave the account
  const num = parseFloat(amount.replace(/[^0-9.]/g, ''));
  const okAmount = !isNaN(num) && num >= 20 && num <= available;
  const tooBig = !isNaN(num) && num > available;

  const submit = () => {
    if (!method) return;
    requestWithdrawal(+num.toFixed(2), method, METHODS.find((m) => m[1] === method)?.[3] ?? '');
    setStep(4);
  };

  return (
    <ScrollView style={s.fill} contentContainerStyle={[s.wrap, { paddingTop: insets.top + 14 }]}>
      <TouchableOpacity onPress={() => (step === 4 || step === 1 ? router.back() : setStep((step - 1) as 1 | 2 | 3))}>
        <Text style={s.back}>← {step === 4 || step === 1 ? 'Back to app' : 'Back'}</Text>
      </TouchableOpacity>
      <View style={s.stepsRow}>
        {[1, 2, 3, 4].map((n) => (
          <View key={n} style={[s.stepDot, n <= step && s.stepOn]} />
        ))}
      </View>

      {step === 1 && (
        <>
          <Text style={s.title}>How much?</Text>
          <Sub style={s.lead}>You can take out your cash anytime. Money inside open trades sells first — Jexi will ask before doing that.</Sub>
          <Card style={{ gap: 6 }}>
            <Sub>Available to withdraw</Sub>
            <Text style={s.avail}>{money(available)}</Text>
            <Sub>Open trades still hold {money(equityOf({ cash: 0, positions }))} — untouched.</Sub>
          </Card>
          <Text style={s.label}>Amount (min $20)</Text>
          <TextInput
            style={s.amountInput}
            placeholder="$0.00"
            placeholderTextColor={C.faint}
            keyboardType="decimal-pad"
            value={amount}
            onChangeText={setAmount}
          />
          {tooBig && <Text style={s.warn}>That is more than your available cash. Try a smaller amount.</Text>}
          <Row style={{ gap: 8 }}>
            {[0.25, 0.5, 1].map((f) => (
              <TouchableOpacity key={f} style={s.pct} onPress={() => setAmount((available * f).toFixed(2))}>
                <Text style={s.pctText}>{f === 1 ? 'Max' : `${f * 100}%`}</Text>
              </TouchableOpacity>
            ))}
          </Row>
          <Btn label="Continue" disabled={!okAmount} onPress={() => setStep(2)} />
        </>
      )}

      {step === 2 && (
        <>
          <Text style={s.title}>Where should it go?</Text>
          <Sub style={s.lead}>Pick where to send {money(num || 0)}.</Sub>
          {METHODS.map(([icon, name, when, dest]) => (
            <TouchableOpacity key={name} activeOpacity={0.8} onPress={() => setMethod(name)}>
              <Card style={[s.method, method === name ? s.methodOn : undefined]}>
                <Row style={{ gap: 12 }}>
                  <Text style={s.methodIcon}>{icon}</Text>
                  <View style={{ flex: 1 }}>
                    <Text style={s.methodName}>{name}</Text>
                    <Sub>{when}</Sub>
                    <Sub style={{ color: C.faint }}>{dest}</Sub>
                  </View>
                  {method === name && <Pill tone="brand" label="Pick" />}
                </Row>
              </Card>
            </TouchableOpacity>
          ))}
          <Btn label="Review withdrawal" disabled={!method} onPress={() => setStep(3)} />
        </>
      )}

      {step === 3 && (
        <>
          <Text style={s.title}>Check it</Text>
          <Sub style={s.lead}>One last look before your money moves.</Sub>
          <Card style={{ gap: 10 }}>
            {[
              ['You are taking out', money(num)],
              ['To', method ?? ''],
              ['Fee', '$0.00 — Jexi charges nothing for withdrawals'],
              ['Arrives', method === 'Crypto (USDC)' ? 'In minutes' : method === 'Broker payout' ? 'Same day' : 'In 1–2 days'],
              ['Cash left after', money(Math.max(available - num, 0))],
            ].map(([k, v]) => (
              <Row key={k} style={{ justifyContent: 'space-between' }}>
                <Sub>{k}</Sub>
                <Text style={s.reviewVal}>{v}</Text>
              </Row>
            ))}
          </Card>
          <Btn label={`Send ${money(num)}`} tone="green" onPress={submit} />
          <Sub style={s.demo}>Demo preview: no real money moves yet. Real withdrawals switch on with the live backend.</Sub>
        </>
      )}

      {step === 4 && (
        <>
          <View style={s.doneWrap}>
            <Text style={s.doneIcon}>✅</Text>
            <Text style={s.title}>Money is on the way</Text>
            <Sub style={s.lead}>
              I started your {money(num)} withdrawal to {method}. I will message you the moment it is sent —
              usually 1–2 days. You can keep using the app normally.
            </Sub>
          </View>
          <Btn label="Done" onPress={() => router.back()} />
        </>
      )}

      {withdrawals.length > 0 && step === 1 && (
        <>
          <Sub style={{ marginTop: 10, fontWeight: '800', color: C.text }}>Past withdrawals</Sub>
          {withdrawals.map((w) => (
            <Card key={w.id} style={{ paddingVertical: 13 }}>
              <Row style={{ justifyContent: 'space-between' }}>
                <View>
                  <Text style={s.wAmount}>{money(w.amount)}</Text>
                  <Sub>{w.method} · {ago(w.ts)}</Sub>
                </View>
                <Pill tone={w.status === 'Sent' ? 'green' : 'amber'} label={w.status === 'Sent' ? 'Sent ✓' : 'Processing…'} />
              </Row>
            </Card>
          ))}
        </>
      )}
    </ScrollView>
  );
}

const s = StyleSheet.create({
  fill: { flex: 1, backgroundColor: C.bg },
  wrap: { paddingHorizontal: 20, paddingBottom: 30, gap: 12 },
  back: { color: C.brand, fontWeight: '800', fontSize: 15 },
  stepsRow: { flexDirection: 'row', gap: 6 },
  stepDot: { flex: 1, height: 4, borderRadius: 2, backgroundColor: C.border },
  stepOn: { backgroundColor: C.brand },
  title: { color: C.text, fontSize: 27, fontWeight: '900', marginTop: 4 },
  lead: { lineHeight: 20, marginTop: -4 },
  avail: { color: C.text, fontSize: 30, fontWeight: '900' },
  label: { color: C.sub, fontSize: 13, fontWeight: '700', marginTop: 4 },
  amountInput: {
    backgroundColor: C.card,
    borderWidth: 1,
    borderColor: C.border,
    borderRadius: 16,
    paddingHorizontal: 18,
    paddingVertical: 16,
    color: C.text,
    fontSize: 26,
    fontWeight: '900',
  },
  warn: { color: C.red, fontSize: 13, fontWeight: '700' },
  pct: { paddingHorizontal: 16, paddingVertical: 8, borderRadius: 999, borderWidth: 1, borderColor: C.border, backgroundColor: C.card },
  pctText: { color: C.text, fontWeight: '800', fontSize: 13 },
  method: { paddingVertical: 14 },
  methodOn: { borderColor: C.brand, backgroundColor: C.card2 },
  methodIcon: { fontSize: 26 },
  methodName: { color: C.text, fontSize: 15.5, fontWeight: '800' },
  reviewVal: { color: C.text, fontWeight: '800', fontSize: 14, textAlign: 'right', flexShrink: 1 },
  demo: { color: C.faint, textAlign: 'center', lineHeight: 18 },
  doneWrap: { alignItems: 'center', gap: 8, marginTop: 30 },
  doneIcon: { fontSize: 56 },
  wAmount: { color: C.text, fontWeight: '900', fontSize: 16 },
});
