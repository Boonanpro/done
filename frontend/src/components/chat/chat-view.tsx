'use client';

import { useState, useRef, useEffect, useCallback, useMemo } from 'react';
import { useSearchParams } from 'next/navigation';
import { motion } from 'framer-motion';
import { Send, Paperclip, Loader2, Bot, AlertCircle, RefreshCw, Check, ChevronDown, ChevronUp, Square, Sparkles, X, Mic, MicOff, SkipForward, File } from 'lucide-react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';

import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

import { Button } from '@/components/ui/button';
import { Avatar, AvatarFallback } from '@/components/ui/avatar';
import { Skeleton } from '@/components/ui/skeleton';
import { api, type MessageResponse, type ProcessStep, type FileUploadResponse } from '@/lib/api-client';
import { useAuthStore } from '@/stores/auth-store';
import { useSessionStateStore, PENDING_PROCESS_ID } from '@/stores/session-state-store';
import { cn } from '@/lib/utils';
import { useVoiceChat } from '@/hooks/useVoiceChat';
import { useGeminiObserver } from '@/hooks/useGeminiObserver';
import { useProjectStore } from '@/stores/project-store';
import { useSessionRecovery } from '@/hooks/useSessionRecovery';

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
    <div className="flex gap-3 mb-3">
      <div className="flex-1 space-y-1">
        <p className="text-xs text-muted-foreground">ダン</p>
        <div className="px-4 py-3 rounded-2xl rounded-bl-md bg-muted/50 border border-border">
          <button
            onClick={onToggle}
            className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors w-full mb-2"
          >
            {isCollapsed ? <ChevronDown className="h-3 w-3" /> : <ChevronUp className="h-3 w-3" />}
            <span className="font-medium">実行中のプロセス</span>
          </button>
          {!isCollapsed && (
            <div className="pl-2 border-l-2 border-primary/30 space-y-2">
              {isProcessing && !hasSteps && (
                <motion.div
                  initial={{ opacity: 0, x: -10 }}
                  animate={{ opacity: 1, x: 0 }}
                  className="flex items-center gap-2 text-xs"
                >
                  <Loader2 className="h-3 w-3 text-primary animate-spin" />
                  <span className="text-foreground">考え中...</span>
                </motion.div>
              )}
              {steps.map((step, index) => {
                const isLatest = index === steps.length - 1;
                const shouldSpin = isLatest && isProcessing;
                return (
                  <motion.div
                    key={step.id}
                    initial={{ opacity: 0, x: -10 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ duration: 0.2 }}
                    className="flex items-center gap-2 text-xs"
                  >
                    {shouldSpin ? (
                      <Loader2 className="h-3 w-3 text-primary animate-spin" />
                    ) : (
                      <Check className="h-3 w-3 text-green-500" />
                    )}
                    <span className={cn(
                      shouldSpin ? "text-foreground font-medium" : "text-muted-foreground"
                    )}>{step.label}</span>
                  </motion.div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

interface ChatViewProps {
  sessionId: string;
  autoVoice?: boolean;
}

export function ChatView({ sessionId, autoVoice = false }: ChatViewProps) {
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();

  const user = useAuthStore((state) => state.user);
  const selectProject = useProjectStore((s) => s.selectProject);
  const [message, setMessage] = useState('');

  // スキル化ダイアログ用の状態（複数提案対応）
  const [showSkillDialog, setShowSkillDialog] = useState(false);
  const [browserSessionId, setBrowserSessionId] = useState<string | null>(null);
  const [isAnalyzingSkill, setIsAnalyzingSkill] = useState(false);
  const [isCreatingSkill, setIsCreatingSkill] = useState(false);
  
  // ファイル添付の状態
  const [attachedFiles, setAttachedFiles] = useState<FileUploadResponse[]>([]);
  const [isUploading, setIsUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
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
  const [currentProposalIndex, setCurrentProposalIndex] = useState(0);

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
  const markAsRead = useSessionStateStore((state) => state.markAsRead);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const refetchMessagesRef = useRef<(() => void) | null>(null);
  const initialLoadRef = useRef(true);

  // Voice chat integration
  const voiceSendRef = useRef<((text: string) => void) | null>(null);
  const voice = useVoiceChat({
    onFinalTranscript: (text: string) => {
      voiceSendRef.current?.(text);
    },
  });

  // AbortController for SSE cancellation
  const abortControllerRef = useRef<AbortController | null>(null);

  // Ref for skill proposal callback
  const handleShowSkillProposalRef = useRef<((sessId: string) => void) | null>(null);

  // Voice observer
  const [voiceMessages, setVoiceMessages] = useState<MessageResponse[]>([]);
  const voiceUserTextBufRef = useRef('');
  const voiceAssistantTextBufRef = useRef('');
  const voiceContentToProcessIdRef = useRef<Map<string, string>>(new Map());

  // Process step staggered queue
  const stepQueueRef = useRef<ProcessStep[]>([]);
  const stepDrainTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const flushVoiceUserTextBuffer = useCallback(() => {
    if (voiceUserTextBufRef.current) {
      const content = voiceUserTextBufRef.current;
      voiceUserTextBufRef.current = '';
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
    mode: 'observer',
    autoConnect: true,
    onUserText: useCallback((text: string) => {
      voiceUserTextBufRef.current += text;
    }, []),
    onAssistantText: useCallback((text: string) => {
      flushVoiceUserTextBuffer();
      voiceAssistantTextBufRef.current += text;
    }, [flushVoiceUserTextBuffer]),
    onToolStart: useCallback((tool: string) => {
      flushVoiceUserTextBuffer();
      if (sessionId) {
        const existing = getSessionState(sessionId).processes.get(PENDING_PROCESS_ID);
        if (!existing || !existing.isProcessing) {
          setProcess(sessionId, PENDING_PROCESS_ID, { steps: [], isCollapsed: false, isProcessing: true });
        }
        addProcessStep(sessionId, PENDING_PROCESS_ID, {
          id: `voice-tool-${tool}-${Date.now()}`,
          label: `${tool}`,
          status: 'running',
        });
      }
    }, [sessionId, flushVoiceUserTextBuffer, getSessionState, setProcess, addProcessStep]),
    onProcessStep: useCallback((stepLabel: string) => {
      if (sessionId) {
        const existing = getSessionState(sessionId).processes.get(PENDING_PROCESS_ID);
        if (!existing || !existing.isProcessing) {
          setProcess(sessionId, PENDING_PROCESS_ID, { steps: [], isCollapsed: false, isProcessing: true });
        }
        addProcessStep(sessionId, PENDING_PROCESS_ID, {
          id: `voice-step-${Date.now()}`,
          label: stepLabel,
          status: 'running',
        });
      }
    }, [sessionId, getSessionState, setProcess, addProcessStep]),
    onToolResult: useCallback((tool: string, success: boolean) => {
      if (sessionId) {
        addProcessStep(sessionId, PENDING_PROCESS_ID, {
          id: `voice-result-${tool}-${Date.now()}`,
          label: success ? `${tool} 完了` : `${tool} 失敗`,
          status: success ? 'completed' : 'error',
        });
      }
    }, [sessionId, addProcessStep]),
    onTurnComplete: useCallback(() => {
      flushVoiceUserTextBuffer();

      const voiceMessageId = `voice-assistant-${Date.now()}`;

      if (sessionId) {
        const pending = getSessionState(sessionId).processes.get(PENDING_PROCESS_ID);
        if (pending && pending.steps.length > 0) {
          setProcess(sessionId, voiceMessageId, {
            steps: pending.steps,
            isCollapsed: true,
            isProcessing: false,
          });
        }
        deleteProcess(sessionId, PENDING_PROCESS_ID);
      }

      if (voiceAssistantTextBufRef.current) {
        const content = voiceAssistantTextBufRef.current;
        voiceAssistantTextBufRef.current = '';
        voiceContentToProcessIdRef.current.set(content.trim(), voiceMessageId);
        setVoiceMessages(prev => [...prev, {
          id: voiceMessageId,
          room_id: sessionId,
          sender_id: 'dan',
          sender_name: 'ダン',
          sender_type: 'ai' as MessageResponse['sender_type'],
          content,
          created_at: new Date().toISOString(),
        }]);
      }
    }, [sessionId, flushVoiceUserTextBuffer, getSessionState, setProcess, deleteProcess]),
  });

  // Auto-activate voice mode from ?voice=true query param or autoVoice prop
  useEffect(() => {
    if ((searchParams.get('voice') === 'true' || autoVoice) && !voice.isActive) {
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

  // メッセージ取得
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
    refetchInterval: 3000,
    retry: 2,
  });

  useEffect(() => { refetchMessagesRef.current = refetchMessages; }, [refetchMessages]);

  // セッション復帰フック: タブ復帰時やページ読み込み時にバックエンド処理中を検知
  useSessionRecovery({
    sessionId: sessionId || null,
    refetchMessages: () => refetchMessagesRef.current?.(),
  });

  const messages = messagesData?.messages || [];

  // 初回ロード完了後にフラグを切り替え（Framer Motionアニメーション制御用）
  useEffect(() => {
    if (messages.length > 0 && initialLoadRef.current) {
      // 次のレンダーサイクルでフラグを落とす
      requestAnimationFrame(() => { initialLoadRef.current = false; });
    }
  }, [messages]);

  // DB messages + voice messages → oldest-first for display
  const allMessages = useMemo(() => {
    const dbMsgs = [...messages].reverse();
    const dbContentSet = new Set(
      dbMsgs.map(m => `${m.sender_type}:${m.content.trim()}`)
    );
    const pendingVoice = voiceMessages.filter(vm =>
      !dbContentSet.has(`${vm.sender_type}:${vm.content.trim()}`)
    );
    const combined = [...dbMsgs, ...pendingVoice];
    const seen = new Set<string>();
    return combined.filter(m => {
      if (seen.has(m.id)) return false;
      seen.add(m.id);
      return true;
    });
  }, [messages, voiceMessages]);

  // DBメッセージのreasoning_stepsをprocessesに初期化
  useEffect(() => {
    if (!messages.length || !sessionId) return;
    initializeProcessesFromMessages(sessionId, messages);
  }, [messages, sessionId, initializeProcessesFromMessages]);

  // Voice process migration
  useEffect(() => {
    if (!messages.length || !sessionId) return;
    const map = voiceContentToProcessIdRef.current;
    if (map.size === 0) return;

    for (const msg of messages) {
      if (msg.sender_type !== 'ai') continue;
      const content = (msg.content || '').trim();
      const voiceId = map.get(content);
      if (!voiceId) continue;

      const processData = getSessionState(sessionId).processes.get(voiceId);
      if (processData) {
        setProcess(sessionId, msg.id, processData);
        deleteProcess(sessionId, voiceId);
      }
      map.delete(content);
    }
  }, [messages, sessionId, getSessionState, setProcess, deleteProcess]);

  // Flush step queue
  const flushStepQueue = useCallback(() => {
    if (stepDrainTimerRef.current) {
      clearTimeout(stepDrainTimerRef.current);
      stepDrainTimerRef.current = null;
    }
    if (!sessionId) return;
    const queue = stepQueueRef.current;
    while (queue.length > 0) {
      addProcessStep(sessionId, PENDING_PROCESS_ID, queue.shift()!);
    }
  }, [sessionId, addProcessStep]);

  // Queue process step with delay
  const queueProcessStep = useCallback((step: ProcessStep) => {
    if (!sessionId) return;
    const existing = getSessionState(sessionId).processes.get(PENDING_PROCESS_ID);
    if (!existing || !existing.isProcessing) {
      setProcess(sessionId, PENDING_PROCESS_ID, { steps: [], isCollapsed: false, isProcessing: true });
    }

    stepQueueRef.current.push(step);

    if (stepDrainTimerRef.current) return;

    const currentProcess = getSessionState(sessionId).processes.get(PENDING_PROCESS_ID);
    const hasVisibleSteps = (currentProcess?.steps.length ?? 0) > 0;

    const drain = () => {
      if (!sessionId || stepQueueRef.current.length === 0) {
        stepDrainTimerRef.current = null;
        return;
      }
      addProcessStep(sessionId, PENDING_PROCESS_ID, stepQueueRef.current.shift()!);
      if (stepQueueRef.current.length > 0) {
        stepDrainTimerRef.current = setTimeout(drain, 200);
      } else {
        stepDrainTimerRef.current = null;
      }
    };

    if (!hasVisibleSteps) {
      drain();
    } else {
      stepDrainTimerRef.current = setTimeout(drain, 200);
    }
  }, [sessionId, getSessionState, setProcess, addProcessStep]);

  // Clean up drain timer
  useEffect(() => {
    return () => {
      if (stepDrainTimerRef.current) {
        clearTimeout(stepDrainTimerRef.current);
        stepDrainTimerRef.current = null;
      }
    };
  }, [sessionId]);

  // メッセージ送信
  const handleSendMessage = useCallback(async (textOverride?: string) => {
    const text = textOverride || message;
    if (!text.trim() && attachedFiles.length === 0) return;
    if (isSending || !sessionId) return;

    // ファイル付きメッセージの場合はファイル情報を含める
    let content = text.trim();
    if (attachedFiles.length > 0) {
      const fileList = attachedFiles.map(f => `[ファイル] ${f.filename} (${f.url})`).join('\n');
      content = content ? `${content}\n\n${fileList}` : fileList;
    }

    setMessage('');
    setAttachedFiles([]); // 送信後に添付ファイルをクリア
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

    const controller = new AbortController();
    abortControllerRef.current = controller;

    try {
      await api.sm.sendMessageStream(
        { message: content, session_id: sessionId },
        {
          onProcessStep: (step) => {
            queueProcessStep(step);
          },
          onUserMessage: (msg) => {
            queryClient.setQueryData(['messages', sessionId], (old: typeof messagesData) => ({
              messages: [msg, ...(old?.messages || []).filter((m: MessageResponse) => m.id !== tempUserMessageId)],
            }));
          },
          onAIMessage: (msg) => {
            flushStepQueue();
            if (sessionId) {
              const pending = getSessionState(sessionId).processes.get(PENDING_PROCESS_ID);
              if (pending && pending.steps.length > 0) {
                setProcess(sessionId, msg.id, {
                  steps: pending.steps,
                  isCollapsed: true,
                  isProcessing: false,
                });
              }
              deleteProcess(sessionId, PENDING_PROCESS_ID);
            }

            queryClient.setQueryData(['messages', sessionId], (old: typeof messagesData) => {
              const existing = old?.messages || [];
              if (existing.some((m: MessageResponse) => m.id === msg.id)) return { messages: existing };
              return { messages: [msg, ...existing] };
            });

            if (voice.isActive && msg.content) {
              voice.speakResponse(msg.content);
            }

            if (msg.ai_context && 'needs_confirmation' in (msg.ai_context as Record<string, unknown>) && (msg.ai_context as Record<string, unknown>).needs_confirmation) {
              setPendingConfirmation(sessionId, {
                session_id: sessionId,
                state: 'confirm' as const,
                response: msg.content,
                reasoning_steps: [],
                needs_confirmation: true,
                is_chat: false,
                proposal: null,
                error: null,
              });
            }
          },
          onComplete: () => {
            flushStepQueue();
            if (sessionId) {
              deleteProcess(sessionId, PENDING_PROCESS_ID);
              setIsSending(sessionId, false);
            }
            refetchMessagesRef.current?.();
          },
          onError: (error) => {
            flushStepQueue();
            if (sessionId) {
              deleteProcess(sessionId, PENDING_PROCESS_ID);
              setIsSending(sessionId, false);
            }
            toast.error(error || 'エラーが発生しました');
          },
          onSkillAvailable: (browserSessId) => {
            handleShowSkillProposalRef.current?.(browserSessId);
          },
          onProjectCreated: (projectId) => {
            queryClient.invalidateQueries({ queryKey: ['projects'] });
            selectProject(projectId);
          },
        },
        controller.signal
      );
    } catch (error) {
      if (sessionId) {
        deleteProcess(sessionId, PENDING_PROCESS_ID);
        setIsSending(sessionId, false);
      }
      if (error instanceof Error && error.name !== 'AbortError') {
        toast.error('メッセージの送信に失敗しました');
      }
    }
  }, [message, isSending, sessionId, queryClient, messagesData, user?.id, user?.display_name, setIsSending, setProcess, getSessionState, addProcessStep, deleteProcess, setPendingConfirmation, voice, queueProcessStep, flushStepQueue, selectProject]);

  // Voice send ref
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

    const controller = new AbortController();
    abortControllerRef.current = controller;

    try {
      await api.sm.sendMessageStream(
        { message: confirmMessage, session_id: sessionId },
        {
          onProcessStep: (step) => {
            queueProcessStep(step);
          },
          onUserMessage: (msg) => {
            queryClient.setQueryData(['messages', sessionId], (old: typeof messagesData) => ({
              messages: [msg, ...(old?.messages || []).filter((m: MessageResponse) => m.id !== tempUserMessageId)],
            }));
          },
          onAIMessage: (msg) => {
            flushStepQueue();
            if (sessionId) {
              const pending = getSessionState(sessionId).processes.get(PENDING_PROCESS_ID);
              if (pending && pending.steps.length > 0) {
                setProcess(sessionId, msg.id, {
                  steps: pending.steps,
                  isCollapsed: true,
                  isProcessing: false,
                });
              }
              deleteProcess(sessionId, PENDING_PROCESS_ID);
            }
            queryClient.setQueryData(['messages', sessionId], (old: typeof messagesData) => {
              const existing = old?.messages || [];
              if (existing.some((m: MessageResponse) => m.id === msg.id)) return { messages: existing };
              return { messages: [msg, ...existing] };
            });
            if (voice.isActive && msg.content) {
              voice.speakResponse(msg.content);
            }
          },
          onComplete: () => {
            flushStepQueue();
            if (sessionId) {
              deleteProcess(sessionId, PENDING_PROCESS_ID);
              setIsSending(sessionId, false);
            }
            refetchMessagesRef.current?.();
          },
          onError: (error) => {
            flushStepQueue();
            if (sessionId) {
              deleteProcess(sessionId, PENDING_PROCESS_ID);
              setIsSending(sessionId, false);
            }
            toast.error(error || 'エラーが発生しました');
          },
          onSkillAvailable: (browserSessId) => {
            handleShowSkillProposalRef.current?.(browserSessId);
          },
          onProjectCreated: (projectId) => {
            queryClient.invalidateQueries({ queryKey: ['projects'] });
            selectProject(projectId);
          },
        },
        controller.signal
      );
    } catch (error) {
      if (sessionId) {
        deleteProcess(sessionId, PENDING_PROCESS_ID);
        setIsSending(sessionId, false);
      }
    }
  }, [pendingConfirmation, sessionId, queryClient, messagesData, user?.id, user?.display_name, setPendingConfirmation, setIsSending, setProcess, getSessionState, addProcessStep, deleteProcess, voice, queueProcessStep, flushStepQueue, selectProject]);

  // 提案を修正
  const handleRevise = useCallback(async () => {
    if (!revisionInput.trim() || !sessionId) return;

    const revisionMessage = revisionInput.trim();
    setPendingConfirmation(sessionId, null);
    setRevisionInput(sessionId, '');
    setShowRevisionInput(sessionId, false);

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

    const controller = new AbortController();
    abortControllerRef.current = controller;

    try {
      await api.sm.sendMessageStream(
        { message: revisionMessage, session_id: sessionId },
        {
          onProcessStep: (step) => {
            queueProcessStep(step);
          },
          onUserMessage: (msg) => {
            queryClient.setQueryData(['messages', sessionId], (old: typeof messagesData) => ({
              messages: [msg, ...(old?.messages || []).filter((m: MessageResponse) => m.id !== tempUserMessageId)],
            }));
          },
          onAIMessage: (msg) => {
            flushStepQueue();
            if (sessionId) {
              const pending = getSessionState(sessionId).processes.get(PENDING_PROCESS_ID);
              if (pending && pending.steps.length > 0) {
                setProcess(sessionId, msg.id, {
                  steps: pending.steps,
                  isCollapsed: true,
                  isProcessing: false,
                });
              }
              deleteProcess(sessionId, PENDING_PROCESS_ID);
            }
            queryClient.setQueryData(['messages', sessionId], (old: typeof messagesData) => {
              const existing = old?.messages || [];
              if (existing.some((m: MessageResponse) => m.id === msg.id)) return { messages: existing };
              return { messages: [msg, ...existing] };
            });
            if (voice.isActive && msg.content) {
              voice.speakResponse(msg.content);
            }
          },
          onComplete: () => {
            flushStepQueue();
            if (sessionId) {
              deleteProcess(sessionId, PENDING_PROCESS_ID);
              setIsSending(sessionId, false);
            }
            refetchMessagesRef.current?.();
          },
          onError: (error) => {
            flushStepQueue();
            if (sessionId) {
              deleteProcess(sessionId, PENDING_PROCESS_ID);
              setIsSending(sessionId, false);
            }
            toast.error(error || 'エラーが発生しました');
          },
          onSkillAvailable: (browserSessId) => {
            handleShowSkillProposalRef.current?.(browserSessId);
          },
          onProjectCreated: (projectId) => {
            queryClient.invalidateQueries({ queryKey: ['projects'] });
            selectProject(projectId);
          },
        },
        controller.signal
      );
    } catch (error) {
      if (sessionId) {
        deleteProcess(sessionId, PENDING_PROCESS_ID);
        setIsSending(sessionId, false);
      }
    }
  }, [revisionInput, sessionId, queryClient, messagesData, user?.id, user?.display_name, setPendingConfirmation, setRevisionInput, setShowRevisionInput, setIsSending, setProcess, getSessionState, addProcessStep, deleteProcess, voice, queueProcessStep, flushStepQueue, selectProject]);

  const pendingProcess = processes.get(PENDING_PROCESS_ID);

  // スクロール（即座に最下部へジャンプ、DOM描画完了後に実行）
  const pendingStepCount = pendingProcess?.steps?.length ?? 0;
  useEffect(() => {
    const el = scrollContainerRef.current;
    if (!el) return;
    // 2フレーム待ってからスクロール（ReactMarkdown等のレイアウト完了を保証）
    const raf1 = requestAnimationFrame(() => {
      const raf2 = requestAnimationFrame(() => {
        el.scrollTop = el.scrollHeight;
      });
      return () => cancelAnimationFrame(raf2);
    });
    return () => cancelAnimationFrame(raf1);
  }, [messages, pendingStepCount]);

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

  const handleCancel = useCallback(async () => {
    if (!sessionId) return;

    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }

    try {
      await api.sm.cancelSession(sessionId);
    } catch (e) {
      console.error('Failed to cancel session:', e);
    }

    setIsSending(sessionId, false);
    deleteProcess(sessionId, PENDING_PROCESS_ID);
    toast.info('処理を停止しました');
  }, [sessionId, setIsSending, deleteProcess]);

  // ファイル添付の処理
  const handleFileSelect = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files || files.length === 0) return;

    setIsUploading(true);
    try {
      const uploadedFiles: FileUploadResponse[] = [];
      for (const file of Array.from(files)) {
        // ファイルサイズ制限 (10MB)
        if (file.size > 10 * 1024 * 1024) {
          toast.error(`${file.name} は10MB以上のファイルは添付できません`);
          continue;
        }
        const uploaded = await api.files.upload(file);
        uploadedFiles.push(uploaded);
      }
      setAttachedFiles(prev => [...prev, ...uploadedFiles]);
      toast.success(`${uploadedFiles.length}件のファイルを添付しました`);
    } catch (error) {
      console.error('File upload failed:', error);
      toast.error('ファイルのアップロードに失敗しました');
    } finally {
      setIsUploading(false);
      // 同じファイルを選択できるように入力をリセット
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
    }
  }, []);

  const handleRemoveFile = useCallback((fileId: string) => {
    setAttachedFiles(prev => prev.filter(f => f.id !== fileId));
  }, []);

  const handleClickAttach = useCallback(() => {
    fileInputRef.current?.click();
  }, []);

  // スキル提案を表示（複数提案対応）
  const handleShowSkillProposal = useCallback(async (sessId: string) => {
    setBrowserSessionId(sessId);
    setIsAnalyzingSkill(true);
    setShowSkillDialog(true);
    setSkillProposals([]);
    setCurrentProposalIndex(0);

    try {
      const result = await api.skills.analyze(sessId);

      if (result.decision === 'skip') {
        setShowSkillDialog(false);
        setBrowserSessionId(null);
        return;
      }

      if (result.success && result.proposals && result.proposals.length > 0) {
        if (sessionId) {
          const proposalIds = result.proposals.map(p => p.proposal_id).join(',');
          localStorage.setItem(`skill_proposal_ids:${sessionId}`, proposalIds);
        }
        setSkillProposals(result.proposals);
        setCurrentProposalIndex(0);
      } else if (result.success && result.skill_name) {
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
      } else {
        setShowSkillDialog(false);
        setBrowserSessionId(null);
      }
    } catch (error) {
      console.error('Exception in skill analyze:', error);
      toast.error('スキル分析に失敗しました。再度お試しください。');
      setShowSkillDialog(false);
      setBrowserSessionId(null);
      return;
    } finally {
      setIsAnalyzingSkill(false);
    }
  }, [sessionId]);

  useEffect(() => { handleShowSkillProposalRef.current = handleShowSkillProposal; }, [handleShowSkillProposal]);

  const currentProposal = skillProposals[currentProposalIndex] || null;

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
        if (currentProposalIndex < skillProposals.length - 1) {
          setCurrentProposalIndex(prev => prev + 1);
          setIsCreatingSkill(false);
          return;
        }
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
      if (currentProposalIndex >= skillProposals.length - 1) {
        setShowSkillDialog(false);
        setBrowserSessionId(null);
        setSkillProposals([]);
      }
    }
  }, [browserSessionId, currentProposal, currentProposalIndex, skillProposals.length, sessionId]);

  const handleSkipCurrentProposal = useCallback(async () => {
    if (!currentProposal) return;
    try {
      await api.skills.dismissProposal(currentProposal.proposal_id);
    } catch (error) {
      console.error('Failed to dismiss proposal:', error);
    }

    if (currentProposalIndex < skillProposals.length - 1) {
      setCurrentProposalIndex(prev => prev + 1);
      return;
    }

    if (sessionId) {
      localStorage.removeItem(`skill_proposal_ids:${sessionId}`);
    }
    setShowSkillDialog(false);
    setBrowserSessionId(null);
    setSkillProposals([]);
  }, [currentProposal, currentProposalIndex, skillProposals.length, sessionId]);

  const handleDismissSkillDialog = useCallback(async () => {
    setShowSkillDialog(false);
    setBrowserSessionId(null);
    setSkillProposals([]);

    if (sessionId) {
      localStorage.removeItem(`skill_proposal_ids:${sessionId}`);
    }

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
        setShowSkillDialog(true);
      } catch (error) {
        console.error('Failed to restore skill proposals:', error);
      }
    })();
    return () => { cancelled = true; };
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
    );
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Header */}
      <div className="shrink-0 flex items-center gap-3 pl-12 pr-3 md:px-6 py-4 border-b border-border">
        <div>
          <h1 className="font-semibold">ダン</h1>
          <p className="text-xs text-muted-foreground">AI秘書</p>
        </div>
      </div>

      {/* Messages Area */}
      <div ref={scrollContainerRef} className="flex-1 min-h-0 overflow-y-auto px-3 md:px-6">
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
                    {!isUser && processData && processData.steps.length > 0 && (
                      <ProcessDisplay
                        steps={processData.steps}
                        isCollapsed={processData.isCollapsed}
                        onToggle={() => handleToggleProcessCollapse(msg.id)}
                        isProcessing={processData.isProcessing}
                      />
                    )}
                    {(isUser || !processData || !processData.isProcessing) && (
                      <motion.div
                        initial={initialLoadRef.current ? false : { opacity: 0, y: 10 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={initialLoadRef.current ? { duration: 0 } : { duration: 0.3 }}
                        className={cn('flex gap-3', isUser && 'justify-end')}
                      >
                        <div className={cn(
                          'space-y-1 flex flex-col',
                          isUser ? 'max-w-[85%] md:max-w-[70%] items-end' : 'w-full'
                        )}>
                          <div
                            className={cn(
                              'px-4 py-3 rounded-2xl text-sm leading-relaxed text-left',
                              isUser
                                ? 'bg-primary text-primary-foreground rounded-br-md w-full'
                                : 'bg-transparent rounded-bl-md prose prose-sm prose-dan max-w-full'
                            )}
                          >
                            {isUser ? msg.content : <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content || ''}</ReactMarkdown>}
                          </div>
                        </div>
                      </motion.div>
                    )}
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

      {/* Skill Creation Dialog */}
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
      <div className="shrink-0 border-t border-border p-2 md:p-4">
        <div className="max-w-3xl mx-auto">
          {/* 添付ファイル一覧 */}
          {attachedFiles.length > 0 && (
            <div className="mb-2 flex flex-wrap gap-2">
              {attachedFiles.map((file) => (
                <div
                  key={file.id}
                  className="flex items-center gap-1.5 px-2 py-1 rounded-md bg-muted border border-border text-xs"
                >
                  <File className="h-3 w-3 text-muted-foreground" />
                  <span className="max-w-[150px] truncate">{file.filename}</span>
                  <button
                    onClick={() => handleRemoveFile(file.id)}
                    className="ml-1 hover:text-destructive"
                  >
                    <X className="h-3 w-3" />
                  </button>
                </div>
              ))}
            </div>
          )}
          
          <div className="flex items-end gap-2 p-2 rounded-2xl border border-border bg-input/30 focus-within:border-primary/50 transition-colors">
            <input
              ref={fileInputRef}
              type="file"
              multiple
              className="hidden"
              onChange={handleFileSelect}
              accept="image/*,.pdf,.txt,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.zip,.rar,.7z,.tar,.gz,.mp3,.wav,.ogg,.m4a,.flac,.mp4,.avi,.mov,.mkv,.webm"
            />
            <Button 
              variant="ghost" 
              size="icon" 
              className="h-9 w-9 shrink-0 text-muted-foreground hover:text-foreground"
              onClick={handleClickAttach}
              disabled={isUploading}
              title="ファイルを添付"
            >
              {isUploading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Paperclip className="h-4 w-4" />}
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
              <Button size="icon" className="h-9 w-9 shrink-0" onClick={() => handleSendMessage()} disabled={!message.trim() && attachedFiles.length === 0}>
                <Send className="h-4 w-4" />
              </Button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
