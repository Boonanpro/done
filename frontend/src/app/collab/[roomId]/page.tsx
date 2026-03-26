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
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Switch } from '@/components/ui/switch';
import {
  Sheet, SheetContent, SheetHeader, SheetTitle, SheetTrigger,
} from '@/components/ui/sheet';

function formatTime(dateStr: string): string {
  return new Date(dateStr).toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit' });
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
    setMessages((prev) => {
      if (prev.some((m) => m.id === msg.id)) return prev;
      return [...prev, msg];
    });
  }, []);

  const { isConnected, onlineUsers, sendMessage: wsSend } = useCollabWebSocket({
    roomId,
    token,
    isGuest: false,
    onMessage: handleNewMessage,
  });

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
    wsSend(content);
    setInput('');
    inputRef.current?.focus();
  };

  // Create invite
  const inviteMutation = useMutation({
    mutationFn: () => api.collab.createInvite(roomId),
    onSuccess: (data) => {
      setInviteUrl(data.invite_url);
      navigator.clipboard.writeText(data.invite_url);
      toast.success('招待リンクをコピーしました');
    },
    onError: () => toast.error('招待リンク作成に失敗しました'),
  });

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
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center gap-3 px-4 py-3 border-b bg-background">
        <Button variant="ghost" size="icon" onClick={() => router.push('/collab')}>
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <div className="flex-1 min-w-0">
          <h2 className="font-semibold truncate">{room?.title ?? '...'}</h2>
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Circle className={`h-2 w-2 fill-current ${isConnected ? 'text-green-500' : 'text-gray-400'}`} />
            <span>{onlineUsers.length}人オンライン</span>
          </div>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => inviteMutation.mutate()}
          disabled={inviteMutation.isPending}
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
      <ScrollArea className="flex-1 px-4" ref={scrollRef}>
        <div className="space-y-3 py-4">
          {messages.map((msg) => (
            <MessageBubble key={msg.id} message={msg} isOwner={msg.sender_type === 'owner'} />
          ))}
        </div>
      </ScrollArea>

      {/* Input */}
      <div className="flex items-center gap-2 px-4 py-3 border-t bg-background">
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
    </MainLayout>
  );
}

function MessageBubble({ message, isOwner }: { message: CollabMessageResponse; isOwner: boolean }) {
  const isDan = message.sender_type.startsWith('dan_');

  return (
    <div className={`flex ${isOwner ? 'justify-end' : 'justify-start'}`}>
      <div
        className={`max-w-[75%] rounded-lg px-3 py-2 ${
          isDan
            ? 'bg-violet-500/10 border border-violet-500/20'
            : isOwner
              ? 'bg-primary text-primary-foreground'
              : 'bg-muted'
        }`}
      >
        <div className="flex items-center gap-1.5 mb-1">
          <SenderIcon type={message.sender_type} />
          <span className="text-xs font-medium opacity-70">
            {message.sender_name}
          </span>
          <span className="text-[10px] opacity-50 ml-auto">
            {formatTime(message.created_at)}
          </span>
        </div>
        <p className="text-sm whitespace-pre-wrap break-words">{message.content}</p>
      </div>
    </div>
  );
}
