'use client';

import { useState, useRef, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { motion, AnimatePresence } from 'framer-motion';
import { Send, Paperclip, Loader2, Bot, AlertCircle, RefreshCw, Check, ChevronDown, ChevronUp } from 'lucide-react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';

import { MainLayout } from '@/components/layout/main-layout';
import { Button } from '@/components/ui/button';
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar';
import { Skeleton } from '@/components/ui/skeleton';
import { api, type MessageResponse, type ProcessStep, ApiError } from '@/lib/api-client';
import { useAuthStore } from '@/stores/auth-store';
import { cn } from '@/lib/utils';

// プロセスステップの表示コンポーネント
interface ProcessDisplayProps {
  steps: ProcessStep[];
  isProcessing: boolean;
  isCollapsed: boolean;
  onToggle: () => void;
}

function ProcessDisplay({ steps, isProcessing, isCollapsed, onToggle }: ProcessDisplayProps) {
  return (
    <motion.div
      initial={{ opacity: 0, height: 0 }}
      animate={{ opacity: 1, height: 'auto' }}
      exit={{ opacity: 0, height: 0 }}
      className="mt-2 ml-[52px]"
    >
      <button
        onClick={onToggle}
        className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors mb-1"
      >
        {isCollapsed ? (
          <ChevronDown className="h-3 w-3" />
        ) : (
          <ChevronUp className="h-3 w-3" />
        )}
        <span>処理プロセス</span>
      </button>
      
      <AnimatePresence>
        {!isCollapsed && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            className="pl-2 border-l-2 border-muted space-y-1"
          >
            {steps.map((step, index) => (
              <motion.div
                key={step.id}
                initial={{ opacity: 0, x: -10 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: index * 0.1 }}
                className="flex items-center gap-2 text-xs"
              >
                {step.status === 'completed' ? (
                  <Check className="h-3 w-3 text-green-500" />
                ) : step.status === 'running' || step.status === 'pending' ? (
                  <Loader2 className="h-3 w-3 text-primary animate-spin" />
                ) : (
                  <span className="h-3 w-3 rounded-full bg-muted-foreground/30" />
                )}
                <span className={cn(
                  step.status === 'completed' ? 'text-green-600 dark:text-green-400' :
                  step.status === 'running' ? 'text-foreground' :
                  'text-muted-foreground'
                )}>
                  {step.label}
                </span>
              </motion.div>
            ))}
            
            {isProcessing && (
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="flex items-center gap-2 text-xs text-muted-foreground"
              >
                <Loader2 className="h-3 w-3 animate-spin" />
                <span>処理中...</span>
              </motion.div>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}

// 処理中の仮プロセスステップ
const pendingSteps: ProcessStep[] = [
  { id: 'receive', label: 'メッセージを受信中...', status: 'running' },
  { id: 'analyze', label: '要望を分析中...', status: 'pending' },
  { id: 'generate', label: '回答を生成中...', status: 'pending' },
];

export default function ChatPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const user = useAuthStore((state) => state.user);
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const isLoading = useAuthStore((state) => state.isLoading);
  const [message, setMessage] = useState('');
  const [currentProcess, setCurrentProcess] = useState<{
    steps: ProcessStep[];
    isProcessing: boolean;
    isCollapsed: boolean;
    messageId?: string;
  } | null>(null);
  const [completedProcesses, setCompletedProcesses] = useState<Map<string, { steps: ProcessStep[]; isCollapsed: boolean }>>(new Map());
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Check if token exists in localStorage
  const hasToken = typeof window !== 'undefined' && !!localStorage.getItem('done-token');

  // Redirect to login if not authenticated
  useEffect(() => {
    if (!isLoading && !isAuthenticated && !hasToken) {
      router.push('/login');
    }
  }, [isLoading, isAuthenticated, hasToken, router]);

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
    staleTime: 30 * 1000,
  });

  // Fetch messages (ポーリング削除 - リアルタイム対応)
  const {
    data: messagesData,
    isLoading: isLoadingMessages,
    error: messagesError,
    refetch: refetchMessages,
  } = useQuery({
    queryKey: ['dan-messages'],
    queryFn: () => api.dan.getMessages({ limit: 50 }),
    enabled: !!danRoom,
    staleTime: 5 * 1000,
    retry: 2,
  });

  const messages = messagesData?.messages || [];
  const hasError = roomError || messagesError;

  // Send message mutation - 同期処理に対応
  const sendMessageMutation = useMutation({
    mutationFn: (content: string) => api.dan.sendMessage(content),
    onMutate: async (content) => {
      // Cancel outgoing refetches
      await queryClient.cancelQueries({ queryKey: ['dan-messages'] });

      // Snapshot previous value
      const previousMessages = queryClient.getQueryData(['dan-messages']);

      // Optimistic update - ユーザーメッセージを先に表示
      const tempMessageId = `temp-${Date.now()}`;
      const optimisticMessage: MessageResponse = {
        id: tempMessageId,
        room_id: danRoom?.id || '',
        sender_id: user?.id || '',
        sender_name: user?.display_name || 'You',
        sender_type: 'human',
        content,
        created_at: new Date().toISOString(),
      };

      queryClient.setQueryData(['dan-messages'], (old: typeof messagesData) => ({
        messages: [optimisticMessage, ...(old?.messages || [])],
      }));

      // プロセス表示を開始
      setCurrentProcess({
        steps: pendingSteps.map((s, i) => ({
          ...s,
          status: i === 0 ? 'running' : 'pending',
        })),
        isProcessing: true,
        isCollapsed: false,
        messageId: tempMessageId,
      });

      return { previousMessages, tempMessageId };
    },
    onError: (err, _content, context) => {
      // Rollback on error
      queryClient.setQueryData(['dan-messages'], context?.previousMessages);
      setCurrentProcess(null);

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
    onSuccess: (response, _content, context) => {
      // レスポンスには user_message と ai_message が両方含まれる
      // キャッシュを更新して両方のメッセージを追加
      queryClient.setQueryData(['dan-messages'], (old: typeof messagesData) => {
        const existingMessages = old?.messages || [];
        // temp メッセージを削除して、実際のメッセージを追加
        const filtered = existingMessages.filter(m => m.id !== context?.tempMessageId);
        return {
          messages: [response.ai_message, response.user_message, ...filtered],
        };
      });

      // プロセスを完了状態に更新
      const completedSteps = response.process_steps.map(s => ({
        ...s,
        status: 'completed' as const,
      }));

      // 完了したプロセスを保存（AI返信メッセージIDに紐づけ）
      setCompletedProcesses(prev => {
        const newMap = new Map(prev);
        newMap.set(response.ai_message.id, {
          steps: completedSteps,
          isCollapsed: true, // デフォルトで折りたたみ
        });
        return newMap;
      });

      setCurrentProcess(null);
    },
  });

  // Scroll to bottom on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, currentProcess]);

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

  const toggleProcessCollapse = (messageId: string) => {
    setCompletedProcesses(prev => {
      const newMap = new Map(prev);
      const existing = newMap.get(messageId);
      if (existing) {
        newMap.set(messageId, { ...existing, isCollapsed: !existing.isCollapsed });
      }
      return newMap;
    });
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
      <div className="flex flex-col h-full overflow-hidden">
        {/* Header */}
        <div className="shrink-0 flex items-center gap-3 px-6 py-4 border-b border-border">
          <Avatar className="h-10 w-10">
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
        <div className="flex-1 min-h-0 overflow-y-auto px-6">
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
            ) : messages.length === 0 && !currentProcess ? (
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
              // Messages (reverse to show oldest first, newest at bottom)
              <AnimatePresence mode="popLayout">
                {[...messages].reverse().map((msg, index) => {
                  const isUser = msg.sender_type === 'human';
                  const processData = completedProcesses.get(msg.id);

                  return (
                    <div key={msg.id}>
                      <motion.div
                        initial={{ opacity: 0, y: 10 }}
                        animate={{ opacity: 1, y: 0 }}
                        exit={{ opacity: 0 }}
                        transition={{ delay: index * 0.02 }}
                        className={cn('flex gap-3', isUser && 'justify-end')}
                      >
                        {!isUser && (
                          <Avatar className="h-10 w-10 shrink-0">
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
                              'px-4 py-3 rounded-2xl text-sm leading-relaxed whitespace-pre-wrap',
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

                      {/* プロセス表示（AIメッセージの下に表示） */}
                      {!isUser && processData && (
                        <ProcessDisplay
                          steps={processData.steps}
                          isProcessing={false}
                          isCollapsed={processData.isCollapsed}
                          onToggle={() => toggleProcessCollapse(msg.id)}
                        />
                      )}
                    </div>
                  );
                })}
              </AnimatePresence>
            )}

            {/* 処理中のプロセス表示 */}
            <AnimatePresence>
              {currentProcess && (
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
                  <div className="flex-1">
                    <p className="text-xs text-muted-foreground mb-1">ダン</p>
                    <div className="px-4 py-3 rounded-2xl rounded-bl-md bg-muted">
                      <div className="space-y-2">
                        {currentProcess.steps.map((step, index) => (
                          <motion.div
                            key={step.id}
                            initial={{ opacity: 0, x: -10 }}
                            animate={{ opacity: 1, x: 0 }}
                            transition={{ delay: index * 0.15 }}
                            className="flex items-center gap-2 text-sm"
                          >
                            {step.status === 'completed' ? (
                              <Check className="h-4 w-4 text-green-500" />
                            ) : step.status === 'running' ? (
                              <Loader2 className="h-4 w-4 text-primary animate-spin" />
                            ) : (
                              <span className="h-4 w-4 rounded-full border border-muted-foreground/30" />
                            )}
                            <span className={cn(
                              step.status === 'completed' ? 'text-green-600 dark:text-green-400' :
                              step.status === 'running' ? 'text-foreground' :
                              'text-muted-foreground'
                            )}>
                              {step.label}
                            </span>
                          </motion.div>
                        ))}
                      </div>
                    </div>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>

            <div ref={messagesEndRef} />
          </div>
        </div>

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
