'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import { useParams } from 'next/navigation';
import { useQuery } from '@tanstack/react-query';
import { toast } from 'sonner';
import { Send, Circle, Bot, User, UserCheck, Paperclip, Pencil } from 'lucide-react';
import { api, type CollabMessageResponse } from '@/lib/api-client';
import { useCollabWebSocket } from '@/hooks/useCollabWebSocket';
import { usePushNotification } from '@/hooks/usePushNotification';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { PWAInstallPrompt } from '@/components/pwa-install-prompt';
import { OpenInBrowserPrompt } from '@/components/open-in-browser';
import { LinkifyText } from '@/components/linkify-text';

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
  const inviteToken = params.token as string;
  const [guestName, setGuestName] = useState(() => {
    if (typeof window !== 'undefined') {
      return localStorage.getItem(GUEST_NAME_KEY) || '';
    }
    return '';
  });
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
  }, [inviteToken]);

  // Fetch invite info
  const { data: inviteInfo } = useQuery({
    queryKey: ['collab-invite', inviteToken],
    queryFn: () => api.collab.getInviteInfo(inviteToken),
    enabled: !!inviteToken && !guestToken,
  });

  // Fetch messages when joined
  useEffect(() => {
    if (roomId && guestToken) {
      api.collab.getMessages(roomId, 50, guestToken).then((data) => {
        setMessages(data.messages);
      }).catch(() => {});
    }
  }, [roomId, guestToken]);

  // WebSocket
  const handleNewMessage = useCallback((msg: CollabMessageResponse) => {
    if (msg.sender_type === 'dan_guest') setDanThinking(false);
    setMessages((prev) => {
      if (prev.some((m) => m.id === msg.id)) return prev;
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

  const { isConnected, onlineUsers, sendMessage: wsSend, sendRead } = useCollabWebSocket({
    roomId: roomId || '',
    token: guestToken || '',
    isGuest: true,
    onMessage: handleNewMessage,
    onRead: handleRead,
    onDanThinking: handleDanThinking,
  });

  // Send read receipt when new messages arrive from owner
  useEffect(() => {
    const lastMsg = messages[messages.length - 1];
    if (lastMsg && lastMsg.sender_type === 'owner') {
      sendRead(lastMsg.id);
    }
  }, [messages, sendRead]);

  // Push notifications
  usePushNotification(roomId || '', 'guest');

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
      setGuestToken(result.guest_token);
      setRoomId(result.room_id);
      setRoomTitle(result.room_title);
      const keys = getStorageKeys(inviteToken);
      localStorage.setItem(keys.tokenKey, result.guest_token);
      localStorage.setItem(keys.roomKey, result.room_id);
      localStorage.setItem(keys.titleKey, result.room_title);
      localStorage.setItem(GUEST_NAME_KEY, guestName.trim());
      toast.success('参加しました');
    } catch (e: any) {
      toast.error(e?.data?.detail || '参加できませんでした');
    } finally {
      setIsJoining(false);
    }
  };

  const handleSend = () => {
    const content = input.trim();
    if (!content) return;
    const finalContent = danMode ? `@ダン ${content}` : content;
    wsSend(finalContent);
    setInput('');
    inputRef.current?.focus();
  };

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !roomId || !guestToken) return;
    setIsUploading(true);
    try {
      const formData = new FormData();
      formData.append('file', file);
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || '';
      const res = await fetch(`${apiUrl}/api/v1/collab/rooms/${roomId}/files`, {
        method: 'POST',
        headers: { 'X-Guest-Token': guestToken },
        body: formData,
      });
      if (!res.ok) throw new Error('Upload failed');
      const fileData = await res.json();
      const fileUrl = apiUrl ? `${apiUrl}${fileData.file_path}` : fileData.file_path;
      wsSend(file.name, {
        file: { id: fileData.id, name: fileData.file_name, url: fileUrl, type: fileData.file_type, size: fileData.file_size },
      });
      toast.success('ファイルを送信しました');
    } catch {
      toast.error('アップロードに失敗しました');
    } finally {
      setIsUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  // Not joined yet - show join form
  if (!guestToken || !roomId) {
    const isExpired = inviteInfo?.status === 'expired';
    const alreadyJoined = inviteInfo?.already_joined;

    return (
      <div className="min-h-screen flex items-start justify-center bg-background p-4 pt-[15vh]">
        <OpenInBrowserPrompt />
        <PWAInstallPrompt />
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
            ) : alreadyJoined ? (
              <p className="text-center text-muted-foreground">この招待リンクは既に使用されています</p>
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
                <GuestMessageBubble
                  message={msg}
                  showRead={msg.sender_type === 'guest' && readByOther != null && messages.filter(m => m.sender_type === 'guest').pop()?.id === msg.id}
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
                if (e.key === 'Enter') {
                  const v = (editNameValue).trim();
                  if (v) { setGuestName(v); localStorage.setItem(GUEST_NAME_KEY, v); toast.success('表示名を変更しました'); }
                  setEditingName(false); setEditNameValue('');
                }
              }}
            />
            <div className="flex gap-2">
              <Button variant="outline" className="flex-1" onClick={() => { setEditingName(false); setEditNameValue(''); }}>キャンセル</Button>
              <Button className="flex-1" onClick={() => {
                const v = (editNameValue).trim();
                if (v) { setGuestName(v); localStorage.setItem(GUEST_NAME_KEY, v); toast.success('表示名を変更しました'); }
                setEditingName(false); setEditNameValue('');
              }}>保存</Button>
            </div>
          </div>
        </div>
      )}

      <PWAInstallPrompt />

      {/* Input */}
      <div className="flex items-center gap-2 px-4 py-3 border-t shrink-0">
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
          className={danMode ? "bg-violet-600 hover:bg-violet-700" : ""}
        >
          <Send className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}

function GuestMessageBubble({ message, showRead }: { message: CollabMessageResponse; showRead?: boolean }) {
  const isGuest = message.sender_type === 'guest';
  const isDan = message.sender_type.startsWith('dan_');

  function SenderIcon({ type }: { type: string }) {
    switch (type) {
      case 'owner': return <User className="h-4 w-4" />;
      case 'guest': return <UserCheck className="h-4 w-4" />;
      default: return <Bot className="h-4 w-4" />;
    }
  }

  const isPrivate = message.metadata?.visibility === 'guest_only';
  const isGuestPrivate = isGuest && isPrivate;

  return (
    <div className={`flex ${isGuest || isDan ? 'justify-end' : 'justify-start'}`}>
      <div
        className={`max-w-[75%] rounded-lg px-3 py-2 ${
          isDan
            ? 'bg-violet-500/10 border border-violet-500/20'
            : isGuestPrivate
              ? 'bg-violet-500/5 border border-dashed border-violet-500/30'
              : isGuest
                ? 'bg-primary text-primary-foreground'
                : 'bg-muted'
        }`}
      >
        <div className="flex items-center gap-1.5 mb-1">
          {isPrivate ? <Bot className="h-4 w-4 text-violet-400" /> : <SenderIcon type={message.sender_type} />}
          <span className={`text-xs font-medium ${isPrivate ? 'text-violet-400' : 'opacity-70'}`}>
            {isGuestPrivate ? `${message.sender_name} → DAN` : message.sender_name}
          </span>
          {isPrivate && (
            <span className="text-[10px] bg-violet-500/20 text-violet-300 px-1.5 py-0.5 rounded-full">非公開</span>
          )}
          <span className="text-[10px] opacity-50 ml-auto">{formatTime(message.created_at)}</span>
        </div>
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
        <p className="text-sm whitespace-pre-wrap break-words"><LinkifyText text={message.content} /></p>
      </div>
      {showRead && (
        <p className="text-[10px] text-muted-foreground text-right mt-0.5 mr-1">既読</p>
      )}
    </div>
  );
}
