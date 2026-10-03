// Small motions for the work log (owner, 2026-10-03: "make it feel richer"): a new step slides in softly, the step
// running now breathes. Nothing moves when the phone asks for reduced motion.
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { AccessibilityInfo, Animated, Easing } from 'react-native';

let reduced = false;
AccessibilityInfo.isReduceMotionEnabled().then((v) => { reduced = v; }).catch(() => undefined);

/** A row that fades and rises 4px into place when it first appears (only while `animate`). */
export function StepIn({ animate, children }: { animate: boolean; children: ReactNode }) {
  const [start] = useState(() => animate && !reduced);
  const shown = useRef(new Animated.Value(start ? 0 : 1)).current;
  useEffect(() => {
    if (!start) return;
    Animated.timing(shown, { toValue: 1, duration: 280, easing: Easing.out(Easing.cubic), useNativeDriver: true }).start();
  }, [start, shown]);
  return (
    <Animated.View style={{ opacity: shown, transform: [{ translateY: shown.interpolate({ inputRange: [0, 1], outputRange: [4, 0] }) }] }}>
      {children}
    </Animated.View>
  );
}

/** Its child breathes (opacity 1 → .35 → 1) while `active`. */
export function Breathe({ active, children }: { active: boolean; children: ReactNode }) {
  const level = useRef(new Animated.Value(1)).current;
  useEffect(() => {
    if (!active || reduced) { level.setValue(1); return; }
    const loop = Animated.loop(Animated.sequence([
      Animated.timing(level, { toValue: 0.35, duration: 700, easing: Easing.inOut(Easing.sin), useNativeDriver: true }),
      Animated.timing(level, { toValue: 1, duration: 700, easing: Easing.inOut(Easing.sin), useNativeDriver: true }),
    ]));
    loop.start();
    return () => loop.stop();
  }, [active, level]);
  return <Animated.View style={{ opacity: level }}>{children}</Animated.View>;
}
