import React, { useEffect } from 'react';
import { View, StyleSheet } from 'react-native';
import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { useFonts } from 'expo-font';
import { useJexi } from '../lib/store';
import { useUpdateGate } from '../lib/update';
import { UpdateGate } from '../lib/update-ui';
import { C } from '../lib/theme';

export default function RootLayout() {
  const boot = useJexi((s) => s.boot);
  const update = useUpdateGate();

  // The exact same variable fonts the JEXI Market web app uses.
  const [fontsReady] = useFonts({
    Fraunces: require('../../assets/fonts/Fraunces-var.ttf'),
    Inter: require('../../assets/fonts/Inter-var.ttf'),
    'JetBrains Mono': require('../../assets/fonts/JetBrainsMono-var.ttf'),
  });

  useEffect(() => {
    boot();
  }, [boot]);

  // Server says this version is too old: show the full-screen update gate.
  if (update.status === 'required') {
    return <UpdateGate info={update.info} />;
  }

  if (!fontsReady) {
    return <View style={s.root} />;
  }

  return (
    <View style={s.root}>
      <StatusBar style="light" />
      <Stack
        screenOptions={{
          headerShown: false,
          contentStyle: { backgroundColor: C.bg },
          animation: 'fade',
        }}
      >
        <Stack.Screen name="index" />
        <Stack.Screen name="onboarding" />
        <Stack.Screen name="signup" />
        <Stack.Screen name="keys" />
        <Stack.Screen name="withdraw" />
        <Stack.Screen name="(tabs)" />
      </Stack>
    </View>
  );
}

const s = StyleSheet.create({
  root: { flex: 1, backgroundColor: C.bg },
});
