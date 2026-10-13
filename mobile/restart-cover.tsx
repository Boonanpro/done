// While Dan's core (the server that runs the chats) restarts, the whole app is covered with "restarting" and an
// indicator that fills; when the core and the room-list server answer again it fills up and the cover goes away
// (owner, 2026-10-13: a restart looked like a broken app for a minute). Same behaviour as the web's RestartCover.
import { useEffect, useRef, useState } from 'react';
import { Animated, DeviceEventEmitter, Easing, Modal, StyleSheet, Text, View } from 'react-native';
import { ui, useUiLanguage } from './ui-language';

const USUAL_MS = 20_000;          // from the stop until both answer, usually
const NEVER_STOPPED_MS = 20_000;  // announced, but the core never went away: the restart was called off
export const RESTARTING = 'dan-restarting';   // {announced, started?}: show the cover
export const BACK = 'dan-back';               // the cover went away: reconnect and reload now

type Alive = { state: 'up' | 'starting' | 'down'; started?: number };
type Cover = { announced: boolean; started?: number; since: number };

/** up = the room-list server answers too / starting = only the core / down = the screen server answers but the core
 *  does not listen (its relay returns 500). null when this phone cannot tell (no network, no answer, the route down). */
export async function askAlive(apiBase: string): Promise<Alive | null> {
  const stop = new AbortController();
  const timer = setTimeout(() => stop.abort(), 4000);
  try {
    const res = await fetch(`${apiBase}/api/v1/chat/alive`, { signal: stop.signal, headers: { 'Cache-Control': 'no-store' } });
    if (res.status === 500) return { state: 'down' };
    if (res.status > 500) return null;
    if (!res.ok) return { state: 'up' };   // a core from before /alive existed
    const d = (await res.json()) as { sandbox?: boolean; started?: number };
    return { state: d.sandbox ? 'up' : 'starting', started: d.started };
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

let covering = false;

/** The feed line dropped without an announcement: cover only when the core is found not listening twice in a row. */
export async function coverIfDown(apiBase: string): Promise<void> {
  if (covering) return;
  if ((await askAlive(apiBase))?.state !== 'down') return;
  await new Promise((r) => setTimeout(r, 1000));
  if ((await askAlive(apiBase))?.state === 'down') DeviceEventEmitter.emit(RESTARTING, { announced: false });
}

export function RestartCover({ apiBase }: { apiBase: string }) {
  useUiLanguage();
  const [cover, setCover] = useState<Cover | null>(null);
  const filled = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    const sub = DeviceEventEmitter.addListener(RESTARTING, (e: { announced: boolean; started?: number }) => {
      covering = true;
      setCover((current) => current ?? { announced: !!e.announced, started: e.started, since: Date.now() });
    });
    return () => sub.remove();
  }, []);

  useEffect(() => {
    if (!cover) return;
    filled.setValue(0);
    let stopped = false;
    let sawDown = !cover.announced;
    let floor = 0;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const fill = (to: number, ms: number, then?: () => void) =>
      Animated.timing(filled, { toValue: to, duration: ms, easing: Easing.linear, useNativeDriver: false }).start(then && (() => then()));
    const back = () => {
      stopped = true;
      fill(1, 300, () => {
        covering = false;
        setCover(null);
        DeviceEventEmitter.emit(BACK);
      });
    };
    const tick = async () => {
      const alive = await askAlive(apiBase);
      if (stopped) return;
      const waited = Date.now() - cover.since;
      if (alive?.state === 'down') sawDown = true;
      const isNew = sawDown || (alive?.started !== undefined && alive.started !== cover.started);
      if (alive && alive.state !== 'down' && isNew) {
        if (alive.state === 'up') return back();
        floor = 0.7;
      } else if (alive && alive.state !== 'down' && waited > NEVER_STOPPED_MS) {
        return back();
      }
      fill(Math.max(floor, 0.9 * (1 - Math.exp(-waited / USUAL_MS))), 1000);
      timer = setTimeout(tick, 1000);
    };
    void tick();
    return () => {
      stopped = true;
      if (timer) clearTimeout(timer);
    };
  }, [cover, apiBase, filled]);

  return (
    <Modal visible={!!cover} transparent statusBarTranslucent animationType="fade" onRequestClose={() => undefined}>
      <View style={styles.cover} accessibilityRole="progressbar" accessibilityLiveRegion="polite">
        <Text style={styles.text}>
          {cover?.announced === false ? ui("Can't reach Dan", 'ダンの本体につながりません') : ui('Restarting Dan', 'ダンを再起動中です')}
        </Text>
        <View style={styles.track}>
          <Animated.View style={[styles.bar, { width: filled.interpolate({ inputRange: [0, 1], outputRange: ['0%', '100%'] }) }]} />
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  cover: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: 20, backgroundColor: 'rgba(246,247,243,0.96)' },
  text: { fontSize: 16, fontWeight: '500', color: '#28251f' },
  track: { width: '70%', maxWidth: 320, height: 6, borderRadius: 3, backgroundColor: '#dbe2da', overflow: 'hidden' },
  bar: { height: '100%', borderRadius: 3, backgroundColor: '#28251f' },
});
