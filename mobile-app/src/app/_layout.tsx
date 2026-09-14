import React, { useEffect } from 'react';
import { View, StyleSheet } from 'react-native';
import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { useJexi } from '../lib/store';
import { C } from '../lib/theme';

export default function RootLayout() {
  const boot = useJexi((s) => s.boot);

  useEffect(() => {
    boot();
  }, [boot]);

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
