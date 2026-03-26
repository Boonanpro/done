'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import { useParams } from 'next/navigation';
import { useQuery } from '@tanstack/react-query';
import { toast } from 'sonner';
import { Send, Circle, Bot, User, UserCheck, Paperclip } from 'lucide-react';
import { api, type CollabMessageResponse } from '@/lib/api-client';
import { useCollabWebSocket } from '@/hooks/useCollabWebSocket';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { PWAInstallPrompt } from '@/components/pwa-install-prompt';

const GUEST_TOKEN_KEY = 'collab-guest-token';
const GUEST_ROOM_KEY = 'collab-guest-room';

function formatTime(dateStr: string): string {
  return new Date(dateStr).toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit' });
}

export default function GuestJoinPage() {
  const params = useParams();
  const inviteToken = params.token as string;
  const [guestName, setGuestName] = useState('');
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

  // Check for existing session
  useEffect(() => {
    const savedToken = localStorage.getItem(GUEST_TOKEN_KEY);
    const savedRoom = localStorage.getItem(GUEST_ROOM_KEY);
    if (savedToken && savedRoom) {
      setGuestToken(savedToken);
      setRoomId(savedRoom);
    }
  }, []);

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
    setMessages((prev) => {
      if (prev.some((m) => m.id === msg.id)) return prev;
      return [...prev, msg];
    });
  }, []);

  const { isConnected, onlineUsers, sendMessage: wsSend } = useCollabWebSocket({
    roomId: roomId || '',
    token: guestToken || '',
    isGuest: true,
    onMessage: handleNewMessage,
  });

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
      localStorage.setItem(GUEST_TOKEN_KEY, result.guest_token);
      localStorage.setItem(GUEST_ROOM_KEY, result.room_id);
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
    wsSend(content);
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
      <div className="min-h-screen flex items-center justify-center bg-background p-4">
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
    <div className="flex flex-col h-dvh bg-background overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-3 px-4 py-3 border-b shrink-0">
        <div className="flex-1 min-w-0">
          <h2 className="font-semibold truncate">{roomTitle || 'コラボルーム'}</h2>
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Circle className={`h-2 w-2 fill-current ${isConnected ? 'text-green-500' : 'text-gray-400'}`} />
            <span>{onlineUsers.length}人オンライン</span>
          </div>
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 overscroll-contain" ref={scrollRef}>
        <div className="space-y-3 py-4">
          {messages.map((msg) => (
            <GuestMessageBubble key={msg.id} message={msg} />
          ))}
        </div>
      </div>

      <PWAInstallPrompt />

      {/* Input */}
      <div className="flex items-center gap-2 px-4 py-3 border-t shrink-0">
        <input type="file" ref={fileInputRef} className="hidden" onChange={handleFileUpload}
          accept="image/*,video/*,audio/*,.pdf,.doc,.docx,.xls,.xlsx,.zip" />
        <Button variant="ghost" size="icon" onClick={() => fileInputRef.current?.click()} disabled={isUploading}>
          <Paperclip className="h-4 w-4" />
        </Button>
        <Input
          ref={inputRef}
          placeholder="メッセージを入力..."
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              handleSend();
            }
          }}
          className="flex-1"
        />
        <Button size="icon" onClick={handleSend} disabled={!input.trim()}>
          <Send className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}

function GuestMessageBubble({ message }: { message: CollabMessageResponse }) {
  const isGuest = message.sender_type === 'guest';
  const isDan = message.sender_type.startsWith('dan_');

  function SenderIcon({ type }: { type: string }) {
    switch (type) {
      case 'owner': return <User className="h-4 w-4" />;
      case 'guest': return <UserCheck className="h-4 w-4" />;
      default: return <Bot className="h-4 w-4" />;
    }
  }

  return (
    <div className={`flex ${isGuest ? 'justify-end' : 'justify-start'}`}>
      <div
        className={`max-w-[75%] rounded-lg px-3 py-2 ${
          isDan
            ? 'bg-violet-500/10 border border-violet-500/20'
            : isGuest
              ? 'bg-primary text-primary-foreground'
              : 'bg-muted'
        }`}
      >
        <div className="flex items-center gap-1.5 mb-1">
          <SenderIcon type={message.sender_type} />
          <span className="text-xs font-medium opacity-70">{message.sender_name}</span>
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
        <p className="text-sm whitespace-pre-wrap break-words">{message.content}</p>
      </div>
    </div>
  );
}
