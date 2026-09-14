import React, { useState } from 'react';
import { View, Text, TextInput, StyleSheet, ScrollView } from 'react-native';
import { useRouter } from 'expo-router';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useJexi } from '../lib/store';
import { C } from '../lib/theme';
import { Btn, Card, Sub } from '../components/ui';

export default function Signup() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const setProfile = useJexi((s) => s.setProfile);
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const ok = name.trim().length > 1 && /\S+@\S+\.\S+/.test(email);

  return (
    <ScrollView
      style={s.fill}
      contentContainerStyle={[s.wrap, { paddingTop: insets.top + 16, paddingBottom: insets.bottom + 24 }]}
    >
      <Text style={s.title}>Who is the boss?</Text>
      <Sub style={s.lead}>Jexi greets you by name and sends updates to you. This stays on your device in this demo.</Sub>

      <Card style={s.form}>
        <Text style={s.label}>Your name</Text>
        <TextInput
          style={s.input}
          placeholder="e.g. Lewis"
          placeholderTextColor={C.faint}
          value={name}
          onChangeText={setName}
        />
        <Text style={s.label}>Email</Text>
        <TextInput
          style={s.input}
          placeholder="you@example.com"
          placeholderTextColor={C.faint}
          value={email}
          onChangeText={setEmail}
          autoCapitalize="none"
          keyboardType="email-address"
        />
      </Card>

      <Sub style={s.note}>
        In the real app this becomes your login. Many people can each have their own Jexi — that is what the
        user database (coming next) is for.
      </Sub>

      <View style={{ flex: 1 }} />
      <Btn
        label="Create my profile"
        disabled={!ok}
        onPress={() => {
          setProfile({ name: name.trim(), email: email.trim() });
          router.push('/keys');
        }}
      />
      <Btn tone="ghost" label="Back" onPress={() => router.back()} style={{ marginTop: 10 }} />
    </ScrollView>
  );
}

const s = StyleSheet.create({
  fill: { flex: 1, backgroundColor: C.bg },
  wrap: { paddingHorizontal: 24, flexGrow: 1 },
  title: { color: C.text, fontSize: 30, fontWeight: '900', marginTop: 12 },
  lead: { marginTop: 8, lineHeight: 20 },
  form: { marginTop: 22, gap: 6 },
  label: { color: C.sub, fontSize: 13, fontWeight: '700', marginTop: 10 },
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
  note: { marginTop: 16, lineHeight: 19, color: C.faint },
});
