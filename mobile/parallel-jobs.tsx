// 並行作業バー（アプリ版）: 1つの部屋の中で、メインの会話と並行して走っている作業の一覧。
//
// - 一覧が空なら何も描かない。あれば1行の折りたたみバー「並行作業 N件（進行中 M）」。
//   variant="icon" の時は、チャットの上の段を増やさないよう、アプリバーの中の小さな印（件数・動いていれば緑の点）
//   だけを出し、押すとアプリバーの下に一覧が重なって開く（チャットの表示域は縮まない）。
// - 開くと各作業の題名・モデル・状態・最新の進み具合を出し、
//   指示を足す / モデルを替える / 止める / 結果を見る の操作ができる。
// - 動いている作業がある間（かつアプリが前面の間）は4秒ごと、それ以外は30秒ごとに取り直す。
//   部屋を閉じる（アンマウント）と止まる。
//
// API: GET/POST /api/v1/projects/{id}/parallel-jobs, POST .../{job_id}/control
// 通信は App.tsx の apiRequest（トークン・自動リフレッシュ込み）を props で受け取って使う。

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  AppState,
  Modal,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { ui } from './ui-language';

export type ParallelJobState =
  | 'queued'
  | 'running'
  | 'waiting'
  | 'awaiting_confirmation'
  | 'paused'
  | 'completed'
  | 'failed'
  | 'cancelled';

export interface ParallelJob {
  id: string;
  title: string;
  task: string;
  model: string;
  model_label: string;
  state: ParallelJobState;
  state_label: string;
  waiting_for: string | null;
  last_progress: string | null;
  result_excerpt: string | null;
  report_message_id: string | null;
  active: boolean;
  created_at: string;
  updated_at: string;
}

export interface ParallelJobModel {
  id: string;
  label: string;
}

interface ParallelJobsResponse {
  jobs: ParallelJob[];
  models: ParallelJobModel[];
  default_model: string;
}

/** App.tsx の apiRequest をトークン付きで包んだもの（パスは /api/v1 以下）。 */
export type ParallelJobsRequest = (path: string, init?: RequestInit) => Promise<unknown>;

type ControlBody =
  | { operation: 'update'; text: string }
  | { operation: 'cancel' }
  | { operation: 'switch_model'; model: string };

interface ParallelJobsBarProps {
  projectId: string;
  request: ParallelJobsRequest;
  /** 結果メッセージへ移動する。読み込まれていなければ false を返す。 */
  onShowMessage?: (messageId: string) => boolean;
  /** bar = 1行の折りたたみバー（従来）／ icon = アプリバーの中の印。押すと一覧が重なって開く。 */
  variant?: 'bar' | 'icon';
  /** variant=icon の一覧を出す位置（画面の上からの距離。アプリバーの下端）。 */
  dropdownTop?: number;
}

const FAST_MS = 4000;
const SLOW_MS = 30000;

export function ParallelJobsBar({ projectId, request, onShowMessage, variant = 'bar', dropdownTop = 0 }: ParallelJobsBarProps) {
  const [data, setData] = useState<ParallelJobsResponse | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [busyJobId, setBusyJobId] = useState<string | null>(null);
  const [addingFor, setAddingFor] = useState<string | null>(null);
  const [addText, setAddText] = useState('');
  const [newOpen, setNewOpen] = useState(false);
  const [newTask, setNewTask] = useState('');
  const [newModel, setNewModel] = useState('');
  const [starting, setStarting] = useState(false);

  // request は親の再描画のたびに作り直されるので、ポーリングの依存に入れず ref で最新を持つ。
  const requestRef = useRef(request);
  requestRef.current = request;
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const aliveRef = useRef(true);
  const anyActiveRef = useRef(false);
  const seqRef = useRef(0);

  const load = useCallback(async () => {
    const seq = ++seqRef.current;
    try {
      const res = (await requestRef.current(`/projects/${projectId}/parallel-jobs`)) as ParallelJobsResponse;
      if (!aliveRef.current || seq !== seqRef.current) return;
      setData(res && Array.isArray(res.jobs) ? res : null);
      anyActiveRef.current = !!res?.jobs?.some((j) => j.active);
    } catch {
      // 取れない時（未対応のサーバー等）は前回の表示のまま。何も出さない。
    }
  }, [projectId]);

  const schedule = useCallback(() => {
    if (timerRef.current) clearTimeout(timerRef.current);
    const delay = anyActiveRef.current && AppState.currentState === 'active' ? FAST_MS : SLOW_MS;
    timerRef.current = setTimeout(async () => {
      if (!aliveRef.current) return;
      if (AppState.currentState === 'active') await load();
      if (aliveRef.current) schedule();
    }, delay);
  }, [load]);

  const refetchNow = useCallback(async () => {
    await load();
    if (aliveRef.current) schedule();
  }, [load, schedule]);

  useEffect(() => {
    aliveRef.current = true;
    setData(null);
    anyActiveRef.current = false;
    void refetchNow();
    const sub = AppState.addEventListener('change', (state) => {
      if (state === 'active') void refetchNow();
    });
    return () => {
      aliveRef.current = false;
      sub.remove();
      if (timerRef.current) clearTimeout(timerRef.current);
      timerRef.current = null;
    };
  }, [refetchNow]);

  const control = useCallback(
    async (job: ParallelJob, body: ControlBody) => {
      setBusyJobId(job.id);
      try {
        await requestRef.current(
          `/projects/${projectId}/parallel-jobs/${encodeURIComponent(job.id)}/control`,
          { method: 'POST', body: JSON.stringify(body) },
        );
        return true;
      } catch (err) {
        Alert.alert(ui('Could not do that', '操作できませんでした'), String((err as Error)?.message ?? err).slice(0, 300));
        return false;
      } finally {
        if (aliveRef.current) setBusyJobId(null);
        void refetchNow();
      }
    },
    [projectId, refetchNow],
  );

  const jobs = data?.jobs ?? [];
  if (jobs.length === 0) return null;

  const models = data?.models ?? [];
  const defaultModel = data?.default_model ?? models[0]?.id ?? '';
  const selectedNewModel = newModel || defaultModel;
  const activeCount = jobs.filter((j) => j.active).length;

  const submitAdd = async (job: ParallelJob) => {
    const text = addText.trim();
    if (!text) return;
    const ok = await control(job, { operation: 'update', text });
    if (ok && aliveRef.current) {
      setAddingFor(null);
      setAddText('');
    }
  };

  const chooseModel = (job: ParallelJob) => {
    // Android のダイアログはボタン3つまで: 他のモデル（最大2つ）＋キャンセル。
    const others = models.filter((m) => m.id !== job.model).slice(0, 2);
    if (others.length === 0) return;
    Alert.alert(
      ui('Switch model', 'モデルを切り替え'),
      ui(
        'This stops the job and restarts the same task on the chosen model.',
        '作業を止めて、選んだモデルで最初からやり直します。',
      ),
      [
        ...others.map((m) => ({
          text: m.label,
          onPress: () => void control(job, { operation: 'switch_model', model: m.id }),
        })),
        { text: ui('Cancel', 'キャンセル'), style: 'cancel' as const },
      ],
      { cancelable: true },
    );
  };

  const cancel = (job: ParallelJob) => {
    Alert.alert(ui('Stop this job?', 'この作業を止めますか？'), job.title, [
      { text: ui('Keep going', '続ける'), style: 'cancel' },
      { text: ui('Stop', '止める'), style: 'destructive', onPress: () => void control(job, { operation: 'cancel' }) },
    ]);
  };

  const showResult = (job: ParallelJob) => {
    if (!job.report_message_id) return;
    const ok = onShowMessage?.(job.report_message_id) ?? false;
    if (ok && variant === 'icon') setExpanded(false); // 重なった一覧を閉じて、会話の結果を見せる
    if (!ok) {
      Alert.alert(
        ui('Not loaded yet', 'まだ読み込まれていません'),
        ui('Scroll up in the chat to find the result.', '会話を上へたどって結果を探してください。'),
      );
    }
  };

  const start = async () => {
    const task = newTask.trim();
    if (!task) return;
    setStarting(true);
    try {
      await requestRef.current(`/projects/${projectId}/parallel-jobs`, {
        method: 'POST',
        body: JSON.stringify({ task, model: selectedNewModel || undefined }),
      });
      if (aliveRef.current) {
        setNewTask('');
        setNewOpen(false);
      }
    } catch (err) {
      Alert.alert(ui('Could not start', '始められませんでした'), String((err as Error)?.message ?? err).slice(0, 300));
    } finally {
      if (aliveRef.current) setStarting(false);
      void refetchNow();
    }
  };

  const list = (
    <ScrollView style={[styles.body, variant === 'icon' && styles.dropdownBody]} keyboardShouldPersistTaps="handled" nestedScrollEnabled>
      {jobs.map((job) => {
        const busy = busyJobId === job.id;
        const status = job.waiting_for ? `${job.state_label}・${job.waiting_for}` : job.state_label;
        const detail = job.active ? job.last_progress : job.result_excerpt ?? job.last_progress;
        const statusStyle =
          job.state === 'failed'
            ? styles.stateFailed
            : job.state === 'awaiting_confirmation'
              ? styles.stateAttention
              : job.active
                ? styles.stateActive
                : styles.stateDone;
        return (
          <View key={job.id} style={styles.row}>
            <View style={styles.rowTop}>
              <Text style={styles.title} numberOfLines={1}>
                {job.title}
              </Text>
              <View style={styles.chip}>
                <Text style={styles.chipText}>{job.model_label}</Text>
              </View>
              {busy ? <ActivityIndicator size="small" color="#5b6b63" /> : null}
            </View>
            <Text style={[styles.state, statusStyle]} numberOfLines={1}>
              {status}
            </Text>
            {detail ? (
              <Text style={styles.detail} numberOfLines={1}>
                {detail}
              </Text>
            ) : null}

            <View style={styles.actions}>
              {job.active ? (
                <>
                  <Pressable
                    disabled={busy}
                    onPress={() => {
                      setAddingFor((cur) => (cur === job.id ? null : job.id));
                      setAddText('');
                    }}
                    hitSlop={6}
                    style={({ pressed }) => [styles.action, pressed && styles.pressed, busy && styles.disabled]}
                  >
                    <Text style={styles.actionText}>{ui('Add instruction', '指示を足す')}</Text>
                  </Pressable>
                  {models.length > 1 ? (
                    <Pressable
                      disabled={busy}
                      onPress={() => chooseModel(job)}
                      hitSlop={6}
                      style={({ pressed }) => [styles.action, pressed && styles.pressed, busy && styles.disabled]}
                    >
                      <Text style={styles.actionText}>{ui('Model', 'モデル')}: {job.model_label} ▾</Text>
                    </Pressable>
                  ) : null}
                  <Pressable
                    disabled={busy}
                    onPress={() => cancel(job)}
                    hitSlop={6}
                    style={({ pressed }) => [styles.action, pressed && styles.pressed, busy && styles.disabled]}
                  >
                    <Text style={[styles.actionText, styles.actionDanger]}>{ui('Stop', '止める')}</Text>
                  </Pressable>
                </>
              ) : null}
              {!job.active && job.report_message_id && onShowMessage ? (
                <Pressable
                  onPress={() => showResult(job)}
                  hitSlop={6}
                  style={({ pressed }) => [styles.action, pressed && styles.pressed]}
                >
                  <Text style={[styles.actionText, styles.actionPrimary]}>{ui('See result', '結果を見る')}</Text>
                </Pressable>
              ) : null}
            </View>

            {addingFor === job.id ? (
              <View style={styles.inputRow}>
                <TextInput
                  autoFocus
                  value={addText}
                  onChangeText={setAddText}
                  placeholder={ui('Extra instruction for this job', 'この作業への追加の指示')}
                  placeholderTextColor="#8a978f"
                  style={styles.input}
                  returnKeyType="send"
                  onSubmitEditing={() => void submitAdd(job)}
                />
                <Pressable
                  disabled={busy || !addText.trim()}
                  onPress={() => void submitAdd(job)}
                  style={({ pressed }) => [
                    styles.sendButton,
                    pressed && styles.pressed,
                    (busy || !addText.trim()) && styles.disabled,
                  ]}
                >
                  <Text style={styles.sendText}>{ui('Send', '送る')}</Text>
                </Pressable>
              </View>
            ) : null}
          </View>
        );
      })}

      {newOpen ? (
        <View style={styles.newBox}>
          <TextInput
            autoFocus
            value={newTask}
            onChangeText={setNewTask}
            placeholder={ui('What should run in parallel?', '並行で頼みたいこと')}
            placeholderTextColor="#8a978f"
            style={[styles.input, styles.newInput]}
            multiline
          />
          {models.length > 0 ? (
            <View style={styles.modelRow}>
              {models.map((m) => {
                const selected = m.id === selectedNewModel;
                return (
                  <Pressable
                    key={m.id}
                    onPress={() => setNewModel(m.id)}
                    accessibilityState={{ selected }}
                    style={({ pressed }) => [styles.modelChip, selected && styles.modelChipSelected, pressed && styles.pressed]}
                  >
                    <Text style={[styles.modelChipText, selected && styles.modelChipTextSelected]}>{m.label}</Text>
                  </Pressable>
                );
              })}
            </View>
          ) : null}
          <View style={styles.newActions}>
            <Pressable onPress={() => setNewOpen(false)} hitSlop={6} style={({ pressed }) => [styles.action, pressed && styles.pressed]}>
              <Text style={styles.actionText}>{ui('Cancel', 'やめる')}</Text>
            </Pressable>
            <Pressable
              disabled={starting || !newTask.trim()}
              onPress={() => void start()}
              style={({ pressed }) => [
                styles.sendButton,
                pressed && styles.pressed,
                (starting || !newTask.trim()) && styles.disabled,
              ]}
            >
              <Text style={styles.sendText}>{starting ? ui('Starting…', '開始中…') : ui('Start', '頼む')}</Text>
            </Pressable>
          </View>
        </View>
      ) : (
        <Pressable onPress={() => setNewOpen(true)} hitSlop={6} style={({ pressed }) => [styles.newEntry, pressed && styles.pressed]}>
          <Ionicons name="add" size={14} color="#304d40" />
          <Text style={styles.newEntryText}>{ui('Run in parallel', '並行で頼む')}</Text>
        </Pressable>
      )}
    </ScrollView>
  );

  if (variant === 'icon') {
    return (
      <>
        <Pressable
          onPress={() => setExpanded((v) => !v)}
          accessibilityRole="button"
          accessibilityState={{ expanded }}
          accessibilityLabel={ui(`Parallel jobs ${jobs.length}, ${activeCount} running`, `並行作業 ${jobs.length}件、進行中 ${activeCount}`)}
          hitSlop={6}
          style={({ pressed }) => [styles.iconButton, pressed && styles.pressed]}
        >
          <Ionicons name="layers-outline" size={22} color="#162e27" />
          <View style={[styles.iconBadge, activeCount > 0 && styles.iconBadgeActive]}>
            <Text style={[styles.iconBadgeText, activeCount > 0 && styles.iconBadgeTextActive]}>{jobs.length}</Text>
          </View>
        </Pressable>
        <Modal visible={expanded} transparent animationType="fade" onRequestClose={() => setExpanded(false)} statusBarTranslucent>
          <Pressable style={styles.dropdownBackdrop} onPress={() => setExpanded(false)} accessibilityLabel={ui('Close', '閉じる')} />
          <View style={[styles.dropdown, { top: dropdownTop }]}>
            <View style={styles.dropdownHeader}>
              <Ionicons name="layers-outline" size={14} color="#5b6b63" />
              <Text style={styles.headerText} numberOfLines={1}>
                {ui(`Parallel jobs ${jobs.length}`, `並行作業 ${jobs.length}件`)}
                <Text style={styles.headerMuted}>{ui(` (${activeCount} running)`, `（進行中 ${activeCount}）`)}</Text>
              </Text>
              {activeCount > 0 ? <ActivityIndicator size="small" color="#5b6b63" style={styles.headerSpinner} /> : null}
            </View>
            {list}
          </View>
        </Modal>
      </>
    );
  }

  return (
    <View style={styles.bar}>
      <Pressable
        onPress={() => setExpanded((v) => !v)}
        accessibilityRole="button"
        accessibilityState={{ expanded }}
        style={({ pressed }) => [styles.header, pressed && styles.pressed]}
        hitSlop={4}
      >
        <Ionicons name={expanded ? 'chevron-down' : 'chevron-forward'} size={14} color="#5b6b63" />
        <Ionicons name="layers-outline" size={14} color="#5b6b63" />
        <Text style={styles.headerText} numberOfLines={1}>
          {ui(`Parallel jobs ${jobs.length}`, `並行作業 ${jobs.length}件`)}
          <Text style={styles.headerMuted}>{ui(` (${activeCount} running)`, `（進行中 ${activeCount}）`)}</Text>
        </Text>
        {activeCount > 0 ? <ActivityIndicator size="small" color="#5b6b63" style={styles.headerSpinner} /> : null}
      </Pressable>

      {expanded ? list : null}
    </View>
  );
}

const styles = StyleSheet.create({
  bar: {
    backgroundColor: '#f6f7f3',
    borderBottomColor: '#dbe2da',
    borderBottomWidth: 1,
  },
  header: {
    alignItems: 'center',
    flexDirection: 'row',
    gap: 6,
    minHeight: 34,
    paddingHorizontal: 12,
  },
  headerText: {
    color: '#162e27',
    flexShrink: 1,
    fontSize: 13,
    fontWeight: '700',
  },
  headerMuted: {
    color: '#5b6b63',
    fontWeight: '400',
  },
  headerSpinner: {
    transform: [{ scale: 0.7 }],
  },
  body: {
    maxHeight: 300,
    paddingHorizontal: 12,
  },
  row: {
    borderTopColor: '#e4e9e3',
    borderTopWidth: StyleSheet.hairlineWidth,
    paddingVertical: 7,
  },
  rowTop: {
    alignItems: 'center',
    flexDirection: 'row',
    gap: 6,
  },
  title: {
    color: '#162e27',
    flexShrink: 1,
    fontSize: 13,
    fontWeight: '700',
  },
  chip: {
    borderColor: '#cfd8d0',
    borderRadius: 6,
    borderWidth: 1,
    paddingHorizontal: 5,
    paddingVertical: 1,
  },
  chipText: {
    color: '#5b6b63',
    fontSize: 10,
    fontWeight: '600',
  },
  state: {
    fontSize: 12,
    marginTop: 2,
  },
  stateActive: { color: '#2f6b4f' },
  stateAttention: { color: '#a8660b' },
  stateFailed: { color: '#b3261e' },
  stateDone: { color: '#5b6b63' },
  detail: {
    color: '#7a877f',
    fontSize: 12,
    marginTop: 1,
  },
  actions: {
    alignItems: 'center',
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 14,
    marginTop: 4,
  },
  action: {
    paddingVertical: 2,
  },
  actionText: {
    color: '#304d40',
    fontSize: 12,
    fontWeight: '600',
  },
  actionDanger: { color: '#b3261e' },
  actionPrimary: { color: '#1f5f8b' },
  inputRow: {
    alignItems: 'center',
    flexDirection: 'row',
    gap: 6,
    marginTop: 6,
  },
  input: {
    backgroundColor: '#ffffff',
    borderColor: '#cfd8d0',
    borderRadius: 8,
    borderWidth: 1,
    color: '#162e27',
    flex: 1,
    fontSize: 13,
    minHeight: 34,
    paddingHorizontal: 9,
    paddingVertical: 6,
  },
  sendButton: {
    backgroundColor: '#162e27',
    borderRadius: 8,
    justifyContent: 'center',
    minHeight: 32,
    paddingHorizontal: 12,
  },
  sendText: {
    color: '#ffffff',
    fontSize: 12,
    fontWeight: '700',
  },
  newEntry: {
    alignItems: 'center',
    alignSelf: 'flex-start',
    flexDirection: 'row',
    gap: 3,
    marginBottom: 8,
    marginTop: 4,
    paddingVertical: 3,
  },
  newEntryText: {
    color: '#304d40',
    fontSize: 12,
    fontWeight: '600',
  },
  newBox: {
    borderTopColor: '#e4e9e3',
    borderTopWidth: StyleSheet.hairlineWidth,
    gap: 6,
    paddingBottom: 10,
    paddingTop: 8,
  },
  newInput: {
    flex: 0,
    maxHeight: 100,
  },
  modelRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 6,
  },
  modelChip: {
    borderColor: '#cfd8d0',
    borderRadius: 12,
    borderWidth: 1,
    paddingHorizontal: 10,
    paddingVertical: 4,
  },
  modelChipSelected: {
    backgroundColor: '#162e27',
    borderColor: '#162e27',
  },
  modelChipText: {
    color: '#304d40',
    fontSize: 12,
    fontWeight: '600',
  },
  modelChipTextSelected: {
    color: '#ffffff',
  },
  newActions: {
    alignItems: 'center',
    flexDirection: 'row',
    gap: 14,
    justifyContent: 'flex-end',
  },
  pressed: { opacity: 0.6 },
  disabled: { opacity: 0.4 },
  iconButton: {
    alignItems: 'center',
    height: 48,
    justifyContent: 'center',
    width: 40,
  },
  iconBadge: {
    alignItems: 'center',
    backgroundColor: '#e4e9e3',
    borderColor: '#f6f7f3',
    borderRadius: 8,
    borderWidth: 1.5,
    height: 16,
    justifyContent: 'center',
    minWidth: 16,
    paddingHorizontal: 3,
    position: 'absolute',
    right: 3,
    top: 8,
  },
  iconBadgeActive: { backgroundColor: '#2f8a5f' },
  iconBadgeText: { color: '#304d40', fontSize: 10, fontWeight: '800' },
  iconBadgeTextActive: { color: '#ffffff' },
  dropdownBackdrop: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: 'rgba(22,46,39,0.12)',
  },
  dropdown: {
    backgroundColor: '#f6f7f3',
    borderBottomLeftRadius: 16,
    borderBottomRightRadius: 16,
    elevation: 8,
    left: 0,
    paddingBottom: 4,
    position: 'absolute',
    right: 0,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.15,
    shadowRadius: 10,
  },
  dropdownHeader: {
    alignItems: 'center',
    flexDirection: 'row',
    gap: 6,
    minHeight: 36,
    paddingHorizontal: 12,
  },
  dropdownBody: {
    maxHeight: 420,
  },
});
