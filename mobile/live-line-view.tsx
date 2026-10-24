// 作業中の1行（スマホ）。3つの点・今していること・送ってからの秒数を出し、押すとこのターンでやったことを時刻と
// かかった秒数つきで全部開く（2026-10-24。本人「考えていますとか返事を書いていますってだけだとやっぱ待たされてる感がえぐいわ」）。
// 決まりは PC・開発室と同じ chat-shapes-live-line.ts。App.tsx から切り出してあるのは、試験台で単独に描いて確かめるため。
import { createContext, useContext, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { clockText, elapsedText, liveLineText, liveRows, secondsText, type LiveStep } from './chat-shapes-live-line';
import { TypingDots } from './typing-dots';

// 畳んだ物を開け閉めしても、押した見出しを画面の同じ位置に留める（チャットの一覧は下から積む作りなので、
// 開くと上へ伸びて見出しが画面の外へ逃げていた）。一覧の側が、開け閉めの前後で見出しの位置を測ってずれを戻す。
export const KeepInPlace = createContext<((moved: number) => void) | null>(null);

/**
 * 作業中の1行（3つの点・今していること・送ってからの秒数）。押すと、このターンでやったことが時刻とかかった秒数つきで
 * 全部開き、もう一度押すと閉じる。PC・開発室と同じ決まり（chat-shapes-live-line.ts。2026-10-24）。
 * 開け閉めしても1行を画面の同じ位置に留める（TurnToolGroup と同じ KeepInPlace）。
 */
export function LiveLineView({ live, startedAt }: { live: LiveStep[]; startedAt?: number | null }) {
  const [open, setOpen] = useState(false);
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  const keep = useContext(KeepInPlace);
  const header = useRef<View>(null);
  const before = useRef<number | null>(null);
  const toggle = () => {
    if (keep && header.current) header.current.measureInWindow((_x, y) => { before.current = y; setOpen((o) => !o); });
    else setOpen((o) => !o);
  };
  useLayoutEffect(() => {
    if (before.current === null || !header.current || !keep) return;
    const was = before.current;
    before.current = null;
    header.current.measureInWindow((_x, y) => { if (Math.abs(y - was) > 1) keep(y - was); });
  }, [open, keep]);
  const steps = live;
  const text = liveLineText(steps);
  const from = startedAt ?? steps.find((st) => st.at)?.at ?? null;
  const rows = open ? liveRows(steps, now, from) : [];
  return (
    <View>
      <Pressable ref={header} onPress={toggle} style={styles.liveLineRow} hitSlop={8} accessibilityRole="button" accessibilityState={{ expanded: open }}>
        <TypingDots color="#7a8f86" />
        <Text style={styles.label} numberOfLines={1}>{text.split('\n')[0]}</Text>
        {from ? <Text style={styles.liveElapsed}>{elapsedText(from, now)}</Text> : null}
        <Ionicons name={open ? 'chevron-up' : 'chevron-down'} size={13} color="#7a8f86" style={{ marginLeft: 4 }} />
      </Pressable>
      {open ? (
        <View style={styles.liveRows}>
          {rows.map((r) => (
            <View key={r.key} style={styles.liveRowItem}>
              <Text style={styles.liveRowTime}>{clockText(r.at)}</Text>
              <Text style={[styles.liveRowText, r.now && styles.liveRowNow]}>
                {r.label}{r.count > 1 ? <Text style={styles.liveRowTime}>{` ×${r.count}`}</Text> : null}
              </Text>
              <Text style={styles.liveRowTime}>{secondsText(r.seconds)}</Text>
            </View>
          ))}
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  label: { marginLeft: 10, fontSize: 13, color: '#7a8f86', flexShrink: 1 },
  liveLineRow: { flexDirection: 'row', alignItems: 'center', minHeight: 22 },
  liveElapsed: { marginLeft: 8, flexShrink: 0, fontSize: 12, color: '#93a39a', fontVariant: ['tabular-nums'] },
  liveRows: { marginTop: 6, marginLeft: 4, paddingLeft: 10, borderLeftWidth: 1, borderLeftColor: '#d5dcd8' },
  liveRowItem: { flexDirection: 'row', alignItems: 'flex-start', paddingVertical: 2 },
  liveRowTime: { flexShrink: 0, fontSize: 11.5, color: '#93a39a', fontVariant: ['tabular-nums'] },
  liveRowText: { flex: 1, marginHorizontal: 8, fontSize: 12.5, lineHeight: 17, color: '#7a8f86' },
  liveRowNow: { color: '#245e49' },
});
