'use client';

import { useState, useRef, useEffect, useCallback, useMemo } from 'react';
import { useRouter, useParams, useSearchParams } from 'next/navigation';
import { motion } from 'framer-motion';
import { Send, Paperclip, Loader2, Bot, AlertCircle, RefreshCw, Check, ChevronDown, ChevronUp, Square, Sparkles, X, Mic, MicOff, SkipForward } from 'lucide-react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';

import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

import { MainLayout } from '@/components/layout/main-layout';
import { Button } from '@/components/ui/button';
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar';
import { Skeleton } from '@/components/ui/skeleton';
import { api, type MessageResponse, type ProcessStep, type StateMachineResponse, type StateMachineState, ApiError } from '@/lib/api-client';
import { useAuthStore } from '@/stores/auth-store';
import { useSessionStateStore, PENDING_PROCESS_ID } from '@/stores/session-state-store';
import { cn } from '@/lib/utils';
import { useVoiceChat } from '@/hooks/useVoiceChat';
import { useGeminiObserver } from '@/hooks/useGeminiObserver';

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
      <div className="w-10 shrink-0" />
      <div className="flex-1 px-4 py-2 rounded-xl bg-muted/50 border border-border">
        <button
          onClick={onToggle}
          className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors w-full"
        >
          {isCollapsed ? <ChevronDown className="h-3 w-3" /> : <ChevronUp className="h-3 w-3" />}
          <span>プロセス</span>
        </button>
        {!isCollapsed && (
          <div className="mt-2 pl-2 border-l-2 border-primary/30 space-y-1">
            {isProcessing && !hasSteps && (
              <div className="flex items-center gap-2 text-xs">
                <Loader2 className="h-3 w-3 text-primary animate-spin" />
                <span>考え中...</span>
              </div>
            )}
            {steps.map((step, index) => {
              const isLatest = index === steps.length - 1;
              const shouldSpin = isLatest && isProcessing;
              return (
                <div key={step.id} className="flex items-center gap-2 text-xs">
                  {shouldSpin ? (
                    <Loader2 className="h-3 w-3 text-primary animate-spin" />
                  ) : (
                    <span className="h-3 w-3" />
                  )}
                  <span className="text-muted-foreground">{step.label}</span>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}

export default function ChatSessionPage() {
  const router = useRouter();
  const params = useParams();
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();

  // URLからセッションIDを取得（唯一の真実源）
  const sessionId = params.sessionId as string;

  const user = useAuthStore((state) => state.user);
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const isLoading = useAuthStore((state) => state.isLoading);
  const [message, setMessage] = useState('');

  // スキル化ダイアログ用の状態（複数提案対応）
  const [showSkillDialog, setShowSkillDialog] = useState(false);
  const [browserSessionId, setBrowserSessionId] = useState<string | null>(null);
  const [isAnalyzingSkill, setIsAnalyzingSkill] = useState(false);
  const [isCreatingSkill, setIsCreatingSkill] = useState(false);
  // 複数提案のリスト
  const [skillProposals, setSkillProposals] = useState<Array<{
    proposal_id: string;
    skill_name: string;
    description: string;
    site: string;
    actions: string[];
    parameters: Array<{ name: string; type: string; required: boolean; description: string }>;
    decision: string;
    target_skill?: string | null;
    new_actions?: string[] | null;
  }>>([]);
  // 現在表示中の提案インデックス
  const [currentProposalIndex, setCurrentProposalIndex] = useState(0);
  // 後方互換用（単一提案の場合）
  const [skillProposal, setSkillProposal] = useState<{
    proposal_id?: string;
    status?: string;
    skill_name: string;
    description: string;
    site: string;
    actions: string[];
    parameters: Array<{ name: string; type: string; required: boolean; description: string }>;
    steps?: string[];
  } | null>(null);

  // セッション別ストア
  const sessions = useSessionStateStore((state) => state.sessions);
  const setActiveSessionId = useSessionStateStore((state) => state.setActiveSessionId);
  const getSessionState = useSessionStateStore((state) => state.getSessionState);
  const setProcess = useSessionStateStore((state) => state.setProcess);
  const deleteProcess = useSessionStateStore((state) => state.deleteProcess);
  const addProcessStep = useSessionStateStore((state) => state.addProcessStep);
  const toggleProcessCollapse = useSessionStateStore((state) => state.toggleProcessCollapse);
  const setPendingConfirmation = useSessionStateStore((state) => state.setPendingConfirmation);
  const setIsSending = useSessionStateStore((state) => state.setIsSending);
  const setRevisionInput = useSessionStateStore((state) => state.setRevisionInput);
  const setShowRevisionInput = useSessionStateStore((state) => state.setShowRevisionInput);
  const initializeProcessesFromMessages = useSessionStateStore((state) => state.initializeProcessesFromMessages);
  const incrementUnread = useSessionStateStore((state) => state.incrementUnread);
  const markAsRead = useSessionStateStore((state) => state.markAsRead);

  const abortControllersRef = useRef<Map<string, AbortController>>(new Map());
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Voice chat integration
  const voiceSendRef = useRef<((text: string) => void) | null>(null);
  const voice = useVoiceChat({
    onFinalTranscript: (text: string) => {
      // Set message and trigger send via ref (avoids stale closure)
      voiceSendRef.current?.(text);
    },
  });

  const hasToken = typeof window !== 'undefined' && !!localStorage.getItem('done-token');

  // Gemini voice observer (connects to active voice session if available)
  const [voiceMessages, setVoiceMessages] = useState<MessageResponse[]>([]);
  const userTextBufRef = useRef('');
  const assistantTextBufRef = useRef('');

  const flushUserTextBuffer = useCallback(() => {
    if (userTextBufRef.current) {
      const content = userTextBufRef.current;
      userTextBufRef.current = '';
      setVoiceMessages(prev => [...prev, {
        id: `voice-user-${Date.now()}`,
        room_id: sessionId,
        sender_id: user?.id || '',
        sender_name: user?.display_name || 'You',
        sender_type: 'human',
        content,
        created_at: new Date().toISOString(),
      }]);
    }
  }, [sessionId, user?.id, user?.display_name]);

  const observer = useGeminiObserver({
    sessionId: sessionId || null,
    autoConnect: true,
    onUserText: useCallback((text: string) => {
      userTextBufRef.current += text;
    }, []),
    onAssistantText: useCallback((text: string) => {
      flushUserTextBuffer();
      assistantTextBufRef.current += text;
    }, [flushUserTextBuffer]),
    onToolStart: useCallback(() => {
      flushUserTextBuffer();
    }, [flushUserTextBuffer]),
    onTurnComplete: useCallback(() => {
      flushUserTextBuffer();
      if (assistantTextBufRef.current) {
        const content = assistantTextBufRef.current;
        assistantTextBufRef.current = '';
        setVoiceMessages(prev => [...prev, {
          id: `voice-assistant-${Date.now()}`,
          room_id: sessionId,
          sender_id: 'dan',
          sender_name: 'ダン',
          sender_type: 'ai' as MessageResponse['sender_type'],
          content,
          created_at: new Date().toISOString(),
        }]);
      }
    }, [sessionId, flushUserTextBuffer]),
  });

  // 認証チェック
  useEffect(() => {
    if (!isLoading && !isAuthenticated && !hasToken) {
      router.push('/login');
    }
  }, [isLoading, isAuthenticated, hasToken, router]);

  // Auto-activate voice mode from ?voice=true query param
  useEffect(() => {
    if (searchParams.get('voice') === 'true' && !voice.isActive) {
      voice.toggleVoice();
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []); // Run once on mount

  // セッションIDが変わったらアクティブセッションを更新
  useEffect(() => {
    if (sessionId) {
      setActiveSessionId(sessionId);
      markAsRead(sessionId);
    }
  }, [sessionId, setActiveSessionId, markAsRead]);

  // 現在のセッションの状態を取得
  const currentSessionState = useMemo(() => {
    if (!sessionId) return null;
    return sessions.get(sessionId) || null;
  }, [sessionId, sessions]);

  const processes = currentSessionState?.processes || new Map();
  const pendingConfirmation = currentSessionState?.pendingConfirmation || null;
  const isSending = currentSessionState?.isSending || false;
  const revisionInput = currentSessionState?.revisionInput || '';
  const showRevisionInput = currentSessionState?.showRevisionInput || false;

  // メッセージ取得（URLのsessionIdを直接使用）
  const {
    data: messagesData,
    isLoading: isLoadingMessages,
    error: messagesError,
    refetch: refetchMessages,
  } = useQuery({
    queryKey: ['messages', sessionId],
    queryFn: () => api.rooms.getMessages(sessionId, { limit: 50 }),
    enabled: !!sessionId,
    staleTime: 5 * 1000,
    refetchInterval: 3000, // 3秒ごとにポーリング（別デバイスからの会話を反映）
    retry: 2,
  });

  const messages = messagesData?.messages || [];

  // DB messages (newest-first) + voice messages (chronological) → oldest-first for display
  const allMessages = useMemo(() => {
    const dbMsgs = [...messages].reverse();
    return [...dbMsgs, ...voiceMessages];
  }, [messages, voiceMessages]);

  // DBから取得したメッセージのreasoning_stepsをprocessesに初期化
  useEffect(() => {
    if (!messages.length || !sessionId) return;
    initializeProcessesFromMessages(sessionId, messages);
  }, [messages, sessionId, initializeProcessesFromMessages]);

  // メッセージ送信 (textOverride: voice mode等から直接テキストを渡す場合)
  const handleSendMessage = useCallback(async (textOverride?: string) => {
    const text = textOverride || message;
    if (!text.trim() || isSending || !sessionId) return;

    const content = text.trim();
    setMessage('');
    setIsSending(sessionId, true);

    const tempUserMessageId = `temp-user-${Date.now()}`;
    const optimisticUserMessage: MessageResponse = {
      id: tempUserMessageId,
      room_id: sessionId,
      sender_id: user?.id || '',
      sender_name: user?.display_name || 'You',
      sender_type: 'human',
      content,
      created_at: new Date().toISOString(),
    };

    queryClient.setQueryData(['messages', sessionId], (old: typeof messagesData) => ({
      messages: [optimisticUserMessage, ...(old?.messages || [])],
    }));

    setProcess(sessionId, PENDING_PROCESS_ID, {
      steps: [],
      isCollapsed: false,
      isProcessing: true,
    });

    try {
      const controller = new AbortController();
      abortControllersRef.current.set(sessionId, controller);

      await api.sm.sendMessageStream(
        {
          message: content,
          session_id: sessionId,
          user_id: user?.id,
        },
        {
          onProcessStep: (step: ProcessStep, eventSessionId?: string) => {
            const targetSessionId = eventSessionId || sessionId;
            addProcessStep(targetSessionId, PENDING_PROCESS_ID, step);
          },

          onUserMessage: (msg, eventSessionId?: string) => {
            const targetSessionId = eventSessionId || sessionId;
            queryClient.setQueryData(['messages', targetSessionId], (old: typeof messagesData) => {
              const filtered = (old?.messages || []).filter(m => !m.id.startsWith('temp-user-'));
              return { messages: [msg, ...filtered] };
            });
          },

          onAIMessage: (msg, eventSessionId?: string) => {
            const targetSessionId = eventSessionId || sessionId;
            const currentActiveSessionId = useSessionStateStore.getState().activeSessionId;
            const isCurrentSession = targetSessionId === currentActiveSessionId;

            // 常に正しいセッションのキャッシュに追加
            queryClient.setQueryData(['messages', targetSessionId], (old: typeof messagesData) => ({
              messages: [msg, ...(old?.messages || [])],
            }));

            // 別セッションの場合は未読カウントを増やす
            if (!isCurrentSession) {
              incrementUnread(targetSessionId);
            }

            // プロセスを確定
            const pendingProcess = getSessionState(targetSessionId).processes.get(PENDING_PROCESS_ID);
            deleteProcess(targetSessionId, PENDING_PROCESS_ID);
            if (pendingProcess) {
              setProcess(targetSessionId, msg.id, {
                steps: pendingProcess.steps,
                isCollapsed: false,
                isProcessing: false,
              });
            }

            // 提案パネル表示（現在のセッションのみ）
            if (isCurrentSession) {
              const msgContent = msg.content || '';
              const isProposeState = msgContent.includes('[STATE: PROPOSE]');
              const hasConfirmationQuestion =
                msgContent.includes('確定しますか') ||
                msgContent.includes('よろしいですか') ||
                msgContent.includes('この内容で進め') ||
                msgContent.includes('予約を実行しますか') ||
                msgContent.includes('予約しますか') ||
                msgContent.includes('購入しますか') ||
                msgContent.includes('実行しますか');

              if (isProposeState || hasConfirmationQuestion) {
                setPendingConfirmation(targetSessionId, {
                  session_id: targetSessionId,
                  state: 'propose' as StateMachineState,
                  response: msgContent,
                  reasoning_steps: [],
                  needs_confirmation: true,
                  is_chat: false,
                  proposal: null,
                  error: null,
                });
              }

              // Voice mode: speak AI response via TTS
              if (voice.isActive && msg.content) {
                voice.speakResponse(msg.content);
              }
            }
          },

          onComplete: (eventSessionId?: string) => {
            const targetSessionId = eventSessionId || sessionId;
            setIsSending(targetSessionId, false);
          },

          onError: (error: string, eventSessionId?: string) => {
            const targetSessionId = eventSessionId || sessionId;
            toast.error(`エラー: ${error}`);
            deleteProcess(targetSessionId, PENDING_PROCESS_ID);
            setIsSending(targetSessionId, false);
          },

          onSkillAvailable: (browserSessId: string, eventSessionId?: string) => {
            const targetSessionId = eventSessionId || sessionId;
            const currentActiveSessionId = useSessionStateStore.getState().activeSessionId;
            // アクティブなセッションの場合のみダイアログを表示（分析→提案）
            if (targetSessionId === currentActiveSessionId) {
              handleShowSkillProposal(browserSessId);
            }
          },
        },
        controller.signal
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
      deleteProcess(sessionId, PENDING_PROCESS_ID);
    } finally {
      setIsSending(sessionId, false);
    }
  }, [message, isSending, sessionId, queryClient, messagesData, user?.id, user?.display_name, setIsSending, setProcess, addProcessStep, getSessionState, deleteProcess, setPendingConfirmation, incrementUnread, voice.isActive, voice.speakResponse]);

  // Voice send ref: allows voice hook to trigger message send
  useEffect(() => {
    voiceSendRef.current = (text: string) => {
      handleSendMessage(text);
    };
  }, [handleSendMessage]);

  // 提案を承認
  const handleConfirm = useCallback(async () => {
    if (!pendingConfirmation || !sessionId) return;

    setPendingConfirmation(sessionId, null);
    const confirmMessage = 'はい、この内容で確定してください。';

    setTimeout(async () => {
      setIsSending(sessionId, true);

      const tempUserMessageId = `temp-user-${Date.now()}`;
      const optimisticUserMessage: MessageResponse = {
        id: tempUserMessageId,
        room_id: sessionId,
        sender_id: user?.id || '',
        sender_name: user?.display_name || 'You',
        sender_type: 'human',
        content: confirmMessage,
        created_at: new Date().toISOString(),
      };

      queryClient.setQueryData(['messages', sessionId], (old: typeof messagesData) => ({
        messages: [optimisticUserMessage, ...(old?.messages || [])],
      }));

      setProcess(sessionId, PENDING_PROCESS_ID, {
        steps: [],
        isCollapsed: false,
        isProcessing: true,
      });

      try {
        const controller = new AbortController();
        abortControllersRef.current.set(sessionId, controller);

        await api.sm.sendMessageStream(
          { message: confirmMessage, session_id: sessionId, user_id: user?.id },
          {
            onProcessStep: (step, eventSessionId) => {
              addProcessStep(eventSessionId || sessionId, PENDING_PROCESS_ID, step);
            },
            onUserMessage: (msg, eventSessionId) => {
              const targetSessionId = eventSessionId || sessionId;
              queryClient.setQueryData(['messages', targetSessionId], (old: typeof messagesData) => {
                const filtered = (old?.messages || []).filter(m => !m.id.startsWith('temp-user-'));
                return { messages: [msg, ...filtered] };
              });
            },
            onAIMessage: (msg, eventSessionId) => {
              const targetSessionId = eventSessionId || sessionId;
              const currentActiveSessionId = useSessionStateStore.getState().activeSessionId;
              const isCurrentSession = targetSessionId === currentActiveSessionId;
              queryClient.setQueryData(['messages', targetSessionId], (old: typeof messagesData) => ({
                messages: [msg, ...(old?.messages || [])],
              }));
              if (!isCurrentSession) {
                incrementUnread(targetSessionId);
              }
              const proc = getSessionState(targetSessionId).processes.get(PENDING_PROCESS_ID);
              deleteProcess(targetSessionId, PENDING_PROCESS_ID);
              if (proc) {
                setProcess(targetSessionId, msg.id, { steps: proc.steps, isCollapsed: false, isProcessing: false });
              }
            },
            onComplete: (eventSessionId) => setIsSending(eventSessionId || sessionId, false),
            onError: (error, eventSessionId) => {
              toast.error(`エラー: ${error}`);
              deleteProcess(eventSessionId || sessionId, PENDING_PROCESS_ID);
              setIsSending(eventSessionId || sessionId, false);
            },
            onSkillAvailable: (browserSessId: string, eventSessionId?: string) => {
              const targetSessionId = eventSessionId || sessionId;
              const currentActiveSessionId = useSessionStateStore.getState().activeSessionId;
              if (targetSessionId === currentActiveSessionId) {
                handleShowSkillProposal(browserSessId);
              }
            },
          },
          controller.signal
        );
      } catch {
        toast.error('確認処理に失敗しました');
        setIsSending(sessionId, false);
      }
    }, 0);
  }, [pendingConfirmation, sessionId, queryClient, messagesData, user?.id, user?.display_name, setPendingConfirmation, setIsSending, setProcess, addProcessStep, getSessionState, deleteProcess, incrementUnread]);

  // 提案を修正
  const handleRevise = useCallback(async () => {
    if (!revisionInput.trim() || !sessionId) return;

    const revisionMessage = revisionInput.trim();
    setPendingConfirmation(sessionId, null);
    setRevisionInput(sessionId, '');
    setShowRevisionInput(sessionId, false);

    setTimeout(async () => {
      setIsSending(sessionId, true);

      const tempUserMessageId = `temp-user-${Date.now()}`;
      const optimisticUserMessage: MessageResponse = {
        id: tempUserMessageId,
        room_id: sessionId,
        sender_id: user?.id || '',
        sender_name: user?.display_name || 'You',
        sender_type: 'human',
        content: revisionMessage,
        created_at: new Date().toISOString(),
      };

      queryClient.setQueryData(['messages', sessionId], (old: typeof messagesData) => ({
        messages: [optimisticUserMessage, ...(old?.messages || [])],
      }));

      setProcess(sessionId, PENDING_PROCESS_ID, {
        steps: [],
        isCollapsed: false,
        isProcessing: true,
      });

      try {
        const controller = new AbortController();
        abortControllersRef.current.set(sessionId, controller);

        await api.sm.sendMessageStream(
          { message: revisionMessage, session_id: sessionId, user_id: user?.id },
          {
            onProcessStep: (step, eventSessionId) => {
              addProcessStep(eventSessionId || sessionId, PENDING_PROCESS_ID, step);
            },
            onUserMessage: (msg, eventSessionId) => {
              const targetSessionId = eventSessionId || sessionId;
              queryClient.setQueryData(['messages', targetSessionId], (old: typeof messagesData) => {
                const filtered = (old?.messages || []).filter(m => !m.id.startsWith('temp-user-'));
                return { messages: [msg, ...filtered] };
              });
            },
            onAIMessage: (msg, eventSessionId) => {
              const targetSessionId = eventSessionId || sessionId;
              const currentActiveSessionId = useSessionStateStore.getState().activeSessionId;
              const isCurrentSession = targetSessionId === currentActiveSessionId;
              queryClient.setQueryData(['messages', targetSessionId], (old: typeof messagesData) => ({
                messages: [msg, ...(old?.messages || [])],
              }));
              if (!isCurrentSession) {
                incrementUnread(targetSessionId);
              }
              const proc = getSessionState(targetSessionId).processes.get(PENDING_PROCESS_ID);
              deleteProcess(targetSessionId, PENDING_PROCESS_ID);
              if (proc) {
                setProcess(targetSessionId, msg.id, { steps: proc.steps, isCollapsed: false, isProcessing: false });
              }
              // 新しい提案検出
              if (isCurrentSession) {
                const msgContent = msg.content || '';
                const isProposeState = msgContent.includes('[STATE: PROPOSE]');
                const hasConfirmationQuestion =
                  msgContent.includes('確定しますか') || msgContent.includes('よろしいですか') ||
                  msgContent.includes('この内容で進め') || msgContent.includes('予約を実行しますか') ||
                  msgContent.includes('予約しますか') || msgContent.includes('購入しますか') ||
                  msgContent.includes('実行しますか');
                if (isProposeState || hasConfirmationQuestion) {
                  setPendingConfirmation(targetSessionId, {
                    session_id: targetSessionId,
                    state: 'propose' as StateMachineState,
                    response: msgContent,
                    reasoning_steps: [],
                    needs_confirmation: true,
                    is_chat: false,
                    proposal: null,
                    error: null,
                  });
                }
              }
            },
            onComplete: (eventSessionId) => setIsSending(eventSessionId || sessionId, false),
            onError: (error, eventSessionId) => {
              toast.error(`エラー: ${error}`);
              deleteProcess(eventSessionId || sessionId, PENDING_PROCESS_ID);
              setIsSending(eventSessionId || sessionId, false);
            },
            onSkillAvailable: (browserSessId: string, eventSessionId?: string) => {
              const targetSessionId = eventSessionId || sessionId;
              const currentActiveSessionId = useSessionStateStore.getState().activeSessionId;
              if (targetSessionId === currentActiveSessionId) {
                handleShowSkillProposal(browserSessId);
              }
            },
          },
          controller.signal
        );
      } catch {
        toast.error('修正処理に失敗しました');
        setIsSending(sessionId, false);
      }
    }, 0);
  }, [revisionInput, sessionId, queryClient, messagesData, user?.id, user?.display_name, setPendingConfirmation, setRevisionInput, setShowRevisionInput, setIsSending, setProcess, addProcessStep, getSessionState, deleteProcess, incrementUnread]);

  // スクロール
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // テキストエリア自動リサイズ
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

  const handleToggleProcessCollapse = useCallback((processId: string) => {
    if (sessionId) {
      toggleProcessCollapse(sessionId, processId);
    }
  }, [sessionId, toggleProcessCollapse]);

  const pendingProcess = processes.get(PENDING_PROCESS_ID);

  const handleCancel = useCallback(async () => {
    if (!sessionId) return;

    // 1. AbortControllerでfetchを中止（既存）
    const controller = abortControllersRef.current.get(sessionId);
    if (controller) {
      controller.abort();
      abortControllersRef.current.delete(sessionId);
    }

    // 2. バックエンドにキャンセルをリクエスト（新規）
    try {
      await api.sm.cancelSession(sessionId);
    } catch (e) {
      console.error('Failed to cancel session:', e);
    }

    // 3. UI更新（既存）
    setIsSending(sessionId, false);
    deleteProcess(sessionId, PENDING_PROCESS_ID);
    toast.info('処理を停止しました');
  }, [sessionId, setIsSending, deleteProcess]);

  // スキル提案を表示（分析→ダイアログ表示）複数提案対応
  const handleShowSkillProposal = useCallback(async (sessId: string) => {
    console.log('[SKILL_DEBUG] handleShowSkillProposal called with sessId:', sessId);
    setBrowserSessionId(sessId);
    setIsAnalyzingSkill(true);
    setShowSkillDialog(true);
    setSkillProposals([]);
    setCurrentProposalIndex(0);
    setSkillProposal(null);

    try {
      console.log('[SKILL_DEBUG] Calling api.skills.analyze...');
      const result = await api.skills.analyze(sessId);
      console.log('[SKILL_DEBUG] API result:', JSON.stringify(result, null, 2));

      // skip の場合はダイアログを表示しない
      if (result.decision === 'skip') {
        console.log('[SKILL_DEBUG] Skipped:', result.skip_reason || result.decision_reason);
        setShowSkillDialog(false);
        setBrowserSessionId(null);
        return;
      }

      // 複数提案対応
      if (result.success && result.proposals && result.proposals.length > 0) {
        console.log('[SKILL_DEBUG] Success! Setting proposals:', result.proposals.length);
        // LocalStorage に提案IDを保存（カンマ区切り）
        if (sessionId) {
          const proposalIds = result.proposals.map(p => p.proposal_id).join(',');
          localStorage.setItem(`skill_proposal_ids:${sessionId}`, proposalIds);
        }
        setSkillProposals(result.proposals);
        setCurrentProposalIndex(0);
        // 後方互換用にも設定
        const first = result.proposals[0];
        setSkillProposal({
          proposal_id: first.proposal_id,
          skill_name: first.skill_name,
          description: first.description || '',
          site: first.site || '',
          actions: first.actions || [],
          parameters: first.parameters || [],
        });
      } else if (result.success && result.skill_name) {
        // 後方互換: 単一提案
        console.log('[SKILL_DEBUG] Success! Setting single proposal:', result.skill_name);
        if (result.proposal_id && sessionId) {
          localStorage.setItem(`skill_proposal_ids:${sessionId}`, result.proposal_id);
        }
        setSkillProposals([{
          proposal_id: result.proposal_id || '',
          skill_name: result.skill_name,
          description: result.description || '',
          site: result.site || '',
          actions: result.actions || [],
          parameters: result.parameters || [],
          decision: result.decision || 'create',
        }]);
        setSkillProposal({
          proposal_id: result.proposal_id || undefined,
          status: result.status || undefined,
          skill_name: result.skill_name,
          description: result.description || '',
          site: result.site || '',
          actions: result.actions || [],
          parameters: result.parameters || [],
          steps: result.steps || undefined,
        });
      } else {
        console.log('[SKILL_DEBUG] API returned success=false or no proposals, closing dialog');
        setShowSkillDialog(false);
        setBrowserSessionId(null);
      }
    } catch (error) {
      console.error('[SKILL_DEBUG] Exception in analyze:', error);
      toast.error('スキル分析に失敗しました。再度お試しください。');
      setShowSkillDialog(false);
      setBrowserSessionId(null);
      return;
    } finally {
      setIsAnalyzingSkill(false);
    }
  }, [sessionId]);

  // 現在表示中の提案
  const currentProposal = skillProposals[currentProposalIndex] || null;

  // スキル作成ハンドラ（現在の提案を作成して次へ）
  const handleCreateSkill = useCallback(async () => {
    if (!browserSessionId || !currentProposal) return;

    if (!currentProposal.proposal_id) {
      toast.error('Proposal ID is missing.');
      return;
    }

    setIsCreatingSkill(true);
    try {
      const result = await api.skills.generate(currentProposal.proposal_id);
      if (result.success) {
        toast.success(`Created skill ${result.skill_name}.`);

        // 次の提案があれば進む
        if (currentProposalIndex < skillProposals.length - 1) {
          setCurrentProposalIndex(prev => prev + 1);
          setIsCreatingSkill(false);
          return;
        }

        // 全て完了
        if (sessionId) {
          localStorage.removeItem(`skill_proposal_ids:${sessionId}`);
        }
      } else {
        toast.error('Skill generation failed.');
      }
    } catch (error) {
      console.error('Failed to create skill:', error);
      toast.error('Failed to create skill.');
    } finally {
      setIsCreatingSkill(false);
      // 最後の提案 or エラー時はダイアログを閉じる
      if (currentProposalIndex >= skillProposals.length - 1) {
        setShowSkillDialog(false);
        setBrowserSessionId(null);
        setSkillProposals([]);
        setSkillProposal(null);
      }
    }
  }, [browserSessionId, currentProposal, currentProposalIndex, skillProposals.length, sessionId]);

  // 現在の提案をスキップして次へ
  const handleSkipCurrentProposal = useCallback(async () => {
    if (!currentProposal) return;

    // 提案をdismiss
    try {
      await api.skills.dismissProposal(currentProposal.proposal_id);
    } catch (error) {
      console.error('Failed to dismiss proposal:', error);
    }

    // 次の提案があれば進む
    if (currentProposalIndex < skillProposals.length - 1) {
      setCurrentProposalIndex(prev => prev + 1);
      return;
    }

    // 全てスキップ完了
    if (sessionId) {
      localStorage.removeItem(`skill_proposal_ids:${sessionId}`);
    }
    setShowSkillDialog(false);
    setBrowserSessionId(null);
    setSkillProposals([]);
    setSkillProposal(null);
  }, [currentProposal, currentProposalIndex, skillProposals.length, sessionId]);

  // スキルダイアログを閉じる（全提案をスキップ）
  const handleDismissSkillDialog = useCallback(async () => {
    setShowSkillDialog(false);
    setBrowserSessionId(null);
    setSkillProposals([]);
    setSkillProposal(null);

    if (sessionId) {
      localStorage.removeItem(`skill_proposal_ids:${sessionId}`);
    }

    // 残りの全提案をdismiss
    for (let i = currentProposalIndex; i < skillProposals.length; i++) {
      const proposal = skillProposals[i];
      if (proposal?.proposal_id) {
        try {
          await api.skills.dismissProposal(proposal.proposal_id);
        } catch (error) {
          console.error('Failed to dismiss skill proposal:', error);
        }
      }
    }
  }, [sessionId, skillProposals, currentProposalIndex]);

  // 複数提案の復元
  useEffect(() => {
    if (!sessionId) return;
    const storedIds = localStorage.getItem(`skill_proposal_ids:${sessionId}`);
    if (!storedIds) return;

    let cancelled = false;
    (async () => {
      try {
        const ids = storedIds.split(',').filter(Boolean);
        const validProposals: typeof skillProposals = [];

        for (const id of ids) {
          const proposal = await api.skills.getProposal(id);
          if (cancelled) return;
          if (proposal.status === 'generated' || proposal.status === 'dismissed' || proposal.status === 'skipped') {
            continue;
          }
          validProposals.push({
            proposal_id: proposal.id,
            skill_name: proposal.skill_name || 'generated_skill',
            description: proposal.description || '',
            site: proposal.site || '',
            actions: proposal.actions || [],
            parameters: proposal.parameters || [],
            decision: 'create',
          });
        }

        if (cancelled) return;

        if (validProposals.length === 0) {
          localStorage.removeItem(`skill_proposal_ids:${sessionId}`);
          return;
        }

        setSkillProposals(validProposals);
        setCurrentProposalIndex(0);
        // 後方互換用
        setSkillProposal({
          proposal_id: validProposals[0].proposal_id,
          skill_name: validProposals[0].skill_name,
          description: validProposals[0].description,
          site: validProposals[0].site,
          actions: validProposals[0].actions,
          parameters: validProposals[0].parameters,
        });
        setShowSkillDialog(true);
      } catch (error) {
        console.error('Failed to restore skill proposals:', error);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [sessionId]);


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

  const setRevisionInputValue = useCallback((value: string) => {
    if (sessionId) setRevisionInput(sessionId, value);
  }, [sessionId, setRevisionInput]);

  const setShowRevisionInputValue = useCallback((show: boolean) => {
    if (sessionId) setShowRevisionInput(sessionId, show);
  }, [sessionId, setShowRevisionInput]);

  const clearPendingConfirmation = useCallback(() => {
    if (sessionId) setPendingConfirmation(sessionId, null);
  }, [sessionId, setPendingConfirmation]);

  // エラー状態
  if (messagesError && !isLoadingMessages) {
    return (
      <MainLayout>
        <div className="flex flex-col items-center justify-center h-full">
          <AlertCircle className="h-16 w-16 text-destructive/50 mb-4" />
          <h2 className="text-xl font-semibold mb-2">接続エラー</h2>
          <p className="text-muted-foreground mb-4 text-center max-w-md">
            サーバーとの接続に問題が発生しました。
          </p>
          <Button onClick={() => refetchMessages()} className="gap-2">
            <RefreshCw className="h-4 w-4" />
            再試行
          </Button>
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
            {isLoadingMessages ? (
              Array.from({ length: 3 }).map((_, i) => (
                <div key={i} className={cn('flex gap-3', i % 2 === 0 ? '' : 'justify-end')}>
                  {i % 2 === 0 && <Skeleton className="h-10 w-10 rounded-full" />}
                  <div className="space-y-2">
                    <Skeleton className="h-4 w-20" />
                    <Skeleton className="h-16 w-64 rounded-xl" />
                  </div>
                </div>
              ))
            ) : allMessages.length === 0 && !pendingProcess ? (
              <motion.div
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                className="text-center py-20"
              >
                <div className="w-20 h-20 mx-auto mb-6 rounded-2xl bg-primary/10 flex items-center justify-center">
                  <Bot className="h-10 w-10 text-primary" />
                </div>
                <h2 className="text-xl font-semibold mb-2">こんにちは!</h2>
                <p className="text-muted-foreground max-w-md mx-auto">
                  私はダン、あなたのAI秘書です。<br />何かお手伝いできることはありますか?
                </p>
              </motion.div>
            ) : (
              <>
                {allMessages.map((msg) => {
                  const isUser = msg.sender_type === 'human';
                  const processData = processes.get(msg.id);

                  return (
                    <div key={msg.id}>
                      {!isUser && processData && (
                        <ProcessDisplay
                          steps={processData.steps}
                          isCollapsed={processData.isCollapsed}
                          onToggle={() => handleToggleProcessCollapse(msg.id)}
                          isProcessing={processData.isProcessing}
                        />
                      )}
                      <div className={cn('flex gap-3', isUser && 'justify-end')}>
                        {!isUser && (
                          <Avatar className="h-10 w-10 shrink-0">
                            <AvatarFallback className="bg-primary/10">
                              <Bot className="h-5 w-5 text-primary" />
                            </AvatarFallback>
                          </Avatar>
                        )}
                        <div className={cn('max-w-[70%] space-y-1 flex flex-col', isUser && 'items-end')}>
                          <p className="text-xs text-muted-foreground">{isUser ? 'あなた' : 'ダン'}</p>
                          <div
                            className={cn(
                              'px-4 py-3 rounded-2xl text-sm leading-relaxed text-left',
                              isUser
                                ? 'bg-primary text-primary-foreground rounded-br-md'
                                : 'bg-muted rounded-bl-md prose prose-sm prose-dan max-w-none'
                            )}
                          >
                            {isUser ? msg.content : <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content || ''}</ReactMarkdown>}
                          </div>
                        </div>
                        {isUser && (
                          <Avatar className="h-10 w-10 shrink-0">
                            <AvatarFallback className="bg-secondary text-secondary-foreground">
                              {user?.display_name?.charAt(0) || 'U'}
                            </AvatarFallback>
                          </Avatar>
                        )}
                      </div>
                    </div>
                  );
                })}
                {pendingProcess && (
                  <ProcessDisplay
                    steps={pendingProcess.steps}
                    isCollapsed={pendingProcess.isCollapsed}
                    onToggle={() => handleToggleProcessCollapse(PENDING_PROCESS_ID)}
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
                    onChange={(e) => setRevisionInputValue(e.target.value)}
                    placeholder="修正内容を入力..."
                    rows={2}
                    className="w-full px-3 py-2 rounded-lg border border-border bg-background text-sm focus:outline-none focus:border-primary/50"
                  />
                  <div className="flex gap-2">
                    <Button size="sm" onClick={handleRevise} disabled={!revisionInput.trim() || isSending}>
                      {isSending ? <Loader2 className="h-4 w-4 animate-spin mr-1" /> : null}
                      送信
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => { setShowRevisionInputValue(false); setRevisionInputValue(''); }}>
                      キャンセル
                    </Button>
                  </div>
                </div>
              ) : (
                <div className="flex gap-2">
                  <Button size="sm" onClick={handleConfirm} disabled={isSending} className="bg-primary hover:bg-primary/90">
                    {isSending ? <Loader2 className="h-4 w-4 animate-spin mr-1" /> : <Check className="h-4 w-4 mr-1" />}
                    これで進める
                  </Button>
                  <Button size="sm" variant="outline" onClick={() => setShowRevisionInputValue(true)}>
                    修正する
                  </Button>
                  <Button size="sm" variant="ghost" onClick={clearPendingConfirmation}>
                    キャンセル
                  </Button>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Skill Creation Dialog (カルーセル対応) */}
        {showSkillDialog && (
          <div className="shrink-0 border-t border-border bg-primary/5 px-4 py-3">
            <div className="max-w-3xl mx-auto">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Sparkles className="h-4 w-4 text-primary" />
                  <span className="text-sm font-medium">
                    {isAnalyzingSkill ? '操作を分析中...' : (
                      skillProposals.length > 1
                        ? `スキル提案 (${currentProposalIndex + 1}/${skillProposals.length})`
                        : 'スキルを作成できます'
                    )}
                  </span>
                </div>
                <Button
                  size="icon"
                  variant="ghost"
                  className="h-6 w-6"
                  onClick={handleDismissSkillDialog}
                  disabled={isAnalyzingSkill || isCreatingSkill}
                >
                  <X className="h-4 w-4" />
                </Button>
              </div>

              {isAnalyzingSkill ? (
                <div className="flex items-center gap-2 mt-2 text-xs text-muted-foreground">
                  <Loader2 className="h-3 w-3 animate-spin" />
                  <span>どんなスキルを作れるか確認しています...</span>
                </div>
              ) : currentProposal ? (
                <>
                  <div className="mt-2 p-2 rounded bg-background/50 border border-border/50">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-sm font-medium text-primary">{currentProposal.skill_name}</span>
                      {currentProposal.site && (
                        <span className="text-xs text-muted-foreground">({currentProposal.site})</span>
                      )}
                      {currentProposal.decision === 'extend' && (
                        <span className="text-xs bg-yellow-100 text-yellow-800 px-1 rounded">拡張</span>
                      )}
                    </div>
                    <p className="text-xs text-muted-foreground">{currentProposal.description}</p>
                    {currentProposal.parameters.length > 0 && (
                      <div className="mt-1 text-xs text-muted-foreground">
                        パラメータ: {currentProposal.parameters.map(p => p.name).join(', ')}
                      </div>
                    )}
                  </div>
                  <div className="flex gap-2 mt-3">
                    <Button
                      size="sm"
                      onClick={handleCreateSkill}
                      disabled={isCreatingSkill}
                      className="bg-primary hover:bg-primary/90"
                    >
                      {isCreatingSkill ? (
                        <Loader2 className="h-4 w-4 animate-spin mr-1" />
                      ) : (
                        <Sparkles className="h-4 w-4 mr-1" />
                      )}
                      {isCreatingSkill ? '作成中...' : (
                        currentProposal.decision === 'extend' ? 'アクションを追加' : 'このスキルを作成'
                      )}
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={handleSkipCurrentProposal}
                      disabled={isCreatingSkill}
                    >
                      {skillProposals.length > 1 && currentProposalIndex < skillProposals.length - 1
                        ? 'スキップして次へ'
                        : 'スキップ'}
                    </Button>
                    {skillProposals.length > 1 && (
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={handleDismissSkillDialog}
                        disabled={isCreatingSkill}
                      >
                        全てスキップ
                      </Button>
                    )}
                  </div>
                </>
              ) : null}
            </div>
          </div>
        )}

        {/* Gemini voice observer banner */}
        {observer.state === 'connected' && (
          <div className="shrink-0 px-4 py-2 bg-green-50 dark:bg-green-950/30 border-t border-green-200 dark:border-green-800">
            <div className="max-w-3xl mx-auto flex items-center gap-2 text-xs">
              <div className="h-2 w-2 rounded-full bg-green-500 animate-pulse" />
              <span className="text-green-700 dark:text-green-300 font-medium">音声セッション接続中</span>
              <button
                onClick={observer.disconnect}
                className="text-green-600 dark:text-green-400 hover:text-green-800 dark:hover:text-green-200 ml-auto"
              >
                切断
              </button>
            </div>
          </div>
        )}

        {/* Voice listening indicator */}
        {voice.isActive && (voice.isListening || voice.isSpeaking) && (
          <div className="shrink-0 px-4 py-2 bg-muted/30 border-t border-border">
            <div className="max-w-3xl mx-auto flex items-center gap-2 text-xs text-muted-foreground">
              {voice.isSpeaking ? (
                <>
                  <div className="h-2 w-2 rounded-full bg-blue-500 animate-pulse" />
                  <span>ダンが話しています...</span>
                  <Button size="sm" variant="ghost" className="h-6 px-2 ml-auto text-xs" onClick={voice.skipSpeaking}>
                    <SkipForward className="h-3 w-3 mr-1" />
                    スキップ
                  </Button>
                </>
              ) : voice.isListening ? (
                <>
                  <div className="h-2 w-2 rounded-full bg-red-500 animate-pulse" />
                  <span>{voice.interimTranscript || '聞いています...'}</span>
                </>
              ) : null}
            </div>
          </div>
        )}

        {/* Input Area */}
        <div className="shrink-0 border-t border-border p-4">
          <div className="max-w-3xl mx-auto">
            <div className="flex items-end gap-2 p-2 rounded-2xl border border-border bg-input/30 focus-within:border-primary/50 transition-colors">
              <Button variant="ghost" size="icon" className="h-9 w-9 shrink-0 text-muted-foreground hover:text-foreground">
                <Paperclip className="h-4 w-4" />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                className={cn(
                  'h-9 w-9 shrink-0 transition-colors',
                  voice.isActive
                    ? 'text-red-500 hover:text-red-600 bg-red-50 hover:bg-red-100'
                    : 'text-muted-foreground hover:text-foreground'
                )}
                onClick={voice.toggleVoice}
                title={voice.isActive ? '音声モード OFF' : '音声モード ON'}
              >
                {voice.isActive ? <MicOff className="h-4 w-4" /> : <Mic className="h-4 w-4" />}
              </Button>
              <textarea
                ref={textareaRef}
                value={voice.isActive && voice.interimTranscript ? voice.interimTranscript : message}
                onChange={(e) => setMessage(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder={voice.isActive ? '音声入力中...' : 'メッセージを入力...'}
                rows={1}
                readOnly={voice.isActive}
                className={cn(
                  'flex-1 resize-none bg-transparent text-sm focus:outline-none min-h-[36px] max-h-[200px] py-2',
                  voice.isActive && 'text-muted-foreground'
                )}
              />
              {isSending ? (
                <Button size="icon" variant="destructive" className="h-9 w-9 shrink-0" onClick={handleCancel} title="停止 (Escキー)">
                  <Square className="h-4 w-4" />
                </Button>
              ) : voice.isSpeaking ? (
                <Button size="icon" variant="outline" className="h-9 w-9 shrink-0" onClick={voice.skipSpeaking} title="スキップ">
                  <SkipForward className="h-4 w-4" />
                </Button>
              ) : (
                <Button size="icon" className="h-9 w-9 shrink-0" onClick={() => handleSendMessage()} disabled={!message.trim() && !voice.isActive}>
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
