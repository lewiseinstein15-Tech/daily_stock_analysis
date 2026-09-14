import React, { useState } from 'react';
import { View, Text, StyleSheet, ScrollView, Alert, Switch, TouchableOpacity } from 'react-native';
import { useRouter } from 'expo-router';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useJexi } from '../../lib/store';
import { C } from '../../lib/theme';
import { Card, Pill, Row, SectionTitle, Sub, Btn, Orb } from '../../components/ui';

function mask(k: string) {
  if (!k) return 'not set';
  return `•••• ${k.slice(-4)}`;
}

export default function Settings() {
  const insets = useSafeAreaInsets();
  const router = useRouter();
  const { profile, keys, paused, killed, setPaused, setKilled, resetAll } = useJexi();
  const [notify, setNotify] = useState(true);

  return (
    <ScrollView style={s.fill} contentContainerStyle={[s.wrap, { paddingTop: insets.top + 14 }]}>
      <Text style={s.title}>Settings</Text>

      <Card style={s.profile}>
        <Orb size={46} />
        <View style={{ flex: 1, marginLeft: 12 }}>
          <Text style={s.profileName}>{profile?.name ?? 'Demo user'}</Text>
          <Sub>{profile?.email ?? 'demo@jexi.app'}</Sub>
        </View>
        <Pill tone="brand" label="DEMO" />
      </Card>

      <SectionTitle right={<Pill tone="green" label="Saved on device" />}>Your two keys</SectionTitle>
      <Card style={{ gap: 12 }}>
        <Row style={{ justifyContent: 'space-between' }}>
          <View>
            <Text style={s.keyName}>🧠 AI brain</Text>
            <Sub>{keys ? `${keys.aiProvider} · ${mask(keys.aiKey)}` : 'No key yet — Jexi runs in demo mode'}</Sub>
          </View>
          <TouchableOpacity onPress={() => router.push('/keys')}>
            <Text style={s.link}>{keys ? 'Change' : 'Add'}</Text>
          </TouchableOpacity>
        </Row>
        <View style={s.hr} />
        <Row style={{ justifyContent: 'space-between' }}>
          <View>
            <Text style={s.keyName}>📈 Trading account</Text>
            <Sub>{keys ? `${keys.broker} · ${mask(keys.brokerKey)}` : 'No broker connected yet'}</Sub>
          </View>
          <TouchableOpacity onPress={() => router.push('/keys')}>
            <Text style={s.link}>{keys ? 'Change' : 'Add'}</Text>
          </TouchableOpacity>
        </Row>
        <Sub style={s.keyNote}>
          🔒 Keys live encrypted on this device only. They never touch GitHub or any code folder.
        </Sub>
      </Card>

      <SectionTitle>Preferences</SectionTitle>
      <Card style={{ gap: 4 }}>
        <Row style={{ justifyContent: 'space-between', paddingVertical: 8 }}>
          <View style={{ flex: 1, paddingRight: 12 }}>
            <Text style={s.prefName}>Plain-English notifications</Text>
            <Sub>Get a message for every trade, in words you understand.</Sub>
          </View>
          <Switch value={notify} onValueChange={setNotify} trackColor={{ true: C.brand, false: C.border }} thumbColor="#fff" />
        </Row>
        <View style={s.hr} />
        <Row style={{ justifyContent: 'space-between', paddingVertical: 8 }}>
          <View style={{ flex: 1, paddingRight: 12 }}>
            <Text style={s.prefName}>{paused || killed ? 'Trading is OFF — resume?' : 'Pause trading'}</Text>
            <Sub>{killed ? 'Everything is stopped right now.' : paused ? 'Watching only, no trades.' : 'Jexi will keep your money safe and stop trading.'}</Sub>
          </View>
          {paused || killed ? (
            <Btn small tone="green" label="Resume" onPress={() => { setKilled(false); setPaused(false); }} />
          ) : (
            <Btn small tone="ghost" label="Pause" onPress={() => setPaused(true)} />
          )}
        </Row>
      </Card>

      <SectionTitle>About</SectionTitle>
      <Card style={{ gap: 6 }}>
        <Sub>Jexi app · version 0.1.0 (demo preview)</Sub>
        <Sub>Demo money only — no real trades, no real withdrawals yet. The user database and live broker link come in the next phase, after your OK.</Sub>
        <Sub>Nothing from this project is uploaded to GitHub.</Sub>
      </Card>

      <Btn
        tone="danger"
        label="Sign out & erase demo data"
        onPress={() =>
          Alert.alert('Erase everything?', 'This clears your demo profile, keys and history from this device.', [
            { text: 'Cancel', style: 'cancel' },
            { text: 'Erase', style: 'destructive', onPress: () => resetAll().then(() => router.replace('/')) },
          ])
        }
        style={{ marginTop: 6, marginBottom: 24 }}
      />
    </ScrollView>
  );
}

const s = StyleSheet.create({
  fill: { flex: 1, backgroundColor: C.bg },
  wrap: { paddingHorizontal: 20, paddingBottom: 24, gap: 14 },
  title: { color: C.text, fontSize: 28, fontWeight: '900' },
  profile: { flexDirection: 'row', alignItems: 'center' },
  profileName: { color: C.text, fontSize: 17, fontWeight: '900' },
  keyName: { color: C.text, fontSize: 15, fontWeight: '800' },
  keyNote: { color: C.faint, lineHeight: 18 },
  prefName: { color: C.text, fontSize: 15, fontWeight: '800' },
  link: { color: C.brand, fontWeight: '800', fontSize: 14 },
  hr: { height: 1, backgroundColor: C.border },
});
