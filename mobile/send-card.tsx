// 送信案カード（部屋のチャットの `[送信案: <id>]` 行）。ダンが書いた外部宛ての下書きを、ここで直して送る／破棄する。
// これまでアプリの部屋のチャットでは描かれず、行の文字がそのまま出ていた（Web とコラボ窓口にはあった）。
// 待ちの間は丸い読み込み表示を出さず、ボタンの文字で状態を見せる（LINE と同じ方針）。
import { useEffect, useRef, useState } from 'react';
import { Pressable, StyleSheet, Text, TextInput, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';

type Proposal = {
  id: string;
  status: string;
  content?: string | null;
  action_data?: {
    channel?: string; to?: string; to_name?: string | null; subject?: string | null; intent?: string | null;
    attachments?: { name: string; url: string }[] | null; sent_at?: string | null;
  } | null;
};
type Request = <T>(path: string, init?: RequestInit) => Promise<T>;

const CHANNEL: Record<string, string> = {
  email: 'メール', instagram_dm: 'Instagram DM', instagram_comment: 'Instagram コメント', line: 'LINE', sms: 'SMS',
  web_form: 'Webフォーム', chatwork: 'Chatwork', slack: 'Slack', x_dm: 'X DM', collab: '外部窓口', other: 'メッセージ',
};
export const SEND_CARD = /^\s*\[送信案: ([0-9a-fA-F-]{8,})\]\s*$/;
export const CONFIRM_CARD = /^\s*\[確認: ([0-9a-fA-F-]{8,})\]\s*$/;

/** 確認カード: 取り返しのつかない確定の前に、何がどうなるかを並べてボタン1つで答える（答えは本人の発言として部屋に届く）。 */
export function ConfirmCard({ id, request, onAnswer }: { id: string; request: Request; onAnswer: (text: string) => void }) {
  const [p, setP] = useState<(Proposal & { title?: string }) | null>(null);
  const [choice, setChoice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => {
    request<Proposal & { title?: string }>(`/chat/proposals/${id}`).then(setP).catch(() => setError('確認カードを読み込めませんでした'));
  }, [id]);   // eslint-disable-line react-hooks/exhaustive-deps
  if (!p) return error ? <Text style={st.muted}>{error}</Text> : <View style={[st.card, { height: 120 }]} />;
  const ad = (p.action_data || {}) as { items?: { label: string; value: string }[]; choices?: string[]; confirm_label?: string };
  const choices = ad.choices || [];
  const pending = p.status === 'pending';
  const answer = async (approve: boolean) => {
    if (approve && choices.length > 0 && !choice) { setError('どれにするか選んでください'); return; }
    setBusy(true); setError('');
    try {
      const next = await request<Proposal>(`/chat/proposals/${id}/respond`, { method: 'POST', body: JSON.stringify({ action: approve ? 'approve' : 'reject' }) });
      setP({ ...p, status: next.status });
      onAnswer(approve ? `承認: ${p.title}${choice ? `（${choice}）` : ''}` : `やめる: ${p.title}`);
    } catch {
      setError('答えを送れませんでした。もう一度押すか、チャットで伝えてください');
    } finally {
      setBusy(false);
    }
  };
  return (
    <View style={[st.card, !pending && st.cardDone]}>
      <View style={st.head}>
        <Ionicons name={pending ? 'shield-checkmark-outline' : p.status === 'approved' ? 'checkmark-circle-outline' : 'close-circle-outline'} size={15} color="#245e49" />
        <Text style={st.title} numberOfLines={2}>{p.title}</Text>
        {!pending ? <Text style={st.state}>{p.status === 'approved' ? '承認しました' : 'やめました'}</Text> : null}
      </View>
      <View style={st.rows}>
        {(ad.items || []).map((it, i) => (
          <View key={i} style={st.row}>
            <Text style={st.rowLabel}>{it.label}</Text>
            <Text style={st.rowValue} selectable>{it.value}</Text>
          </View>
        ))}
      </View>
      {choices.length > 0 ? (
        <View style={{ gap: 6 }}>
          {choices.map((c) => (
            <Pressable key={c} disabled={!pending || busy} onPress={() => setChoice(c)} style={[st.choice, choice === c && st.choiceOn]}>
              <Ionicons name={choice === c ? 'radio-button-on' : 'radio-button-off'} size={15} color="#245e49" />
              <Text style={st.choiceText}>{c}</Text>
            </Pressable>
          ))}
        </View>
      ) : null}
      {error ? <Text style={st.error}>{error}</Text> : null}
      {pending ? (
        <View style={st.buttons}>
          <Pressable style={({ pressed }) => [st.btn, st.ghost, pressed && st.pressed]} disabled={busy} onPress={() => answer(false)}>
            <Text style={st.ghostText}>やめる</Text>
          </Pressable>
          <Pressable style={({ pressed }) => [st.btn, st.primary, (pressed || busy) && st.pressed]} disabled={busy} onPress={() => answer(true)}>
            <Text style={st.primaryText}>{busy ? '送っています…' : ad.confirm_label || '承認する'}</Text>
          </Pressable>
        </View>
      ) : null}
    </View>
  );
}

export function SendCard({ id, request }: { id: string; request: Request }) {
  const [p, setP] = useState<Proposal | null>(null);
  const [failed, setFailed] = useState(false);
  const [body, setBody] = useState('');
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState<'send' | 'discard' | null>(null);
  const [error, setError] = useState('');
  const loaded = useRef('');
  const status = useRef('');

  const load = async () => {
    try {
      const got = await request<Proposal>(`/chat/proposals/${id}`);
      setP(got); status.current = got.status;
      if (!dirty || got.status !== 'pending') setBody(got.content || '');
      loaded.current = got.content || '';
    } catch {
      setFailed(true);
    }
  };
  useEffect(() => {
    void load();
    // 送信中（ダンが手で送っている）や更新を拾う。届いた後は止める。
    const timer = setInterval(() => { if (!status.current || ['pending', 'sending'].includes(status.current)) void load(); }, 15000);
    return () => clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  if (failed && !p) return <Text style={st.muted}>送信案を読み込めませんでした</Text>;
  if (!p) return <View style={[st.card, { height: 120 }]} />;

  const ad = p.action_data || {};
  const channel = CHANNEL[ad.channel || 'other'] || ad.channel || 'メッセージ';
  const pending = p.status === 'pending';
  // 取り下げた案は画面から消す。送った案は印（チェック）と淡い色だけで見せ、文字の札は付けない（2026-10-03）
  if (p.status === 'rejected') return null;
  const state = p.status === 'sending' ? '送信中' : '';

  const act = async (kind: 'send' | 'discard') => {
    setBusy(kind); setError('');
    try {
      if (kind === 'send' && dirty) {
        await request(`/chat/proposals/${id}/draft`, { method: 'PATCH', body: JSON.stringify({ body }) });
      }
      const next = await request<Proposal>(`/chat/proposals/${id}/${kind}`, { method: 'POST' });
      setP(next); status.current = next.status; setDirty(false);
    } catch (e) {
      setError(kind === 'send' ? '送れませんでした。もう一度押すか、ダンに伝えてください' : '破棄できませんでした');
    } finally {
      setBusy(null);
    }
  };

  return (
    <View style={[st.card, !pending && st.cardDone]}>
      <View style={st.head}>
        <Ionicons name={pending ? 'paper-plane-outline' : p.status === 'rejected' ? 'close-circle-outline' : 'checkmark-circle-outline'} size={15} color="#245e49" />
        <Text style={st.title} numberOfLines={1}>{channel} → {ad.to_name || ad.to || '相手'}</Text>
        {state ? <Text style={st.state}>{state}</Text> : null}
      </View>
      {ad.subject ? <Text style={st.subject} numberOfLines={2}>件名: {ad.subject}</Text> : null}
      {pending ? (
        <TextInput style={st.body} value={body} multiline editable={!busy}
          onChangeText={(t) => { setBody(t); setDirty(t !== loaded.current); }} />
      ) : (
        <Text style={[st.body, st.bodyRead]} selectable numberOfLines={8}>{body}</Text>
      )}
      {ad.attachments?.length ? (
        <View style={{ gap: 2 }}>{ad.attachments.map((f) => <Text key={f.url} style={st.muted}>📎 {f.name}</Text>)}</View>
      ) : null}
      {error ? <Text style={st.error}>{error}</Text> : null}
      {pending ? (
        <View style={st.buttons}>
          <Pressable style={({ pressed }) => [st.btn, st.ghost, pressed && st.pressed]} disabled={!!busy} onPress={() => act('discard')}>
            <Text style={st.ghostText}>{busy === 'discard' ? '破棄しています…' : '破棄'}</Text>
          </Pressable>
          <Pressable style={({ pressed }) => [st.btn, st.primary, (pressed || busy === 'send') && st.pressed]} disabled={!!busy} onPress={() => act('send')}>
            <Ionicons name="send" size={13} color="#ffffff" />
            <Text style={st.primaryText}>{busy === 'send' ? '送っています…' : dirty ? '直した文で送る' : '送信'}</Text>
          </Pressable>
        </View>
      ) : null}
    </View>
  );
}

const st = StyleSheet.create({
  card: { borderWidth: 1, borderColor: '#cfdcd5', backgroundColor: '#ffffff', borderRadius: 14, padding: 12, gap: 8, alignSelf: 'stretch' },
  cardDone: { backgroundColor: '#f6f8f7' },
  head: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  title: { flex: 1, fontSize: 14, fontWeight: '700', color: '#162e27' },
  state: { fontSize: 12, color: '#59685f' },
  subject: { fontSize: 13, color: '#3d4b44' },
  body: { minHeight: 80, borderWidth: 1, borderColor: '#dfe7e2', borderRadius: 10, padding: 10, fontSize: 15, lineHeight: 22, color: '#162e27', textAlignVertical: 'top', backgroundColor: '#fbfcfb' },
  bodyRead: { minHeight: 0, borderWidth: 0, padding: 0, backgroundColor: 'transparent', color: '#3d4b44' },
  buttons: { flexDirection: 'row', justifyContent: 'flex-end', gap: 8 },
  btn: { flexDirection: 'row', alignItems: 'center', gap: 6, borderRadius: 999, paddingHorizontal: 14, paddingVertical: 8 },
  ghost: { borderWidth: 1, borderColor: '#cfdcd5' },
  ghostText: { color: '#59685f', fontSize: 13 },
  primary: { backgroundColor: '#245e49' },
  primaryText: { color: '#ffffff', fontSize: 13, fontWeight: '700' },
  pressed: { opacity: 0.6 },
  muted: { fontSize: 12, color: '#59685f' },
  error: { fontSize: 12, color: '#a2413b' },
  rows: { gap: 4 },
  row: { flexDirection: 'row', gap: 10 },
  rowLabel: { width: 84, fontSize: 13, color: '#59685f' },
  rowValue: { flex: 1, fontSize: 14, color: '#162e27', fontWeight: '600' },
  choice: { flexDirection: 'row', alignItems: 'center', gap: 8, borderWidth: 1, borderColor: '#dfe7e2', borderRadius: 10, paddingHorizontal: 10, paddingVertical: 8 },
  choiceOn: { borderColor: '#245e49', backgroundColor: '#eef4f0' },
  choiceText: { flex: 1, fontSize: 14, color: '#162e27' },
});
