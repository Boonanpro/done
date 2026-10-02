// 「考え中・作業中」の3つの点（メッセージアプリの入力中表示）。
// 定義: docs/current/chat-timeline-definition.md — 状態なので常に一番下に1つだけ出す。
// 点は左から順に少し浮いて濃くなり、元に戻る（約1.2秒で一巡）。動きを減らす設定では点を並べるだけ。
import React, { useEffect, useRef, useState } from 'react';
import { AccessibilityInfo, Animated, Easing, StyleSheet, View, type ViewStyle } from 'react-native';

type Props = { color?: string; size?: number; style?: ViewStyle };

const PERIOD = 1200;   // one round of the three dots
const STAGGER = 160;   // the next dot starts this much later

export function TypingDots({ color = '#7a8580', size = 7, style }: Props) {
  const values = useRef([0, 1, 2].map(() => new Animated.Value(0))).current;
  const [still, setStill] = useState(false);

  useEffect(() => {
    let alive = true;
    AccessibilityInfo.isReduceMotionEnabled().then((on) => alive && setStill(on)).catch(() => null);
    const sub = AccessibilityInfo.addEventListener('reduceMotionChanged', (on) => setStill(on));
    return () => { alive = false; sub.remove(); };
  }, []);

  useEffect(() => {
    if (still) return;
    const up = PERIOD * 0.28;
    const loops = values.map((value, i) =>
      Animated.loop(
        Animated.sequence([
          Animated.delay(i * STAGGER),
          Animated.timing(value, { toValue: 1, duration: up, easing: Easing.out(Easing.quad), useNativeDriver: true }),
          Animated.timing(value, { toValue: 0, duration: up, easing: Easing.in(Easing.quad), useNativeDriver: true }),
          Animated.delay(PERIOD - 2 * up - i * STAGGER),
        ]),
      ),
    );
    loops.forEach((loop) => loop.start());
    return () => loops.forEach((loop) => loop.stop());
  }, [still, values]);

  return (
    <View style={[styles.row, style]} accessibilityRole="progressbar" accessibilityLabel="Dan is working">
      {values.map((value, i) => (
        <Animated.View
          key={i}
          style={{
            width: size,
            height: size,
            borderRadius: size / 2,
            marginHorizontal: size * 0.3,
            backgroundColor: color,
            opacity: still ? 0.6 : value.interpolate({ inputRange: [0, 1], outputRange: [0.35, 1] }),
            transform: still ? [] : [{ translateY: value.interpolate({ inputRange: [0, 1], outputRange: [0, -size * 0.6] }) }],
          }}
        />
      ))}
    </View>
  );
}

const styles = StyleSheet.create({ row: { flexDirection: 'row', alignItems: 'center', paddingVertical: 4 } });
