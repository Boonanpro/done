// アプリの更新をボタン1つにする（2026-10-24）。本人「とりあえずインストールを押すやつで良いわ。いちいちUSB繋いでデバックするよりはまし。
// ただどこから押せばいいのか分からないのでそれは分かりやすくしてほしい」。
//
// 起動した時と画面に戻った時に、サーバーの最新版（GET /api/v1/push/native/app-latest。app/services/app_release.py）を見て、
// 入っている版より新しければホーム・チャット・ログインの画面の上に「新しい版 1.0.x があります［更新する］」を出す。
// ［更新する］で APK を落とし、Android のインストール画面を開く（plugins/withDanAppUpdate.js の DanAppUpdate）。
// 初めての時だけ Android が「この提供元のアプリを許可」を求めるので、1文の案内と設定を開くボタンを出し、
// 設定から戻ったら続きを自動で進める。DanAppUpdate が無い古いアプリや Web では何も出さない。
import { useCallback, useEffect, useRef, useState } from 'react';
import { AppState, NativeModules, Platform, Pressable, StyleSheet, Text, View } from 'react-native';
import * as FileSystem from 'expo-file-system/legacy';

type Latest = { version_name: string; version_code: number; url: string; size?: number | null; notes?: string | null };
type Installed = { versionName: string; versionCode: number };
type Native = {
  info(): Promise<Installed>;
  canInstall(): Promise<boolean>;
  openInstallSettings(): Promise<boolean>;
  install(contentUri: string): Promise<boolean>;
};

export type UpdatePhase = 'none' | 'ready' | 'downloading' | 'permission' | 'installing' | 'failed';
export type AppUpdate = {
  phase: UpdatePhase;
  latest: Latest | null;
  progress: number;
  start: () => void;
  openSettings: () => void;
};

function nativeUpdater(): Native | null {
  if (Platform.OS !== 'android') return null;
  const m = (NativeModules as { DanAppUpdate?: Native }).DanAppUpdate;
  return m && typeof m.install === 'function' ? m : null;
}

/** 新しい版が要るか（versionCode で比べる。版の名前は見せるだけ） */
export function isNewer(latest: Latest | null, installed: Installed | null): boolean {
  return !!latest && !!installed && Number.isFinite(latest.version_code) && latest.version_code > installed.versionCode;
}

export function useAppUpdate(apiBase: string, token: string | null): AppUpdate {
  const updater = useRef(nativeUpdater()).current;
  const [installed, setInstalled] = useState<Installed | null>(null);
  const [latest, setLatest] = useState<Latest | null>(null);
  const [phase, setPhase] = useState<UpdatePhase>('none');
  const [progress, setProgress] = useState(0);
  const phaseRef = useRef<UpdatePhase>('none');
  phaseRef.current = phase;
  // 1回の［更新する］で落とすのは1回だけ（設定から戻った時に画面の「戻った」の知らせが2回来ることがある）
  const runningRef = useRef(false);

  const check = useCallback(async () => {
    if (!updater) return;
    try {
      const mine = installed ?? (await updater.info());
      if (!installed) setInstalled(mine);
      // ログインしていなくても見る（ログインの画面にも出す。最新版の情報は誰が見てもよい物だけ）
      const res = await fetch(`${apiBase}/api/v1/push/native/app-latest`, token ? { headers: { Authorization: `Bearer ${token}` } } : {});
      if (!res.ok) return;
      const body = (await res.json()) as { latest?: Latest | null };
      const next = body.latest ?? null;
      setLatest(next);
      const busy = phaseRef.current === 'downloading' || phaseRef.current === 'permission' || phaseRef.current === 'installing';
      if (!busy) setPhase(isNewer(next, mine) ? 'ready' : 'none');
      // 入れ終わった版の APK は端末に残さない
      if (!isNewer(next, mine) && FileSystem.cacheDirectory) {
        const names = await FileSystem.readDirectoryAsync(FileSystem.cacheDirectory).catch(() => [] as string[]);
        for (const n of names) if (/^Done-.*\.apk$/.test(n)) await FileSystem.deleteAsync(FileSystem.cacheDirectory + n, { idempotent: true }).catch(() => undefined);
      }
      // 入れ終わって戻った時（版が追いついた）は消す
      if (phaseRef.current === 'installing' && !isNewer(next, mine)) setPhase('none');
    } catch {
      /* 次に戻った時にまた見る */
    }
  }, [apiBase, installed, token, updater]);

  const run = useCallback(async () => {
    if (!updater || !latest || runningRef.current) return;
    runningRef.current = true;
    try {
      if (!(await updater.canInstall())) {
        setPhase('permission');
        return;
      }
      setPhase('downloading');
      setProgress(0);
      const target = `${FileSystem.cacheDirectory}Done-${latest.version_name}.apk`;
      await FileSystem.deleteAsync(target, { idempotent: true }).catch(() => undefined);
      const url = /^https?:/.test(latest.url) ? latest.url : `${apiBase}${latest.url}`;
      const dl = FileSystem.createDownloadResumable(url, target, {}, (p) => {
        const total = p.totalBytesExpectedToWrite || latest.size || 0;
        if (total > 0) setProgress(Math.min(1, p.totalBytesWritten / total));
      });
      const done = await dl.downloadAsync();
      if (!done || done.status < 200 || done.status >= 300) throw new Error(`download ${done?.status}`);
      const contentUri = await FileSystem.getContentUriAsync(done.uri);
      await updater.install(contentUri);
      setPhase('installing');
    } catch {
      setPhase('failed');
    } finally {
      runningRef.current = false;
    }
  }, [apiBase, latest, updater]);

  const openSettings = useCallback(() => {
    void updater?.openInstallSettings().catch(() => undefined);
  }, [updater]);

  useEffect(() => {
    void check();
    const sub = AppState.addEventListener('change', (state) => {
      if (state !== 'active') return;
      // 設定で許して戻ってきたら、続きを自動で進める
      if (phaseRef.current === 'permission') {
        void updater?.canInstall().then((ok) => { if (ok) void run(); }).catch(() => undefined);
        return;
      }
      void check();
    });
    return () => sub.remove();
  }, [check, run, updater]);

  return { phase, latest, progress, start: () => void run(), openSettings };
}

/** ホームとチャットの上に出す1枚。新しい版が無ければ何も出さない */
export function AppUpdateBanner({ update, topInset = 0 }: { update: AppUpdate; topInset?: number }) {
  const { phase, latest, progress } = update;
  if (phase === 'none' || !latest) return null;
  let text = `新しい版 ${latest.version_name} があります`;
  let sub = latest.notes || '';
  let action: { label: string; onPress: () => void } | null = { label: '更新する', onPress: update.start };
  if (phase === 'downloading') {
    text = `新しい版を落としています ${Math.round(progress * 100)}%`;
    sub = '';
    action = null;
  } else if (phase === 'permission') {
    text = '初めての時だけ、Android の設定で「この提供元のアプリを許可」をオンにしてください';
    sub = 'オンにして戻ると、そのまま続きます';
    action = { label: '設定を開く', onPress: update.openSettings };
  } else if (phase === 'installing') {
    text = '開いた画面で「インストール」を押してください';
    sub = '画面が閉じてしまった時は、もう一度押してください';
    action = { label: 'もう一度開く', onPress: update.start };
  } else if (phase === 'failed') {
    text = '新しい版を落とせませんでした';
    sub = '';
    action = { label: 'もう一度', onPress: update.start };
  }
  return (
    <View style={[styles.wrap, { paddingTop: topInset + 8 }]} accessibilityRole="alert">
      <View style={styles.card}>
        <View style={styles.texts}>
          <Text style={styles.text}>{text}</Text>
          {sub ? <Text style={styles.sub} numberOfLines={2}>{sub}</Text> : null}
          {phase === 'downloading' ? (
            <View style={styles.bar}><View style={[styles.barFill, { width: `${Math.round(progress * 100)}%` }]} /></View>
          ) : null}
        </View>
        {action ? (
          <Pressable onPress={action.onPress} style={({ pressed }) => [styles.button, pressed && { opacity: 0.8 }]} accessibilityRole="button" hitSlop={6}>
            <Text style={styles.buttonText}>{action.label}</Text>
          </Pressable>
        ) : null}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { paddingHorizontal: 12, paddingBottom: 4, backgroundColor: 'transparent' },
  card: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingVertical: 12, paddingHorizontal: 14, borderRadius: 14, backgroundColor: '#e9f4f0', borderWidth: 1, borderColor: '#bcdccf' },
  texts: { flex: 1, minWidth: 0 },
  text: { fontSize: 14.5, fontWeight: '700', color: '#163d31', lineHeight: 20 },
  sub: { marginTop: 2, fontSize: 12.5, color: '#4b6b5f', lineHeight: 17 },
  bar: { marginTop: 8, height: 4, borderRadius: 2, backgroundColor: '#cfe5dc', overflow: 'hidden' },
  barFill: { height: 4, backgroundColor: '#1d6b57' },
  button: { paddingVertical: 9, paddingHorizontal: 16, borderRadius: 999, backgroundColor: '#1d6b57' },
  buttonText: { color: '#fff', fontSize: 14, fontWeight: '700' },
});
