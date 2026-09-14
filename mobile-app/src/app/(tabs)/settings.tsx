import React, { useState } from 'react';
import { View, Text, TextInput, StyleSheet, ScrollView, Alert, Switch, TouchableOpacity } from 'react-native';
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
  const { profile, keys, paused, killed, liveMode, serverUrl, setPaused, setKilled, resetAll, connectServer, disconnectServer } = useJexi();
  const [notify, setNotify] = useState(true);
  const [url, setUrl] = useState('');
  const [email, setEmail] = useState(profile?.email ?? '');
  const [pass, setPass] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');

  const connect = async () => {
    setBusy(true);
    setErr('');
    const problem = await connectServer(url, email.trim(), pass);
    setBusy(false);
    if (problem) setErr(problem);
    else {
      setPass('');
      Alert.alert('Connected', 'Your app is now live with your server. Balance, trades and profits come from your own account.');
    }
  };

  return (
    <ScrollView style={s.fill} contentContainerStyle={[s.wrap, { paddingTop: insets.top + 14 }]}>
      <Text style={s.title}>Settings</Text>

      <Card style={s.profile}>
        <Orb size={46} />
        <View style={{ flex: 1, marginLeft: 12 }}>
          <Text style={s.profileName}>{profile?.name ?? 'Demo user'}</Text>
          <Sub>{profile?.email ?? 'demo@jexi.app'}</Sub>
        </View>
        <Pill tone={liveMode ? 'green' : 'amber'} label={liveMode ? 'LIVE' : 'DEMO'} />
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

      <SectionTitle right={<Pill tone={liveMode ? 'green' : 'amber'} label={liveMode ? 'Connected' : 'Not connected'} />}>Your server</SectionTitle>
      <Card style={{ gap: 10 }}>
        {liveMode ? (
          <>
            <Sub style={{ color: C.text, fontWeight: '700' }}>{serverUrl}</Sub>
            <Sub>Everything updates from your own server. Your keys are encrypted there too.</Sub>
            <Btn small tone="ghost" label="Disconnect" onPress={disconnectServer} />
          </>
        ) : (
          <>
            <Sub>Connect this app to your own Jexi server (Vercel + Cloudflare) to trade for real. Ask Jexi support for the address, or paste it below.</Sub>
            <Text style={s.keyName}>Server address</Text>
            <TextInput
              style={s.input}
              placeholder="https://your-app.vercel.app"
              placeholderTextColor={C.faint}
              value={url}
              onChangeText={setUrl}
              autoCapitalize="none"
              autoCorrect={false}
              keyboardType="url"
            />
            <Text style={s.keyName}>Email</Text>
            <TextInput
              style={s.input}
              placeholder="you@example.com"
              placeholderTextColor={C.faint}
              value={email}
              onChangeText={setEmail}
              autoCapitalize="none"
              keyboardType="email-address"
            />
            <Text style={s.keyName}>Password</Text>
            <TextInput
              style={s.input}
              placeholder="Your server password"
              placeholderTextColor={C.faint}
              value={pass}
              onChangeText={setPass}
              secureTextEntry
            />
            {err !== '' && <Text style={{ color: C.red, fontWeight: '700', fontSize: 13 }}>{err}</Text>}
            <Btn small label={busy ? 'Connecting…' : 'Connect to my server'} disabled={busy} onPress={connect} />
          </>
        )}
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
        <Sub>Jexi app · version 1.1.0 {liveMode ? '(live with your server)' : '(demo mode)'}</Sub>
        <Sub>{liveMode ? 'Live mode: your money numbers come from your server account.' : 'Demo money only until you connect your server in the card above.'}</Sub>
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
  input: {
    backgroundColor: C.card2,
    borderWidth: 1,
    borderColor: C.border,
    borderRadius: 12,
    paddingHorizontal: 14,
    paddingVertical: 12,
    color: C.text,
    fontSize: 15,
  },
  hr: { height: 1, backgroundColor: C.border },
});
