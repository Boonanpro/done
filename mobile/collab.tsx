// コラボチャット（外部クライアント窓口）のネイティブ画面。
// voice.tsx と同じ流儀: App.tsx からは import と画面分岐だけで使える自己完結モジュール。
// 通信は REST ポーリングのみ（Web 版の Vercel フォールバックと同一経路＝確実に動く）。
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ActivityIndicator, Alert, FlatList, Image, KeyboardAvoidingView, Linking, Platform, Pressable,
  StyleSheet, Text, TextInput, View,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import * as ImagePicker from 'expo-image-picker';
import * as DocumentPicker from 'expo-document-picker';
import { animateNextLayout, pressedScale } from './motion';
import { MediaGrid, type MediaGridItem } from './media-grid';

const REACTION_CHOICES = ['🙏', '👍', '❤️', '😂', '🎉'];

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
  /** 相手の公開メッセージが自分の既読位置より後にある（サーバー判定） */
  unread?: boolean;
  unread_count?: number;
}

type CollabFile = { id?: string; name: string; url: string; type?: string; size?: number };
type PendingFile = { uri: string; name: string; mime: string };

interface CollabMessage {
  id: string;
  room_id: string;
  sender_type: string;
  sender_name: string;
  content: string;
  metadata?: {
    visibility?: string;
    reply_to?: { id?: string; sender_name?: string; sender_type?: string; content?: string };
    reactions?: Record<string, string[]>;
    file?: CollabFile;
    files?: CollabFile[];
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
  action_data?: {
    to?: string; to_name?: string | null; intent?: string | null;
    attachments?: { name: string; url: string; type?: string; size?: number }[] | null;
    sender?: 'dan' | 'owner' | null;
    revision?: number;
    dan_updated_at?: string | null;
    pending_update?: { body: string; at: string } | null;
  } | null;
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
                <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
                  <Text style={[s.roomPreview, { flex: 1 }, item.unread && { color: C.text, fontWeight: '600' }]} numberOfLines={1}>
                    {item.last_message || 'まだメッセージはありません'}
                  </Text>
                  {(item.unread_count ?? 0) > 0 ? (
                    <View style={s.unreadBadge}>
                      <Text style={s.unreadBadgeText}>{(item.unread_count ?? 0) > 99 ? '99+' : item.unread_count}</Text>
                    </View>
                  ) : item.unread ? <View style={s.unreadDot} /> : null}
                </View>
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
export function CollabChatScreen({ request, apiBase, token, roomId, roomTitle, onBack, topInset, bottomInset }: {
  request: RequestFn;
  apiBase: string;
  token: string | null;
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
  const [uploading, setUploading] = useState(false);
  // 送信前の添付（添付しただけでは送らない。送信ボタンで本文と一緒に1メッセージ）
  const [pending, setPending] = useState<PendingFile[]>([]);
  // 特定のメッセージへの返信（LINE式: 引用付き）
  const [replyTo, setReplyTo] = useState<CollabMessage | null>(null);
  const [highlightId, setHighlightId] = useState<string | null>(null);
  // 長押しメニュー（スタンプ/返信）を開いているメッセージ。画面のどこを触っても閉じる
  const [pickerFor, setPickerFor] = useState<string | null>(null);
  // WebSocket（dan.paina.info は Cloudflare の名前付きトンネル経由なので WS が通る。
  // 繋がっている間はポーリングを止め、届いた瞬間に画面へ出す）
  const [wsConnected, setWsConnected] = useState(false);
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

  // WebSocket: 新着・考え中・リアクションを押し込みで受け取る。
  // 切れたら指数バックオフで張り直し、その間はポーリングが受け持つ。
  useEffect(() => {
    if (!token || !roomId) return;
    let alive = true;
    let ws: WebSocket | null = null;
    let retry = 0;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const connect = () => {
      if (!alive) return;
      const wsUrl = `${apiBase.replace(/^http/, 'ws')}/api/v1/collab/ws/${roomId}`;
      ws = new WebSocket(wsUrl);
      ws.onopen = () => ws?.send(JSON.stringify({ type: 'auth', token }));
      ws.onmessage = (e) => {
        if (!alive) return;
        try {
          const d = JSON.parse(String(e.data));
          switch (d.type) {
            case 'auth_success':
              retry = 0;
              setWsConnected(true);
              break;
            case 'new_message':
              animateNextLayout();
              mergeMessage(d.message);
              if (String(d.message?.sender_type || '').startsWith('dan_')) setDanThinking(false);
              break;
            case 'dan_thinking': setDanThinking(true); break;
            case 'dan_done': setDanThinking(false); break;
            case 'reaction':
              setMessages((prev) => prev.map((m) => (
                m.id === d.message_id ? { ...m, metadata: { ...(m.metadata || {}), reactions: d.reactions } } : m
              )));
              break;
          }
        } catch { /* 壊れた行は捨てる */ }
      };
      ws.onerror = () => { try { ws?.close(); } catch { /* noop */ } };
      ws.onclose = () => {
        if (!alive) return;
        setWsConnected(false);
        const delay = Math.min(1000 * 2 ** retry, 30000);
        retry += 1;
        timer = setTimeout(connect, delay);
      };
    };
    connect();
    return () => {
      alive = false;
      if (timer) clearTimeout(timer);
      try { ws?.close(); } catch { /* noop */ }
      setWsConnected(false);
    };
  }, [roomId, token, apiBase, mergeMessage]);

  // 受信のフォールバック: WS が繋がっていない時だけ4秒ポーリング
  useEffect(() => {
    let alive = true;
    const load = () => {
      request<{ messages: CollabMessage[] }>(`/collab/rooms/${roomId}/messages?limit=50`)
        .then((d) => {
          if (!alive) return;
          setMessages((prev) => {
            const next = reconcileList(prev, d.messages);
            if (next.length > prev.length) animateNextLayout();
            return next;
          });
        })
        .catch(() => {});
      request<{ thinking: boolean }>(`/collab/rooms/${roomId}/dan-status`)
        .then((d) => { if (alive) setDanThinking(!!d.thinking); })
        .catch(() => {});
    };
    load();
    if (wsConnected) return () => { alive = false; };   // 初回だけ取り、あとは WS 任せ
    const t = setInterval(load, 4_000);
    return () => { alive = false; clearInterval(t); };
  }, [roomId, request, wsConnected]);

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
          setProposals((prev) => {
            if (pend.length !== prev.length) animateNextLayout();
            return pend;
          });
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
    if (!text && !(extraMeta && (extraMeta as { files?: unknown[] }).files?.length)) return;
    const tempId = `temp-${Date.now()}`;
    const metadata: Record<string, unknown> = { ...(extraMeta || {}), client_msg_id: tempId };
    const optimistic: CollabMessage = {
      id: tempId, room_id: roomId, sender_type: 'owner',
      sender_name: participants?.owner.name || 'あなた',
      content: text, metadata: metadata as CollabMessage['metadata'],
      created_at: new Date().toISOString(),
    };
    animateNextLayout();
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

  // リアクション: 押した瞬間に反映し、サーバーの確定値で上書き（トグル）
  const myName = participants?.owner.name || '';
  const react = useCallback(async (messageId: string, emoji: string) => {
    if (messageId.startsWith('temp-')) return;
    setMessages((prev) => prev.map((m) => {
      if (m.id !== messageId) return m;
      const reactions = { ...(m.metadata?.reactions || {}) };
      const names = [...(reactions[emoji] || [])];
      const idx = myName ? names.indexOf(myName) : -1;
      if (idx >= 0) names.splice(idx, 1); else names.push(myName || 'あなた');
      if (names.length) reactions[emoji] = names; else delete reactions[emoji];
      return { ...m, metadata: { ...(m.metadata || {}), reactions } };
    }));
    try {
      const r = await request<{ reactions: Record<string, string[]> }>(
        `/collab/rooms/${roomId}/messages/${messageId}/react`,
        { method: 'POST', body: JSON.stringify({ emoji }) },
      );
      setMessages((prev) => prev.map((m) => (
        m.id === messageId ? { ...m, metadata: { ...(m.metadata || {}), reactions: r.reactions } } : m
      )));
    } catch { /* 次のポーリングで実状態に戻る */ }
  }, [roomId, request, myName]);

  // 添付: 写真・動画（複数）またはファイル → 全部アップロード → 1メッセージ（LINE式グリッド）
  const uploadOne = useCallback(async (uri: string, name: string, mime: string): Promise<CollabFile> => {
    const form = new FormData();
    form.append('file', { uri, name, type: mime } as unknown as Blob);
    const res = await fetch(`${apiBase}/api/v1/collab/rooms/${roomId}/files`, {
      method: 'POST',
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
      body: form,
    });
    if (!res.ok) throw new Error(`upload ${res.status}`);
    const d = await res.json();
    return { id: d.id, name: d.file_name, url: d.file_path, type: d.file_type || mime, size: d.file_size };
  }, [apiBase, roomId, token]);

  const handleSend = useCallback(async () => {
    const text = input.trim();
    if ((!text && pending.length === 0) || sending || uploading) return;
    const filesToSend = pending;
    let extra: Record<string, unknown> | undefined;
    const savedReplyTo = replyTo;
    if (savedReplyTo) {
      extra = {
        reply_to: {
          id: savedReplyTo.id,
          sender_name: savedReplyTo.sender_name,
          sender_type: savedReplyTo.sender_type,
          content: (savedReplyTo.content || '').slice(0, 200),
        },
      };
      setReplyTo(null);
    }
    if (filesToSend.length > 0) {
      setUploading(true);
      try {
        const files: CollabFile[] = [];
        for (const p of filesToSend) files.push(await uploadOne(p.uri, p.name, p.mime));
        extra = { ...(extra || {}), files, file: files[0] };
        setPending([]);
      } catch (e) {
        Alert.alert('アップロードに失敗しました', String((e as Error).message));
        setUploading(false);
        return;
      }
      setUploading(false);
    }
    setInput('');
    setSending(true);
    try {
      await send(text, extra);
    } catch {
      setInput(text);
      if (filesToSend.length > 0) setPending(filesToSend);
      if (savedReplyTo) setReplyTo(savedReplyTo);
    } finally {
      setSending(false);
    }
  }, [input, pending, sending, uploading, send, uploadOne, replyTo]);



  const sendFiles = useCallback(async (picked: PendingFile[]) => {
    if (picked.length === 0) return;
    animateNextLayout();
    setPending((prev) => [...prev, ...picked]);
  }, []);

  const pickMedia = useCallback(async () => {
    const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!perm.granted) { Alert.alert('権限が必要です', '設定アプリから写真へのアクセスを許可してください。'); return; }
    const r = await ImagePicker.launchImageLibraryAsync({ mediaTypes: ['images', 'videos'], allowsMultipleSelection: true, quality: 0.9 });
    if (r.canceled) return;
    await sendFiles(r.assets.map((a, i) => {
      const isVideo = a.type === 'video';
      return {
        uri: a.uri,
        name: a.fileName || `${isVideo ? 'video' : 'image'}-${Date.now()}-${i}.${isVideo ? 'mp4' : 'jpg'}`,
        mime: a.mimeType || (isVideo ? 'video/mp4' : 'image/jpeg'),
      };
    }));
  }, [sendFiles]);

  const pickDocument = useCallback(async () => {
    const r = await DocumentPicker.getDocumentAsync({ multiple: true, copyToCacheDirectory: true });
    if (r.canceled) return;
    await sendFiles(r.assets.map((a, i) => ({ uri: a.uri, name: a.name || `file-${Date.now()}-${i}`, mime: a.mimeType || 'application/octet-stream' })));
  }, [sendFiles]);

  const openAttach = useCallback(() => {
    Alert.alert('添付', undefined, [
      { text: '写真・動画', onPress: () => { pickMedia().catch(() => {}); } },
      { text: 'ファイル', onPress: () => { pickDocument().catch(() => {}); } },
      { text: 'キャンセル', style: 'cancel' },
    ]);
  }, [pickMedia, pickDocument]);

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

  // 引用をタップ → 元メッセージへスクロールして一瞬ハイライト
  const jumpTo = useCallback((id: string) => {
    const idx = listData.findIndex((m) => m.id === id);
    if (idx < 0) return;
    listRef.current?.scrollToIndex({ index: idx, animated: true, viewPosition: 0.5 });
    setHighlightId(id);
    setTimeout(() => setHighlightId((cur) => (cur === id ? null : cur)), 1500);
  }, [listData]);

  const names = participants
    ? `${1 + participants.guests.length}人: ${[participants.owner.name, ...participants.guests.map((g) => g.name)].join('、')}`
    : '';

  return (
    <KeyboardAvoidingView
      style={[s.screen, { paddingTop: topInset }]}
      behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
      // メニューが開いている時は、画面のどこを触っても閉じる（メニュー自身は stopPropagation で除外）
      onTouchStart={() => { if (pickerFor) setPickerFor(null); }}
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
        onScrollToIndexFailed={(info) => {
          setTimeout(() => listRef.current?.scrollToIndex({ index: info.index, animated: true, viewPosition: 0.5 }), 300);
        }}
        contentContainerStyle={{ paddingHorizontal: 12, paddingVertical: 10 }}
        renderItem={({ item }) => (
          <MessageRow
            msg={item}
            threadReplies={threadMap.get(item.id)}
            showRead={item.id === lastReadOwnId}
            apiBase={apiBase}
            myName={myName}
            onReact={react}
            onReply={(m) => setReplyTo(m)}
            onJump={jumpTo}
            highlighted={highlightId === item.id}
            pickerOpen={pickerFor === item.id}
            onTogglePicker={() => setPickerFor((cur) => (cur === item.id ? null : item.id))}
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
              <ProposalCard key={p.id} proposal={p} request={request} apiBase={apiBase} />
            ))}
          </View>
        }
      />

      {replyTo && (
        <View style={s.replyBar}>
          <Ionicons name="arrow-undo" size={14} color={C.accent} />
          <View style={{ flex: 1, minWidth: 0 }}>
            <Text style={s.replyBarName} numberOfLines={1}>
              {replyTo.sender_type.startsWith('dan_') ? 'ダン' : replyTo.sender_name}に返信
            </Text>
            <Text style={s.replyBarText} numberOfLines={1}>{previewOf(replyTo)}</Text>
          </View>
          <Pressable hitSlop={8} onPress={() => setReplyTo(null)}>
            <Ionicons name="close" size={18} color={C.muted} />
          </Pressable>
        </View>
      )}
      {pending.length > 0 && (
        <View style={s.pendingStrip}>
          {pending.map((p, i) => (
            <View key={`${p.uri}-${i}`} style={s.pendingItem}>
              {p.mime.startsWith('image/') ? (
                <Image source={{ uri: p.uri }} style={s.pendingThumb} />
              ) : (
                <View style={[s.pendingThumb, s.pendingFileBox]}>
                  <Ionicons name={p.mime.startsWith('video/') ? 'videocam' : 'document-text'} size={20} color={C.muted} />
                  <Text style={s.pendingName} numberOfLines={1}>{p.name}</Text>
                </View>
              )}
              <Pressable style={s.pendingRemove} hitSlop={6} onPress={() => setPending((prev) => prev.filter((_, j) => j !== i))}>
                <Ionicons name="close" size={12} color={C.bg} />
              </Pressable>
            </View>
          ))}
        </View>
      )}
      <View style={[s.composer, { paddingBottom: Math.max(bottomInset, 8) }]}>
        <Pressable
          style={({ pressed }) => [s.attachBtn, pressedScale({ pressed })]}
          onPress={openAttach}
          disabled={uploading}
          hitSlop={6}
        >
          <Ionicons name="attach" size={22} color={C.muted} />
        </Pressable>
        <TextInput
          style={s.input}
          placeholder="メッセージを入力..."
          placeholderTextColor={C.muted2}
          value={input}
          onChangeText={setInput}
          multiline
        />
        <Pressable
          style={({ pressed }) => [s.sendBtn, ((!input.trim() && pending.length === 0) || sending || uploading) && { opacity: 0.4 }, pressedScale({ pressed })]}
          onPress={handleSend}
          disabled={(!input.trim() && pending.length === 0) || sending || uploading}
        >
          {uploading ? <ActivityIndicator size="small" color="#0c1513" /> : <Ionicons name="send" size={18} color="#0c1513" />}
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
// 引用や返信バーに出す短い本文（添付だけなら「📷 画像」等）
function previewOf(m: CollabMessage): string {
  const files = m.metadata?.files || (m.metadata?.file ? [m.metadata.file] : []);
  const body = (m.content || '').trim();
  if (body && !files.some((f) => f.name === body)) return body.slice(0, 100);
  if (files.length === 0) return '';
  const kinds = files.map((f) => f.type || '');
  if (kinds.every((k) => k.startsWith('image/'))) return files.length > 1 ? `📷 画像 ${files.length}枚` : '📷 画像';
  if (kinds.every((k) => k.startsWith('video/'))) return files.length > 1 ? `🎬 動画 ${files.length}本` : '🎬 動画';
  return `📎 ${files[0].name}`;
}

function MessageRow({ msg, threadReplies, showRead, apiBase, myName, onReact, onReply, onJump, highlighted, pickerOpen, onTogglePicker, onThreadReply }: {
  msg: CollabMessage;
  threadReplies?: CollabMessage[];
  showRead: boolean;
  apiBase: string;
  myName: string;
  onReact: (messageId: string, emoji: string) => void;
  onReply: (msg: CollabMessage) => void;
  onJump: (id: string) => void;
  highlighted: boolean;
  pickerOpen: boolean;
  onTogglePicker: () => void;
  onThreadReply: (parent: CollabMessage, text: string) => void;
}) {
  const isDan = msg.sender_type.startsWith('dan_');
  const isOwnSide = msg.sender_type === 'owner' || isDan;
  const isPrivate = msg.metadata?.visibility === 'owner_only';
  const stamp = isStamp(msg.content);
  const reactions = msg.metadata?.reactions;
  const rawFiles: CollabFile[] = msg.metadata?.files || (msg.metadata?.file ? [msg.metadata.file] : []);
  const mediaItems: MediaGridItem[] = rawFiles
    .filter((f) => (f.type || '').startsWith('image/') || (f.type || '').startsWith('video/'))
    .map((f) => ({ url: f.url.startsWith('http') ? f.url : `${apiBase}${f.url}`, kind: (f.type || '').startsWith('video/') ? 'video' : 'image', name: f.name }));
  const otherFiles = rawFiles.filter((f) => !((f.type || '').startsWith('image/') || (f.type || '').startsWith('video/')));
  const hasFiles = rawFiles.length > 0;
  // 添付だけのメッセージは本文が空かファイル名（旧形式）なので本文行を出さない
  const bodyText = hasFiles && (!msg.content || rawFiles.some((f) => f.name === msg.content)) ? '' : msg.content;
  // 画像・動画だけの発言は吹き出しの枠を付けず、そのまま置く（LINE式）
  const bare = mediaItems.length > 0 && !bodyText && otherFiles.length === 0 && !isPrivate && !msg.metadata?.reply_to?.id;
  const [replyText, setReplyText] = useState('');
  const canReact = !isPrivate && !msg.id.startsWith('temp-');

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
  // 引用（この発言が返信なら、元の発言を上に小さく出す。タップで元へ飛ぶ）
  const rt = msg.metadata?.reply_to;
  const quote = rt?.id && !isPrivate ? (
    <Pressable onPress={() => onJump(rt.id!)} style={[s.quote, isOwnSide ? s.quoteOwn : s.quoteOther]}>
      <Text style={[s.quoteName, { color: isOwnSide ? '#0c1513aa' : C.accent }]} numberOfLines={1}>{(rt.sender_type || '').startsWith('dan_') ? 'ダン' : rt.sender_name}</Text>
      <Text style={[s.quoteText, { color: isOwnSide ? '#0c1513aa' : C.muted }]} numberOfLines={2}>{(rt.content || '').replace(/\[添付[^\]]*\]/g, '').trim() || '(添付)'}</Text>
    </Pressable>
  ) : null;

  const bubbleBody = (
    <Pressable
      onLongPress={canReact ? onTogglePicker : undefined}
      delayLongPress={250}
      style={({ pressed }) => [
        stamp || bare ? s.stampBox : s.bubble,
        !stamp && !bare && (isPrivate ? s.bubblePrivate : isOwnSide ? s.bubbleOwn : s.bubbleOther),
        pressed && canReact ? { opacity: 0.85 } : undefined,
        highlighted ? s.bubbleHighlight : undefined,
      ]}
    >
      {quote}
      {mediaItems.length > 0 && (
        <MediaGrid
          items={mediaItems}
          width={236}
          // 画像/動画の長押しは「開く/再生」ではなく返信・スタンプのメニュー（タップで開く）
          onLongPress={canReact ? onTogglePicker : undefined}
        />
      )}
      {otherFiles.map((file) => (
        <Pressable key={file.url} onPress={() => Linking.openURL(file.url.startsWith('http') ? file.url : `${apiBase}${file.url}`)}>
          <Text style={[s.fileLink, isOwnSide && !isPrivate ? { color: '#0c1513' } : undefined]}>
            📎 {file.name}
          </Text>
        </Pressable>
      ))}
      {!!bodyText && (
        <Text
          style={[
            stamp ? s.stampText : s.msgText,
            !stamp && isOwnSide && !isPrivate ? { color: '#0c1513' } : undefined,
          ]}
        >
          {bodyText}
        </Text>
      )}
      {!!reactions && Object.keys(reactions).length > 0 && (
        <View style={s.reactionRow}>
          {Object.entries(reactions).map(([emoji, ns]) => {
            const mine = !!myName && (ns || []).includes(myName);
            return (
              <Pressable
                key={emoji}
                onPress={canReact ? () => onReact(msg.id, emoji) : undefined}
                style={({ pressed }) => [
                  s.reactionChip,
                  mine && s.reactionChipMine,
                  pressedScale({ pressed }),
                ]}
              >
                <Text style={{ fontSize: 13, color: C.text }}>{emoji}{(ns || []).length > 1 ? ` ${ns.length}` : ''}</Text>
              </Pressable>
            );
          })}
        </View>
      )}
    </Pressable>
  );

  // 長押しで出るスタンプ選択（LINE式）。選ぶ／もう一度長押しで閉じる
  const picker = pickerOpen && canReact ? (
    <View
      style={[s.reactionPicker, isOwnSide ? { alignSelf: 'flex-end' } : { alignSelf: 'flex-start' }]}
      onTouchStart={(e) => e.stopPropagation()}
    >
      {REACTION_CHOICES.map((emoji) => (
        <Pressable
          key={emoji}
          hitSlop={4}
          onPress={() => { onTogglePicker(); onReact(msg.id, emoji); }}
          style={({ pressed }) => [s.reactionPickItem, pressedScale({ pressed })]}
        >
          <Text style={{ fontSize: 20 }}>{emoji}</Text>
        </Pressable>
      ))}
      <View style={s.pickerSep} />
      <Pressable
        hitSlop={4}
        onPress={() => { onTogglePicker(); onReply(msg); }}
        style={({ pressed }) => [s.reactionPickItem, { flexDirection: 'row', alignItems: 'center', gap: 4 }, pressedScale({ pressed })]}
      >
        <Ionicons name="arrow-undo" size={16} color={C.text} />
        <Text style={{ color: C.text, fontSize: 13 }}>返信</Text>
      </Pressable>
    </View>
  ) : null;


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
      {picker}
    </View>
  );
}

// ============================================================
// 送信案カード（承認・編集・破棄）
// ============================================================
function ProposalCard({ proposal, request, apiBase }: { proposal: Proposal; request: RequestFn; apiBase: string }) {
  const [body, setBody] = useState(proposal.content || '');
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState<'send' | 'discard' | 'sender' | 'apply' | null>(null);
  const [gone, setGone] = useState(false);
  const [dismissedAt, setDismissedAt] = useState<string | null>(null);
  const [sender, setSender] = useState<'dan' | 'owner'>(proposal.action_data?.sender === 'owner' ? 'owner' : 'dan');
  const ad = proposal.action_data || {};

  // ダンが下書きを更新した（作業が進んだ）ら、こちらで編集中でない限り本文を追従させる
  const lastContent = useRef(proposal.content || '');
  useEffect(() => {
    if (proposal.content !== lastContent.current) {
      lastContent.current = proposal.content || '';
      if (!dirty) setBody(proposal.content || '');
    }
  }, [proposal.content, dirty]);
  useEffect(() => {
    if (ad.sender === 'owner' || ad.sender === 'dan') setSender(ad.sender);
  }, [ad.sender]);

  if (gone) return null;

  const pendingUpdate = ad.pending_update && ad.pending_update.at !== dismissedAt ? ad.pending_update : null;
  const attItems: MediaGridItem[] = (ad.attachments || [])
    .filter((f) => (f.type || '').startsWith('image/') || (f.type || '').startsWith('video/'))
    .map((f) => ({ url: f.url.startsWith('http') ? f.url : `${apiBase}${f.url}`, kind: (f.type || '').startsWith('video/') ? 'video' : 'image', name: f.name }));
  const attOthers = (ad.attachments || []).filter((f) => !((f.type || '').startsWith('image/') || (f.type || '').startsWith('video/')));

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

  const changeSender = async (next: 'dan' | 'owner') => {
    if (next === sender || busy) return;
    setSender(next); setBusy('sender');
    try {
      await request(`/chat/proposals/${proposal.id}/draft`, { method: 'PATCH', body: JSON.stringify({ sender: next }) });
    } catch {
      setSender(sender);
    } finally { setBusy(null); }
  };

  const applyUpdate = async () => {
    setBusy('apply');
    try {
      const updated = await request<Proposal>(`/chat/proposals/${proposal.id}/draft`, { method: 'PATCH', body: JSON.stringify({ apply_update: true }) });
      lastContent.current = updated.content || '';
      setBody(updated.content || ''); setDirty(false);
    } catch { /* 次のポーリングで再表示 */ } finally { setBusy(null); }
  };

  return (
    <View style={s.card}>
      <View style={s.cardHead}>
        <Ionicons name="paper-plane-outline" size={14} color={C.accent} />
        <Text style={s.cardTitle} numberOfLines={1}>
          返信案 → {ad.to_name || ad.to || '相手'}{ad.intent ? ` — ${ad.intent}` : ''}
        </Text>
        {(ad.revision || 1) > 1 && !!ad.dan_updated_at && (
          <Text style={s.cardMeta}>更新 {fmtTime(ad.dan_updated_at)}</Text>
        )}
      </View>
      {pendingUpdate && (
        <View style={s.cardUpdate}>
          <Ionicons name="refresh" size={14} color={C.accent} />
          <Text style={[s.cardUpdateText, { flex: 1 }]}>ダンが新しい版を用意しました（{fmtTime(pendingUpdate.at)}）</Text>
          <Pressable style={[s.cardBtn, s.cardBtnPrimary, { paddingVertical: 5, paddingHorizontal: 10 }]} disabled={!!busy} onPress={applyUpdate}>
            {busy === 'apply' ? <ActivityIndicator size="small" color="#0c1513" /> : <Text style={{ color: '#0c1513', fontSize: 12, fontWeight: '600' }}>新しい版にする</Text>}
          </Pressable>
          <Pressable hitSlop={8} onPress={() => setDismissedAt(pendingUpdate.at)}>
            <Ionicons name="close" size={16} color={C.muted} />
          </Pressable>
        </View>
      )}
      <View style={s.cardSenderRow}>
        <Text style={s.cardMeta}>名義:</Text>
        {(['dan', 'owner'] as const).map((k) => (
          <Pressable key={k} onPress={() => changeSender(k)} style={[s.cardSenderBtn, sender === k && s.cardSenderBtnOn]}>
            <Text style={[s.cardSenderText, sender === k && { color: '#0c1513', fontWeight: '600' }]}>{k === 'dan' ? 'ダン' : 'あなた'}</Text>
          </Pressable>
        ))}
        <Text style={[s.cardMeta, { flex: 1 }]} numberOfLines={1}>
          {sender === 'owner' ? '本人の発言として届く' : 'ダンの発言として届く'}
        </Text>
      </View>
      {(attItems.length > 0 || attOthers.length > 0) && (
        <View style={{ gap: 4, marginBottom: 6 }}>
          <Text style={s.cardMeta}>添付（一緒に届きます）</Text>
          {attItems.length > 0 && <MediaGrid items={attItems} width={220} />}
          {attOthers.map((f) => (
            <Text key={f.url} style={s.fileLink}>📎 {f.name}</Text>
          ))}
        </View>
      )}
      <TextInput
        style={s.cardBody}
        value={body}
        onChangeText={(t) => { setBody(t); setDirty(t !== (proposal.content || '')); }}
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
  metaCol: { alignItems: 'flex-end', justifyContent: 'flex-end', flexShrink: 0 },
  metaRead: { color: C.muted2, fontSize: 9 },
  metaTime: { color: C.muted2, fontSize: 10 },
  stampBox: { paddingHorizontal: 2, flexShrink: 1 },
  emptyText: { color: C.muted, fontSize: 13, textAlign: 'center', marginTop: 48, paddingHorizontal: 32, lineHeight: 20 },

  roomRow: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingHorizontal: 14, paddingVertical: 12 },
  avatar: { width: 46, height: 46, borderRadius: 23, alignItems: 'center', justifyContent: 'center' },
  avatarText: { color: '#fff', fontSize: 18, fontWeight: '700' },
  roomTop: { flexDirection: 'row', alignItems: 'baseline', justifyContent: 'space-between', gap: 8 },
  roomTitle: { color: C.text, fontSize: 15, fontWeight: '600', flexShrink: 1 },
  roomTime: { color: C.muted2, fontSize: 11 },
  roomPreview: { color: C.muted, fontSize: 13, marginTop: 2 },
  unreadDot: { width: 9, height: 9, borderRadius: 5, backgroundColor: C.accent, marginTop: 2 },
  replyBar: { flexDirection: 'row', alignItems: 'center', gap: 8, paddingHorizontal: 12, paddingVertical: 6, backgroundColor: C.bg, borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: C.border },
  replyBarName: { color: C.accent, fontSize: 12, fontWeight: '600' },
  replyBarText: { color: C.muted, fontSize: 12 },
  quote: { borderLeftWidth: 2, paddingLeft: 8, paddingVertical: 2, marginBottom: 6, maxWidth: '100%' },
  quoteOwn: { borderLeftColor: '#0c151366' },
  quoteOther: { borderLeftColor: C.accent },
  quoteName: { fontSize: 11, fontWeight: '600' },
  quoteText: { fontSize: 12 },
  bubbleHighlight: { borderWidth: 2, borderColor: C.accent },
  pickerSep: { width: StyleSheet.hairlineWidth, backgroundColor: C.border, marginHorizontal: 4, alignSelf: 'stretch' },
  // プロジェクト一覧（App.tsx unreadBadge）と同じ見た目
  unreadBadge: { alignItems: 'center', backgroundColor: C.danger, borderRadius: 13, minWidth: 26, height: 26, justifyContent: 'center', paddingHorizontal: 7 },
  unreadBadgeText: { color: '#fffaf5', fontSize: 11, fontWeight: '900' },
  attachBtn: { paddingVertical: 8, paddingHorizontal: 2, justifyContent: 'center' },
  pendingStrip: { flexDirection: 'row', flexWrap: 'wrap', gap: 8, paddingHorizontal: 12, paddingTop: 8, backgroundColor: C.bg, borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: C.border },
  pendingItem: { position: 'relative' },
  pendingThumb: { width: 60, height: 60, borderRadius: 10, backgroundColor: C.card },
  pendingFileBox: { width: 110, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 6, gap: 2 },
  pendingName: { color: C.muted, fontSize: 10, maxWidth: 96 },
  pendingRemove: { position: 'absolute', top: -5, right: -5, backgroundColor: C.text, borderRadius: 9, width: 18, height: 18, alignItems: 'center', justifyContent: 'center' },
  sep: { height: StyleSheet.hairlineWidth, backgroundColor: C.border, marginLeft: 72 },

  thinkingRow: { flexDirection: 'row', alignItems: 'center', gap: 8, alignSelf: 'flex-end', backgroundColor: C.violetBg, borderRadius: 12, paddingHorizontal: 12, paddingVertical: 8, marginTop: 8 },
  thinkingText: { color: C.violet, fontSize: 12 },

  msgWrap: { marginVertical: 4, maxWidth: '85%' },
  msgLeft: { alignSelf: 'flex-start' },
  msgRight: { alignSelf: 'flex-end' },
  // 時刻カラムと横並びの row 内で縮まないと長文が画面外へはみ出す（RN の flexShrink 既定は 0）
  bubble: { borderRadius: 14, paddingHorizontal: 12, paddingVertical: 8, flexShrink: 1 },
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
  reactionChipMine: { borderColor: C.accent, backgroundColor: '#1f3a33' },
  reactionPicker: { flexDirection: 'row', gap: 4, marginTop: 6, backgroundColor: C.card, borderWidth: 1, borderColor: C.border, borderRadius: 22, paddingHorizontal: 8, paddingVertical: 5 },
  reactionPickItem: { paddingHorizontal: 5, paddingVertical: 2 },
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
  cardMeta: { color: C.muted, fontSize: 11 },
  cardUpdate: { flexDirection: 'row', alignItems: 'center', gap: 8, backgroundColor: '#1f3a33', borderRadius: 8, paddingHorizontal: 8, paddingVertical: 6, marginBottom: 8 },
  cardUpdateText: { color: C.text, fontSize: 12 },
  cardSenderRow: { flexDirection: 'row', alignItems: 'center', gap: 6, marginBottom: 8 },
  cardSenderBtn: { borderWidth: 1, borderColor: C.border, borderRadius: 8, paddingHorizontal: 10, paddingVertical: 4 },
  cardSenderBtnOn: { backgroundColor: C.accent, borderColor: C.accent },
  cardSenderText: { color: C.text, fontSize: 12 },
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
