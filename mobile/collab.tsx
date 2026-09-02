// コラボチャット（外部クライアント窓口）のネイティブ画面。
// voice.tsx と同じ流儀: App.tsx からは import と画面分岐だけで使える自己完結モジュール。
// 通信は REST ポーリングのみ（Web 版の Vercel フォールバックと同一経路＝確実に動く）。
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ActivityIndicator, FlatList, KeyboardAvoidingView, Linking, Platform, Pressable,
  StyleSheet, Text, TextInput, View,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';

// 既存パレット踏襲（App.tsx の実質規約）
const C = {
  bg: '#12110f',
  card: '#1d1b18',
  text: '#f4f0e8',
  muted: '#a7a19a',
  muted2: '#77736b',
  accent: '#7fd1c7',
  danger: '#ff5a3d',
  border: '#3a3631',
  violet: '#a78bfa',
  violetBg: '#2a2438',
};

type RequestFn = <T = any>(endpoint: string, options?: any) => Promise<T>;

export interface CollabRoomSummary {
  id: string;
  title: string;
  guest_count: number;
  last_message: string | null;
  last_message_at: string | null;
  updated_at: string;
}

interface CollabMessage {
  id: string;
  room_id: string;
  sender_type: string;
  sender_name: string;
  content: string;
  metadata?: {
    visibility?: string;
    reply_to?: { id?: string; sender_name?: string; content?: string };
    reactions?: Record<string, string[]>;
    file?: { name: string; url: string; type?: string; size?: number };
    client_msg_id?: string;
  } | null;
  created_at: string;
}

interface Participants {
  owner: { name: string; last_read_at: string | null };
  guests: { id: string; name: string; joined_at: string | null; last_read_at: string | null }[];
}

interface Proposal {
  id: string;
  status: string;
  content: string;
  action_data?: { to?: string; to_name?: string | null; intent?: string | null } | null;
}

const AVATAR_COLORS = ['#3b82f6', '#8b5cf6', '#10b981', '#f59e0b', '#ef4444', '#6366f1'];
function avatarColor(seed: string): string {
  let h = 0;
  for (let i = 0; i < seed.length; i++) h = (h * 31 + seed.charCodeAt(i)) >>> 0;
  return AVATAR_COLORS[h % AVATAR_COLORS.length];
}

function fmtListTime(dateStr?: string | null): string {
  if (!dateStr) return '';
  const d = new Date(dateStr);
  if (Number.isNaN(d.getTime())) return '';
  const now = new Date();
  if (d.toDateString() === now.toDateString()) {
    return d.toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit' });
  }
  const y = new Date(now); y.setDate(now.getDate() - 1);
  if (d.toDateString() === y.toDateString()) return '昨日';
  return `${d.getMonth() + 1}/${d.getDate()}`;
}

function fmtTime(dateStr: string): string {
  const d = new Date(dateStr);
  return d.toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit' });
}

const isStamp = (content: string) =>
  /^(\p{Extended_Pictographic}(️)?){1,2}$/u.test((content || '').trim());

// ============================================================
// ルーム一覧
// ============================================================
export function CollabRoomsScreen({ request, onOpenRoom, onBack, topInset }: {
  request: RequestFn;
  onOpenRoom: (room: CollabRoomSummary) => void;
  onBack: () => void;
  topInset: number;
}) {
  const [rooms, setRooms] = useState<CollabRoomSummary[] | null>(null);
  const [myName, setMyName] = useState('');
  const [editingProfile, setEditingProfile] = useState(false);
  const [nameInput, setNameInput] = useState('');

  const load = useCallback(() => {
    request<{ rooms: CollabRoomSummary[] }>('/collab/rooms')
      .then((d) => setRooms(d.rooms))
      .catch(() => {});
  }, [request]);

  useEffect(() => {
    load();
    request<{ display_name?: string; email?: string }>('/chat/me')
      .then((u) => setMyName(u.display_name || (u.email || '').split('@')[0] || ''))
      .catch(() => {});
    const t = setInterval(load, 20_000);
    return () => clearInterval(t);
  }, [load, request]);

  const saveProfile = async () => {
    const v = nameInput.trim();
    setEditingProfile(false);
    if (!v || v === myName) return;
    try {
      await request('/chat/profile', { method: 'POST', body: JSON.stringify({ display_name: v }) });
      setMyName(v);
    } catch { /* keep old name */ }
  };

  return (
    <View style={[s.screen, { paddingTop: topInset }]}>
      <View style={s.appBar}>
        <Pressable onPress={onBack} hitSlop={12}>
          <Ionicons name="chevron-back" size={24} color={C.text} />
        </Pressable>
        <Text style={[s.appBarTitle, { flex: 1 }]}>コミュニケーション</Text>
        {/* 自分のプロフィール（タップで名前編集） */}
        <Pressable style={s.profileChip} onPress={() => { setNameInput(myName); setEditingProfile(true); }}>
          <View style={s.profileAvatar}>
            <Ionicons name="person" size={14} color="#0c1513" />
          </View>
          {!!myName && <Text style={s.profileName} numberOfLines={1}>{myName}</Text>}
        </Pressable>
      </View>

      {editingProfile && (
        <View style={s.profileEditRow}>
          <TextInput
            style={s.profileEditInput}
            value={nameInput}
            onChangeText={setNameInput}
            autoFocus
            placeholder="表示名"
            placeholderTextColor={C.muted2}
            onSubmitEditing={saveProfile}
          />
          <Pressable style={s.profileEditSave} onPress={saveProfile}>
            <Text style={{ color: '#0c1513', fontWeight: '600', fontSize: 13 }}>保存</Text>
          </Pressable>
          <Pressable hitSlop={8} onPress={() => setEditingProfile(false)}>
            <Ionicons name="close" size={18} color={C.muted} />
          </Pressable>
        </View>
      )}
      {rooms === null ? (
        <ActivityIndicator style={{ marginTop: 40 }} color={C.accent} />
      ) : rooms.length === 0 ? (
        <Text style={s.emptyText}>まだ窓口がありません。PCの「新しいルーム」またはダンへの依頼で作成できます。</Text>
      ) : (
        <FlatList
          data={rooms}
          keyExtractor={(r) => r.id}
          renderItem={({ item }) => (
            <Pressable style={s.roomRow} onPress={() => onOpenRoom(item)}>
              <View style={[s.avatar, { backgroundColor: avatarColor(item.id) }]}>
                <Ionicons name="person" size={22} color="#ffffffcc" />
              </View>
              <View style={{ flex: 1, minWidth: 0 }}>
                <View style={s.roomTop}>
                  <Text style={s.roomTitle} numberOfLines={1}>{item.title}</Text>
                  <Text style={s.roomTime}>{fmtListTime(item.last_message_at || item.updated_at)}</Text>
                </View>
                <Text style={s.roomPreview} numberOfLines={1}>
                  {item.last_message || 'まだメッセージはありません'}
                </Text>
              </View>
            </Pressable>
          )}
          ItemSeparatorComponent={() => <View style={s.sep} />}
        />
      )}
    </View>
  );
}

// ============================================================
// チャット画面
// ============================================================
export function CollabChatScreen({ request, apiBase, roomId, roomTitle, onBack, topInset, bottomInset }: {
  request: RequestFn;
  apiBase: string;
  roomId: string;
  roomTitle?: string;
  onBack: () => void;
  topInset: number;
  bottomInset: number;
}) {
  const [title, setTitle] = useState(roomTitle || '');
  const [messages, setMessages] = useState<CollabMessage[]>([]);
  const [participants, setParticipants] = useState<Participants | null>(null);
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [danThinking, setDanThinking] = useState(false);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const listRef = useRef<FlatList>(null);

  // 受信合流点: client_msg_id の仮バブルは差し替え（Web と同一ロジック）
  const mergeMessage = useCallback((msg: CollabMessage) => {
    setMessages((prev) => {
      if (prev.some((m) => m.id === msg.id)) return prev;
      const cid = msg.metadata?.client_msg_id;
      if (cid && prev.some((m) => m.id === cid)) {
        return prev.map((m) => (m.id === cid ? msg : m));
      }
      return [...prev, msg];
    });
  }, []);

  // ルーム情報（通知起動でタイトル未取得の場合）
  useEffect(() => {
    if (!title) {
      request<{ title: string }>(`/collab/rooms/${roomId}`)
        .then((r) => setTitle(r.title))
        .catch(() => {});
    }
  }, [roomId, title, request]);

  // メッセージ＋考え中: 4秒ポーリング
  useEffect(() => {
    let alive = true;
    const load = () => {
      request<{ messages: CollabMessage[] }>(`/collab/rooms/${roomId}/messages?limit=50`)
        .then((d) => { if (alive) setMessages((prev) => reconcileList(prev, d.messages)); })
        .catch(() => {});
      request<{ thinking: boolean }>(`/collab/rooms/${roomId}/dan-status`)
        .then((d) => { if (alive) setDanThinking(!!d.thinking); })
        .catch(() => {});
    };
    load();
    const t = setInterval(load, 4_000);
    return () => { alive = false; clearInterval(t); };
  }, [roomId, request]);

  // 参加者＋既読位置: 10秒。自分の既読も更新
  useEffect(() => {
    const tick = () => {
      request<Participants>(`/collab/rooms/${roomId}/participants`)
        .then(setParticipants).catch(() => {});
      request(`/collab/rooms/${roomId}/read`, { method: 'POST' }).catch(() => {});
    };
    tick();
    const t = setInterval(tick, 10_000);
    return () => clearInterval(t);
  }, [roomId, request]);

  // 送信案カード: 10秒
  useEffect(() => {
    const tick = () => {
      request<{ proposals: { id: string }[] }>(`/chat/proposals/outbound-for-collab/${roomId}`)
        .then(async (d) => {
          const pend: Proposal[] = [];
          for (const p of d.proposals) {
            try {
              const full = await request<Proposal>(`/chat/proposals/${p.id}`);
              if (full.status === 'pending') pend.push(full);
            } catch { /* skip */ }
          }
          setProposals(pend);
        })
        .catch(() => {});
    };
    tick();
    const t = setInterval(tick, 10_000);
    return () => clearInterval(t);
  }, [roomId, request]);

  // 送信（楽観表示＋client_msg_id 差し替え）
  const send = useCallback(async (content: string, extraMeta?: Record<string, unknown>) => {
    const text = content.trim();
    if (!text) return;
    const tempId = `temp-${Date.now()}`;
    const metadata: Record<string, unknown> = { ...(extraMeta || {}), client_msg_id: tempId };
    const optimistic: CollabMessage = {
      id: tempId, room_id: roomId, sender_type: 'owner',
      sender_name: participants?.owner.name || 'あなた',
      content: text, metadata: metadata as CollabMessage['metadata'],
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, optimistic]);
    try {
      const sent = await request<CollabMessage>(`/collab/rooms/${roomId}/messages`, {
        method: 'POST',
        body: JSON.stringify({ content: text, metadata }),
      });
      mergeMessage(sent);
    } catch {
      setMessages((prev) => prev.filter((m) => m.id !== tempId));
      throw new Error('send failed');
    }
  }, [roomId, request, participants, mergeMessage]);

  const handleSend = useCallback(async () => {
    const text = input.trim();
    if (!text || sending) return;
    setInput('');
    setSending(true);
    try {
      await send(text);
    } catch {
      setInput(text);
    } finally {
      setSending(false);
    }
  }, [input, sending, send]);

  // 相談スレッド構造（Web と同一: 親=ダンの非公開、子=reply_to 付き非公開）
  const messageIds = useMemo(() => new Set(messages.map((m) => m.id)), [messages]);
  const threadMap = useMemo(() => {
    const map = new Map<string, CollabMessage[]>();
    for (const m of messages) {
      const md = m.metadata;
      if (
        (m.sender_type === 'owner' || m.sender_type === 'dan_owner') &&
        md?.visibility === 'owner_only' && md?.reply_to?.id && messageIds.has(md.reply_to.id)
      ) {
        const arr = map.get(md.reply_to.id) || [];
        arr.push(m);
        map.set(md.reply_to.id, arr);
      }
    }
    return map;
  }, [messages, messageIds]);

  // 既読: 相手の既読位置以前の自分側公開メッセージの最後
  const guestMaxRead = Math.max(
    0,
    ...((participants?.guests ?? []).map((g) => (g.last_read_at ? new Date(g.last_read_at).getTime() : 0)))
  );
  const lastReadOwnId = useMemo(() => {
    let id: string | null = null;
    for (const m of messages) {
      if (
        (m.sender_type === 'owner' || m.sender_type === 'dan_owner') &&
        !m.metadata?.visibility && new Date(m.created_at).getTime() <= guestMaxRead
      ) id = m.id;
    }
    return id;
  }, [messages, guestMaxRead]);

  // 表示リスト（スレッド子は除外、inverted 用に逆順）
  const listData = useMemo(() => {
    const rows = messages.filter((m) => {
      const md = m.metadata;
      return !(
        (m.sender_type === 'owner' || m.sender_type === 'dan_owner') &&
        md?.visibility === 'owner_only' && md?.reply_to?.id && messageIds.has(md.reply_to.id)
      );
    });
    return [...rows].reverse();
  }, [messages, messageIds]);

  const names = participants
    ? `${1 + participants.guests.length}人: ${[participants.owner.name, ...participants.guests.map((g) => g.name)].join('、')}`
    : '';

  return (
    <KeyboardAvoidingView
      style={[s.screen, { paddingTop: topInset }]}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      <View style={s.appBar}>
        <Pressable onPress={onBack} hitSlop={12}>
          <Ionicons name="chevron-back" size={24} color={C.text} />
        </Pressable>
        <View style={{ flex: 1, minWidth: 0 }}>
          <Text style={s.appBarTitle} numberOfLines={1}>{title || '...'}</Text>
          {!!names && <Text style={s.appBarSub} numberOfLines={1}>{names}</Text>}
        </View>
        <View style={{ width: 24 }} />
      </View>

      <FlatList
        ref={listRef}
        inverted
        data={listData}
        keyExtractor={(m) => m.metadata?.client_msg_id || m.id}
        contentContainerStyle={{ paddingHorizontal: 12, paddingVertical: 10 }}
        renderItem={({ item }) => (
          <MessageRow
            msg={item}
            threadReplies={threadMap.get(item.id)}
            showRead={item.id === lastReadOwnId}
            apiBase={apiBase}
            onThreadReply={(parent, text) =>
              send(text, {
                visibility: 'owner_only',
                reply_to: {
                  id: parent.id,
                  sender_name: parent.sender_name,
                  sender_type: parent.sender_type,
                  content: (parent.content || '').slice(0, 200),
                },
              }).catch(() => {})
            }
          />
        )}
        ListHeaderComponent={
          <View>
            {danThinking && (
              <View style={s.thinkingRow}>
                <ActivityIndicator size="small" color={C.violet} />
                <Text style={s.thinkingText}>考え中...</Text>
              </View>
            )}
            {proposals.map((p) => (
              <ProposalCard key={p.id} proposal={p} request={request} />
            ))}
          </View>
        }
      />

      <View style={[s.composer, { paddingBottom: Math.max(bottomInset, 8) }]}>
        <TextInput
          style={s.input}
          placeholder="メッセージを入力...（相手に届きます）"
          placeholderTextColor={C.muted2}
          value={input}
          onChangeText={setInput}
          multiline
        />
        <Pressable
          style={[s.sendBtn, (!input.trim() || sending) && { opacity: 0.4 }]}
          onPress={handleSend}
          disabled={!input.trim() || sending}
        >
          <Ionicons name="send" size={18} color="#0c1513" />
        </Pressable>
      </View>
    </KeyboardAvoidingView>
  );
}

// サーバーの一覧で状態を更新しつつ、送信直後の仮バブル（temp-*）は消さない
function reconcileList(prev: CollabMessage[], server: CollabMessage[]): CollabMessage[] {
  const serverIds = new Set(server.map((m) => m.id));
  const serverCids = new Set(server.map((m) => m.metadata?.client_msg_id).filter(Boolean));
  const keepTemps = prev.filter(
    (m) => m.id.startsWith('temp-') && !serverIds.has(m.id) && !serverCids.has(m.id)
  );
  return [...server, ...keepTemps];
}

// ============================================================
// メッセージ行
// ============================================================
function MessageRow({ msg, threadReplies, showRead, apiBase, onThreadReply }: {
  msg: CollabMessage;
  threadReplies?: CollabMessage[];
  showRead: boolean;
  apiBase: string;
  onThreadReply: (parent: CollabMessage, text: string) => void;
}) {
  const isDan = msg.sender_type.startsWith('dan_');
  const isOwnSide = msg.sender_type === 'owner' || isDan;
  const isPrivate = msg.metadata?.visibility === 'owner_only';
  const stamp = isStamp(msg.content);
  const reactions = msg.metadata?.reactions;
  const file = msg.metadata?.file;
  const [replyText, setReplyText] = useState('');

  // ダンの相談（非公開）はLINEバブルではなく専用パネル（スレッド付き）
  if (isDan && isPrivate) {
    return (
      <View style={[s.msgWrap, s.msgRight]}>
        <View style={[s.bubble, s.bubblePrivate]}>
          <View style={s.msgHead}>
            <Ionicons name="hardware-chip-outline" size={12} color={C.violet} />
            <Text style={[s.msgName, { color: C.violet }]}>ダン</Text>
            <Text style={s.privateTag}>非公開</Text>
            <Text style={s.msgTime}>{fmtTime(msg.created_at)}</Text>
          </View>
          <Text style={s.msgText}>{msg.content}</Text>
          <View style={s.thread}>
            {(threadReplies || []).map((r) => (
              <View key={r.id} style={[s.threadItem, r.sender_type === 'dan_owner' && { backgroundColor: '#332b47' }]}>
                <Text style={s.threadName}>
                  {r.sender_type === 'dan_owner' ? 'ダン' : 'あなた → ダン'}
                </Text>
                <Text style={s.msgText}>{r.content}</Text>
              </View>
            ))}
            <View style={s.threadInputRow}>
              <TextInput
                style={s.threadInput}
                placeholder="ダンに返事…（相手には見えません）"
                placeholderTextColor={C.muted2}
                value={replyText}
                onChangeText={setReplyText}
              />
              <Pressable
                style={[s.threadSend, !replyText.trim() && { opacity: 0.4 }]}
                disabled={!replyText.trim()}
                onPress={() => {
                  const t = replyText.trim();
                  if (!t) return;
                  setReplyText('');
                  onThreadReply(msg, t);
                }}
              >
                <Ionicons name="send" size={14} color="#fff" />
              </Pressable>
            </View>
          </View>
        </View>
      </View>
    );
  }

  // LINE式: 名前は相手側だけバブルの上（自分の名前は出さない。ダンだけ右側でも小さく表示）、
  // 時刻・既読はバブルの外側（横・下揃え）
  const bubbleBody = (
    <View
      style={[
        stamp ? s.stampBox : s.bubble,
        !stamp && (isPrivate ? s.bubblePrivate : isOwnSide ? s.bubbleOwn : s.bubbleOther),
      ]}
    >
      {file ? (
        <Pressable onPress={() => Linking.openURL(file.url.startsWith('http') ? file.url : `${apiBase}${file.url}`)}>
          <Text style={[s.fileLink, isOwnSide && !isPrivate ? { color: '#0c1513' } : undefined]}>
            📎 {file.name}
          </Text>
        </Pressable>
      ) : (
        <Text
          style={[
            stamp ? s.stampText : s.msgText,
            !stamp && isOwnSide && !isPrivate ? { color: '#0c1513' } : undefined,
          ]}
        >
          {msg.content}
        </Text>
      )}
      {!!reactions && Object.keys(reactions).length > 0 && (
        <View style={s.reactionRow}>
          {Object.entries(reactions).map(([emoji, ns]) => (
            <View key={emoji} style={s.reactionChip}>
              <Text style={{ fontSize: 13 }}>{emoji}{(ns || []).length > 1 ? ` ${ns.length}` : ''}</Text>
            </View>
          ))}
        </View>
      )}
    </View>
  );

  return (
    <View style={[s.msgWrap, isOwnSide ? s.msgRight : s.msgLeft]}>
      {!isOwnSide && <Text style={s.senderName}>{msg.sender_name}</Text>}
      {isOwnSide && isDan && <Text style={[s.senderName, { textAlign: 'right' }]}>ダン</Text>}
      <View style={[s.msgLine, { flexDirection: isOwnSide ? 'row' : 'row-reverse' }]}>
        <View style={s.metaCol}>
          {showRead && <Text style={s.metaRead}>既読</Text>}
          <Text style={s.metaTime}>{fmtTime(msg.created_at)}</Text>
        </View>
        {bubbleBody}
      </View>
    </View>
  );
}

// ============================================================
// 送信案カード（承認・編集・破棄）
// ============================================================
function ProposalCard({ proposal, request }: { proposal: Proposal; request: RequestFn }) {
  const [body, setBody] = useState(proposal.content || '');
  const [busy, setBusy] = useState<'send' | 'discard' | null>(null);
  const [gone, setGone] = useState(false);
  const ad = proposal.action_data || {};

  if (gone) return null;

  const act = async (kind: 'send' | 'discard') => {
    setBusy(kind);
    try {
      if (kind === 'send' && body !== proposal.content) {
        await request(`/chat/proposals/${proposal.id}/draft`, {
          method: 'PATCH',
          body: JSON.stringify({ body }),
        });
      }
      await request(`/chat/proposals/${proposal.id}/${kind === 'send' ? 'send' : 'discard'}`, { method: 'POST' });
      setGone(true);
    } catch {
      // 失敗時はカードを残す
    } finally {
      setBusy(null);
    }
  };

  return (
    <View style={s.card}>
      <View style={s.cardHead}>
        <Ionicons name="paper-plane-outline" size={14} color={C.accent} />
        <Text style={s.cardTitle} numberOfLines={1}>
          返信案 → {ad.to_name || ad.to || '相手'}{ad.intent ? ` — ${ad.intent}` : ''}
        </Text>
      </View>
      <TextInput
        style={s.cardBody}
        value={body}
        onChangeText={setBody}
        multiline
      />
      <View style={s.cardBtns}>
        <Pressable style={[s.cardBtn, s.cardBtnGhost]} disabled={!!busy} onPress={() => act('discard')}>
          {busy === 'discard' ? <ActivityIndicator size="small" color={C.muted} /> : <Text style={{ color: C.muted, fontSize: 13 }}>破棄</Text>}
        </Pressable>
        <Pressable style={[s.cardBtn, s.cardBtnPrimary]} disabled={!!busy} onPress={() => act('send')}>
          {busy === 'send' ? <ActivityIndicator size="small" color="#0c1513" /> : (
            <View style={{ flexDirection: 'row', alignItems: 'center', gap: 6 }}>
              <Ionicons name="send" size={14} color="#0c1513" />
              <Text style={{ color: '#0c1513', fontWeight: '600', fontSize: 13 }}>送信</Text>
            </View>
          )}
        </Pressable>
      </View>
    </View>
  );
}

const s = StyleSheet.create({
  screen: { flex: 1, backgroundColor: C.bg },
  appBar: {
    flexDirection: 'row', alignItems: 'center', gap: 10,
    paddingHorizontal: 14, paddingVertical: 10,
    borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: C.border,
  },
  appBarTitle: { color: C.text, fontSize: 17, fontWeight: '700' },
  appBarSub: { color: C.muted2, fontSize: 11, marginTop: 1 },

  profileChip: { flexDirection: 'row', alignItems: 'center', gap: 6, backgroundColor: C.card, borderRadius: 16, paddingLeft: 4, paddingRight: 10, paddingVertical: 4, maxWidth: 140 },
  profileAvatar: { width: 24, height: 24, borderRadius: 12, backgroundColor: C.accent, alignItems: 'center', justifyContent: 'center' },
  profileName: { color: C.text, fontSize: 12, flexShrink: 1 },
  profileEditRow: { flexDirection: 'row', alignItems: 'center', gap: 8, paddingHorizontal: 14, paddingVertical: 8, borderBottomWidth: StyleSheet.hairlineWidth, borderBottomColor: C.border },
  profileEditInput: { flex: 1, backgroundColor: C.card, borderRadius: 10, color: C.text, fontSize: 14, paddingHorizontal: 12, paddingVertical: 7 },
  profileEditSave: { backgroundColor: C.accent, borderRadius: 10, paddingHorizontal: 14, paddingVertical: 7 },

  senderName: { color: C.muted, fontSize: 11, marginBottom: 2, marginHorizontal: 4 },
  msgLine: { alignItems: 'flex-end', gap: 5 },
  metaCol: { alignItems: 'flex-end', justifyContent: 'flex-end' },
  metaRead: { color: C.muted2, fontSize: 9 },
  metaTime: { color: C.muted2, fontSize: 10 },
  stampBox: { paddingHorizontal: 2 },
  emptyText: { color: C.muted, fontSize: 13, textAlign: 'center', marginTop: 48, paddingHorizontal: 32, lineHeight: 20 },

  roomRow: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingHorizontal: 14, paddingVertical: 12 },
  avatar: { width: 46, height: 46, borderRadius: 23, alignItems: 'center', justifyContent: 'center' },
  avatarText: { color: '#fff', fontSize: 18, fontWeight: '700' },
  roomTop: { flexDirection: 'row', alignItems: 'baseline', justifyContent: 'space-between', gap: 8 },
  roomTitle: { color: C.text, fontSize: 15, fontWeight: '600', flexShrink: 1 },
  roomTime: { color: C.muted2, fontSize: 11 },
  roomPreview: { color: C.muted, fontSize: 13, marginTop: 2 },
  sep: { height: StyleSheet.hairlineWidth, backgroundColor: C.border, marginLeft: 72 },

  thinkingRow: { flexDirection: 'row', alignItems: 'center', gap: 8, alignSelf: 'flex-end', backgroundColor: C.violetBg, borderRadius: 12, paddingHorizontal: 12, paddingVertical: 8, marginTop: 8 },
  thinkingText: { color: C.violet, fontSize: 12 },

  msgWrap: { marginVertical: 4, maxWidth: '85%' },
  msgLeft: { alignSelf: 'flex-start' },
  msgRight: { alignSelf: 'flex-end' },
  bubble: { borderRadius: 14, paddingHorizontal: 12, paddingVertical: 8 },
  bubbleOther: { backgroundColor: C.card },
  bubbleOwn: { backgroundColor: C.accent },
  bubblePrivate: { backgroundColor: C.violetBg, borderWidth: 1, borderColor: '#4c3d6e', borderStyle: 'dashed' },
  msgHead: { flexDirection: 'row', alignItems: 'center', gap: 6, marginBottom: 3 },
  msgName: { fontSize: 11, fontWeight: '600' },
  privateTag: { fontSize: 9, color: C.violet, backgroundColor: '#3b2f57', borderRadius: 8, paddingHorizontal: 6, paddingVertical: 1, overflow: 'hidden' },
  msgTime: { fontSize: 10, color: C.muted2, marginLeft: 'auto' },
  msgText: { color: C.text, fontSize: 14.5, lineHeight: 21 },
  stampText: { fontSize: 34, lineHeight: 42, paddingVertical: 2 },
  fileLink: { color: C.accent, fontSize: 14, textDecorationLine: 'underline' },
  reactionRow: { flexDirection: 'row', gap: 6, marginTop: 5 },
  reactionChip: { backgroundColor: C.bg, borderWidth: 1, borderColor: C.border, borderRadius: 12, paddingHorizontal: 7, paddingVertical: 2 },
  readMark: { color: C.muted2, fontSize: 10, textAlign: 'right', marginTop: 2, marginRight: 4 },

  thread: { borderTopWidth: 1, borderTopColor: '#4c3d6e55', marginTop: 8, paddingTop: 8, gap: 6 },
  threadItem: { backgroundColor: '#241f33', borderRadius: 10, paddingHorizontal: 10, paddingVertical: 6 },
  threadName: { color: '#c4b5fd', fontSize: 10, marginBottom: 2 },
  threadInputRow: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  threadInput: { flex: 1, backgroundColor: '#1a1626', borderWidth: 1, borderColor: '#4c3d6e', borderRadius: 10, color: C.text, fontSize: 13, paddingHorizontal: 10, paddingVertical: 7 },
  threadSend: { backgroundColor: '#7c5cd6', borderRadius: 10, padding: 8 },

  card: { backgroundColor: C.card, borderWidth: 1, borderColor: C.accent + '66', borderRadius: 14, padding: 12, marginTop: 8 },
  cardHead: { flexDirection: 'row', alignItems: 'center', gap: 6, marginBottom: 8 },
  cardTitle: { color: C.text, fontSize: 12, fontWeight: '600', flex: 1 },
  cardBody: { backgroundColor: C.bg, borderWidth: 1, borderColor: C.border, borderRadius: 10, color: C.text, fontSize: 14, lineHeight: 20, padding: 10, minHeight: 80, textAlignVertical: 'top' },
  cardBtns: { flexDirection: 'row', justifyContent: 'flex-end', gap: 10, marginTop: 10 },
  cardBtn: { borderRadius: 10, paddingHorizontal: 16, paddingVertical: 8, alignItems: 'center', justifyContent: 'center' },
  cardBtnGhost: { borderWidth: 1, borderColor: C.border },
  cardBtnPrimary: { backgroundColor: C.accent },

  composer: {
    flexDirection: 'row', alignItems: 'flex-end', gap: 8,
    paddingHorizontal: 12, paddingTop: 8,
    borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: C.border,
    backgroundColor: C.bg,
  },
  input: {
    flex: 1, backgroundColor: C.card, borderRadius: 18, color: C.text,
    fontSize: 15, paddingHorizontal: 14, paddingVertical: 9, maxHeight: 110,
  },
  sendBtn: { backgroundColor: C.accent, borderRadius: 18, padding: 10 },
});
