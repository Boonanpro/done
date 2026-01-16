'use client';

import { useState, useRef, useEffect, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { motion } from 'framer-motion';
import { Send, Paperclip, Loader2, Bot, AlertCircle, RefreshCw, Check, ChevronDown, ChevronUp, Square } from 'lucide-react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';

import { MainLayout } from '@/components/layout/main-layout';
import { Button } from '@/components/ui/button';
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar';
import { Skeleton } from '@/components/ui/skeleton';
import { api, type MessageResponse, type ProcessStep, type StateMachineResponse, type StateMachineState, ApiError } from '@/lib/api-client';
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
            {steps.map((step, index) => {
              const isLatest = index === steps.length - 1;
              const shouldSpin = isLatest && isProcessing;

              return (
                <div
                  key={step.id}
                  className="flex items-center gap-2 text-xs"
                >
                  {shouldSpin ? (
                    <Loader2 className="h-3 w-3 text-primary animate-spin" />
                  ) : (
                    <span className="h-3 w-3" />
                  )}
                  <span className="text-muted-foreground">
                    {step.label}
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

// ペンディング中のプロセスを管理するための特別なID
const PENDING_PROCESS_ID = '__pending__';

// セッションID保存キー
const SM_SESSION_KEY = 'done-sm-session';

export default function ChatPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const user = useAuthStore((state) => state.user);
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const isLoading = useAuthStore((state) => state.isLoading);
  const [message, setMessage] = useState('');
  const [isSending, setIsSending] = useState(false);
  const abortControllerRef = useRef<AbortController | null>(null);
  
  // StateMachine state - localStorageから初期化
  const [smSession, setSmSession] = useState<string | null>(() => {
    if (typeof window !== 'undefined') {
      return localStorage.getItem(SM_SESSION_KEY);
    }
    return null;
  });
  const [pendingConfirmation, setPendingConfirmation] = useState<StateMachineResponse | null>(null);
  const [revisionInput, setRevisionInput] = useState('');
  const [showRevisionInput, setShowRevisionInput] = useState(false);
  
  // セッションIDをlocalStorageに保存
  useEffect(() => {
    if (smSession) {
      localStorage.setItem(SM_SESSION_KEY, smSession);
    }
  }, [smSession]);
  
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
  
  // dan_room_idをセッションIDとして使用（ブラウザリフレッシュ後も維持）
  useEffect(() => {
    if (danRoom?.id && !smSession) {
      setSmSession(danRoom.id);
    }
  }, [danRoom?.id, smSession]);

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

  // DBから取得したメッセージのreasoning_stepsをprocessesに初期化
  useEffect(() => {
    if (!messages.length) return;
    
    setProcesses(prev => {
      const newMap = new Map(prev);
      
      // AIメッセージのreasoning_stepsを読み込む
      for (const msg of messages) {
        if (msg.sender_type === 'ai' && msg.ai_context?.reasoning_steps?.length) {
          // 既にprocessesに存在しない場合のみ追加
          if (!newMap.has(msg.id)) {
            newMap.set(msg.id, {
              steps: msg.ai_context.reasoning_steps.map((step, idx) => ({
                id: `step-${idx}`,
                label: step,
                status: 'completed' as const,
              })),
              isCollapsed: true, // 既存のプロセスは折りたたんで表示
              isProcessing: false,
            });
          }
        }
      }
      
      return newMap;
    });
  }, [messages]);

  // StateMachine APIでメッセージ送信
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
    
    try {
      // AbortController作成
      const controller = new AbortController();
      abortControllerRef.current = controller;

      // SSEストリーミングでStateMachine APIを呼び出し
      console.log('[Chat] Starting SSE stream', { content, smSession, userId: user?.id });
      const aiMessageId = `ai-${Date.now()}`;
      let stepIndex = 0;

      await api.sm.sendMessageStream(
        {
          message: content,
          session_id: smSession || undefined,
          user_id: user?.id,
        },
        {
          // プロセスステップをリアルタイムで表示
          onProcessStep: (step: ProcessStep) => {
            setProcesses(prev => {
              const newMap = new Map(prev);
              const current = newMap.get(PENDING_PROCESS_ID) || {
                steps: [],
                isCollapsed: false,
                isProcessing: true,
              };

              // 既存のステップをIDで探す
              const existingIndex = current.steps.findIndex(s => s.id === step.id);
              let updatedSteps: ProcessStep[];

              if (existingIndex >= 0) {
                // 既存のステップを更新
                updatedSteps = [...current.steps];
                updatedSteps[existingIndex] = step;
              } else {
                // 新しいステップを追加
                updatedSteps = [...current.steps, step];
              }

              newMap.set(PENDING_PROCESS_ID, {
                ...current,
                steps: updatedSteps,
              });
              return newMap;
            });
          },

          // ユーザーメッセージを受信
          onUserMessage: (message) => {
            // 楽観的更新を実メッセージで置き換え
            queryClient.setQueryData(['dan-messages'], (old: typeof messagesData) => {
              const filtered = (old?.messages || []).filter(m => !m.id.startsWith('temp-user-'));
              return {
                messages: [message, ...filtered],
              };
            });
          },

          // AIメッセージを受信
          onAIMessage: (message) => {
            // AI返信をメッセージとして追加
            queryClient.setQueryData(['dan-messages'], (old: typeof messagesData) => ({
              messages: [message, ...(old?.messages || [])],
            }));

            // プロセスを確定（全ステップをcompletedに）
            setProcesses(prev => {
              const newMap = new Map(prev);
              const pendingProcess = newMap.get(PENDING_PROCESS_ID);
              newMap.delete(PENDING_PROCESS_ID);

              if (pendingProcess) {
                newMap.set(message.id, {
                  steps: pendingProcess.steps,
                  isCollapsed: false,
                  isProcessing: false,
                });
              }

              return newMap;
            });

            // PROPOSE状態（承認待ち）を検出して承認パネルを表示
            const content = message.content || '';
            const isProposeState = content.includes('[STATE: PROPOSE]');
            const hasConfirmationQuestion =
              content.includes('確定しますか') ||
              content.includes('よろしいですか') ||
              content.includes('この内容で進め') ||
              content.includes('予約を実行しますか') ||
              content.includes('予約しますか') ||
              content.includes('購入しますか') ||
              content.includes('実行しますか');

            if (isProposeState || hasConfirmationQuestion) {
              // StateMachineResponse形式で承認待ち状態を設定
              setPendingConfirmation({
                session_id: smSession || '',
                state: 'propose' as StateMachineState,
                response: content,
                reasoning_steps: [],
                needs_confirmation: true,
                is_chat: false,
                proposal: null,
                error: null,
              });
            }
          },

          // 完了時の処理
          onComplete: () => {
            setIsSending(false);
          },
          
          // エラー時の処理
          onError: (error: string) => {
            toast.error(`エラー: ${error}`);
            setProcesses(prev => {
              const newMap = new Map(prev);
              newMap.delete(PENDING_PROCESS_ID);
              return newMap;
            });
            setIsSending(false);
          },
        },
        controller.signal  // AbortSignal追加
      );
      
      return; // SSEのコールバックでisSendingを制御するので、ここでは何もしない
      
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
  }, [message, isSending, queryClient, messagesData, danRoom?.id, user?.id, user?.display_name, smSession]);

  // 提案を承認 - 明確な承認メッセージを送信
  const handleConfirm = useCallback(async () => {
    if (!pendingConfirmation) return;

    // 承認パネルを閉じる
    setPendingConfirmation(null);

    // 明確な承認メッセージを送信（通常のチャットフローを使用）
    const confirmMessage = 'はい、この内容で確定してください。';
    setMessage(confirmMessage);

    // 少し遅延してから送信（setMessageの反映を待つ）
    setTimeout(() => {
      // handleSendMessageと同等の処理を実行
      const sendConfirmation = async () => {
        setMessage('');
        setIsSending(true);

        // 楽観的更新：ユーザーメッセージを即座に表示
        const tempUserMessageId = `temp-user-${Date.now()}`;
        const optimisticUserMessage: MessageResponse = {
          id: tempUserMessageId,
          room_id: danRoom?.id || '',
          sender_id: user?.id || '',
          sender_name: user?.display_name || 'You',
          sender_type: 'human',
          content: confirmMessage,
          created_at: new Date().toISOString(),
        };

        queryClient.setQueryData(['dan-messages'], (old: typeof messagesData) => ({
          messages: [optimisticUserMessage, ...(old?.messages || [])],
        }));

        // プロセス表示を開始
        setProcesses(prev => {
          const newMap = new Map(prev);
          newMap.set(PENDING_PROCESS_ID, {
            steps: [],
            isCollapsed: false,
            isProcessing: true,
          });
          return newMap;
        });

        try {
          // AbortController作成
          const controller = new AbortController();
          abortControllerRef.current = controller;

          await api.sm.sendMessageStream(
            {
              message: confirmMessage,
              session_id: smSession || undefined,
              user_id: user?.id,
            },
            {
              onProcessStep: (step) => {
                setProcesses(prev => {
                  const newMap = new Map(prev);
                  const current = newMap.get(PENDING_PROCESS_ID) || {
                    steps: [],
                    isCollapsed: false,
                    isProcessing: true,
                  };
                  const existingIndex = current.steps.findIndex(s => s.id === step.id);
                  let updatedSteps;
                  if (existingIndex >= 0) {
                    updatedSteps = [...current.steps];
                    updatedSteps[existingIndex] = step;
                  } else {
                    updatedSteps = [...current.steps, step];
                  }
                  newMap.set(PENDING_PROCESS_ID, { ...current, steps: updatedSteps });
                  return newMap;
                });
              },
              onUserMessage: (message) => {
                queryClient.setQueryData(['dan-messages'], (old: typeof messagesData) => {
                  const filtered = (old?.messages || []).filter(m => !m.id.startsWith('temp-user-'));
                  return { messages: [message, ...filtered] };
                });
              },
              onAIMessage: (message) => {
                queryClient.setQueryData(['dan-messages'], (old: typeof messagesData) => ({
                  messages: [message, ...(old?.messages || [])],
                }));
                setProcesses(prev => {
                  const newMap = new Map(prev);
                  const pendingProcess = newMap.get(PENDING_PROCESS_ID);
                  newMap.delete(PENDING_PROCESS_ID);
                  if (pendingProcess) {
                    newMap.set(message.id, {
                      steps: pendingProcess.steps,
                      isCollapsed: false,
                      isProcessing: false,
                    });
                  }
                  return newMap;
                });
                // 完了メッセージの場合は承認パネルを表示しない
              },
              onComplete: () => {
                setIsSending(false);
              },
              onError: (error) => {
                toast.error(`エラー: ${error}`);
                setProcesses(prev => {
                  const newMap = new Map(prev);
                  newMap.delete(PENDING_PROCESS_ID);
                  return newMap;
                });
                setIsSending(false);
              },
            },
            controller.signal  // AbortSignal追加
          );
        } catch (error) {
          toast.error('確認処理に失敗しました');
          setIsSending(false);
        }
      };

      sendConfirmation();
    }, 0);
  }, [pendingConfirmation, queryClient, messagesData, danRoom?.id, user?.id, user?.display_name, smSession]);

  // 提案を修正 - 修正内容をメッセージとして送信
  const handleRevise = useCallback(async () => {
    if (!revisionInput.trim()) return;

    const revisionMessage = revisionInput.trim();

    // UI状態をリセット
    setPendingConfirmation(null);
    setRevisionInput('');
    setShowRevisionInput(false);

    // 修正要望をメッセージとして設定して送信
    setMessage(revisionMessage);

    // 少し遅延してから送信
    setTimeout(() => {
      const sendRevision = async () => {
        setMessage('');
        setIsSending(true);

        // 楽観的更新
        const tempUserMessageId = `temp-user-${Date.now()}`;
        const optimisticUserMessage: MessageResponse = {
          id: tempUserMessageId,
          room_id: danRoom?.id || '',
          sender_id: user?.id || '',
          sender_name: user?.display_name || 'You',
          sender_type: 'human',
          content: revisionMessage,
          created_at: new Date().toISOString(),
        };

        queryClient.setQueryData(['dan-messages'], (old: typeof messagesData) => ({
          messages: [optimisticUserMessage, ...(old?.messages || [])],
        }));

        // プロセス表示を開始
        setProcesses(prev => {
          const newMap = new Map(prev);
          newMap.set(PENDING_PROCESS_ID, {
            steps: [],
            isCollapsed: false,
            isProcessing: true,
          });
          return newMap;
        });

        try {
          // AbortController作成
          const controller = new AbortController();
          abortControllerRef.current = controller;

          await api.sm.sendMessageStream(
            {
              message: revisionMessage,
              session_id: smSession || undefined,
              user_id: user?.id,
            },
            {
              onProcessStep: (step) => {
                setProcesses(prev => {
                  const newMap = new Map(prev);
                  const current = newMap.get(PENDING_PROCESS_ID) || {
                    steps: [],
                    isCollapsed: false,
                    isProcessing: true,
                  };
                  const existingIndex = current.steps.findIndex(s => s.id === step.id);
                  let updatedSteps;
                  if (existingIndex >= 0) {
                    updatedSteps = [...current.steps];
                    updatedSteps[existingIndex] = step;
                  } else {
                    updatedSteps = [...current.steps, step];
                  }
                  newMap.set(PENDING_PROCESS_ID, { ...current, steps: updatedSteps });
                  return newMap;
                });
              },
              onUserMessage: (message) => {
                queryClient.setQueryData(['dan-messages'], (old: typeof messagesData) => {
                  const filtered = (old?.messages || []).filter(m => !m.id.startsWith('temp-user-'));
                  return { messages: [message, ...filtered] };
                });
              },
              onAIMessage: (message) => {
                queryClient.setQueryData(['dan-messages'], (old: typeof messagesData) => ({
                  messages: [message, ...(old?.messages || [])],
                }));
                setProcesses(prev => {
                  const newMap = new Map(prev);
                  const pendingProcess = newMap.get(PENDING_PROCESS_ID);
                  newMap.delete(PENDING_PROCESS_ID);
                  if (pendingProcess) {
                    newMap.set(message.id, {
                      steps: pendingProcess.steps,
                      isCollapsed: false,
                      isProcessing: false,
                    });
                  }
                  return newMap;
                });

                // 新しい提案の場合は承認パネルを表示
                const content = message.content || '';
                const isProposeState = content.includes('[STATE: PROPOSE]');
                const hasConfirmationQuestion =
                  content.includes('確定しますか') ||
                  content.includes('よろしいですか') ||
                  content.includes('この内容で進め') ||
                  content.includes('予約を実行しますか') ||
                  content.includes('予約しますか') ||
                  content.includes('購入しますか') ||
                  content.includes('実行しますか');

                if (isProposeState || hasConfirmationQuestion) {
                  setPendingConfirmation({
                    session_id: smSession || '',
                    state: 'propose' as StateMachineState,
                    response: content,
                    reasoning_steps: [],
                    needs_confirmation: true,
                    is_chat: false,
                    proposal: null,
                    error: null,
                  });
                }
              },
              onComplete: () => {
                setIsSending(false);
              },
              onError: (error) => {
                toast.error(`エラー: ${error}`);
                setProcesses(prev => {
                  const newMap = new Map(prev);
                  newMap.delete(PENDING_PROCESS_ID);
                  return newMap;
                });
                setIsSending(false);
              },
            },
            controller.signal  // AbortSignal追加
          );
        } catch (error) {
          toast.error('修正処理に失敗しました');
          setIsSending(false);
        }
      };

      sendRevision();
    }, 0);
  }, [revisionInput, queryClient, messagesData, danRoom?.id, user?.id, user?.display_name, smSession]);

  // Scroll to bottom on new messages (not on process toggle)
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

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

  // 処理をキャンセル
  const handleCancel = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    setIsSending(false);
    setProcesses(prev => {
      const newMap = new Map(prev);
      newMap.delete(PENDING_PROCESS_ID);
      return newMap;
    });
    toast.info('処理を停止しました');
  }, []);

  // Escapeキーでキャンセル
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && isSending) {
        e.preventDefault();
        handleCancel();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isSending, handleCancel]);

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
                            'max-w-[70%] space-y-1 flex flex-col',
                            isUser && 'items-end'
                          )}
                        >
                          <p className="text-xs text-muted-foreground">
                            {isUser ? 'あなた' : 'ダン'}
                          </p>
                          <div
                            className={cn(
                              'px-4 py-3 rounded-2xl text-sm leading-relaxed whitespace-pre-wrap text-left',
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

        {/* Confirmation Panel */}
        {pendingConfirmation && (
          <div className="shrink-0 border-t border-border bg-muted/30 px-4 py-3">
            <div className="max-w-3xl mx-auto">
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm font-medium text-primary">確認が必要です</span>
              </div>
              {showRevisionInput ? (
                <div className="space-y-2">
                  <textarea
                    value={revisionInput}
                    onChange={(e) => setRevisionInput(e.target.value)}
                    placeholder="修正内容を入力..."
                    rows={2}
                    className="w-full px-3 py-2 rounded-lg border border-border bg-background text-sm focus:outline-none focus:border-primary/50"
                  />
                  <div className="flex gap-2">
                    <Button
                      size="sm"
                      onClick={handleRevise}
                      disabled={!revisionInput.trim() || isSending}
                    >
                      {isSending ? <Loader2 className="h-4 w-4 animate-spin mr-1" /> : null}
                      送信
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => {
                        setShowRevisionInput(false);
                        setRevisionInput('');
                      }}
                    >
                      キャンセル
                    </Button>
                  </div>
                </div>
              ) : (
                <div className="flex gap-2">
                  <Button
                    size="sm"
                    onClick={handleConfirm}
                    disabled={isSending}
                    className="bg-primary hover:bg-primary/90"
                  >
                    {isSending ? <Loader2 className="h-4 w-4 animate-spin mr-1" /> : <Check className="h-4 w-4 mr-1" />}
                    これで進める
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => setShowRevisionInput(true)}
                  >
                    修正する
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => setPendingConfirmation(null)}
                  >
                    キャンセル
                  </Button>
                </div>
              )}
            </div>
          </div>
        )}

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

              {isSending ? (
                <Button
                  size="icon"
                  variant="destructive"
                  className="h-9 w-9 shrink-0"
                  onClick={handleCancel}
                  title="停止 (Escキー)"
                >
                  <Square className="h-4 w-4" />
                </Button>
              ) : (
                <Button
                  size="icon"
                  className="h-9 w-9 shrink-0"
                  onClick={handleSendMessage}
                  disabled={!message.trim()}
                >
                  <Send className="h-4 w-4" />
                </Button>
              )}
            </div>
          </div>
        </div>
      </div>
    </MainLayout>
  );
}
