'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { useQuery } from '@tanstack/react-query';
import { toast } from 'sonner';
import { Send, Circle, Bot, User, UserCheck, Paperclip, Pencil, Sparkles, Loader2, Reply, X, Bell } from 'lucide-react';
import { api, type CollabMessageResponse } from '@/lib/api-client';
import { useCollabWebSocket } from '@/hooks/useCollabWebSocket';
import { usePushNotification } from '@/hooks/usePushNotification';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Share, MoreVertical, Download } from 'lucide-react';
import { OpenInBrowserPrompt } from '@/components/open-in-browser';
import { LinkifyText } from '@/components/linkify-text';
import { ReactionBar } from '@/components/collab/reaction-bar';

const GUEST_NAME_KEY = 'collab-guest-name'; // shared across all rooms

function getStorageKeys(inviteToken: string) {
  return {
    tokenKey: `collab-guest-token-${inviteToken}`,
    roomKey: `collab-guest-room-${inviteToken}`,
    titleKey: `collab-guest-title-${inviteToken}`,
  };
}

function formatTime(dateStr: string): string {
  const d = new Date(dateStr);
  const now = new Date();
  const isToday = d.toDateString() === now.toDateString();
  const yesterday = new Date(now);
  yesterday.setDate(yesterday.getDate() - 1);
  const isYesterday = d.toDateString() === yesterday.toDateString();
  const time = d.toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit' });
  if (isToday) return time;
  if (isYesterday) return `昨日 ${time}`;
  return `${d.getMonth() + 1}/${d.getDate()} ${time}`;
}

function formatDateSeparator(dateStr: string): string {
  const d = new Date(dateStr);
  const now = new Date();
  if (d.toDateString() === now.toDateString()) return '今日';
  const yesterday = new Date(now);
  yesterday.setDate(yesterday.getDate() - 1);
  if (d.toDateString() === yesterday.toDateString()) return '昨日';
  return d.toLocaleDateString('ja-JP', { year: 'numeric', month: 'long', day: 'numeric', weekday: 'short' });
}

export default function GuestJoinPage() {
  const params = useParams();
  const router = useRouter();
  const inviteToken = params.token as string;
  const [guestName, setGuestName] = useState('');
  const [guestNameLoaded, setGuestNameLoaded] = useState(false);
  const [guestToken, setGuestToken] = useState<string | null>(null);
  const [roomId, setRoomId] = useState<string | null>(null);
  const [roomTitle, setRoomTitle] = useState('');
  const [messages, setMessages] = useState<CollabMessageResponse[]>([]);
  const [input, setInput] = useState('');
  const [isJoining, setIsJoining] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [readByOther, setReadByOther] = useState<string | null>(null);
  const [danMode, setDanMode] = useState(false);
  const [danThinking, setDanThinking] = useState(false);
  const [editingName, setEditingName] = useState(false);
  const [editNameValue, setEditNameValue] = useState('');
  const [showInstallGuide, setShowInstallGuide] = useState(false);
  // Reply generation state - keyed by message ID
  const [replyStates, setReplyStates] = useState<Record<string, { state: 'loading' | 'ready' | 'sent'; reply: string }>>({});
  const [replyTo, setReplyTo] = useState<CollabMessageResponse | null>(null);

  // Check for existing session + restore guest name
  useEffect(() => {
    const keys = getStorageKeys(inviteToken);
    const savedToken = localStorage.getItem(keys.tokenKey);
    const savedRoom = localStorage.getItem(keys.roomKey);
    const savedTitle = localStorage.getItem(keys.titleKey);
    const savedName = localStorage.getItem(GUEST_NAME_KEY);

    // Restore name from: 1) localStorage 2) JWT token payload
    if (savedName) {
      setGuestName(savedName);
    } else if (savedToken) {
      try {
        const payload = JSON.parse(atob(savedToken.split('.')[1]));
        if (payload.guest_name) {
          setGuestName(payload.guest_name);
          localStorage.setItem(GUEST_NAME_KEY, payload.guest_name);
        }
      } catch { /* invalid token */ }
    }

    if (savedToken && savedRoom) {
      setGuestToken(savedToken);
      setRoomId(savedRoom);
      if (savedTitle) setRoomTitle(savedTitle);
    }
    setGuestNameLoaded(true);
  }, [inviteToken]);

  // Fetch invite info
  const { data: inviteInfo } = useQuery({
    queryKey: ['collab-invite', inviteToken],
    queryFn: () => api.collab.getInviteInfo(inviteToken),
    enabled: !!inviteToken && !guestToken,
  });

  // 身分モデル: 入口URL（共有）では名前を入れて参加 → 本人専用URLへ切り替わる。
  // 本人専用URLは開いた端末・ブラウザに関係なくその人として入室できる。
  useEffect(() => {
    const info = inviteInfo as { personal?: boolean; rejoin_token?: string; room_id?: string; room_title?: string; guest_name?: string } | undefined;
    if (!info?.personal || !info.rejoin_token || guestToken) return;
    setGuestToken(info.rejoin_token);
    setRoomId(info.room_id || null);
    setRoomTitle(info.room_title || '');
    if (info.guest_name) {
      setGuestName(info.guest_name);
      localStorage.setItem(GUEST_NAME_KEY, info.guest_name);
    }
    const keys = getStorageKeys(inviteToken);
    localStorage.setItem(keys.tokenKey, info.rejoin_token);
    if (info.room_id) localStorage.setItem(keys.roomKey, info.room_id);
    if (info.room_title) localStorage.setItem(keys.titleKey, info.room_title);
  }, [inviteInfo, inviteToken, guestToken]);

  // 移行: 入口URLに古いセッション（ブラウザ保存のトークン）で来た人を本人専用URLへ誘導。
  // 身分が消えていれば保存トークンを捨てて参加フォームに戻す。
  useEffect(() => {
    if (!guestToken || !roomId) return;
    api.collab.me(guestToken)
      .then((me) => {
        if (me.personal_token && me.personal_token !== inviteToken) {
          const keys = getStorageKeys(me.personal_token);
          localStorage.setItem(keys.tokenKey, guestToken);
          localStorage.setItem(keys.roomKey, roomId);
          localStorage.setItem(keys.titleKey, roomTitle || '');
          router.replace(`/collab/join/${me.personal_token}`);
        }
      })
      .catch((e: unknown) => {
        const status = (e as { status?: number })?.status;
        if (status === 404 || status === 403) {
          const keys = getStorageKeys(inviteToken);
          localStorage.removeItem(keys.tokenKey);
          localStorage.removeItem(keys.roomKey);
          setGuestToken(null);
          setRoomId(null);
        }
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [guestToken, roomId]);

  // Fetch messages when joined
  useEffect(() => {
    if (roomId && guestToken) {
      api.collab.getMessages(roomId, 50, guestToken).then((data) => {
        setMessages(data.messages);
      }).catch(() => {});
    }
  }, [roomId, guestToken]);

  // 参加者名簿＋オーナーの既読位置（既読表示用）
  const { data: participants } = useQuery({
    queryKey: ['collab-guest-participants', roomId],
    queryFn: () => api.collab.getParticipants(roomId!, guestToken!),
    enabled: !!roomId && !!guestToken,
    refetchInterval: 10_000,
  });

  // 自分の既読位置を定期更新（オーナー側の「既読」表示の元になる）
  useEffect(() => {
    if (!roomId || !guestToken) return;
    const mark = () => api.collab.markRead(roomId, guestToken).catch(() => {});
    mark();
    const timer = setInterval(mark, 10_000);
    return () => clearInterval(timer);
  }, [roomId, guestToken]);

  // オーナーの既読位置以前の「自分の発言」の最後の1件に「既読」を付ける
  const ownerReadTime = participants?.owner.last_read_at
    ? new Date(participants.owner.last_read_at).getTime() : 0;
  const lastReadOwnId = (() => {
    let id: string | null = null;
    for (const m of messages) {
      if (m.sender_type === 'guest' && new Date(m.created_at).getTime() <= ownerReadTime) id = m.id;
    }
    return id;
  })();

  // WebSocket
  // 楽観表示の仮バブル（client_msg_id）と同一なら追加ではなく差し替え（二重表示防止）
  const handleNewMessage = useCallback((msg: CollabMessageResponse) => {
    if (msg.sender_type === 'dan_guest') setDanThinking(false);
    setMessages((prev) => {
      if (prev.some((m) => m.id === msg.id)) return prev;
      const cid = (msg.metadata as { client_msg_id?: string } | undefined)?.client_msg_id;
      if (cid && prev.some((m) => m.id === cid)) {
        return prev.map((m) => (m.id === cid ? msg : m));
      }
      return [...prev, msg];
    });
  }, []);

  const handleDanThinking = useCallback((thinking: boolean) => {
    setDanThinking(thinking);
  }, []);

  const handleRead = useCallback((data: { sender_type: string; message_id: string }) => {
    if (data.sender_type === 'owner') {
      setReadByOther(data.message_id);
    }
  }, []);

  // リアクション（🙏既読サイン等）の反映
  const handleReaction = useCallback((data: { message_id: string; reactions: Record<string, string[]> }) => {
    setMessages((prev) => prev.map((m) =>
      m.id === data.message_id
        ? { ...m, metadata: { ...(m.metadata || {}), reactions: data.reactions } }
        : m
    ));
  }, []);

  const { isConnected, onlineUsers, sendMessage: wsSend, sendRead } = useCollabWebSocket({
    roomId: roomId || '',
    token: guestToken || '',
    isGuest: true,
    onMessage: handleNewMessage,
    onRead: handleRead,
    onDanThinking: handleDanThinking,
    onReaction: handleReaction,
  });

  // Send read receipt when new messages arrive from owner
  useEffect(() => {
    const lastMsg = messages[messages.length - 1];
    if (lastMsg && lastMsg.sender_type === 'owner') {
      sendRead(lastMsg.id);
    }
  }, [messages, sendRead]);

  // WebSocket が張れない環境（Vercel 経由など。rewrites は WS を通せない）では
  // REST ポーリングで受信を代替する。REST が正なのでリストごと置き換える。
  useEffect(() => {
    if (!roomId || !guestToken || isConnected) return;
    const timer = setInterval(() => {
      api.collab.getMessages(roomId, 50, guestToken)
        .then((data) => setMessages(data.messages))
        .catch(() => {});
    }, 5000);
    return () => clearInterval(timer);
  }, [roomId, guestToken, isConnected]);

  // Push notifications
  const { permission: pushPermission, subscribe: pushSubscribe } = usePushNotification(roomId || '', 'guest');

  // Auto-scroll
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  // Join room
  const handleJoin = async () => {
    if (!guestName.trim()) return;
    setIsJoining(true);
    try {
      const result = await api.collab.joinRoom(inviteToken, guestName.trim());
      localStorage.setItem(GUEST_NAME_KEY, result.guest_name || guestName.trim());
      // 本人専用URLへ切り替える（身分をURLに持たせる。端末・ブラウザの保存領域に依存しない）
      const personal = result.personal_token || inviteToken;
      const keys = getStorageKeys(personal);
      localStorage.setItem(keys.tokenKey, result.guest_token);
      localStorage.setItem(keys.roomKey, result.room_id);
      localStorage.setItem(keys.titleKey, result.room_title);
      if (personal !== inviteToken) {
        router.replace(`/collab/join/${personal}`);
        return;
      }
      setGuestToken(result.guest_token);
      setRoomId(result.room_id);
      setRoomTitle(result.room_title);
      toast.success('参加しました');
    } catch (e: any) {
      toast.error(e?.data?.detail || '参加できませんでした');
    } finally {
      setIsJoining(false);
    }
  };

  // 表示名の変更（サーバーの身分ごと更新。以後の発言から新しい名前になる）
  const applyRename = async () => {
    const v = editNameValue.trim();
    if (!v || !guestToken) {
      setEditingName(false); setEditNameValue('');
      return;
    }
    try {
      const res = await api.collab.rename(v, guestToken);
      setGuestName(res.guest_name);
      setGuestToken(res.guest_token);
      localStorage.setItem(GUEST_NAME_KEY, res.guest_name);
      const keys = getStorageKeys(inviteToken);
      localStorage.setItem(keys.tokenKey, res.guest_token);
      toast.success('表示名を変更しました（今後の発言から反映されます）');
    } catch {
      toast.error('変更に失敗しました');
    }
    setEditingName(false);
    setEditNameValue('');
  };


  // 入力欄→吹き出しの連続移動（iMessage式）: 送った文字が入力欄の位置から
  // 吹き出しの最終位置へ移動して見える。「押した→生えた」を一つの物にする。
  const flipFromComposer = (tempId: string) => {
    if (typeof window === 'undefined') return;
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    const from = inputRef.current?.getBoundingClientRect();
    if (!from) return;
    requestAnimationFrame(() => {
      const bubble = document.querySelector<HTMLElement>(`[data-collab-msg-id="${tempId}"] [data-bubble]`);
      if (!bubble) return;
      const to = bubble.getBoundingClientRect();
      const dx = from.left - to.left;
      const dy = from.top - to.top;
      bubble.animate(
        [{ transform: `translate(${dx}px, ${dy}px) scale(0.96)`, opacity: 0.5 }, { transform: 'none', opacity: 1 }],
        { duration: 220, easing: 'cubic-bezier(.2,.8,.2,1)' }
      );
    });
  };

  const handleSend = async () => {
    const content = input.trim();
    if (!content) return;
    const finalContent = danMode ? `@ダン ${content}` : content;
    const metadata: Record<string, unknown> = {};
    if (replyTo) {
      metadata.reply_to = {
        id: replyTo.id,
        sender_name: replyTo.sender_name,
        sender_type: replyTo.sender_type,
        content: replyTo.content.slice(0, 200),
      };
    }
    const md = Object.keys(metadata).length > 0 ? metadata : undefined;
    // @ダン の私的相談だけは WS 専用機能なので接続時は WS、それ以外は常に REST
    // （確実・即時に自分の画面へ反映。WS は受信専用）。
    if (danMode && isConnected) {
      wsSend(finalContent, md);
      setInput('');
      setReplyTo(null);
      inputRef.current?.focus();
      return;
    }
    if (!roomId || !guestToken) return;
    // 楽観表示: 押した瞬間に自分のバブルを即表示。client_msg_id 焼き込みで
    // WSエコー/REST応答のどちらが先でも handleNewMessage が1回で差し替える
    const savedInput = content;
    const tempId = `temp-${Date.now()}`;
    metadata.client_msg_id = tempId;
    const optimistic = {
      id: tempId, room_id: roomId, sender_type: 'guest', sender_name: guestName || 'あなた',
      content: finalContent, metadata: metadata as CollabMessageResponse['metadata'],
      created_at: new Date().toISOString(),
    } as CollabMessageResponse;
    setInput('');
    setReplyTo(null);
    setMessages((prev) => [...prev, optimistic]);
    flipFromComposer(tempId);
    inputRef.current?.focus();
    try {
      const sent = await api.collab.sendMessage(roomId, finalContent, guestToken, metadata);
      handleNewMessage(sent);
    } catch {
      toast.error('送信に失敗しました。通信環境をご確認ください');
      setMessages((prev) => prev.filter((m) => m.id !== tempId));
      setInput(savedInput);
    }
  };

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !roomId || !guestToken) return;
    setIsUploading(true);
    try {
      const formData = new FormData();
      formData.append('file', file);
      const res = await fetch(`/api/v1/collab/rooms/${roomId}/files`, {
        method: 'POST',
        headers: { 'X-Guest-Token': guestToken },
        body: formData,
      });
      if (!res.ok) throw new Error('Upload failed');
      const fileData = await res.json();
      const fileUrl = fileData.file_path;
      const fileMeta = {
        file: { id: fileData.id, name: fileData.file_name, url: fileUrl, type: fileData.file_type, size: fileData.file_size },
      };
      const sent = await api.collab.sendMessage(roomId, file.name, guestToken, fileMeta);
      handleNewMessage(sent);
      toast.success('ファイルを送信しました');
    } catch {
      toast.error('アップロードに失敗しました');
    } finally {
      setIsUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  // Wait for localStorage to load before showing form
  if (!guestNameLoaded) return null;

  // Not joined yet - show join form
  if (!guestToken || !roomId) {
    const isExpired = inviteInfo?.status === 'expired';
    const alreadyJoined = inviteInfo?.already_joined;

    return (
      <div className="min-h-screen flex items-start justify-center bg-background p-4 pt-[15vh]">
        <OpenInBrowserPrompt />
        <Card className="w-full max-w-md">
          <CardHeader className="text-center">
            <CardTitle className="text-xl">
              {inviteInfo?.room_title ?? 'コラボルーム'}
            </CardTitle>
            {inviteInfo?.room_description && (
              <p className="text-sm text-muted-foreground mt-1">{inviteInfo.room_description}</p>
            )}
          </CardHeader>
          <CardContent>
            {isExpired ? (
              <p className="text-center text-destructive">この招待リンクは期限切れです</p>
            ) : (
              <div className="space-y-4">
                <div>
                  <label className="text-sm font-medium">あなたの名前</label>
                  <Input
                    placeholder="表示名を入力"
                    value={guestName}
                    onChange={(e) => setGuestName(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') handleJoin();
                    }}
                  />
                </div>
                <Button
                  className="w-full"
                  onClick={handleJoin}
                  disabled={!guestName.trim() || isJoining}
                >
                  {isJoining ? '参加中...' : '参加する'}
                </Button>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    );
  }

  // Joined - show chat
  return (
    <div className="flex flex-col h-dvh bg-background overflow-hidden relative">
      <OpenInBrowserPrompt />
      {/* Header */}
      <div className="flex items-center gap-3 px-4 py-3 border-b shrink-0">
        <div className="flex-1 min-w-0">
          <h2 className="font-semibold truncate">{roomTitle || 'コラボルーム'}</h2>
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Circle className={`h-2 w-2 fill-current ${isConnected ? 'text-green-500' : 'text-gray-400'}`} />
            <span>{onlineUsers.length}人オンライン</span>
          </div>
        </div>
        <button
          className="flex items-center gap-2 hover:bg-accent rounded-full px-2 py-1 transition-colors"
          onClick={() => { setEditNameValue(guestName); setEditingName(true); }}
        >
          <div className="h-8 w-8 rounded-full bg-blue-600 flex items-center justify-center text-sm font-bold text-white shrink-0">
            {guestName.charAt(0).toUpperCase()}
          </div>
          <span className="text-sm max-w-[80px] truncate">{guestName}</span>
        </button>
      </div>

      {/* 通知バナー:
          - アプリ（ホーム画面追加後）で開いていて未許可 → 許可ダイアログを出すボタン
          - ブラウザで開いている → ホーム画面追加の案内（iOSは追加後でないと許可できない） */}
      {typeof window !== 'undefined' &&
        (/iPad|iPhone|iPod|Android/i.test(navigator.userAgent)) && (
        window.matchMedia('(display-mode: standalone)').matches ? (
          pushPermission !== 'granted' && (
            <button
              onClick={async () => {
                const ok = await pushSubscribe();
                if (ok) toast.success('通知をオンにしました');
                else toast.error('通知を許可できませんでした。端末の設定アプリから通知を許可してください');
              }}
              className="flex items-center gap-2 px-4 py-2 bg-violet-500/15 border-b border-violet-500/30 text-violet-300 text-xs font-medium shrink-0 hover:bg-violet-500/20 transition-colors"
            >
              <Bell className="h-3.5 w-3.5 shrink-0 animate-pulse" />
              <span>タップして通知をオンにする（新着に気づけます）</span>
            </button>
          )
        ) : (
          <button
            onClick={() => setShowInstallGuide(true)}
            className="flex items-center gap-2 px-4 py-2 bg-violet-500/10 border-b border-violet-500/20 text-violet-400 text-xs shrink-0 hover:bg-violet-500/15 transition-colors"
          >
            <Bell className="h-3.5 w-3.5 shrink-0" />
            <span>通知がほしい場合</span>
          </button>
        )
      )}

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 overscroll-contain" ref={scrollRef}>
        <div className="space-y-3 py-4">
          {messages.map((msg, i) => {
            const prevDate = i > 0 ? new Date(messages[i - 1].created_at).toDateString() : '';
            const curDate = new Date(msg.created_at).toDateString();
            const showSeparator = curDate !== prevDate;
            return (
              <div key={(msg.metadata as { client_msg_id?: string } | undefined)?.client_msg_id || msg.id} data-collab-msg-id={msg.id}>
                {showSeparator && (
                  <div className="flex items-center gap-3 py-2">
                    <div className="flex-1 border-t border-border" />
                    <span className="text-[10px] text-muted-foreground shrink-0">{formatDateSeparator(msg.created_at)}</span>
                    <div className="flex-1 border-t border-border" />
                  </div>
                )}
                <GuestMessageBubble
                  message={msg}
                  myName={guestName}
                  onReact={(m, emoji) => {
                    if (!roomId || !guestToken) return;
                    api.collab.react(roomId, m.id, emoji, guestToken)
                      .then((r) => handleReaction({ message_id: m.id, reactions: r.reactions }))
                      .catch(() => toast.error('リアクションに失敗しました'));
                  }}
                  showRead={msg.id === lastReadOwnId}
                  replyState={replyStates[msg.id]?.state}
                  onReply={setReplyTo}
                  onGenerateReply={msg.sender_type === 'owner' && !replyStates[msg.id] ? async () => {
                    if (!roomId || !guestToken) return;
                    setReplyStates(prev => ({ ...prev, [msg.id]: { state: 'loading', reply: '' } }));
                    try {
                      const result = await api.collab.generateReplyGuest(roomId, msg.id, msg.content, guestToken);
                      setReplyStates(prev => ({ ...prev, [msg.id]: { state: 'ready', reply: result.reply } }));
                    } catch {
                      toast.error('返信の生成に失敗しました');
                      setReplyStates(prev => { const n = { ...prev }; delete n[msg.id]; return n; });
                    }
                  } : undefined}
                />
                {/* Reply editor for owner messages - right-aligned with connector */}
                {msg.sender_type === 'owner' && replyStates[msg.id]?.state === 'ready' && (
                  <div className="flex items-stretch gap-0 mt-0">
                    <div className="flex-1 flex items-end justify-end pr-1.5 pb-6">
                      <div className="w-full h-[calc(100%-8px)] border-b-2 border-l-2 border-violet-500/25 rounded-bl-xl" />
                    </div>
                    <div className="w-[min(65%,420px)] space-y-1.5 pt-1">
                      <textarea
                        value={replyStates[msg.id].reply}
                        onChange={(e) => setReplyStates(prev => ({ ...prev, [msg.id]: { ...prev[msg.id], reply: e.target.value } }))}
                        className="w-full text-sm bg-background border border-violet-500/30 rounded-lg px-3 py-2 resize-none focus:outline-none focus:border-violet-500"
                        rows={Math.min((replyStates[msg.id].reply || '').split('\n').length + 1, 5)}
                      />
                      <div className="flex gap-1.5">
                        <Button
                          size="sm"
                          variant="ghost"
                          className="flex-1 text-xs"
                          onClick={() => setReplyStates(prev => { const n = { ...prev }; delete n[msg.id]; return n; })}
                        >
                          キャンセル
                        </Button>
                        <Button
                          size="sm"
                          className="flex-1 bg-violet-600 hover:bg-violet-700 text-white"
                          onClick={() => {
                            const text = replyStates[msg.id].reply.trim();
                            if (text) {
                              wsSend(text);
                              setReplyStates(prev => ({ ...prev, [msg.id]: { ...prev[msg.id], state: 'sent' } }));
                            }
                          }}
                          disabled={!replyStates[msg.id].reply.trim()}
                        >
                          <Send className="h-3.5 w-3.5 mr-1" />
                          送信
                        </Button>
                      </div>
                    </div>
                  </div>
                )}
                {msg.sender_type === 'owner' && replyStates[msg.id]?.state === 'sent' && (
                  <p className="text-[10px] text-violet-300 mt-1 text-right">返信済み</p>
                )}
              </div>
            );
          })}
          {danThinking && (
            <div className="flex justify-end">
              <div className="bg-violet-500/10 border border-violet-500/20 rounded-lg px-3 py-2 flex items-center gap-2">
                <Bot className="h-4 w-4 text-violet-400 animate-pulse" />
                <span className="text-xs text-violet-300">DAN 分析中...</span>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Name edit overlay */}
      {editingName && (
        <div className="absolute inset-0 z-50 bg-background/80 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-card border rounded-xl shadow-lg p-4 w-full max-w-sm space-y-3">
            <p className="font-semibold text-sm">表示名を変更</p>
            <Input
              value={editNameValue}
              onChange={(e) => setEditNameValue(e.target.value)}
              autoFocus
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.nativeEvent.isComposing) applyRename();
              }}
            />
            <div className="flex gap-2">
              <Button variant="outline" className="flex-1" onClick={() => { setEditingName(false); setEditNameValue(''); }}>キャンセル</Button>
              <Button className="flex-1" onClick={applyRename}>保存</Button>
            </div>
          </div>
        </div>
      )}

      {/* Install guide modal */}
      {showInstallGuide && (
        <div className="absolute inset-0 z-50 bg-background/90 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-card border rounded-2xl shadow-xl p-5 w-full max-w-sm space-y-4 relative max-h-[90vh] overflow-y-auto">
            <button onClick={() => setShowInstallGuide(false)} className="absolute top-3 right-3 text-muted-foreground hover:text-foreground">
              <X className="h-5 w-5" />
            </button>
            <h3 className="font-bold text-base">通知を受け取るには</h3>
            <p className="text-xs text-muted-foreground">ホーム画面にアプリを追加すると、LINEのように新着メッセージの通知が届きます。</p>
            <p className="text-xs text-violet-300">
              追加したアイコンから開くと、画面上部に<b>「タップして通知をオンにする」</b>が出ます。押して「許可」を選べば設定完了です。
            </p>

            {/iPad|iPhone|iPod/.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1) ? (
              <div className="space-y-3">
                <div className="flex items-center gap-3 bg-muted/50 rounded-xl p-3">
                  <div className="h-9 w-9 rounded-full bg-blue-500/20 flex items-center justify-center text-lg font-bold text-blue-400 shrink-0">1</div>
                  <div>
                    <p className="text-sm font-medium">画面下の共有ボタンをタップ</p>
                    <div className="flex items-center gap-1 mt-0.5">
                      <Share className="h-4 w-4 text-blue-400" />
                      <span className="text-xs text-muted-foreground">四角に上矢印のアイコン</span>
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-3 bg-muted/50 rounded-xl p-3">
                  <div className="h-9 w-9 rounded-full bg-blue-500/20 flex items-center justify-center text-lg font-bold text-blue-400 shrink-0">2</div>
                  <div>
                    <p className="text-sm font-medium">「ホーム画面に追加」をタップ</p>
                    <span className="text-xs text-muted-foreground">下にスクロールすると見つかります</span>
                  </div>
                </div>
                <div className="flex items-center gap-3 bg-muted/50 rounded-xl p-3">
                  <div className="h-9 w-9 rounded-full bg-green-500/20 flex items-center justify-center text-lg font-bold text-green-400 shrink-0">3</div>
                  <div>
                    <p className="text-sm font-medium">右上の「追加」をタップ</p>
                    <span className="text-xs text-muted-foreground">ホーム画面にアイコンが追加されます</span>
                  </div>
                </div>
              </div>
            ) : (
              <div className="space-y-3">
                <div className="flex items-center gap-3 bg-muted/50 rounded-xl p-3">
                  <div className="h-9 w-9 rounded-full bg-blue-500/20 flex items-center justify-center text-lg font-bold text-blue-400 shrink-0">1</div>
                  <div>
                    <p className="text-sm font-medium">右上の「⋮」メニューをタップ</p>
                    <div className="flex items-center gap-1 mt-0.5">
                      <MoreVertical className="h-4 w-4 text-blue-400" />
                      <span className="text-xs text-muted-foreground">3つの点のアイコン</span>
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-3 bg-muted/50 rounded-xl p-3">
                  <div className="h-9 w-9 rounded-full bg-blue-500/20 flex items-center justify-center text-lg font-bold text-blue-400 shrink-0">2</div>
                  <div>
                    <p className="text-sm font-medium">「アプリをインストール」</p>
                    <p className="text-sm font-medium">または「ホーム画面に追加」</p>
                  </div>
                </div>
              </div>
            )}

            <button onClick={() => setShowInstallGuide(false)} className="w-full text-center text-xs text-muted-foreground hover:text-foreground py-1">
              閉じる
            </button>
          </div>
        </div>
      )}

      {/* Input */}
      <div className="shrink-0 border-t px-4 py-3">
        {replyTo && (
          <div className="mb-2 flex items-center gap-2 rounded-lg border border-primary/30 bg-primary/5 px-3 py-2">
            <Reply className="h-3.5 w-3.5 shrink-0 text-primary" />
            <div className="min-w-0 flex-1">
              <span className="text-xs font-medium text-primary">
                {replyTo.sender_type.startsWith('dan_') ? 'DAN' : replyTo.sender_name}に返信
              </span>
              <p className="truncate text-xs text-muted-foreground">
                {(replyTo.content || '').slice(0, 100) || '(ファイル)'}
              </p>
            </div>
            <button onClick={() => setReplyTo(null)} className="shrink-0 text-muted-foreground hover:text-foreground">
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        )}
      <div className="flex items-center gap-2">
        <input type="file" ref={fileInputRef} className="hidden" onChange={handleFileUpload}
          accept="image/*,video/*,audio/*,.pdf,.doc,.docx,.xls,.xlsx,.zip" />
        <Button variant="ghost" size="icon" onClick={() => fileInputRef.current?.click()} disabled={isUploading}>
          <Paperclip className="h-4 w-4" />
        </Button>
        <Button
          variant={danMode ? "default" : "ghost"}
          size="icon"
          onClick={() => setDanMode(!danMode)}
          className={danMode ? "bg-violet-600 hover:bg-violet-700 text-white" : ""}
          title={danMode ? "DANモード ON（相手に見えません）" : "AIに聞く"}
        >
          <Bot className="h-4 w-4" />
        </Button>
        <div className="flex-1 relative">
          {danMode && (
            <div className="absolute left-3 top-1/2 -translate-y-1/2 text-[10px] text-violet-400 font-medium pointer-events-none">
              DAN宛
            </div>
          )}
          <textarea
            ref={inputRef as any}
            placeholder={danMode ? "AIに質問..." : "メッセージを入力..."}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            rows={1}
            className={`flex w-full rounded-md border border-input bg-background px-3 py-2 text-sm resize-none ${danMode ? "pl-14 border-violet-500/50 bg-violet-500/5" : ""}`}
            style={{ maxHeight: '120px', overflowY: 'auto' }}
            onInput={(e) => {
              const t = e.target as HTMLTextAreaElement;
              t.style.height = 'auto';
              t.style.height = Math.min(t.scrollHeight, 120) + 'px';
            }}
          />
        </div>
        <Button
          size="icon"
          onClick={handleSend}
          disabled={!input.trim()}
          className={`transition-transform active:scale-90 ${danMode ? "bg-violet-600 hover:bg-violet-700" : ""}`}
        >
          <Send className="h-4 w-4" />
        </Button>
      </div>
      </div>
    </div>
  );
}

function GuestCollabReplyQuote({ replyTo }: { replyTo: { id: string; sender_name: string; sender_type: string; content: string } }) {
  const truncated = (replyTo.content || '').slice(0, 80);
  const label = replyTo.sender_type.startsWith('dan_') ? 'DAN' : replyTo.sender_name;

  const handleClick = useCallback(() => {
    const el = document.querySelector(`[data-collab-msg-id="${replyTo.id}"]`);
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'center' });
      el.classList.add('ring-2', 'ring-primary/50', 'rounded-lg');
      setTimeout(() => el.classList.remove('ring-2', 'ring-primary/50', 'rounded-lg'), 1500);
    }
  }, [replyTo.id]);

  return (
    <div
      onClick={handleClick}
      className="flex items-start gap-1.5 rounded-md bg-muted/60 border-l-2 border-primary/50 px-2.5 py-1.5 text-xs text-muted-foreground mb-1 max-w-full overflow-hidden cursor-pointer hover:bg-muted/80 transition-colors"
    >
      <Reply className="h-3 w-3 mt-0.5 shrink-0 rotate-180" />
      <div className="min-w-0">
        <span className="font-medium text-foreground/80">{label}</span>
        <p className="truncate">{truncated || '(ファイル)'}</p>
      </div>
    </div>
  );
}

function GuestMessageBubble({ message, showRead, replyState, onGenerateReply, onReply, myName, onReact }: {
  message: CollabMessageResponse;
  showRead?: boolean;
  replyState?: 'loading' | 'ready' | 'sent';
  onGenerateReply?: () => void;
  onReply?: (msg: CollabMessageResponse) => void;
  myName?: string;
  onReact?: (msg: CollabMessageResponse, emoji: string) => void;
}) {
  const isGuest = message.sender_type === 'guest';
  const isDan = message.sender_type.startsWith('dan_');
  const isOwner = message.sender_type === 'owner';
  // 絵文字1〜2個だけの発言はスタンプとして大きく表示
  const isStamp = /^(\p{Extended_Pictographic}(️)?){1,2}$/u.test((message.content || '').trim());

  function SenderIcon({ type }: { type: string }) {
    switch (type) {
      case 'owner': return <User className="h-4 w-4" />;
      case 'guest': return <UserCheck className="h-4 w-4" />;
      default: return <Bot className="h-4 w-4" />;
    }
  }

  const isPrivate = message.metadata?.visibility === 'guest_only';
  const isGuestPrivate = isGuest && isPrivate;
  const replyToData = message.metadata?.reply_to as { id: string; sender_name: string; sender_type: string; content: string } | undefined;

  return (
    <div className={`flex flex-col animate-in fade-in slide-in-from-bottom-2 duration-150 ease-out motion-reduce:animate-none ${isGuest || (isDan && isPrivate) ? 'items-end' : 'items-start'} max-w-[75%] ${isGuest || (isDan && isPrivate) ? 'ml-auto' : 'mr-auto'}`}>
      {replyToData && <GuestCollabReplyQuote replyTo={replyToData} />}
      {/* LINE式: 名前は相手側とダンだけバブルの上（自分の名前は出さない） */}
      {!isPrivate && !isGuest && (
        <span className="mb-0.5 mx-1 text-[11px] text-muted-foreground">
          {isDan ? 'ダン' : message.sender_name}
        </span>
      )}
      <div className={`group flex items-end gap-1.5 ${isGuest || (isDan && isPrivate) ? 'flex-row' : 'flex-row-reverse'}`}>
        {onReply && (
          <button
            onClick={() => onReply(message)}
            className="self-start mt-1.5 opacity-0 group-hover:opacity-100 transition-opacity text-muted-foreground hover:text-foreground p-1 rounded"
            title="返信"
          >
            <Reply className="h-3.5 w-3.5" />
          </button>
        )}
        {/* LINE式: 時刻・既読はバブルの外側（横・下揃え） */}
        {!isPrivate && (
          <div className={`flex flex-col justify-end pb-0.5 text-[10px] leading-tight text-muted-foreground ${isGuest ? 'items-end' : 'items-start'}`}>
            {showRead && <span>既読</span>}
            <span>{formatTime(message.created_at)}</span>
          </div>
        )}
        <div
          data-bubble
          className={`rounded-lg ${isStamp && !isPrivate ? 'px-1 py-0' : 'px-3 py-2'} ${
            isStamp && !isPrivate
              ? ''
              : isPrivate
                ? 'bg-violet-500/10 border border-dashed border-violet-500/30'
                : isGuest
                  ? 'bg-primary text-primary-foreground'
                  : 'bg-muted'
          }`}
        >
          {isPrivate && (
            <div className="flex items-center gap-1.5 mb-1">
              <Bot className="h-4 w-4 text-violet-400" />
              <span className="text-xs font-medium text-violet-400">
                {isGuestPrivate ? `${message.sender_name} → DAN` : 'DAN'}
              </span>
              <span className="text-[10px] bg-violet-500/20 text-violet-300 px-1.5 py-0.5 rounded-full">非公開</span>
              <span className="text-[10px] opacity-50 ml-auto">{formatTime(message.created_at)}</span>
            </div>
          )}
          {(() => {
            const file = message.metadata?.file as { name: string; url: string; type: string; size: number } | undefined;
            const isImage = file?.type?.startsWith('image/');
            if (file && isImage) {
              return <a href={file.url} target="_blank" rel="noopener noreferrer"><img src={file.url} alt={file.name} className="max-w-full max-h-60 rounded mt-1" /></a>;
            }
            if (file) {
              return <a href={file.url} target="_blank" rel="noopener noreferrer" className="flex items-center gap-2 mt-1 text-sm underline opacity-80"><Paperclip className="h-3.5 w-3.5" />{file.name}</a>;
            }
            return null;
          })()}
          <p className={`whitespace-pre-wrap break-words ${isStamp ? 'text-4xl leading-tight py-1' : 'text-sm'}`}><LinkifyText text={message.content} /></p>

          {/* リアクション（ダンの🙏既読サイン＋自分の付け外し。スマホ向けに「+」常時表示） */}
          {onReact && (
            <ReactionBar
              reactions={message.metadata?.reactions as Record<string, string[]> | undefined}
              myName={myName}
              align={isGuest ? 'right' : 'left'}
              compact
              onToggle={(emoji) => onReact(message, emoji)}
            />
          )}

          {/* Reply generation button for owner messages */}
          {isOwner && !replyState && onGenerateReply && (
            <button
              onClick={onGenerateReply}
              className="mt-1.5 flex items-center gap-1 text-[11px] text-violet-400 hover:text-violet-300 transition-colors"
            >
              <Sparkles className="h-3 w-3" />
              返信を生成
            </button>
          )}
          {isOwner && replyState === 'loading' && (
            <div className="mt-1.5 flex items-center gap-1 text-[11px] text-violet-400">
              <Loader2 className="h-3 w-3 animate-spin" />
              生成中...
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
