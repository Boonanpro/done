'use client';

import { useState, useRef, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Users,
  Plus,
  Search,
  Copy,
  Check,
  ToggleLeft,
  ToggleRight,
  MessageCircle,
  Send,
  Loader2,
  Bot,
} from 'lucide-react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';

import { MainLayout } from '@/components/layout/main-layout';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { api, type MessageResponse } from '@/lib/api-client';
import { useAuthStore } from '@/stores/auth-store';
import { cn } from '@/lib/utils';

export default function FriendsPage() {
  const queryClient = useQueryClient();
  const user = useAuthStore((state) => state.user);
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedFriendId, setSelectedFriendId] = useState<string | null>(null);
  const [selectedRoomId, setSelectedRoomId] = useState<string | null>(null);
  const [inviteCopied, setInviteCopied] = useState(false);
  const [message, setMessage] = useState('');
  const [aiEnabled] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Fetch friends
  const { data: friendsData, isLoading: isLoadingFriends } = useQuery({
    queryKey: ['friends'],
    queryFn: () => api.friends.list(),
  });

  // Fetch rooms to get room IDs for friends
  const { data: roomsData } = useQuery({
    queryKey: ['rooms'],
    queryFn: () => api.rooms.list(),
  });

  const friends = friendsData?.friends || [];
  const rooms = roomsData?.rooms || [];


  // Fetch messages for selected room
  const { data: messagesData, isLoading: isLoadingMessages } = useQuery({
    queryKey: ['room-messages', selectedRoomId],
    queryFn: () => api.rooms.getMessages(selectedRoomId!, { limit: 50 }),
    enabled: !!selectedRoomId,
    refetchInterval: 5000, // Poll every 5 seconds (replace with WebSocket in production)
  });

  // Fetch AI settings for selected room
  const { data: aiSettings } = useQuery({
    queryKey: ['ai-settings', selectedRoomId],
    queryFn: () => api.rooms.getAiSettings(selectedRoomId!),
    enabled: !!selectedRoomId,
  });

  // Sync AI enabled state with fetched settings
  const currentAiEnabled = aiSettings?.enabled ?? aiEnabled;

  const messages = messagesData?.messages || [];

  // Scroll to bottom on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Create invite mutation
  const createInviteMutation = useMutation({
    mutationFn: () => api.invites.create({ max_uses: 1, expires_in_hours: 24 }),
    onSuccess: (data) => {
      navigator.clipboard.writeText(data.invite_url);
      setInviteCopied(true);
      toast.success('招待リンクをコピーしました');
      setTimeout(() => setInviteCopied(false), 3000);
    },
    onError: () => {
      toast.error('招待リンクの作成に失敗しました');
    },
  });

  // Send message mutation
  const sendMessageMutation = useMutation({
    mutationFn: (content: string) => api.rooms.sendMessage(selectedRoomId!, content),
    onMutate: async (content) => {
      await queryClient.cancelQueries({ queryKey: ['room-messages', selectedRoomId] });

      const previousMessages = queryClient.getQueryData(['room-messages', selectedRoomId]);

      // Optimistic update
      const optimisticMessage: MessageResponse = {
        id: `temp-${Date.now()}`,
        room_id: selectedRoomId!,
        sender_id: user?.id || '',
        sender_name: user?.display_name || 'You',
        sender_type: 'human',
        content,
        created_at: new Date().toISOString(),
      };

      queryClient.setQueryData(['room-messages', selectedRoomId], (old: typeof messagesData) => ({
        messages: [...(old?.messages || []), optimisticMessage],
      }));

      return { previousMessages };
    },
    onError: (_err, _content, context) => {
      queryClient.setQueryData(['room-messages', selectedRoomId], context?.previousMessages);
      toast.error('メッセージの送信に失敗しました');
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['room-messages', selectedRoomId] });
    },
  });

  // Toggle AI setting mutation
  const toggleAiMutation = useMutation({
    mutationFn: (enabled: boolean) =>
      api.rooms.updateAiSettings(selectedRoomId!, { enabled }),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['ai-settings', selectedRoomId] });
      toast.success(data.enabled ? 'AIを有効にしました' : 'AIを無効にしました');
    },
    onError: () => {
      toast.error('AI設定の変更に失敗しました');
    },
  });

  const handleSelectFriend = (friendId: string) => {
    setSelectedFriendId(friendId);
    // Find the room for this friend (direct room)
    // Try to find room from rooms list where type is 'direct'
    const room = rooms.find((r) => r.type === 'direct');
    if (room) {
      setSelectedRoomId(room.id);
    }
  };

  const handleSend = () => {
    if (!message.trim() || !selectedRoomId || sendMessageMutation.isPending) return;
    sendMessageMutation.mutate(message.trim());
    setMessage('');
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const filteredFriends = friends.filter((friend) =>
    friend.display_name?.toLowerCase().includes(searchQuery.toLowerCase())
  );

  const selectedFriend = friends.find((f) => f.id === selectedFriendId);

  return (
    <TooltipProvider>
      <MainLayout showNotifications={false}>
        <div className="flex h-full">
          {/* Friends List */}
          <div className="w-80 border-r border-border flex flex-col">
            {/* Header */}
            <div className="shrink-0 p-4 border-b border-border">
              <div className="flex items-center justify-between mb-4">
                <h1 className="text-lg font-semibold">友達</h1>
                <Dialog>
                  <DialogTrigger asChild>
                    <Button size="icon" variant="ghost" className="h-8 w-8">
                      <Plus className="h-4 w-4" />
                    </Button>
                  </DialogTrigger>
                  <DialogContent>
                    <DialogHeader>
                      <DialogTitle>友達を招待</DialogTitle>
                      <DialogDescription>
                        招待リンクを共有して友達を追加しましょう
                      </DialogDescription>
                    </DialogHeader>
                    <div className="space-y-4 pt-4">
                      <Button
                        className="w-full"
                        onClick={() => createInviteMutation.mutate()}
                        disabled={createInviteMutation.isPending}
                      >
                        {createInviteMutation.isPending ? (
                          <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                        ) : inviteCopied ? (
                          <>
                            <Check className="mr-2 h-4 w-4" />
                            コピーしました
                          </>
                        ) : (
                          <>
                            <Copy className="mr-2 h-4 w-4" />
                            招待リンクを作成
                          </>
                        )}
                      </Button>
                      <p className="text-xs text-muted-foreground text-center">
                        リンクは24時間有効です
                      </p>
                    </div>
                  </DialogContent>
                </Dialog>
              </div>

              {/* Search */}
              <div className="relative">
                <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                <Input
                  placeholder="友達を検索..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="pl-8 h-9"
                />
              </div>
            </div>

            {/* Friends List */}
            <ScrollArea className="flex-1">
              <div className="p-2 space-y-1">
                {isLoadingFriends ? (
                  Array.from({ length: 5 }).map((_, i) => (
                    <div key={i} className="flex items-center gap-3 p-3 animate-pulse">
                      <div className="w-10 h-10 rounded-full bg-muted" />
                      <div className="flex-1 space-y-2">
                        <div className="h-4 w-24 bg-muted rounded" />
                        <div className="h-3 w-32 bg-muted rounded" />
                      </div>
                    </div>
                  ))
                ) : filteredFriends.length === 0 ? (
                  <div className="text-center py-12">
                    <Users className="h-12 w-12 mx-auto mb-4 text-muted-foreground/50" />
                    <p className="text-muted-foreground">
                      {searchQuery ? '該当する友達がいません' : 'まだ友達がいません'}
                    </p>
                  </div>
                ) : (
                  <AnimatePresence>
                    {filteredFriends.map((friend, index) => (
                      <motion.button
                        key={friend.id}
                        initial={{ opacity: 0, x: -10 }}
                        animate={{ opacity: 1, x: 0 }}
                        transition={{ delay: index * 0.05 }}
                        onClick={() => handleSelectFriend(friend.id)}
                        className={cn(
                          'w-full flex items-center gap-3 p-3 rounded-lg text-left transition-colors',
                          selectedFriendId === friend.id
                            ? 'bg-accent'
                            : 'hover:bg-muted/50'
                        )}
                      >
                        <Avatar className="h-10 w-10">
                        <AvatarImage src={friend.avatar_url || undefined} />
                        <AvatarFallback className="bg-primary/10 text-primary">
                          {friend.display_name?.charAt(0) || 'U'}
                        </AvatarFallback>
                      </Avatar>
                      <div className="flex-1 min-w-0">
                        <p className="font-medium truncate">{friend.display_name}</p>
                        <p className="text-xs text-muted-foreground truncate">
                          チャットを始めましょう
                        </p>
                      </div>
                      </motion.button>
                    ))}
                  </AnimatePresence>
                )}
              </div>
            </ScrollArea>
          </div>

          {/* Chat Area */}
          <div className="flex-1 flex flex-col">
            {selectedFriend ? (
              <>
                {/* Chat Header */}
                <div className="shrink-0 flex items-center justify-between px-6 py-4 border-b border-border">
                  <div className="flex items-center gap-3">
                    <Avatar className="h-10 w-10">
                      <AvatarImage src={selectedFriend.avatar_url || undefined} />
                      <AvatarFallback className="bg-primary/10 text-primary">
                        {selectedFriend.display_name?.charAt(0) || 'U'}
                      </AvatarFallback>
                    </Avatar>
                    <div>
                      <h2 className="font-semibold">{selectedFriend.display_name}</h2>
                      <p className="text-xs text-muted-foreground">
                        {currentAiEnabled ? 'ダンが代理で返信します' : '友達'}
                      </p>
                    </div>
                  </div>

                  {/* AI Toggle */}
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Button
                        variant={currentAiEnabled ? 'default' : 'outline'}
                        size="sm"
                        className="gap-2"
                        onClick={() => toggleAiMutation.mutate(!currentAiEnabled)}
                        disabled={toggleAiMutation.isPending}
                      >
                        {toggleAiMutation.isPending ? (
                          <Loader2 className="h-4 w-4 animate-spin" />
                        ) : currentAiEnabled ? (
                          <ToggleRight className="h-4 w-4" />
                        ) : (
                          <ToggleLeft className="h-4 w-4" />
                        )}
                        AI: {currentAiEnabled ? 'ON' : 'OFF'}
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent>
                      {currentAiEnabled
                        ? 'ダンがあなたの代わりに返信します'
                        : 'クリックしてダンに返信を任せる'}
                    </TooltipContent>
                  </Tooltip>
                </div>

                {/* Messages Area */}
                <ScrollArea className="flex-1 px-6">
                  <div className="max-w-3xl mx-auto py-6 space-y-4">
                    {isLoadingMessages ? (
                      Array.from({ length: 3 }).map((_, i) => (
                        <div key={i} className={cn('flex gap-3', i % 2 === 0 ? '' : 'justify-end')}>
                          {i % 2 === 0 && <div className="w-10 h-10 rounded-full bg-muted animate-pulse" />}
                          <div className="space-y-2">
                            <div className="h-4 w-20 bg-muted rounded animate-pulse" />
                            <div className="h-12 w-48 bg-muted rounded-xl animate-pulse" />
                          </div>
                        </div>
                      ))
                    ) : messages.length === 0 ? (
                      <div className="text-center py-20">
                        <MessageCircle className="h-16 w-16 mx-auto mb-4 text-muted-foreground/30" />
                        <p className="text-muted-foreground">メッセージはまだありません</p>
                        <p className="text-sm text-muted-foreground/70">
                          会話を始めましょう
                        </p>
                      </div>
                    ) : (
                      <AnimatePresence mode="popLayout">
                        {messages.map((msg, index) => {
                          const isMe = msg.sender_id === user?.id;
                          const isAi = msg.sender_type === 'ai';

                          return (
                            <motion.div
                              key={msg.id}
                              initial={{ opacity: 0, y: 10 }}
                              animate={{ opacity: 1, y: 0 }}
                              exit={{ opacity: 0 }}
                              transition={{ delay: index * 0.02 }}
                              className={cn('flex gap-3', isMe && 'justify-end')}
                            >
                              {!isMe && (
                                <Avatar className="h-10 w-10 shrink-0">
                                  <AvatarImage src={selectedFriend.avatar_url || undefined} />
                                  <AvatarFallback className="bg-primary/10 text-primary">
                                    {selectedFriend.display_name?.charAt(0) || 'U'}
                                  </AvatarFallback>
                                </Avatar>
                              )}

                              <div
                                className={cn(
                                  'max-w-[70%] space-y-1',
                                  isMe && 'items-end text-right'
                                )}
                              >
                                <div className="flex items-center gap-2">
                                  <p className="text-xs text-muted-foreground">
                                    {isMe ? (isAi ? 'ダン (代理)' : 'あなた') : msg.sender_name}
                                  </p>
                                  {isAi && isMe && (
                                    <Bot className="h-3 w-3 text-primary" />
                                  )}
                                </div>
                                <div
                                  className={cn(
                                    'px-4 py-3 rounded-2xl text-sm leading-relaxed',
                                    isMe
                                      ? isAi
                                        ? 'bg-primary/80 text-primary-foreground rounded-br-md'
                                        : 'bg-primary text-primary-foreground rounded-br-md'
                                      : 'bg-muted rounded-bl-md'
                                  )}
                                >
                                  {msg.content}
                                </div>
                              </div>

                              {isMe && (
                                <Avatar className="h-10 w-10 shrink-0">
                                  {isAi ? (
                                    <AvatarFallback className="bg-primary/10">
                                      <Bot className="h-5 w-5 text-primary" />
                                    </AvatarFallback>
                                  ) : (
                                    <>
                                      <AvatarImage src={user?.avatar_url || undefined} />
                                      <AvatarFallback className="bg-secondary text-secondary-foreground">
                                        {user?.display_name?.charAt(0) || 'U'}
                                      </AvatarFallback>
                                    </>
                                  )}
                                </Avatar>
                              )}
                            </motion.div>
                          );
                        })}
                      </AnimatePresence>
                    )}
                    <div ref={messagesEndRef} />
                  </div>
                </ScrollArea>

                {/* Input Area */}
                <div className="shrink-0 border-t border-border p-4">
                  <div className="max-w-3xl mx-auto">
                    <div className="flex items-center gap-2 p-2 rounded-xl border border-border bg-input/30 focus-within:border-primary/50 transition-colors">
                      <Input
                        value={message}
                        onChange={(e) => setMessage(e.target.value)}
                        onKeyDown={handleKeyDown}
                        placeholder={currentAiEnabled ? 'ダンが返信を担当中...' : 'メッセージを入力...'}
                        className="border-0 bg-transparent focus-visible:ring-0"
                        disabled={currentAiEnabled}
                      />
                      <Button
                        size="sm"
                        onClick={handleSend}
                        disabled={!message.trim() || sendMessageMutation.isPending || currentAiEnabled}
                      >
                        {sendMessageMutation.isPending ? (
                          <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                          <Send className="h-4 w-4" />
                        )}
                      </Button>
                    </div>
                    {currentAiEnabled && (
                      <p className="text-xs text-muted-foreground text-center mt-2">
                        AIモードが有効です。自分で返信するにはAIをOFFにしてください。
                      </p>
                    )}
                  </div>
                </div>
              </>
            ) : (
              <div className="flex-1 flex items-center justify-center">
                <div className="text-center">
                  <Users className="h-20 w-20 mx-auto mb-6 text-muted-foreground/20" />
                  <h2 className="text-xl font-semibold mb-2">友達とチャット</h2>
                  <p className="text-muted-foreground max-w-sm">
                    左側のリストから友達を選択してチャットを始めましょう。
                    ダンがあなたの代わりに会話することもできます。
                  </p>
                </div>
              </div>
            )}
          </div>
        </div>
      </MainLayout>
    </TooltipProvider>
  );
}
