'use client';

import { useState, useRef, useEffect, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { motion } from 'framer-motion';
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
  isProcessing?: boolean;
}

function ProcessDisplay({ steps, isCollapsed, onToggle, isProcessing = false }: ProcessDisplayProps) {
  const hasSteps = steps.length > 0;
  
  return (
    <div className="flex gap-3 mb-2">
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
          <span>プロセス</span>
        </button>
        
        {!isCollapsed && (
          <div className="mt-2 pl-2 border-l-2 border-primary/30 space-y-1">
            {/* 「考え中...」表示（ステップがない場合） */}
            {isProcessing && !hasSteps && (
              <div className="flex items-center gap-2 text-xs">
                <Loader2 className="h-3 w-3 text-primary animate-spin" />
                <span>考え中...</span>
              </div>
            )}
            
            {/* プロセスステップ */}
            {steps.map((step) => (
              <div
                key={step.id}
                className="flex items-center gap-2 text-xs"
              >
                {step.status === 'completed' ? (
                  <Check className="h-3 w-3 text-muted-foreground" />
                ) : step.status === 'running' ? (
                  <Loader2 className="h-3 w-3 text-primary animate-spin" />
                ) : (
                  <span className="h-3 w-3 rounded-full bg-muted-foreground/30" />
                )}
                <span className="text-muted-foreground">
                  {step.label}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ペンディング中のプロセスを管理するための特別なID
const PENDING_PROCESS_ID = '__pending__';

export default function ChatPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const user = useAuthStore((state) => state.user);
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const isLoading = useAuthStore((state) => state.isLoading);
  const [message, setMessage] = useState('');
  const [isSending, setIsSending] = useState(false);
  
  // すべてのプロセスを統一管理（処理中も完了後も同じ）
  const [processes, setProcesses] = useState<Map<string, { 
    steps: ProcessStep[]; 
    isCollapsed: boolean;
    isProcessing: boolean;
  }>>(new Map());
  
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
    
    // 1. 楽観的更新：ユーザーメッセージを即座に表示
    const tempUserMessageId = `temp-user-${Date.now()}`;
    const optimisticUserMessage: MessageResponse = {
      id: tempUserMessageId,
      room_id: danRoom?.id || '',
      sender_id: user?.id || '',
      sender_name: user?.display_name || 'You',
      sender_type: 'human',
      content,
      created_at: new Date().toISOString(),
    };
    
    queryClient.setQueryData(['dan-messages'], (old: typeof messagesData) => ({
      messages: [optimisticUserMessage, ...(old?.messages || [])],
    }));
    
    // 2. プロセス表示を開始（ペンディングIDで）
    setProcesses(prev => {
      const newMap = new Map(prev);
      newMap.set(PENDING_PROCESS_ID, {
        steps: [],
        isCollapsed: false,
        isProcessing: true,
      });
      return newMap;
    });
    
    let realUserMessageId: string | null = null;
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
          setProcesses(prev => {
            const newMap = new Map(prev);
            newMap.set(PENDING_PROCESS_ID, {
              steps: [...processSteps],
              isCollapsed: false,
              isProcessing: true,
            });
            return newMap;
          });
        },
        // onUserMessage
        (userMsg) => {
          realUserMessageId = userMsg.id;
          // 楽観的に追加したメッセージを実際のメッセージに置き換え
          queryClient.setQueryData(['dan-messages'], (old: typeof messagesData) => {
            const existingMessages = old?.messages || [];
            const filtered = existingMessages.filter(m => m.id !== tempUserMessageId);
            return { messages: [userMsg, ...filtered] };
          });
        },
        // onAiMessage
        (aiMsg) => {
          aiMessageId = aiMsg.id;
          // AI返信をキャッシュに追加
          queryClient.setQueryData(['dan-messages'], (old: typeof messagesData) => ({
            messages: [aiMsg, ...(old?.messages || [])],
          }));
        },
        // onError
        (error) => {
          toast.error(`エラー: ${error}`);
          // プロセスをエラー状態で保持（削除しない）
          setProcesses(prev => {
            const newMap = new Map(prev);
            newMap.delete(PENDING_PROCESS_ID);
            return newMap;
          });
        },
        // onDone
        () => {
          // ペンディングプロセスをAIメッセージIDに紐づけて確定
          if (aiMessageId) {
            setProcesses(prev => {
              const newMap = new Map(prev);
              newMap.delete(PENDING_PROCESS_ID);
              newMap.set(aiMessageId!, {
                steps: [...processSteps],
                isCollapsed: false,
                isProcessing: false,
              });
              return newMap;
            });
          } else {
            // AI返信がなかった場合はプロセスを削除
            setProcesses(prev => {
              const newMap = new Map(prev);
              newMap.delete(PENDING_PROCESS_ID);
              return newMap;
            });
          }
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
      // エラー時はプロセスを削除
      setProcesses(prev => {
        const newMap = new Map(prev);
        newMap.delete(PENDING_PROCESS_ID);
        return newMap;
      });
    } finally {
      setIsSending(false);
    }
  }, [message, isSending, queryClient, messagesData, danRoom?.id, user?.id, user?.display_name]);

  // Scroll to bottom on new messages
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, processes]);

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

  const toggleProcessCollapse = (processId: string) => {
    setProcesses(prev => {
      const newMap = new Map(prev);
      const existing = newMap.get(processId);
      if (existing) {
        newMap.set(processId, { ...existing, isCollapsed: !existing.isCollapsed });
      }
      return newMap;
    });
  };

  // ペンディングプロセスがあるか
  const pendingProcess = processes.get(PENDING_PROCESS_ID);

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
          <div className="max-w-3xl mx-auto py-6 space-y-4">
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
            ) : messages.length === 0 && !pendingProcess ? (
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
              <>
                {[...messages].reverse().map((msg) => {
                  const isUser = msg.sender_type === 'human';
                  const processData = processes.get(msg.id);

                  return (
                    <div key={msg.id}>
                      {/* プロセス表示（AIメッセージの上に表示） */}
                      {!isUser && processData && (
                        <ProcessDisplay
                          steps={processData.steps}
                          isCollapsed={processData.isCollapsed}
                          onToggle={() => toggleProcessCollapse(msg.id)}
                          isProcessing={processData.isProcessing}
                        />
                      )}
                      
                      {/* メッセージ本体 */}
                      <div
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
                      </div>
                    </div>
                  );
                })}

                {/* ペンディング中のプロセス表示（AI返信待ち） */}
                {pendingProcess && (
                  <ProcessDisplay
                    steps={pendingProcess.steps}
                    isCollapsed={pendingProcess.isCollapsed}
                    onToggle={() => toggleProcessCollapse(PENDING_PROCESS_ID)}
                    isProcessing={pendingProcess.isProcessing}
                  />
                )}
              </>
            )}

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
