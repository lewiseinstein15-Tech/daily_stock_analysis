import React, { useMemo, useState } from 'react';
import { View, Text, StyleSheet, ScrollView, TouchableOpacity } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useJexi, Trade } from '../../lib/store';
import { C } from '../../lib/theme';
import { money, ago } from '../../lib/format';
import { Card, Pill, Row, SectionTitle, Sub } from '../../components/ui';

const FILTERS = ['All', 'Bought', 'Sold'] as const;

export default function Trades() {
  const insets = useSafeAreaInsets();
  const { trades } = useJexi();
  const [filter, setFilter] = useState<(typeof FILTERS)[number]>('All');
  const [open, setOpen] = useState<Trade | null>(null);

  const list = useMemo(() => {
    if (filter === 'Bought') return trades.filter((t) => t.side === 'BUY');
    if (filter === 'Sold') return trades.filter((t) => t.side === 'SELL');
    return trades;
  }, [trades, filter]);

  if (open) {
    const g = (open.pnl ?? 0) >= 0;
    return (
      <ScrollView style={s.fill} contentContainerStyle={[s.wrap, { paddingTop: insets.top + 14 }]}>
        <TouchableOpacity onPress={() => setOpen(null)}>
          <Text style={s.back}>← Back to all trades</Text>
        </TouchableOpacity>
        <Card style={{ marginTop: 14 }}>
          <Row style={{ justifyContent: 'space-between' }}>
            <View>
              <Text style={s.bigSym}>{open.sym}</Text>
              <Sub>{open.name}</Sub>
            </View>
            <Pill tone={open.side === 'BUY' ? 'brand' : g ? 'green' : 'red'} label={open.side === 'BUY' ? 'BOUGHT' : 'SOLD'} />
          </Row>
          <View style={s.detailGrid}>
            {[
              ['Shares', `${open.shares}`],
              ['Price', money(open.price)],
              ['Total', money(open.value)],
              ['Profit / loss', open.pnl == null ? '— not sold yet' : money(open.pnl, true)],
              ['When', ago(open.ts)],
            ].map(([k, v]) => (
              <View key={k} style={s.detailItem}>
                <Sub>{k}</Sub>
                <Text style={s.detailVal}>{v}</Text>
              </View>
            ))}
          </View>
        </Card>
        <SectionTitle>Why Jexi did this</SectionTitle>
        <Card>
          <Text style={s.reason}>{open.reason}</Text>
        </Card>
        <Sub style={s.footNote}>Every trade is explained like this — no confusing trading words.</Sub>
      </ScrollView>
    );
  }

  return (
    <ScrollView style={s.fill} contentContainerStyle={[s.wrap, { paddingTop: insets.top + 14 }]}>
      <Text style={s.title}>Trades</Text>
      <Sub style={s.lead}>Every buy and sell Jexi made with your account. Tap one to see the full story.</Sub>

      <Row style={{ gap: 8, marginTop: 4 }}>
        {FILTERS.map((f) => (
          <TouchableOpacity key={f} onPress={() => setFilter(f)} style={[s.chip, filter === f && s.chipOn]}>
            <Text style={[s.chipText, filter === f && s.chipTextOn]}>{f}</Text>
          </TouchableOpacity>
        ))}
      </Row>

      {list.length === 0 && (
        <Card><Sub>Nothing here yet.</Sub></Card>
      )}
      {list.map((t) => {
        const g = (t.pnl ?? 0) >= 0;
        return (
          <TouchableOpacity key={t.id} activeOpacity={0.8} onPress={() => setOpen(t)}>
            <Card style={s.trade}>
              <View style={[s.sideBadge, { backgroundColor: t.side === 'BUY' ? C.brandSoft : g ? C.greenSoft : C.redSoft }]}>
                <Text style={[s.sideText, { color: t.side === 'BUY' ? C.brand : g ? C.green : C.red }]}>{t.side}</Text>
              </View>
              <View style={s.tradeMid}>
                <Text style={s.tradeSym}>{t.sym} <Sub>· {t.shares} sh @ {money(t.price)}</Sub></Text>
                <Sub>{ago(t.ts)}</Sub>
              </View>
              <View style={s.tradeRight}>
                <Text style={s.tradeVal}>{money(t.value)}</Text>
                {t.pnl != null && (
                  <Text style={{ color: g ? C.green : C.red, fontWeight: '800', fontSize: 13 }}>{money(t.pnl, true)}</Text>
                )}
              </View>
            </Card>
          </TouchableOpacity>
        );
      })}
    </ScrollView>
  );
}

const s = StyleSheet.create({
  fill: { flex: 1, backgroundColor: C.bg },
  wrap: { paddingHorizontal: 20, paddingBottom: 24, gap: 12 },
  title: { color: C.text, fontSize: 28, fontWeight: '900' },
  lead: { lineHeight: 19, marginTop: -6 },
  back: { color: C.brand, fontWeight: '800', fontSize: 15 },
  chip: { paddingHorizontal: 14, paddingVertical: 7, borderRadius: 999, borderWidth: 1, borderColor: C.border },
  chipOn: { borderColor: C.brand, backgroundColor: C.brandSoft },
  chipText: { color: C.sub, fontWeight: '700', fontSize: 13 },
  chipTextOn: { color: C.brand },
  trade: { paddingVertical: 13, flexDirection: 'row', alignItems: 'center', gap: 12, marginTop: -4 },
  sideBadge: { paddingHorizontal: 9, paddingVertical: 5, borderRadius: 8 },
  sideText: { fontSize: 11.5, fontWeight: '900' },
  tradeMid: { flex: 1 },
  tradeSym: { color: C.text, fontWeight: '800', fontSize: 15 },
  tradeRight: { alignItems: 'flex-end' },
  tradeVal: { color: C.text, fontWeight: '800', fontSize: 14.5 },
  bigSym: { color: C.text, fontSize: 26, fontWeight: '900' },
  detailGrid: { flexDirection: 'row', flexWrap: 'wrap', marginTop: 16, gap: 14 },
  detailItem: { width: '47%' },
  detailVal: { color: C.text, fontWeight: '800', fontSize: 15, marginTop: 2 },
  reason: { color: C.text, fontSize: 15, lineHeight: 23 },
  footNote: { color: C.faint, textAlign: 'center', marginBottom: 8 },
});
