import React, { useEffect } from 'react';
import { View, Text, StyleSheet, ColorValue } from 'react-native';
import { Tabs, router } from 'expo-router';
import { Ionicons } from '@expo/vector-icons';
import { StatusBar } from 'expo-status-bar';
import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { useJexi } from '../../lib/store';
import { C } from '../../lib/theme';

function TabIcon({ name, color, focused }: { name: keyof typeof Ionicons.glyphMap; color: ColorValue; focused: boolean }) {
  return (
    <View style={styles.iconWrap}>
      <Ionicons name={name} size={22} color={color} />
      {focused && <View style={[styles.iconBar, { backgroundColor: color as string }]} />}
    </View>
  );
}

export default function TabsLayout() {
  const booted = useJexi((s) => s.booted);
  const onboarded = useJexi((s) => s.onboarded);
  const startEngine = useJexi((s) => s.startEngine);
  const insets = useSafeAreaInsets();

  useEffect(() => {
    if (booted && !onboarded) router.replace('/');
  }, [booted, onboarded]);

  useEffect(() => {
    startEngine();
  }, [startEngine]);

  return (
    <View style={styles.root}>
      <StatusBar style="light" />
      <Tabs
        screenOptions={{
          headerShown: false,
          sceneStyle: { backgroundColor: C.bg },
          tabBarActiveTintColor: C.brand,
          tabBarInactiveTintColor: C.faint,
          tabBarStyle: {
            backgroundColor: C.card,
            borderTopColor: C.border,
            borderTopWidth: 1,
            height: 64 + insets.bottom,
            paddingBottom: insets.bottom,
            paddingTop: 6,
          },
          tabBarLabelStyle: { fontSize: 10.5, fontWeight: '700' },
        }}
      >
        <Tabs.Screen
          name="home"
          options={{
            title: 'Home',
            tabBarIcon: ({ color, focused }) => <TabIcon name={focused ? 'home' : 'home-outline'} color={color} focused={focused} />,
          }}
        />
        <Tabs.Screen
          name="trades"
          options={{
            title: 'Trades',
            tabBarIcon: ({ color, focused }) => <TabIcon name={focused ? 'swap-horizontal' : 'swap-horizontal-outline'} color={color} focused={focused} />,
          }}
        />
        <Tabs.Screen
          name="profits"
          options={{
            title: 'Profits',
            tabBarIcon: ({ color, focused }) => <TabIcon name={focused ? 'trending-up' : 'trending-up-outline'} color={color} focused={focused} />,
          }}
        />
        <Tabs.Screen
          name="jexi"
          options={{
            title: 'Jexi',
            tabBarIcon: ({ color, focused }) => <TabIcon name={focused ? 'chatbubbles' : 'chatbubbles-outline'} color={color} focused={focused} />,
          }}
        />
        <Tabs.Screen
          name="settings"
          options={{
            title: 'Settings',
            tabBarIcon: ({ color, focused }) => <TabIcon name={focused ? 'settings' : 'settings-outline'} color={color} focused={focused} />,
          }}
        />
      </Tabs>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: C.bg },
  iconWrap: { alignItems: 'center', justifyContent: 'center', width: 44, height: 26 },
  iconBar: { width: 14, height: 2.5, borderRadius: 2, marginTop: 2 },
});
