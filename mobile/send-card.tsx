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
  const state = p.status === 'sent' ? '送信済み' : p.status === 'sending' ? '送信中' : p.status === 'rejected' ? '破棄しました' : '';

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
});
