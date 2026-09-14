import React, { useEffect, useRef } from 'react';
import { View, Text, StyleSheet, ScrollView } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useJexi, FeedItem } from '../../lib/store';
import { C } from '../../lib/theme';
import { clock } from '../../lib/format';
import { Btn, Card, Orb, Pill, Row, Sub } from '../../components/ui';

const ICONS: Record<FeedItem['kind'], string> = {
  buy: '🛒',
  sell: '💰',
  info: '💡',
  warn: '⚠️',
  win: '🎉',
};

export default function JexiFeed() {
  const insets = useSafeAreaInsets();
  const { feed, paused, killed, setPaused, setKilled } = useJexi();
  const scrollRef = useRef<ScrollView>(null);
  const tickCount = feed.length;

  useEffect(() => {
    scrollRef.current?.scrollTo({ y: 0, animated: true });
  }, [tickCount]);

  const live = !paused && !killed;

  return (
    <View style={s.fill}>
      <ScrollView
        ref={scrollRef}
        style={s.fill}
        contentContainerStyle={[s.wrap, { paddingTop: insets.top + 14 }]}
      >
        <Text style={s.title}>Jexi</Text>
        <Sub style={s.lead}>What Jexi did and why — in plain English. No trading jargon, ever.</Sub>

        <Card style={s.statusCard}>
          <Row style={{ justifyContent: 'space-between' }}>
            <View style={{ gap: 4 }}>
              <Text style={s.statusTitle}>
                {killed ? 'Everything is stopped' : paused ? 'Paused — watching, not trading' : 'Trading for you'}
              </Text>
              <Sub>{killed ? 'Nothing will move until you resume.' : paused ? 'I will still message you if something important happens.' : 'Safety rules are on. You can pause me anytime.'}</Sub>
            </View>
            {live ? <Pill tone="green" label="LIVE" /> : <Pill tone="amber" label="PAUSED" />}
          </Row>
          <Row style={{ gap: 10, marginTop: 14 }}>
            {live ? (
              <Btn tone="ghost" label="⏸ Pause trading" onPress={() => setPaused(true)} style={{ flex: 1 }} />
            ) : (
              <Btn tone="green" label="▶ Resume trading" onPress={() => { setKilled(false); setPaused(false); }} style={{ flex: 1 }} />
            )}
            {!killed && (
              <Btn tone="danger" label="STOP everything" onPress={() => setKilled(true)} style={{ flex: 1 }} />
            )}
          </Row>
        </Card>

        {feed.map((f) => (
          <View key={f.id} style={s.msg}>
            <Orb size={30} />
            <View style={s.bubble}>
              <Row style={{ justifyContent: 'space-between' }}>
                <Text style={s.msgIcon}>{ICONS[f.kind]}</Text>
                <Sub style={s.msgTime}>{clock(f.ts)}</Sub>
              </Row>
              <Text style={s.msgText}>{f.text}</Text>
            </View>
          </View>
        ))}
        <Sub style={s.end}>That is everything so far. You will also get these as phone notifications in the real app.</Sub>
      </ScrollView>
    </View>
  );
}

const s = StyleSheet.create({
  fill: { flex: 1, backgroundColor: C.bg },
  wrap: { paddingHorizontal: 20, paddingBottom: 24, gap: 12 },
  title: { color: C.text, fontSize: 28, fontWeight: '900' },
  lead: { lineHeight: 19, marginTop: -6 },
  statusCard: { gap: 2 },
  statusTitle: { color: C.text, fontSize: 16, fontWeight: '900' },
  msg: { flexDirection: 'row', gap: 10, alignItems: 'flex-start', marginTop: 2 },
  bubble: {
    flex: 1,
    backgroundColor: C.card,
    borderRadius: 16,
    borderTopLeftRadius: 6,
    borderWidth: 1,
    borderColor: C.border,
    padding: 12,
  },
  msgIcon: { fontSize: 14 },
  msgTime: { fontSize: 11 },
  msgText: { color: C.text, fontSize: 14.5, lineHeight: 21, marginTop: 4 },
  end: { textAlign: 'center', color: C.faint, marginTop: 6 },
});
