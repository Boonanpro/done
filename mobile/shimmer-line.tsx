// The call screen's one line (what Dan is doing), with a faint light passing across the letters every 3 seconds.
// The letters never move or change size; only the fill does: a narrow, barely brighter band sweeps left to right,
// slow at the start and end, fast in the middle (the owner's request, 2026-10-01). Off when the phone asks for
// reduced motion.
import React, { useEffect, useState } from 'react';
import { AccessibilityInfo, Easing, View } from 'react-native';
import Svg, { Defs, LinearGradient, Stop, Text as SvgText } from 'react-native-svg';

const PERIOD_MS = 3000;
const SWEEP_MS = 1400;
const BAND = 0.14;                        // half-width of the light band, as a share of the line
const ease = Easing.inOut(Easing.cubic);  // slow - fast - slow

function brighter(hex: string, amount: number): string {
  const n = parseInt(hex.slice(1), 16);
  const mix = (c: number) => Math.round(c + (255 - c) * amount);
  const r = mix((n >> 16) & 255), g = mix((n >> 8) & 255), b = mix(n & 255);
  return `#${((r << 16) | (g << 8) | b).toString(16).padStart(6, '0')}`;
}

export function ShimmerLine({ text, color, fontSize = 13, height = 20 }: { text: string; color: string; fontSize?: number; height?: number }) {
  const [width, setWidth] = useState(0);
  const [at, setAt] = useState(-1);   // band centre across the line (0..1); outside = no light
  const [still, setStill] = useState(false);

  useEffect(() => {
    AccessibilityInfo.isReduceMotionEnabled().then(setStill).catch(() => {});
    const sub = AccessibilityInfo.addEventListener('reduceMotionChanged', setStill);
    return () => sub.remove();
  }, []);

  useEffect(() => {
    if (still) { setAt(-1); return; }
    let frame = 0;
    const sweep = () => {
      const began = Date.now();
      const step = () => {
        const t = (Date.now() - began) / SWEEP_MS;
        if (t >= 1) { setAt(-1); return; }
        setAt(-BAND + (1 + 2 * BAND) * ease(t));
        frame = requestAnimationFrame(step);
      };
      frame = requestAnimationFrame(step);
    };
    const timer = setInterval(sweep, PERIOD_MS);
    return () => { clearInterval(timer); cancelAnimationFrame(frame); };
  }, [still]);

  const glow = brighter(color, 0.45);
  const lit = at > -1;
  return (
    <View accessible accessibilityRole="text" accessibilityLabel={text} accessibilityLiveRegion="polite"
          style={{ width: '100%', height }} onLayout={(e) => setWidth(e.nativeEvent.layout.width)}>
      {width > 0 && (
        <Svg width={width} height={height}>
          <Defs>
            <LinearGradient id="shine" x1="0" y1="0" x2={String(width)} y2="0" gradientUnits="userSpaceOnUse">
              <Stop offset="0" stopColor={color} />
              <Stop offset={String(lit ? Math.min(1, Math.max(0, at - BAND)) : 0.3)} stopColor={color} />
              <Stop offset={String(lit ? Math.min(1, Math.max(0, at)) : 0.5)} stopColor={lit ? glow : color} />
              <Stop offset={String(lit ? Math.min(1, Math.max(0, at + BAND)) : 0.7)} stopColor={color} />
              <Stop offset="1" stopColor={color} />
            </LinearGradient>
          </Defs>
          <SvgText x={width / 2} y={height / 2 + fontSize * 0.36} fontSize={fontSize} textAnchor="middle" fill="url(#shine)">
            {text}
          </SvgText>
        </Svg>
      )}
    </View>
  );
}
