// Full-screen "Update your app" gate — shown when the server reports the
// installed version is below minRequired. Uses the JEXI warm theme tokens.

import React from 'react';
import { View, Text, StyleSheet, Linking, Pressable } from 'react-native';
import type { VersionInfo } from './update';
import { APP_VERSION } from './update';

const WARM = {
  bg: '#14100c',
  panel: '#1e1913',
  line: '#332a20',
  ink: '#f3ece2',
  ink2: '#b8a893',
  ink3: '#7d7264',
  ember: '#ff7a3d',
  gold: '#e6b45a',
};

export function UpdateGate({ info }: { info: VersionInfo | null }) {
  return (
    <View style={s.root}>
      <View style={s.card}>
        <View style={s.orb} />
        <Text style={s.h1}>Update your app</Text>
        <Text style={s.body}>
          You are running JEXI {APP_VERSION}, but version {info?.minRequired || 'newer'} or newer is
          required to keep everything working correctly.
        </Text>
        {info?.notes ? <Text style={s.notes}>What's new: {info.notes}</Text> : null}
        {info?.url ? (
          <Pressable style={s.btn} onPress={() => Linking.openURL(info.url)}>
            <Text style={s.btnText}>Get the latest version</Text>
          </Pressable>
        ) : null}
        <Text style={s.foot}>Paper trading only · not financial advice</Text>
      </View>
    </View>
  );
}

export function SoftUpdateBanner({ info }: { info: VersionInfo | null }) {
  if (!info) return null;
  return (
    <View style={s.banner}>
      <Text style={s.bannerText}>
        JEXI {info.latest} is available — you are on {APP_VERSION}.
      </Text>
      {info.url ? (
        <Pressable onPress={() => Linking.openURL(info.url)}>
          <Text style={s.bannerLink}>Update</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: WARM.bg, alignItems: 'center', justifyContent: 'center', padding: 24 },
  card: {
    backgroundColor: WARM.panel,
    borderColor: WARM.line,
    borderWidth: 1,
    borderRadius: 22,
    padding: 28,
    width: '100%',
    maxWidth: 420,
    alignItems: 'center',
  },
  orb: {
    width: 56,
    height: 56,
    borderRadius: 28,
    marginBottom: 18,
    backgroundColor: WARM.ember,
    opacity: 0.9,
  },
  h1: { color: WARM.ink, fontSize: 24, fontWeight: '800', letterSpacing: -0.4 },
  body: { color: WARM.ink2, fontSize: 14, lineHeight: 21, marginTop: 10, textAlign: 'center' },
  notes: { color: WARM.ink3, fontSize: 12.5, lineHeight: 18, marginTop: 8, textAlign: 'center' },
  btn: {
    marginTop: 22,
    backgroundColor: WARM.ember,
    borderRadius: 12,
    paddingHorizontal: 22,
    paddingVertical: 13,
    width: '100%',
  },
  btnText: { color: '#180f08', fontWeight: '800', fontSize: 14.5, textAlign: 'center' },
  foot: { color: WARM.ink3, fontSize: 11, marginTop: 16 },
  banner: {
    backgroundColor: 'rgba(255,122,61,.12)',
    borderColor: WARM.line,
    borderWidth: 1,
    borderRadius: 12,
    paddingHorizontal: 14,
    paddingVertical: 10,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 12,
  },
  bannerText: { color: WARM.ink2, fontSize: 12.5, flex: 1 },
  bannerLink: { color: WARM.ember, fontWeight: '800', fontSize: 12.5 },
});
