import React from 'react';
import { View, Text, StyleSheet, ScrollView, TouchableOpacity } from 'react-native';
import { useRouter } from 'expo-router';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useJexi, equityOf } from '../../lib/store';
import { C } from '../../lib/theme';
import { money, pct } from '../../lib/format';
import { Card, LiveDot, Pill, Row, SectionTitle, Sub, Btn, Orb } from '../../components/ui';
import { AreaChart } from '../../components/charts';

function greeting() {
  const h = new Date().getHours();
  if (h < 12) return 'Good morning';
  if (h < 18) return 'Good afternoon';
  return 'Good evening';
}

export default function Home() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const { profile, cash, positions, equityHistory, paused, killed, dayStartEquity, tick, trades } = useJexi();

  const equity = equityOf({ cash, positions });
  const dayPnl = equity - dayStartEquity;
  const dayPct = dayStartEquity ? (dayPnl / dayStartEquity) * 100 : 0;
  const up = dayPnl >= 0;
  const live = !killed && !paused;

  return (
    <ScrollView
      style={s.fill}
      contentContainerStyle={[s.wrap, { paddingTop: insets.top + 14, paddingBottom: 24 }]}
    >
      <Row style={s.top}>
        <View style={s.topLeft}>
          <Text style={s.greet}>{greeting()}{profile ? `, ${profile.name.split(' ')[0]}` : ''}</Text>
          <Row style={{ gap: 6, marginTop: 3 }}>
            <LiveDot tone={live ? C.green : C.amber} />
            <Text style={[s.liveText, { color: live ? C.green : C.amber }]}>
              {killed ? 'Stopped' : paused ? 'Paused — watching only' : 'Live — Jexi is working'}
            </Text>
          </Row>
        </View>
        <Orb size={38} />
      </Row>

      <Card style={s.balanceCard}>
        <Sub>Total balance (cash + investments)</Sub>
        <Text style={s.balance} adjustsFontSizeToFit numberOfLines={1}>
          {money(equity)}
        </Text>
        <Row style={{ gap: 8, marginTop: 8 }}>
          <Pill tone={up ? 'green' : 'red'} label={`${money(dayPnl, true)} today`} />
          <Pill tone={up ? 'green' : 'red'} label={pct(dayPct)} />
          <Pill tone="sub" label={`Cash ${money(cash)}`} />
        </Row>
        <View style={s.chartWrap} key={tick}>
          <AreaChart data={equityHistory.length > 1 ? equityHistory : [1, 1]} />
        </View>
        <Sub style={s.chartNote}>Last {equityHistory.length} live updates · updates every few seconds</Sub>
      </Card>

      <SectionTitle right={<TouchableOpacity onPress={() => router.push('/(tabs)/trades')}><Sub style={s.link}>All trades</Sub></TouchableOpacity>}>
        Open positions ({positions.length})
      </SectionTitle>
      {positions.length === 0 && (
        <Card>
          <Sub>No open positions right now. Jexi only buys when a safe moment appears — patience is part of the plan.</Sub>
        </Card>
      )}
      {positions.map((p) => {
        const pnl = (p.price - p.avg) * p.shares;
        const pPct = ((p.price - p.avg) / p.avg) * 100;
        const g = pnl >= 0;
        return (
          <Card key={p.id} style={s.pos}>
            <View style={s.posLeft}>
              <Text style={s.sym}>{p.sym}</Text>
              <Sub>{p.name} · {p.shares} share{p.shares > 1 ? 's' : ''}</Sub>
            </View>
            <View style={s.posRight}>
              <Text style={s.posValue}>{money(p.shares * p.price)}</Text>
              <Text style={[s.posPnl, { color: g ? C.green : C.red }]}>
                {money(pnl, true)} · {pct(pPct)}
              </Text>
            </View>
          </Card>
        );
      })}

      <SectionTitle>Quick actions</SectionTitle>
      <View style={s.actions}>
        <TouchableOpacity style={s.action} activeOpacity={0.8} onPress={() => router.push('/withdraw')}>
          <Text style={s.actionIcon}>💸</Text>
          <Text style={s.actionText}>Withdraw</Text>
        </TouchableOpacity>
        <TouchableOpacity style={s.action} activeOpacity={0.8} onPress={() => router.push('/(tabs)/profits')}>
          <Text style={s.actionIcon}>📊</Text>
          <Text style={s.actionText}>My profit</Text>
        </TouchableOpacity>
        <TouchableOpacity style={s.action} activeOpacity={0.8} onPress={() => router.push('/(tabs)/jexi')}>
          <Text style={s.actionIcon}>{live ? '⏸️' : '▶️'}</Text>
          <Text style={s.actionText}>{live ? 'Pause Jexi' : 'Resume'}</Text>
        </TouchableOpacity>
        <TouchableOpacity style={s.action} activeOpacity={0.8} onPress={() => router.push('/(tabs)/jexi')}>
          <Text style={s.actionIcon}>💬</Text>
          <Text style={s.actionText}>Ask Jexi</Text>
        </TouchableOpacity>
      </View>

      <Card style={s.aiNote}>
        <Row style={{ gap: 10 }}>
          <Orb size={30} />
          <View style={{ flex: 1 }}>
            <Text style={s.aiTitle}>
              {killed ? 'Jexi is fully stopped' : paused ? 'Jexi is paused' : `Jexi made ${trades.filter((t) => t.side === 'SELL').length} exits so far — all rules respected`}
            </Text>
            <Sub>{killed ? 'Press resume in Settings when you want it back.' : 'Tap “Ask Jexi” to read what it did and why, in plain English.'}</Sub>
          </View>
        </Row>
      </Card>
    </ScrollView>
  );
}

const s = StyleSheet.create({
  fill: { flex: 1, backgroundColor: C.bg },
  wrap: { paddingHorizontal: 20, gap: 14 },
  top: { justifyContent: 'space-between' },
  topLeft: {},
  greet: { color: C.text, fontSize: 22, fontWeight: '900' },
  liveText: { fontSize: 12.5, fontWeight: '700' },
  balanceCard: { gap: 4 },
  balance: { color: C.text, fontSize: 38, fontWeight: '900', marginTop: 2 },
  chartWrap: { marginTop: 12 },
  chartNote: { marginTop: 6, fontSize: 11.5 },
  link: { color: C.brand, fontWeight: '700' },
  pos: { paddingVertical: 14, marginTop: -6 },
  posLeft: { flex: 1 },
  sym: { color: C.text, fontSize: 16, fontWeight: '800' },
  posRight: { alignItems: 'flex-end' },
  posValue: { color: C.text, fontSize: 15, fontWeight: '800' },
  posPnl: { fontSize: 13, fontWeight: '700', marginTop: 2 },
  actions: { flexDirection: 'row', gap: 10, marginTop: -6 },
  action: {
    flex: 1,
    backgroundColor: C.card,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: C.border,
    paddingVertical: 14,
    alignItems: 'center',
    gap: 6,
  },
  actionIcon: { fontSize: 20 },
  actionText: { color: C.text, fontSize: 12, fontWeight: '700' },
  aiNote: { marginBottom: 8 },
  aiTitle: { color: C.text, fontSize: 14, fontWeight: '800' },
});
