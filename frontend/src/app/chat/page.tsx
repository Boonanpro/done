'use client';

import { useState, useRef, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Send, Paperclip, Loader2, Bot, AlertCircle, RefreshCw } from 'lucide-react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';

import { MainLayout } from '@/components/layout/main-layout';
import { Button } from '@/components/ui/button';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar';
import { Skeleton } from '@/components/ui/skeleton';
import { api, type MessageResponse, ApiError } from '@/lib/api-client';
import { useAuthStore } from '@/stores/auth-store';
import { cn } from '@/lib/utils';

export default function ChatPage() {
  const queryClient = useQueryClient();
  const user = useAuthStore((state) => state.user);
  const [message, setMessage] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Fetch Dan room
  const {
    data: danRoom,
    isLoading: isLoadingRoom,
    error: roomError,
    refetch: refetchRoom,
  } = useQuery({
    queryKey: ['dan-room'],
    queryFn: () => api.dan.getRoom(),
    retry: 2,
    retryDelay: 1000,
  });

  // Fetch messages
  const {
    data: messagesData,
    isLoading: isLoadingMessages,
    error: messagesError,
    refetch: refetchMessages,
  } = useQuery({
    queryKey: ['dan-messages'],
    queryFn: () => api.dan.getMessages({ limit: 50 }),
    enabled: !!danRoom,
    refetchInterval: 5000, // Poll every 5 seconds
    retry: 2,
  });

  const messages = messagesData?.messages || [];
  const hasError = roomError || messagesError;

  // Send message mutation
  const sendMessageMutation = useMutation({
    mutationFn: (content: string) => api.dan.sendMessage(content),
    onMutate: async (content) => {
      // Cancel outgoing refetches
      await queryClient.cancelQueries({ queryKey: ['dan-messages'] });

      // Snapshot previous value
      const previousMessages = queryClient.getQueryData(['dan-messages']);

      // Optimistic update
      const optimisticMessage: MessageResponse = {
        id: `temp-${Date.now()}`,
        room_id: danRoom?.id || '',
        sender_id: user?.id || '',
        sender_name: user?.display_name || 'You',
        sender_type: 'human',
        content,
        created_at: new Date().toISOString(),
      };

      queryClient.setQueryData(['dan-messages'], (old: typeof messagesData) => ({
        messages: [...(old?.messages || []), optimisticMessage],
      }));

      setIsTyping(true);

      return { previousMessages };
    },
    onError: (err, _content, context) => {
      // Rollback on error
      queryClient.setQueryData(['dan-messages'], context?.previousMessages);
      setIsTyping(false);

      // Show error message
      if (err instanceof ApiError) {
        if (err.status === 401) {
          toast.error('セッションが切れました。再度ログインしてください。');
        } else {
          toast.error('メッセージの送信に失敗しました');
        }
      } else {
        toast.error('ネットワークエラーが発生しました');
      }
    },
    onSuccess: () => {
      // Refetch to get AI response
      setTimeout(() => {
        queryClient.invalidateQueries({ queryKey: ['dan-messages'] });
        setIsTyping(false);
      }, 1000);
    },
  });

  // Scroll to bottom on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isTyping]);

  // Auto-resize textarea
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 200)}px`;
    }
  }, [message]);

  const handleSend = () => {
    if (!message.trim() || sendMessageMutation.isPending) return;
    sendMessageMutation.mutate(message.trim());
    setMessage('');
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleRetry = () => {
    if (roomError) {
      refetchRoom();
    }
    if (messagesError) {
      refetchMessages();
    }
  };

  // Error state
  if (hasError && !isLoadingRoom && !isLoadingMessages) {
    return (
      <MainLayout>
        <div className="flex flex-col items-center justify-center h-full">
          <AlertCircle className="h-16 w-16 text-destructive/50 mb-4" />
          <h2 className="text-xl font-semibold mb-2">接続エラー</h2>
          <p className="text-muted-foreground mb-4 text-center max-w-md">
            サーバーとの接続に問題が発生しました。
            <br />
            バックエンドサーバーが起動しているか確認してください。
          </p>
          <Button onClick={handleRetry} className="gap-2">
            <RefreshCw className="h-4 w-4" />
            再試行
          </Button>
          <p className="text-xs text-muted-foreground mt-4">
            {roomError instanceof ApiError
              ? `エラー: ${roomError.status} ${roomError.statusText}`
              : messagesError instanceof ApiError
                ? `エラー: ${messagesError.status} ${messagesError.statusText}`
                : 'ネットワークエラー'}
          </p>
        </div>
      </MainLayout>
    );
  }

  return (
    <MainLayout>
      <div className="flex flex-col h-full">
        {/* Header */}
        <div className="shrink-0 flex items-center gap-3 px-6 py-4 border-b border-border">
          <Avatar className="h-10 w-10">
            <AvatarImage src="/dan-avatar.png" />
            <AvatarFallback className="bg-primary/10">
              <Bot className="h-5 w-5 text-primary" />
            </AvatarFallback>
          </Avatar>
          <div>
            <h1 className="font-semibold">ダン</h1>
            <p className="text-xs text-muted-foreground">AI秘書</p>
          </div>
        </div>

        {/* Messages Area */}
        <ScrollArea className="flex-1 px-6">
          <div className="max-w-3xl mx-auto py-6 space-y-6">
            {isLoadingRoom || isLoadingMessages ? (
              // Loading skeletons
              Array.from({ length: 3 }).map((_, i) => (
                <div key={i} className={cn('flex gap-3', i % 2 === 0 ? '' : 'justify-end')}>
                  {i % 2 === 0 && <Skeleton className="h-10 w-10 rounded-full" />}
                  <div className="space-y-2">
                    <Skeleton className="h-4 w-20" />
                    <Skeleton className="h-16 w-64 rounded-xl" />
                  </div>
                </div>
              ))
            ) : messages.length === 0 ? (
              // Empty state
              <motion.div
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                className="text-center py-20"
              >
                <div className="w-20 h-20 mx-auto mb-6 rounded-2xl bg-primary/10 flex items-center justify-center">
                  <Bot className="h-10 w-10 text-primary" />
                </div>
                <h2 className="text-xl font-semibold mb-2">こんにちは！</h2>
                <p className="text-muted-foreground max-w-md mx-auto">
                  私はダン、あなたのAI秘書です。
                  <br />
                  何かお手伝いできることはありますか？
                </p>
              </motion.div>
            ) : (
              // Messages
              <AnimatePresence mode="popLayout">
                {messages.map((msg, index) => {
                  const isUser = msg.sender_type === 'human';

                  return (
                    <motion.div
                      key={msg.id}
                      initial={{ opacity: 0, y: 10 }}
                      animate={{ opacity: 1, y: 0 }}
                      exit={{ opacity: 0 }}
                      transition={{ delay: index * 0.05 }}
                      className={cn('flex gap-3', isUser && 'justify-end')}
                    >
                      {!isUser && (
                        <Avatar className="h-10 w-10 shrink-0">
                          <AvatarImage src="/dan-avatar.png" />
                          <AvatarFallback className="bg-primary/10">
                            <Bot className="h-5 w-5 text-primary" />
                          </AvatarFallback>
                        </Avatar>
                      )}

                      <div
                        className={cn(
                          'max-w-[70%] space-y-1',
                          isUser && 'items-end text-right'
                        )}
                      >
                        <p className="text-xs text-muted-foreground">
                          {isUser ? 'あなた' : 'ダン'}
                        </p>
                        <div
                          className={cn(
                            'px-4 py-3 rounded-2xl text-sm leading-relaxed',
                            isUser
                              ? 'bg-primary text-primary-foreground rounded-br-md'
                              : 'bg-muted rounded-bl-md'
                          )}
                        >
                          {msg.content}
                        </div>
                      </div>

                      {isUser && (
                        <Avatar className="h-10 w-10 shrink-0">
                          <AvatarImage src={user?.avatar_url || undefined} />
                          <AvatarFallback className="bg-secondary text-secondary-foreground">
                            {user?.display_name?.charAt(0) || 'U'}
                          </AvatarFallback>
                        </Avatar>
                      )}
                    </motion.div>
                  );
                })}
              </AnimatePresence>
            )}

            {/* Typing indicator */}
            <AnimatePresence>
              {isTyping && (
                <motion.div
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0 }}
                  className="flex gap-3"
                >
                  <Avatar className="h-10 w-10">
                    <AvatarFallback className="bg-primary/10">
                      <Bot className="h-5 w-5 text-primary" />
                    </AvatarFallback>
                  </Avatar>
                  <div className="space-y-1">
                    <p className="text-xs text-muted-foreground">ダン</p>
                    <div className="px-4 py-3 rounded-2xl rounded-bl-md bg-muted">
                      <div className="flex gap-1">
                        <motion.span
                          animate={{ opacity: [0.4, 1, 0.4] }}
                          transition={{ duration: 1.5, repeat: Number.POSITIVE_INFINITY, delay: 0 }}
                          className="w-2 h-2 rounded-full bg-muted-foreground"
                        />
                        <motion.span
                          animate={{ opacity: [0.4, 1, 0.4] }}
                          transition={{ duration: 1.5, repeat: Number.POSITIVE_INFINITY, delay: 0.2 }}
                          className="w-2 h-2 rounded-full bg-muted-foreground"
                        />
                        <motion.span
                          animate={{ opacity: [0.4, 1, 0.4] }}
                          transition={{ duration: 1.5, repeat: Number.POSITIVE_INFINITY, delay: 0.4 }}
                          className="w-2 h-2 rounded-full bg-muted-foreground"
                        />
                      </div>
                    </div>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>

            <div ref={messagesEndRef} />
          </div>
        </ScrollArea>

        {/* Input Area */}
        <div className="shrink-0 border-t border-border p-4">
          <div className="max-w-3xl mx-auto">
            <div className="flex items-end gap-2 p-2 rounded-2xl border border-border bg-input/30 focus-within:border-primary/50 transition-colors">
              <Button
                variant="ghost"
                size="icon"
                className="h-9 w-9 shrink-0 text-muted-foreground hover:text-foreground"
              >
                <Paperclip className="h-4 w-4" />
              </Button>

              <textarea
                ref={textareaRef}
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="メッセージを入力..."
                rows={1}
                className="flex-1 resize-none bg-transparent text-sm focus:outline-none min-h-[36px] max-h-[200px] py-2"
              />

              <Button
                size="icon"
                className="h-9 w-9 shrink-0"
                onClick={handleSend}
                disabled={!message.trim() || sendMessageMutation.isPending}
              >
                {sendMessageMutation.isPending ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Send className="h-4 w-4" />
                )}
              </Button>
            </div>
          </div>
        </div>
      </div>
    </MainLayout>
  );
}
