'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import {
  ArrowLeft, Send, Copy, Link2, Users, Settings2, Paperclip,
  Bot, User, UserCheck, Circle,
} from 'lucide-react';
import { api, type CollabMessageResponse } from '@/lib/api-client';
import { MainLayout } from '@/components/layout/main-layout';
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
  const [input, setInput] = useState('');
  const [messages, setMessages] = useState<CollabMessageResponse[]>([]);
  const [inviteUrl, setInviteUrl] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [danThinking, setDanThinking] = useState(false);
  const [danMode, setDanMode] = useState(false);
  const [readByOther, setReadByOther] = useState<string | null>(null); // last message_id read by other side

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

  useEffect(() => {
    if (messagesData?.messages) {
      setMessages(messagesData.messages);
    }
  }, [messagesData]);

  // Get auth token
  const token = typeof window !== 'undefined' ? localStorage.getItem('done-token') || '' : '';

  // WebSocket
  const handleNewMessage = useCallback((msg: CollabMessageResponse) => {
    if (msg.sender_type?.startsWith('dan_')) {
      setDanThinking(false);
    }
    setMessages((prev) => {
      if (prev.some((m) => m.id === msg.id)) return prev;
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

  const { isConnected, onlineUsers, sendMessage: wsSend, sendRead } = useCollabWebSocket({
    roomId,
    token,
    isGuest: false,
    onMessage: handleNewMessage,
    onDanThinking: handleDanThinking,
    onRead: handleRead,
  });

  // Send read receipt when new messages arrive from guest
  useEffect(() => {
    const lastMsg = messages[messages.length - 1];
    if (lastMsg && lastMsg.sender_type === 'guest') {
      sendRead(lastMsg.id);
    }
  }, [messages, sendRead]);

  // Push notifications
  usePushNotification(roomId, 'owner');

  // Auto-scroll
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  // Send message
  const handleSend = () => {
    const content = input.trim();
    if (!content) return;
    const finalContent = danMode ? `@ダン ${content}` : content;
    wsSend(finalContent);
    setInput('');
    inputRef.current?.focus();
  };

  // File upload
  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setIsUploading(true);
    try {
      const formData = new FormData();
      formData.append('file', file);
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || '';
      const res = await fetch(`${apiUrl}/api/v1/collab/rooms/${roomId}/files`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
        body: formData,
      });
      if (!res.ok) throw new Error('Upload failed');
      const fileData = await res.json();
      // Send message with file attachment
      const fileUrl = apiUrl
        ? `${apiUrl}${fileData.file_path}`
        : fileData.file_path;
      wsSend(`${file.name}`, {
        file: { id: fileData.id, name: fileData.file_name, url: fileUrl, type: fileData.file_type, size: fileData.file_size },
      });
      toast.success('ファイルを送信しました');
    } catch {
      toast.error('ファイルのアップロードに失敗しました');
    } finally {
      setIsUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
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
    <MainLayout showNotifications={false}>
    <div className="flex flex-col h-full overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-3 px-4 py-3 pl-14 sm:pl-4 border-b bg-background shrink-0">
        <Button variant="ghost" size="icon" onClick={() => router.push('/collab')}>
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
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Circle className={`h-2 w-2 fill-current ${isConnected ? 'text-green-500' : 'text-gray-400'}`} />
            <span>{onlineUsers.length}人オンライン</span>
          </div>
        </div>
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
      <div className="flex-1 overflow-y-auto px-4 overscroll-contain" ref={scrollRef}>
        <div className="space-y-3 py-4">
          {messages.map((msg, i) => {
            const prevDate = i > 0 ? new Date(messages[i - 1].created_at).toDateString() : '';
            const curDate = new Date(msg.created_at).toDateString();
            const showSeparator = curDate !== prevDate;
            return (
              <div key={msg.id}>
                {showSeparator && (
                  <div className="flex items-center gap-3 py-2">
                    <div className="flex-1 border-t border-border" />
                    <span className="text-[10px] text-muted-foreground shrink-0">{formatDateSeparator(msg.created_at)}</span>
                    <div className="flex-1 border-t border-border" />
                  </div>
                )}
                <MessageBubble
                  message={msg}
                  isOwner={msg.sender_type === 'owner'}
                  onSendReply={wsSend}
                  showRead={msg.sender_type === 'owner' && !msg.metadata?.visibility && readByOther != null && messages.filter(m => m.sender_type === 'owner' && !m.metadata?.visibility).pop()?.id === msg.id}
                />
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

      {/* Input */}
      <div className="flex items-center gap-2 px-4 py-3 border-t bg-background shrink-0">
        <input
          type="file"
          ref={fileInputRef}
          className="hidden"
          onChange={handleFileUpload}
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
        <Button
          variant={danMode ? "default" : "ghost"}
          size="icon"
          onClick={() => setDanMode(!danMode)}
          className={danMode ? "bg-violet-600 hover:bg-violet-700 text-white" : ""}
          title={danMode ? "DANモード ON（相手に見えません）" : "DANに話しかける"}
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
            placeholder={danMode ? "DANへの指示を入力..." : "メッセージを入力..."}
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
          className={danMode ? "bg-violet-600 hover:bg-violet-700" : ""}
        >
          <Send className="h-4 w-4" />
        </Button>
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

    </MainLayout>
  );
}

function extractReply(content: string): { body: string; reply: string | null } {
  // Match patterns like 返信案: 「...」 or **返信案:** 「...」 or 返信案:\n「...」
  const patterns = [
    /(?:\*\*)?返信案(?:\*\*)?[:：]\s*[「「]([^」」]+)[」」]/,
    /(?:\*\*)?返信案(?:\*\*)?[:：]\s*「([^」]+)」/,
    /(?:\*\*)?返信案(?:\*\*)?[:：]\s*\n?[「「]([^」」]+)[」」]/,
  ];
  for (const pattern of patterns) {
    const match = content.match(pattern);
    if (match) {
      return { body: content, reply: match[1].trim() };
    }
  }
  return { body: content, reply: null };
}

function MessageBubble({ message, isOwner, onSendReply, showRead }: {
  message: CollabMessageResponse;
  isOwner: boolean;
  onSendReply?: (content: string) => void;
  showRead?: boolean;
}) {
  const [sent, setSent] = useState(false);
  const isDan = message.sender_type.startsWith('dan_');
  const isPrivate = message.metadata?.visibility === 'owner_only';
  const file = message.metadata?.file as { name: string; url: string; type: string; size: number } | undefined;
  const isImage = file?.type?.startsWith('image/');
  const { reply } = isDan ? extractReply(message.content) : { reply: null };
  const [editedReply, setEditedReply] = useState(reply || '');

  const handleSendReply = () => {
    const text = editedReply.trim();
    if (text && onSendReply) {
      onSendReply(text);
      setSent(true);
    }
  };

  // Private owner messages (sent via DAN mode) - show on right with dashed border
  const isOwnerPrivate = isOwner && isPrivate;

  return (
    <div className={`flex ${isOwner || isDan ? 'justify-end' : 'justify-start'}`}>
      <div
        className={`max-w-[75%] rounded-lg px-3 py-2 ${
          isDan
            ? 'bg-violet-500/10 border border-violet-500/20'
            : isOwnerPrivate
              ? 'bg-violet-500/5 border border-dashed border-violet-500/30'
              : isOwner
                ? 'bg-primary text-primary-foreground'
                : 'bg-muted'
        }`}
      >
        <div className="flex items-center gap-1.5 mb-1">
          {isPrivate ? <Bot className="h-4 w-4 text-violet-400" /> : <SenderIcon type={message.sender_type} />}
          <span className={`text-xs font-medium ${isPrivate ? 'text-violet-400' : 'opacity-70'}`}>
            {isOwnerPrivate ? `${message.sender_name} → DAN` : message.sender_name}
          </span>
          {isPrivate && (
            <span className="text-[10px] bg-violet-500/20 text-violet-300 px-1.5 py-0.5 rounded-full">非公開</span>
          )}
          <span className="text-[10px] opacity-50 ml-auto">
            {formatTime(message.created_at)}
          </span>
        </div>
        {file && isImage ? (
          <a href={file.url} target="_blank" rel="noopener noreferrer">
            <img src={file.url} alt={file.name} className="max-w-full max-h-60 rounded mt-1" />
          </a>
        ) : file ? (
          <a
            href={file.url}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-2 mt-1 text-sm underline opacity-80"
          >
            <Paperclip className="h-3.5 w-3.5" />
            {file.name}
            {file.size && <span className="text-xs opacity-50">({(file.size / 1024).toFixed(0)}KB)</span>}
          </a>
        ) : null}
        <p className="text-sm whitespace-pre-wrap break-words"><LinkifyText text={message.content} /></p>
        {reply && !sent && (
          <div className="mt-2 space-y-1.5">
            <textarea
              value={editedReply}
              onChange={(e) => setEditedReply(e.target.value)}
              className="w-full text-sm bg-background/50 border border-violet-500/30 rounded px-2 py-1.5 resize-none focus:outline-none focus:border-violet-500"
              rows={Math.min(editedReply.split('\n').length + 1, 4)}
            />
            <Button
              size="sm"
              className="w-full bg-violet-600 hover:bg-violet-700 text-white"
              onClick={handleSendReply}
              disabled={!editedReply.trim()}
            >
              <Send className="h-3.5 w-3.5 mr-1.5" />
              返信を送信
            </Button>
          </div>
        )}
        {reply && sent && (
          <p className="text-[10px] text-violet-300 mt-1.5">送信済み</p>
        )}
      </div>
      {showRead && (
        <p className="text-[10px] text-muted-foreground text-right mt-0.5 mr-1">既読</p>
      )}
    </div>
  );
}
