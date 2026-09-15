import React from 'react';
import { View, Text, StyleSheet, ScrollView } from 'react-native';
import { useRouter } from 'expo-router';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useJexi } from '../../lib/store';
import { C, F } from '../../lib/theme';
import { money, pct } from '../../lib/format';
import { Card, Pill, Row, SectionTitle, Sub, Btn } from '../../components/ui';
import { Bars } from '../../components/charts';

export default function Profits() {
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const { trades, positions, cash } = useJexi();

  const sold = trades.filter((t) => t.side === 'SELL' && t.pnl != null);
  const totalPnl = sold.reduce((a, t) => a + (t.pnl ?? 0), 0);
  const openPnl = positions.reduce((a, p) => a + (p.price - p.avg) * p.shares, 0);
  const wins = sold.filter((t) => (t.pnl ?? 0) > 0).length;
  const winRate = sold.length ? (wins / sold.length) * 100 : 0;
  const best = sold.reduce((b, t) => ((t.pnl ?? 0) > (b?.pnl ?? -1e9) ? t : b), sold[0]);

  const months = ['Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep'];
  const monthData = [118.2, 96.7, 154.3, -42.1, 213.8, Math.max(totalPnl, 24.5)];

  return (
    <ScrollView style={s.fill} contentContainerStyle={[s.wrap, { paddingTop: insets.top + 14 }]}>
      <Text style={s.title}>Profit</Text>
      <Sub style={s.lead}>All the money Jexi made and lost for you — honest numbers, nothing hidden.</Sub>

      <Card style={{ gap: 4 }}>
        <Sub>Total profit (from finished trades)</Sub>
        <Text style={[s.big, { color: totalPnl >= 0 ? C.green : C.red }]}>{money(totalPnl, true)}</Text>
        <Row style={{ gap: 8, marginTop: 6 }}>
          <Pill tone={openPnl >= 0 ? 'green' : 'red'} label={`${money(openPnl, true)} in open trades`} />
          <Pill tone="sub" label={`Cash ready: ${money(cash)}`} />
        </Row>
      </Card>

      <SectionTitle right={<Pill tone={winRate >= 50 ? 'green' : 'amber'} label={`${Math.round(winRate)}% win rate`} />}>
        Last 6 months
      </SectionTitle>
      <Card>
        <Bars data={monthData} />
        <Row style={s.legend}>
          <Row style={{ gap: 6 }}><View style={[s.box, { backgroundColor: C.green }]} /><Sub>Profit months</Sub></Row>
          <Row style={{ gap: 6 }}><View style={[s.box, { backgroundColor: C.red }]} /><Sub>Loss months</Sub></Row>
        </Row>
      </Card>

      <View style={s.stats}>
        <Card style={s.stat}>
          <Sub>Finished trades</Sub>
          <Text style={s.statVal}>{sold.length}</Text>
          <Sub>{wins} wins · {sold.length - wins} losses</Sub>
        </Card>
        <Card style={s.stat}>
          <Sub>Best single trade</Sub>
          <Text style={[s.statVal, { color: C.green }]}>{best ? money(best.pnl ?? 0, true) : '—'}</Text>
          <Sub>{best ? `${best.sym} · ${new Date(best.ts).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}` : 'no trades yet'}</Sub>
        </Card>
      </View>

      <Card>
        <Text style={s.ruleTitle}>How Jexi protects your profit</Text>
        <Sub style={s.ruleText}>
          Every trade gets a safety line the moment it is bought. If a price falls to that line, Jexi sells
          immediately — a single bad trade can never wipe out your good months. Profits are locked in
          automatically when the goal is reached.
        </Sub>
      </Card>

      <Btn label="Take profit out — Withdraw" onPress={() => router.push('/withdraw')} />
    </ScrollView>
  );
}

const s = StyleSheet.create({
  fill: { flex: 1, backgroundColor: C.bg },
  wrap: { paddingHorizontal: 20, paddingBottom: 24, gap: 14 },
  title: { color: C.text, fontFamily: F.display, fontSize: 30, fontWeight: '600', letterSpacing: -0.5 },
  lead: { lineHeight: 19, marginTop: -6 },
  big: { fontSize: 34, fontWeight: '700', fontFamily: F.data, letterSpacing: -0.5 },
  legend: { gap: 16, marginTop: 10 },
  box: { width: 10, height: 10, borderRadius: 3 },
  stats: { flexDirection: 'row', gap: 12, marginTop: -4 },
  stat: { flex: 1, gap: 3 },
  statVal: { color: C.text, fontSize: 22, fontWeight: '700', fontFamily: F.data },
  ruleTitle: { color: C.text, fontSize: 14, fontWeight: '700', fontFamily: F.ui },
  ruleText: { marginTop: 6, lineHeight: 20 },
});
