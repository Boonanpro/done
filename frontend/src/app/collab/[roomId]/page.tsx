'use client';

import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import {
  ArrowLeft, Send, Copy, Link2, Users, Settings2, Paperclip,
  Bot, User, UserCheck, Circle, Sparkles, Loader2, Reply, X,
} from 'lucide-react';
import { api, type CollabMessageResponse } from '@/lib/api-client';
import { OutboundMessageCard } from '@/components/chat/outbound-message-card';
import { ReactionBar } from '@/components/collab/reaction-bar';
import { MediaGrid, collabMediaItems } from '@/components/chat/media-grid';
import { PendingAttachments, uploadCollabFiles } from '@/components/collab/pending-attachments';
import { mergeLatest, mergeOlder, isAtBottom, isNearTop } from '@/lib/collab-scroll';
import { useUnreadStore } from '@/stores/unread-store';
import { useCollabWebSocket, type OnlineUser } from '@/hooks/useCollabWebSocket';
import { usePushNotification } from '@/hooks/usePushNotification';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { LinkifyText } from '@/components/linkify-text';
import { Switch } from '@/components/ui/switch';
import {
  Sheet, SheetContent, SheetHeader, SheetTitle, SheetTrigger,
} from '@/components/ui/sheet';

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

function SenderIcon({ type }: { type: string }) {
  switch (type) {
    case 'owner': return <User className="h-4 w-4" />;
    case 'guest': return <UserCheck className="h-4 w-4" />;
    case 'dan_owner':
    case 'dan_guest':
      return <Bot className="h-4 w-4" />;
    default: return <User className="h-4 w-4" />;
  }
}

function senderLabel(type: string): string {
  switch (type) {
    case 'owner': return 'オーナー';
    case 'guest': return 'ゲスト';
    case 'dan_owner': return 'DAN';
    case 'dan_guest': return 'DAN (ゲスト)';
    default: return type;
  }
}

export default function CollabRoomPage() {
  const params = useParams();
  const router = useRouter();
  const roomId = params.roomId as string;
  const queryClient = useQueryClient();
  const markRead = useUnreadStore((s) => s.markRead);

  // Mark room as read on mount
  useEffect(() => { markRead(roomId); }, [roomId, markRead]);
  const [input, setInput] = useState('');
  const [messages, setMessages] = useState<CollabMessageResponse[]>([]);
  const [inviteUrl, setInviteUrl] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  // スクロール制御: 「下にいる時だけ」新着で下へ送る。上へ遡っている間は動かさない
  const atBottomRef = useRef(true);
  const loadingOlderRef = useRef(false);
  const noMoreOlderRef = useRef(false);
  const messagesRef = useRef<CollabMessageResponse[]>([]);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [isUploading, setIsUploading] = useState(false);
  // 送信前の添付（添付しただけでは送らない。送信ボタンで本文と一緒に1メッセージ）
  const [pendingFiles, setPendingFiles] = useState<File[]>([]);
  const [danThinking, setDanThinking] = useState(false);
  const [readByOther, setReadByOther] = useState<string | null>(null); // last message_id read by other side
  // Reply generation state - keyed by message ID to survive re-renders
  const [replyStates, setReplyStates] = useState<Record<string, { state: 'loading' | 'ready' | 'sent'; reply: string }>>({});
  const [replyTo, setReplyTo] = useState<CollabMessageResponse | null>(null);

  // Fetch room info
  const { data: room } = useQuery({
    queryKey: ['collab-room', roomId],
    queryFn: () => api.collab.getRoom(roomId),
    enabled: !!roomId,
  });

  // Fetch initial messages
  const { data: messagesData } = useQuery({
    queryKey: ['collab-messages', roomId],
    queryFn: () => api.collab.getMessages(roomId),
    enabled: !!roomId,
  });

  // 参加者名簿＋既読位置（入室した人は恒久的に掲載。オンライン判定はしない）
  const { data: participants } = useQuery({
    queryKey: ['collab-participants', roomId],
    queryFn: () => api.collab.getParticipants(roomId),
    enabled: !!roomId,
    refetchInterval: 10_000,
  });

  // 自分の既読位置を定期更新（相手側の「既読」表示の元になる）
  useEffect(() => {
    if (!roomId) return;
    const mark = () => api.collab.markRead(roomId)
      .then(() => queryClient.invalidateQueries({ queryKey: ['collab-rooms'] }))
      .catch(() => {});
    mark();
    const timer = setInterval(mark, 10_000);
    return () => clearInterval(timer);
  }, [roomId]);

  // この窓口宛のダンの送信案カード（pending をインライン表示。承認/編集/破棄は本体チャットと同じ経路）
  const { data: outboundData } = useQuery({
    queryKey: ['collab-outbound', roomId],
    queryFn: () => api.proposals.listForCollab(roomId),
    enabled: !!roomId,
    refetchInterval: 10_000,
  });
  const pendingProposals = (outboundData?.proposals ?? []).filter((p) => p.status === 'pending');

  useEffect(() => {
    if (messagesData?.messages) {
      setMessages(messagesData.messages);
    }
  }, [messagesData]);

  // Get auth token
  const token = typeof window !== 'undefined' ? localStorage.getItem('done-token') || '' : '';

  // WebSocket
  // 受信メッセージの合流点。楽観表示の仮バブル（client_msg_id）と同一なら
  // 追加ではなく「その場で差し替え」る。WSエコー・REST応答・どちらが先でも
  // 二重表示にならず、描画キーも client_msg_id なのでDOMも作り直されない。
  const handleNewMessage = useCallback((msg: CollabMessageResponse) => {
    if (msg.sender_type?.startsWith('dan_')) {
      setDanThinking(false);
    }
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
    if (data.sender_type === 'guest') {
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
    roomId,
    token,
    isGuest: false,
    onMessage: handleNewMessage,
    onDanThinking: handleDanThinking,
    onRead: handleRead,
    onReaction: handleReaction,
  });

  // Send read receipt when new messages arrive from guest
  useEffect(() => {
    const lastMsg = messages[messages.length - 1];
    if (lastMsg && lastMsg.sender_type === 'guest') {
      sendRead(lastMsg.id);
    }
  }, [messages, sendRead]);

  // 部屋を開いた瞬間・WS再接続時に「考え中」状態を取得する。
  // これが無いと、ダンの作業中に部屋を開いた場合にインジケーターが出ない
  // （WSは開始イベントを聞き逃すと done まで何も来ないため）。
  useEffect(() => {
    if (!roomId) return;
    api.collab.getDanStatus(roomId)
      .then((s) => setDanThinking(!!s.thinking))
      .catch(() => {});
  }, [roomId, isConnected]);

  // WS が張れない環境（Vercel 経由など。rewrites は WS を通せない）では
  // REST ポーリングで受信＋考え中状態を代替する（4秒間隔＝体感リアルタイム）。
  useEffect(() => {
    if (!roomId || isConnected) return;
    const timer = setInterval(() => {
      api.collab.getMessages(roomId)
        .then((d) => setMessages((prev) => mergeLatest(prev, d.messages)))
        .catch(() => {});
      api.collab.getDanStatus(roomId)
        .then((s) => setDanThinking(!!s.thinking))
        .catch(() => {});
    }, 4000);
    return () => clearInterval(timer);
  }, [roomId, isConnected]);

  // Push notifications
  usePushNotification(roomId, 'owner');

  useEffect(() => { messagesRef.current = messages; }, [messages]);

  // 過去を読み足す（上端に近づいた時）。読んだ分だけ下へずらして、見ていた行を動かさない
  const loadOlder = useCallback(async () => {
    if (!roomId) return;
    if (loadingOlderRef.current || noMoreOlderRef.current) return;
    const oldest = messagesRef.current.find((m) => !m.id.startsWith('temp-'));
    if (!oldest) return;
    loadingOlderRef.current = true;
    setLoadingOlder(true);
    const el = scrollRef.current;
    const prevHeight = el?.scrollHeight ?? 0;
    const prevTop = el?.scrollTop ?? 0;
    try {
      const data = await api.collab.getMessages(roomId, 50, undefined, oldest.created_at);
      if (data.messages.length === 0) {
        noMoreOlderRef.current = true;
        return;
      }
      setMessages((prev) => mergeOlder(prev, data.messages));
      requestAnimationFrame(() => {
        const cur = scrollRef.current;
        if (cur) cur.scrollTop = prevTop + (cur.scrollHeight - prevHeight);
      });
    } catch {
      // 失敗時は次のスクロールで再試行
    } finally {
      loadingOlderRef.current = false;
      setLoadingOlder(false);
    }
  }, [roomId]);

  const handleScroll = useCallback(() => {
    const el = scrollRef.current;
    atBottomRef.current = isAtBottom(el);
    if (isNearTop(el)) void loadOlder();
  }, [loadOlder]);

  // 新着で最下部へ送るのは「いま最下部にいる時」だけ。
  // 上へ遡っている最中に送ると、4秒ごとのポーリングのたびに下へ戻されて遡れない。
  useEffect(() => {
    if (!atBottomRef.current) return;
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages]);


  // Send message — メインの入力欄は**相手（クライアント）専用**。
  // ダンへの返事は相談メッセージ内のスレッド入力欄から（sendPrivateReply）。
  const handleSend = async () => {
    const content = input.trim();
    if ((!content && pendingFiles.length === 0) || isUploading) return;
    atBottomRef.current = true;  // 自分が送った時は遡っていても最新へ戻る
    const metadata: Record<string, unknown> = {};
    // 添付は送信時にまとめてアップロード → files[] として本文と同じメッセージに載せる
    const filesToSend = pendingFiles;
    if (filesToSend.length > 0) {
      setIsUploading(true);
      try {
        const uploaded = await uploadCollabFiles(roomId, filesToSend, { token });
        metadata.files = uploaded;
        metadata.file = uploaded[0];
      } catch (err) {
        toast.error(`アップロードに失敗しました: ${(err as Error).message}`);
        setIsUploading(false);
        return;
      }
      setIsUploading(false);
      setPendingFiles([]);
    }
    if (replyTo) {
      metadata.reply_to = {
        id: replyTo.id,
        sender_name: replyTo.sender_name,
        sender_type: replyTo.sender_type,
        content: replyTo.content.slice(0, 200),
      };
    }
    // 楽観表示: 押した瞬間に自分のバブルを即表示。client_msg_id を焼き込み、
    // WSエコー/REST応答のどちらが先に来ても handleNewMessage が1回で差し替える。
    const savedReplyTo = replyTo;
    const tempId = `temp-${Date.now()}`;
    metadata.client_msg_id = tempId;
    const optimistic = {
      id: tempId, room_id: roomId, sender_type: 'owner',
      sender_name: [...messages].reverse().find((m) => m.sender_type === 'owner')?.sender_name || 'あなた',
      content, metadata: metadata as CollabMessageResponse['metadata'],
      created_at: new Date().toISOString(),
    } as CollabMessageResponse;
    setInput('');
    setReplyTo(null);
    setMessages((prev) => [...prev, optimistic]);
    inputRef.current?.focus();
    try {
      const sent = await api.collab.sendMessage(roomId, content, undefined, metadata);
      handleNewMessage(sent);
    } catch {
      toast.error('送信に失敗しました。通信環境をご確認ください');
      setMessages((prev) => prev.filter((m) => m.id !== tempId));
      setInput(content);
      setReplyTo(savedReplyTo);
      if (filesToSend.length > 0) setPendingFiles(filesToSend);
    }
  };

  // 相談スレッド内からのダン宛返信（相手には見えない）
  const sendPrivateReply = async (parent: CollabMessageResponse, text: string) => {
    const content = text.trim();
    if (!content) return;
    const md: Record<string, unknown> = {
      visibility: 'owner_only',
      reply_to: {
        id: parent.id,
        sender_name: parent.sender_name,
        sender_type: parent.sender_type,
        content: (parent.content || '').slice(0, 200),
      },
    };
    // 楽観表示（相談スレッド内の返信も押した瞬間に出す）
    const tempId = `temp-${Date.now()}`;
    md.client_msg_id = tempId;
    const myName = [...messages].reverse().find((m) => m.sender_type === 'owner')?.sender_name || 'あなた';
    const optimistic = {
      id: tempId, room_id: roomId, sender_type: 'owner', sender_name: myName,
      content, metadata: md as CollabMessageResponse['metadata'],
      created_at: new Date().toISOString(),
    } as CollabMessageResponse;
    setMessages((prev) => [...prev, optimistic]);
    try {
      const sent = await api.collab.sendMessage(roomId, content, undefined, md);
      handleNewMessage(sent);
    } catch {
      toast.error('送信に失敗しました。通信環境をご確認ください');
      setMessages((prev) => prev.filter((m) => m.id !== tempId));
    }
  };

  // 既読表示: 相手（ゲスト）の既読位置以前の「自分側の公開メッセージ」の最後の1件に「既読」を付ける
  const guestMaxRead = Math.max(
    0,
    ...((participants?.guests ?? []).map((g) => (g.last_read_at ? new Date(g.last_read_at).getTime() : 0)))
  );
  const lastReadOwnId = useMemo(() => {
    let id: string | null = null;
    for (const m of messages) {
      const priv = (m.metadata as { visibility?: string } | undefined)?.visibility;
      if (
        (m.sender_type === 'owner' || m.sender_type === 'dan_owner') && !priv &&
        new Date(m.created_at).getTime() <= guestMaxRead
      ) {
        id = m.id;
      }
    }
    return id;
  }, [messages, guestMaxRead]);

  // 相談スレッドの構造化: 親（相談）への返信（あなた・ダンの続き発言とも）を親の下にぶら下げる
  const messageIds = useMemo(() => new Set(messages.map((m) => m.id)), [messages]);
  const privateReplyMap = useMemo(() => {
    const map = new Map<string, CollabMessageResponse[]>();
    for (const m of messages) {
      const md = m.metadata as { visibility?: string; reply_to?: { id?: string } } | undefined;
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

  // 添付ボタン: 送信前の一覧に積むだけ（送信は handleSend で本文と一緒に）
  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || []);
    if (files.length > 0) setPendingFiles((prev) => [...prev, ...files]);
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  // Create invite
  const [showInviteDialog, setShowInviteDialog] = useState(false);

  const handleInvite = async () => {
    try {
      const data = await api.collab.createInvite(roomId);
      setInviteUrl(data.invite_url);

      // Copy using hidden input + execCommand (works on mobile Safari)
      const copied = copyToClipboard(data.invite_url);
      if (copied) {
        toast.success('招待リンクをコピーしました');
        return;
      }

      // Fallback: show dialog
      setShowInviteDialog(true);
    } catch (e: any) {
      const detail = e?.data?.detail || e?.message || '';
      toast.error(`招待リンク作成に失敗: ${detail}`, { duration: 10000 });
    }
  };

  function copyToClipboard(text: string): boolean {
    try {
      const textarea = document.createElement('textarea');
      textarea.value = text;
      textarea.style.position = 'fixed';
      textarea.style.opacity = '0';
      document.body.appendChild(textarea);
      textarea.focus();
      textarea.select();
      const ok = document.execCommand('copy');
      document.body.removeChild(textarea);
      return ok;
    } catch {
      return false;
    }
  }

  // AI assist toggle
  const toggleAssist = useMutation({
    mutationFn: (enabled: boolean) =>
      api.collab.updateRoom(roomId, { ai_auto_assist: enabled }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['collab-room', roomId] });
    },
  });

  return (
    <>
    <div className="flex flex-col h-full overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-3 px-4 py-3 border-b bg-background shrink-0">
        <Button variant="ghost" size="icon" className="shrink-0" onClick={() => router.push('/collab')}>
          <ArrowLeft className="h-5 w-5" />
        </Button>
        <div className="flex-1 min-w-0">
          <h2
            className="font-semibold truncate cursor-pointer hover:underline decoration-dashed underline-offset-4"
            onClick={() => {
              const newTitle = prompt('ルーム名を変更', room?.title || '');
              if (newTitle && newTitle.trim() && newTitle !== room?.title) {
                api.collab.updateRoom(roomId, { title: newTitle.trim() }).then(() => {
                  queryClient.invalidateQueries({ queryKey: ['collab-room', roomId] });
                });
              }
            }}
          >
            {room?.title ?? '...'}
          </h2>
          <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <Users className="h-3 w-3 shrink-0" />
            <span className="truncate">
              {participants
                ? `${1 + participants.guests.length}人: ${[participants.owner.name, ...participants.guests.map((g) => g.name)].join('、')}`
                : '...'}
            </span>
          </div>
        </div>
        {/* 自分のプロフィール（クリックで表示名を編集。チャット内では自分の名前を出さない代わり） */}
        <button
          className="flex items-center gap-1.5 rounded-full bg-muted/60 hover:bg-muted px-1 py-1 pr-2.5 transition-colors max-w-[130px]"
          title="表示名を編集"
          onClick={async () => {
            const current = participants?.owner.name || '';
            const v = window.prompt('表示名を変更', current);
            if (v && v.trim() && v.trim() !== current) {
              try {
                await api.auth.updateProfile(v.trim());
                queryClient.invalidateQueries({ queryKey: ['collab-participants', roomId] });
                toast.success('表示名を変更しました');
              } catch {
                toast.error('変更に失敗しました');
              }
            }
          }}
        >
          <span className="flex h-6 w-6 items-center justify-center rounded-full bg-primary">
            <User className="h-3.5 w-3.5 text-primary-foreground" />
          </span>
          <span className="truncate text-xs">{participants?.owner.name || '...'}</span>
        </button>
        <Button
          variant="outline"
          size="sm"
          onClick={handleInvite}
        >
          <Link2 className="h-4 w-4 mr-1" />
          招待
        </Button>
        <Sheet>
          <SheetTrigger asChild>
            <Button variant="ghost" size="icon">
              <Settings2 className="h-4 w-4" />
            </Button>
          </SheetTrigger>
          <SheetContent>
            <SheetHeader>
              <SheetTitle>ルーム設定</SheetTitle>
            </SheetHeader>
            <div className="space-y-6 mt-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="font-medium text-sm">DAN 自動アシスト</p>
                  <p className="text-xs text-muted-foreground">フィードバック要約・ファイル整理</p>
                </div>
                <Switch
                  checked={room?.ai_auto_assist ?? true}
                  onCheckedChange={(v) => toggleAssist.mutate(v)}
                />
              </div>

              <div>
                <p className="font-medium text-sm mb-2">参加者</p>
                <div className="space-y-1.5 text-sm">
                  {participants ? (
                    <>
                      <div className="flex items-center gap-2">
                        <User className="h-3.5 w-3.5 text-muted-foreground" />
                        <span>{participants.owner.name}（あなた）</span>
                      </div>
                      {participants.guests.map((g) => (
                        <div key={g.id} className="flex items-center gap-2">
                          <UserCheck className="h-3.5 w-3.5 text-muted-foreground" />
                          <span>{g.name}</span>
                          {g.joined_at && (
                            <span className="text-[10px] text-muted-foreground">
                              {new Date(g.joined_at).toLocaleDateString('ja-JP')}参加
                            </span>
                          )}
                        </div>
                      ))}
                      {participants.guests.length === 0 && (
                        <p className="text-xs text-muted-foreground">まだ相手が参加していません</p>
                      )}
                    </>
                  ) : (
                    <p className="text-xs text-muted-foreground">読み込み中...</p>
                  )}
                </div>
              </div>

              {inviteUrl && (
                <div>
                  <p className="font-medium text-sm mb-2">招待リンク</p>
                  <div className="flex gap-2">
                    <Input value={inviteUrl} readOnly className="text-xs" />
                    <Button
                      size="icon"
                      variant="outline"
                      onClick={() => {
                        navigator.clipboard.writeText(inviteUrl);
                        toast.success('コピーしました');
                      }}
                    >
                      <Copy className="h-4 w-4" />
                    </Button>
                  </div>
                </div>
              )}

              <div>
                <p className="font-medium text-sm mb-2">参加者</p>
                <div className="space-y-2">
                  {onlineUsers.map((u, i) => (
                    <div key={i} className="flex items-center gap-2 text-sm">
                      <SenderIcon type={u.sender_type} />
                      <span>{u.sender_name}</span>
                      <span className="text-xs text-muted-foreground">({senderLabel(u.sender_type)})</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </SheetContent>
        </Sheet>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 overscroll-contain" ref={scrollRef} onScroll={handleScroll}>
        <div className="space-y-3 py-4">
          {loadingOlder && (
            <div className="flex justify-center py-2">
              <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
            </div>
          )}
          {messages.map((msg, i) => {
            // 相談スレッドに属する私的メッセージ（あなたの返信・ダンの続き）は
            // 親のスレッド内に表示するので、単独では出さない
            const mdv = msg.metadata as { visibility?: string; reply_to?: { id?: string } } | undefined;
            if (
              (msg.sender_type === 'owner' || msg.sender_type === 'dan_owner') &&
              mdv?.visibility === 'owner_only' && mdv?.reply_to?.id && messageIds.has(mdv.reply_to.id)
            ) {
              return null;
            }
            const prevDate = i > 0 ? new Date(messages[i - 1].created_at).toDateString() : '';
            const curDate = new Date(msg.created_at).toDateString();
            const showSeparator = curDate !== prevDate;
            const rs = replyStates[msg.id];
            return (
              <div key={(msg.metadata as { client_msg_id?: string } | undefined)?.client_msg_id || msg.id}>
                {showSeparator && (
                  <div className="flex items-center gap-3 py-2">
                    <div className="flex-1 border-t border-border" />
                    <span className="text-[10px] text-muted-foreground shrink-0">{formatDateSeparator(msg.created_at)}</span>
                    <div className="flex-1 border-t border-border" />
                  </div>
                )}
                <div data-collab-msg-id={msg.id}>
                <MessageBubble
                  message={msg}
                  privateReplies={privateReplyMap.get(msg.id)}
                  onPrivateReply={sendPrivateReply}
                  myName={participants?.owner.name}
                  onReact={(m, emoji) => {
                    api.collab.react(roomId, m.id, emoji)
                      .then((r) => handleReaction({ message_id: m.id, reactions: r.reactions }))
                      .catch(() => toast.error('リアクションに失敗しました'));
                  }}
                  isOwner={msg.sender_type === 'owner'}
                  showRead={msg.id === lastReadOwnId}
                  replyState={rs?.state}
                  onReply={setReplyTo}
                  onGenerateReply={async () => {
                    setReplyStates(prev => ({ ...prev, [msg.id]: { state: 'loading', reply: '' } }));
                    try {
                      const result = await api.collab.generateReply(roomId, msg.id, msg.content);
                      setReplyStates(prev => ({ ...prev, [msg.id]: { state: 'ready', reply: result.reply } }));
                    } catch {
                      toast.error('返信の生成に失敗しました');
                      setReplyStates(prev => { const n = { ...prev }; delete n[msg.id]; return n; });
                    }
                  }}
                />
                {/* Reply editor - right-aligned with connector line to guest message */}
                {msg.sender_type === 'guest' && rs?.state === 'ready' && (
                  <div className="flex items-stretch gap-0 mt-0">
                    {/* Connector line: curves from left (guest msg) to right (reply editor) */}
                    <div className="flex-1 flex items-end justify-end pr-1.5 pb-6">
                      <div className="w-full h-[calc(100%-8px)] border-b-2 border-l-2 border-violet-500/25 rounded-bl-xl" />
                    </div>
                    <div className="w-[min(65%,420px)] space-y-1.5 pt-1">
                      <textarea
                        value={rs.reply}
                        onChange={(e) => setReplyStates(prev => ({ ...prev, [msg.id]: { ...prev[msg.id], reply: e.target.value } }))}
                        className="w-full text-sm bg-background border border-violet-500/30 rounded-lg px-3 py-2 resize-none focus:outline-none focus:border-violet-500"
                        rows={Math.min((rs.reply || '').split('\n').length + 1, 5)}
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
                            const text = rs.reply.trim();
                            if (text) {
                              wsSend(text);
                              setReplyStates(prev => ({ ...prev, [msg.id]: { ...prev[msg.id], state: 'sent' } }));
                            }
                          }}
                          disabled={!rs.reply.trim()}
                        >
                          <Send className="h-3.5 w-3.5 mr-1" />
                          送信
                        </Button>
                      </div>
                    </div>
                  </div>
                )}
                {msg.sender_type === 'guest' && rs?.state === 'sent' && (
                  <p className="text-[10px] text-violet-300 mt-1 text-right">返信済み</p>
                )}
                </div>
              </div>
            );
          })}
          {danThinking && (
            <div className="flex justify-end">
              <div className="bg-violet-500/10 border border-violet-500/20 rounded-lg px-3 py-2 flex items-center gap-2">
                <Bot className="h-4 w-4 text-violet-400 animate-pulse" />
                <span className="text-xs text-violet-300">考え中...</span>
              </div>
            </div>
          )}
          {/* ダンの送信案カード（承認すると相手のチャットに送られる。オーナーだけに見える）
              自分側から出るものなので右寄せ */}
          {pendingProposals.length > 0 && (
            <div className="flex flex-col items-end space-y-3 pt-2">
              <div className="flex items-center gap-1.5 text-xs text-violet-300">
                <Bot className="h-3.5 w-3.5" />
                ダンが返信案を用意しています（送信するまで相手には見えません）
              </div>
              {pendingProposals.map((p) => (
                <OutboundMessageCard key={p.id} proposalId={p.id} />
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Input */}
      <div className="shrink-0 border-t bg-background px-4 py-3">
        {replyTo && (
          <div className="mb-2 flex items-center gap-2 rounded-lg border border-primary/30 bg-primary/5 px-3 py-2">
            <Reply className="h-3.5 w-3.5 shrink-0 text-primary" />
            <div className="min-w-0 flex-1">
              <span className="text-xs font-medium text-primary">
                {replyTo.sender_name}に返信
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
        <input
          type="file"
          ref={fileInputRef}
          className="hidden"
          onChange={handleFileUpload}
          multiple
          accept="image/*,video/*,audio/*,.pdf,.doc,.docx,.xls,.xlsx,.zip"
        />
        <Button
          variant="ghost"
          size="icon"
          onClick={() => fileInputRef.current?.click()}
          disabled={isUploading}
        >
          <Paperclip className="h-4 w-4" />
        </Button>
        <div className="flex-1 relative">
          <PendingAttachments files={pendingFiles} onRemove={(i) => setPendingFiles((p) => p.filter((_, j) => j !== i))} />
          <textarea
            ref={inputRef as any}
            placeholder="メッセージを入力..."
            value={input}
            onChange={(e) => setInput(e.target.value)}
            rows={1}
            className="flex w-full rounded-md border border-input bg-background px-3 py-2 text-sm resize-none"
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
          disabled={(!input.trim() && pendingFiles.length === 0) || isUploading}
          className="transition-transform active:scale-90"
        >
          {isUploading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
        </Button>
      </div>
      </div>
    </div>

    {/* Invite link dialog */}
    {showInviteDialog && inviteUrl && (
      <div className="fixed inset-0 z-50 bg-background/80 backdrop-blur-sm flex items-center justify-center p-4">
        <div className="bg-card border rounded-xl shadow-lg p-5 w-full max-w-sm space-y-4">
          <h3 className="font-semibold">招待リンク</h3>
          <p className="text-xs text-muted-foreground">このリンクを友人に共有してください</p>
          <input
            readOnly
            value={inviteUrl}
            className="w-full text-xs bg-muted rounded px-3 py-2 select-all"
            onFocus={(e) => e.target.select()}
          />
          <div className="flex gap-2">
            {typeof navigator !== 'undefined' && navigator.share && (
              <Button
                className="flex-1"
                onClick={async () => {
                  try {
                    await navigator.share({ title: room?.title || 'コラボルーム', url: inviteUrl });
                    setShowInviteDialog(false);
                  } catch { /* cancelled */ }
                }}
              >
                共有
              </Button>
            )}
            <Button
              variant="outline"
              className="flex-1"
              onClick={() => {
                if (copyToClipboard(inviteUrl)) {
                  toast.success('コピーしました');
                  setShowInviteDialog(false);
                } else {
                  toast.error('テキストを長押しでコピーしてください');
                }
              }}
            >
              <Copy className="h-4 w-4 mr-1" />
              コピー
            </Button>
          </div>
          <Button variant="ghost" className="w-full" onClick={() => setShowInviteDialog(false)}>
            閉じる
          </Button>
        </div>
      </div>
    )}

    </>
  );
}

function CollabReplyQuote({ replyTo }: { replyTo: { id: string; sender_name: string; sender_type: string; content: string } }) {
  const truncated = (replyTo.content || '').replace(/\[添付[^\]]*\]/g, '').trim().slice(0, 80);
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

function MessageBubble({ message, isOwner, showRead, replyState, onGenerateReply, onReply, privateReplies, onPrivateReply, myName, onReact }: {
  message: CollabMessageResponse;
  isOwner: boolean;
  showRead?: boolean;
  replyState?: 'loading' | 'ready' | 'sent';
  onGenerateReply?: () => void;
  onReply?: (msg: CollabMessageResponse) => void;
  privateReplies?: CollabMessageResponse[];
  onPrivateReply?: (parent: CollabMessageResponse, text: string) => void;
  myName?: string;
  onReact?: (msg: CollabMessageResponse, emoji: string) => void;
}) {
  const isDan = message.sender_type.startsWith('dan_');
  const isGuest = message.sender_type === 'guest';
  const isPrivate = message.metadata?.visibility === 'owner_only';
  const { media, others } = collabMediaItems(message.metadata as Record<string, unknown> | undefined);
  const hasFiles = media.length > 0 || others.length > 0;
  // 添付だけのメッセージは本文がファイル名（旧形式）か空なので本文行を出さない
  const bodyText = hasFiles && (!message.content || others.some((f) => f.name === message.content) || media.some((m) => m.name === message.content)) ? '' : (message.content || '');
  // 絵文字1〜2個だけの発言はスタンプとして大きく表示
  const isStamp = !hasFiles && /^(\p{Extended_Pictographic}(️)?){1,2}$/u.test((message.content || '').trim());
  // 画像・動画だけの発言は吹き出しの枠を付けず、そのまま置く（LINE式）
  const bare = (isStamp || (media.length > 0 && !bodyText && others.length === 0)) && !isPrivate;
  const isOwnerPrivate = isOwner && isPrivate;
  const replyToData = message.metadata?.reply_to as { id: string; sender_name: string; sender_type: string; content: string } | undefined;

  return (
    <div className={`flex flex-col animate-in fade-in slide-in-from-bottom-3 zoom-in-95 duration-200 motion-reduce:animate-none ${isOwner || isDan ? 'items-end' : 'items-start'} max-w-[75%] ${isOwner || isDan ? 'ml-auto' : 'mr-auto'}`}>
      {replyToData && <CollabReplyQuote replyTo={replyToData} />}
      {/* LINE式: 名前は相手側とダンだけバブルの上（自分の名前は出さない） */}
      {!isPrivate && !isOwner && !isDan && (
        <span className="mb-0.5 mx-1 text-[11px] text-muted-foreground">{message.sender_name}</span>
      )}
      {!isPrivate && isDan && (
        <span className="mb-0.5 mx-1 text-[11px] text-muted-foreground">ダン</span>
      )}
      <div className={`group flex items-end gap-1.5 ${isOwner || isDan ? 'flex-row' : 'flex-row-reverse'}`}>
        {onReply && !(isDan && isPrivate) && (
          <button
            onClick={() => onReply(message)}
            className="self-start mt-1.5 opacity-40 group-hover:opacity-100 transition-opacity text-muted-foreground hover:text-foreground p-1 rounded"
            title="返信"
          >
            <Reply className="h-3.5 w-3.5" />
          </button>
        )}
        {/* LINE式: 時刻・既読はバブルの外側（横・下揃え） */}
        {!isPrivate && (
          <div className={`flex flex-col justify-end pb-0.5 text-[10px] leading-tight text-muted-foreground ${isOwner || isDan ? 'items-end' : 'items-start'}`}>
            {showRead && <span>既読</span>}
            <span>{formatTime(message.created_at)}</span>
          </div>
        )}
        <div
          data-bubble
          className={`rounded-lg ${bare ? 'px-1 py-0' : 'px-3 py-2'} ${
            /* 色の意味: 紫=あなたにしか見えない（相談・ダンへの私的返信）/
               primary=相手に見える自分側（あなた・ダン）/ muted=相手 */
            bare
              ? ''
              : isPrivate
                ? 'bg-violet-500/15 border border-dashed border-violet-500/40'
                : isOwner || isDan
                  ? 'bg-primary text-primary-foreground'
                  : 'bg-muted'
          }`}
        >
          {isPrivate && (
            <div className="flex items-center gap-1.5 mb-1">
              <Bot className="h-4 w-4 text-violet-400" />
              <span className="text-xs font-medium text-violet-400">
                {isOwnerPrivate ? `${message.sender_name} → DAN` : 'ダン'}
              </span>
              <span className="text-[10px] bg-violet-500/20 text-violet-300 px-1.5 py-0.5 rounded-full">非公開</span>
              <span className="text-[10px] opacity-50 ml-auto">
                {formatTime(message.created_at)}
              </span>
            </div>
          )}
          {media.length > 0 && <MediaGrid items={media} />}
          {others.map((f) => (
            <a
              key={f.url}
              href={f.url}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-2 mt-1 text-sm underline opacity-80"
            >
              <Paperclip className="h-3.5 w-3.5" />
              {f.name}
              {f.size ? <span className="text-xs opacity-50">({(f.size / 1024).toFixed(0)}KB)</span> : null}
            </a>
          ))}
          {bodyText && <p className={`whitespace-pre-wrap break-words ${isStamp ? 'text-4xl leading-tight py-1' : 'text-sm'}`}><LinkifyText text={bodyText} /></p>}

          {/* リアクション（ダンの🙏既読サイン＋人間の付け外し） */}
          {onReact && (
            <ReactionBar
              reactions={message.metadata?.reactions as Record<string, string[]> | undefined}
              myName={myName}
              align={isOwner || isDan ? 'right' : 'left'}
              onToggle={(emoji) => onReact(message, emoji)}
            />
          )}

          {/* 相談スレッド: あなたの返事の履歴 + 専用入力欄（メインの入力欄は相手専用） */}
          {isDan && isPrivate && (
            <div className="mt-2.5 space-y-1.5 border-t border-violet-500/25 pt-2">
              {(privateReplies || []).map((r) => (
                <div
                  key={r.id}
                  className={`rounded-md px-2.5 py-1.5 ${
                    r.sender_type === 'dan_owner' ? 'bg-violet-500/20' : 'bg-violet-500/10'
                  }`}
                >
                  <p className="mb-0.5 text-[10px] text-violet-300/80">
                    {r.sender_type === 'dan_owner' ? 'ダン' : `${r.sender_name} → ダン`}
                  </p>
                  <p className="whitespace-pre-wrap break-words text-sm">{r.content}</p>
                </div>
              ))}
              {onPrivateReply && (
                <ConsultReplyInput onSend={(t) => onPrivateReply(message, t)} />
              )}
            </div>
          )}

          {/* Reply generation button - stays inside bubble */}
          {isGuest && !replyState && (
            <button
              onClick={onGenerateReply}
              className="mt-1.5 flex items-center gap-1 text-[11px] text-violet-400 hover:text-violet-300 transition-colors"
            >
              <Sparkles className="h-3 w-3" />
              返信を生成
            </button>
          )}
          {isGuest && replyState === 'loading' && (
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

/** 相談メッセージ内のダン宛スレッド入力欄。相手には一切見えない。 */
function ConsultReplyInput({ onSend }: { onSend: (text: string) => void }) {
  const [text, setText] = useState('');
  const submit = () => {
    const t = text.trim();
    if (!t) return;
    onSend(t);
    setText('');
  };
  return (
    <div className="flex items-center gap-1.5">
      <input
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.nativeEvent.isComposing) {
            e.preventDefault();
            submit();
          }
        }}
        placeholder="ダンに返事…（相手には見えません）"
        className="flex-1 rounded-md border border-violet-500/40 bg-background/60 px-2.5 py-1.5 text-sm focus:outline-none focus:border-violet-400"
      />
      <button
        onClick={submit}
        disabled={!text.trim()}
        className="rounded-md bg-violet-600 p-1.5 text-white transition-colors hover:bg-violet-700 disabled:opacity-40"
        aria-label="ダンに送信"
      >
        <Send className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}
