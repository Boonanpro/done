'use client';

import { useState, useRef, useEffect, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { motion, AnimatePresence } from 'framer-motion';
import { Send, Paperclip, Loader2, Bot, AlertCircle, RefreshCw, Check, ChevronDown, ChevronUp } from 'lucide-react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
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
  isCollapsed: boolean;
  onToggle: () => void;
}

function ProcessDisplay({ steps, isCollapsed, onToggle }: ProcessDisplayProps) {
  if (steps.length === 0) return null;
  
  const completedCount = steps.filter(s => s.status === 'completed').length;
  
  return (
    <motion.div
      initial={{ opacity: 0, height: 0 }}
      animate={{ opacity: 1, height: 'auto' }}
      className="flex gap-3 mb-2"
    >
      {/* アバタースペース（ダンのアバターと揃える） */}
      <div className="w-10 shrink-0" />
      
      <div className="flex-1 px-4 py-2 rounded-xl bg-muted/50 border border-border">
        <button
          onClick={onToggle}
          className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors w-full"
        >
          {isCollapsed ? (
            <ChevronDown className="h-3 w-3" />
          ) : (
            <ChevronUp className="h-3 w-3" />
          )}
          <span>プロセス ({completedCount}ステップ完了)</span>
        </button>
        
        <AnimatePresence>
          {!isCollapsed && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              exit={{ opacity: 0, height: 0 }}
              className="mt-2 pl-2 border-l-2 border-primary/30 space-y-1"
            >
              {steps.map((step, index) => (
                <motion.div
                  key={step.id + '-' + index}
                  initial={{ opacity: 0, x: -10 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: index * 0.05 }}
                  className="flex items-center gap-2 text-xs"
                >
                  {step.status === 'completed' ? (
                    <Check className="h-3 w-3 text-green-500" />
                  ) : step.status === 'running' ? (
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
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </motion.div>
  );
}

export default function ChatPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const user = useAuthStore((state) => state.user);
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const isLoading = useAuthStore((state) => state.isLoading);
  const [message, setMessage] = useState('');
  const [isSending, setIsSending] = useState(false);
  const [currentProcess, setCurrentProcess] = useState<{
    steps: ProcessStep[];
    isCollapsed: boolean;
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
    staleTime: 5 * 1000,
    retry: 2,
  });

  const messages = messagesData?.messages || [];
  const hasError = roomError || messagesError;

  // SSEストリーミングでメッセージ送信
  const handleSendMessage = useCallback(async () => {
    if (!message.trim() || isSending) return;
    
    const content = message.trim();
    setMessage('');
    setIsSending(true);
    
    // プロセス表示を開始（最初は「考え中...」のみ）
    setCurrentProcess({
      steps: [],
      isCollapsed: false,
    });
    
    let aiMessageId: string | null = null;
    const processSteps: ProcessStep[] = [];
    
    try {
      await api.dan.sendMessageStream(
        content,
        // onProcess
        (step) => {
          // 既存のステップを更新または追加
          const existingIndex = processSteps.findIndex(s => s.id === step.id);
          if (existingIndex >= 0) {
            processSteps[existingIndex] = step;
          } else {
            processSteps.push(step);
          }
          setCurrentProcess({
            steps: [...processSteps],
            isCollapsed: false,
          });
        },
        // onUserMessage
        (userMsg) => {
          // キャッシュを更新
          queryClient.setQueryData(['dan-messages'], (old: typeof messagesData) => ({
            messages: [userMsg, ...(old?.messages || [])],
          }));
        },
        // onAiMessage
        (aiMsg) => {
          aiMessageId = aiMsg.id;
          // キャッシュを更新
          queryClient.setQueryData(['dan-messages'], (old: typeof messagesData) => ({
            messages: [aiMsg, ...(old?.messages || [])],
          }));
        },
        // onError
        (error) => {
          toast.error(`エラー: ${error}`);
          setCurrentProcess(null);
        },
        // onDone
        () => {
          // 完了したプロセスを保存
          if (aiMessageId) {
            setCompletedProcesses(prev => {
              const newMap = new Map(prev);
              newMap.set(aiMessageId!, {
                steps: [...processSteps],
                isCollapsed: false, // デフォルトでオープン
              });
              return newMap;
            });
          }
          setCurrentProcess(null);
        }
      );
    } catch (error) {
      if (error instanceof ApiError) {
        if (error.status === 401) {
          toast.error('セッションが切れました。再度ログインしてください。');
        } else {
          toast.error('メッセージの送信に失敗しました');
        }
      } else {
        toast.error('ネットワークエラーが発生しました');
      }
      setCurrentProcess(null);
    } finally {
      setIsSending(false);
    }
  }, [message, isSending, queryClient, messagesData]);

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

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
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
                      {/* プロセス表示（AIメッセージの上に表示） */}
                      {!isUser && processData && (
                        <ProcessDisplay
                          steps={processData.steps}
                          isCollapsed={processData.isCollapsed}
                          onToggle={() => toggleProcessCollapse(msg.id)}
                        />
                      )}
                      
                      <motion.div
                        initial={{ opacity: 0, y: 10 }}
                        animate={{ opacity: 1, y: 0 }}
                        exit={{ opacity: 0 }}
                        transition={{ delay: index * 0.02 }}
                        className={cn('flex gap-3', isUser && 'justify-end', !isUser && processData && 'mt-2')}
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
                        {currentProcess.steps.length === 0 ? (
                          // まだプロセスがない場合は「考え中...」
                          <motion.div
                            initial={{ opacity: 0 }}
                            animate={{ opacity: 1 }}
                            className="flex items-center gap-2 text-sm"
                          >
                            <Loader2 className="h-4 w-4 text-primary animate-spin" />
                            <span>考え中...</span>
                          </motion.div>
                        ) : (
                          // プロセスを1つずつ表示
                          currentProcess.steps.map((step, index) => (
                            <motion.div
                              key={step.id + '-' + index}
                              initial={{ opacity: 0, x: -10 }}
                              animate={{ opacity: 1, x: 0 }}
                              transition={{ delay: 0.1 }}
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
                          ))
                        )}
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
                onClick={handleSendMessage}
                disabled={!message.trim() || isSending}
              >
                {isSending ? (
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
