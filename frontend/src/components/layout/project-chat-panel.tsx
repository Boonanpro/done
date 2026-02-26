'use client';

import { useState, useRef, useEffect, useCallback, useMemo, memo } from 'react';
import { X, FolderKanban, Loader2, MessageSquare, Send, Square, CheckCircle2, XCircle, ChevronDown, ChevronRight, Check, FileText, Terminal, Brain, AlertCircle } from 'lucide-react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

import { Button } from '@/components/ui/button';
import { api, type MessageResponse, type ProjectStatusType, type ProjectProposalResponse, type ProcessStep, type ExecutionEvent } from '@/lib/api-client';
import { useProjectStore, useProcessState, useProcessActions } from '@/stores/project-store';
import { useAuthStore } from '@/stores/auth-store';

interface ProjectChatPanelProps {
  projectId: string;
}

const STATUS_LABELS: Record<ProjectStatusType, { label: string; color: string }> = {
  planning: { label: '計画中', color: 'bg-blue-500/15 text-blue-600' },
  proposed: { label: '提案中', color: 'bg-yellow-500/15 text-yellow-600' },
  approved: { label: '承認済', color: 'bg-green-500/15 text-green-600' },
  in_progress: { label: '進行中', color: 'bg-purple-500/15 text-purple-600' },
  completed: { label: '完了', color: 'bg-gray-500/15 text-gray-600' },
  paused: { label: '一時停止', color: 'bg-orange-500/15 text-orange-600' },
  cancelled: { label: 'キャンセル', color: 'bg-red-500/15 text-red-600' },
};

// Step info with optional member role
type StepInfo = { label: string; type: 'tool' | 'reasoning' | 'error'; role?: 'researcher' | 'critic' | 'leader' | null };

// Member role badge
function MemberBadge({ role }: { role: 'researcher' | 'critic' }) {
  const config = {
    researcher: { emoji: '🔬', color: 'text-blue-500' },
    critic: { emoji: '🔍', color: 'text-orange-500' },
  } as const;
  const c = config[role];
  return (
    <span className={`inline-flex items-center text-[9px] font-medium ${c.color} shrink-0`}>
      {c.emoji}
    </span>
  );
}

// --- Inline Process Block ---
function InlineProcessBlock({
  steps,
  fullTexts,
  isLive = false,
  defaultCollapsed = true,
}: {
  steps: StepInfo[];
  fullTexts?: string[];
  isLive?: boolean;
  defaultCollapsed?: boolean;
}) {
  const [isCollapsed, setIsCollapsed] = useState(defaultCollapsed);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Live block: auto-expand and auto-scroll
  useEffect(() => {
    if (isLive && steps.length > 0) {
      setIsCollapsed(false);
    }
  }, [isLive, steps.length]);

  useEffect(() => {
    if (!isCollapsed && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [steps.length, isCollapsed]);

  if (steps.length === 0 && !isLive) return null;

  // reasoning ステップを全文テキストにマッピング（インデックスベース）
  // fullTexts は reasoning/text イベントのみの全文配列
  const reasoningFullMap = (() => {
    if (!fullTexts || fullTexts.length === 0) return {};
    const map: Record<number, string> = {};
    let fullIdx = 0;
    for (let i = 0; i < steps.length; i++) {
      if (steps[i].type === 'reasoning' && fullIdx < fullTexts.length) {
        // ラベルと全文が異なる場合のみマッピング（展開する意味がある場合のみ）
        if (fullTexts[fullIdx] && fullTexts[fullIdx] !== steps[i].label) {
          map[i] = fullTexts[fullIdx];
        }
        fullIdx++;
      }
    }
    return map;
  })();

  return (
    <div className="my-1">
      <div className="max-w-[90%] rounded-lg border border-border/40 bg-muted/20 overflow-hidden">
        {/* Header */}
        <button
          onClick={() => setIsCollapsed((v) => !v)}
          className="flex items-center gap-1.5 w-full px-3 py-1.5 text-xs md:text-[11px] text-muted-foreground hover:bg-muted/30 transition-colors"
        >
          {isCollapsed ? (
            <ChevronRight className="h-3 w-3 shrink-0" />
          ) : (
            <ChevronDown className="h-3 w-3 shrink-0" />
          )}
          <Terminal className="h-3 w-3 shrink-0 text-primary/60" />
          <span className="font-medium">
            {isLive && steps.length === 0
              ? '処理を開始中...'
              : `実行ログ (${steps.length}件)`}
          </span>
          {isLive && (
            <Loader2 className="h-3 w-3 animate-spin text-primary ml-auto shrink-0" />
          )}
          {!isLive && steps.some((s) => s.type === 'error') && (
            <AlertCircle className="h-3 w-3 text-red-500 ml-auto shrink-0" />
          )}
          {!isLive && !steps.some((s) => s.type === 'error') && steps.length > 0 && (
            <Check className="h-3 w-3 text-green-500 ml-auto shrink-0" />
          )}
        </button>

        {/* Steps */}
        {!isCollapsed && (
          <div
            ref={scrollRef}
            className="max-h-[400px] overflow-y-auto px-3 pb-2"
          >
            <div className="border-l-2 border-primary/20 pl-2.5 space-y-0.5">
              {steps.map((step, i) => {
                const isLastLive = isLive && i === steps.length - 1;
                const fullText = reasoningFullMap[i];
                return (
                  <ProcessStepItem
                    key={i}
                    step={step}
                    fullText={fullText}
                    isLastLive={isLastLive}
                  />
                );
              })}
              {isLive && steps.length === 0 && (
                <div className="flex items-center gap-1.5 text-xs md:text-[10px] text-muted-foreground">
                  <Loader2 className="h-2.5 w-2.5 animate-spin text-primary" />
                  <span>接続中...</span>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// --- Process Step Item ---
function ProcessStepItem({
  step,
  fullText,
  isLastLive,
}: {
  step: StepInfo;
  fullText?: string;
  isLastLive: boolean;
}) {
  const displayText = fullText || step.label;

  return (
    <div className="flex items-start gap-1.5 text-xs md:text-[10px] leading-relaxed">
      {step.type === 'error' ? (
        <AlertCircle className="h-2.5 w-2.5 text-red-500 shrink-0 mt-0.5" />
      ) : step.type === 'reasoning' ? (
        isLastLive ? (
          <Loader2 className="h-2.5 w-2.5 animate-spin text-primary shrink-0 mt-0.5" />
        ) : (
          <Brain className="h-2.5 w-2.5 text-yellow-500/70 shrink-0 mt-0.5" />
        )
      ) : isLastLive ? (
        <Loader2 className="h-2.5 w-2.5 animate-spin text-primary shrink-0 mt-0.5" />
      ) : (
        <Check className="h-2.5 w-2.5 text-green-500 shrink-0 mt-0.5" />
      )}
      {step.role && step.role !== 'leader' && <MemberBadge role={step.role} />}
      <span
        className={`${
          step.type === 'error'
            ? 'text-red-500'
            : step.type === 'reasoning'
              ? 'text-muted-foreground/70 italic'
              : 'text-muted-foreground'
        } whitespace-pre-wrap`}
      >
        {displayText}
      </span>
    </div>
  );
}

// --- Display item types ---
type DisplayItem =
  | { kind: 'message'; msg: MessageResponse }
  | { kind: 'execution-block'; steps: StepInfo[]; isLive: boolean; id: string };

// --- Execution event helpers ---
interface ExecutionRun {
  events: ExecutionEvent[];
  isDone: boolean;
  startTime: string;
}

function groupExecutionRuns(events: ExecutionEvent[]): ExecutionRun[] {
  const runs: ExecutionRun[] = [];
  let currentRun: ExecutionEvent[] = [];

  for (const event of events) {
    if (event.event_type === 'done') {
      if (currentRun.length > 0) {
        runs.push({ events: currentRun, isDone: true, startTime: currentRun[0].created_at });
      }
      currentRun = [];
    } else {
      currentRun.push(event);
    }
  }

  // Remaining events (no done yet)
  if (currentRun.length > 0) {
    runs.push({ events: currentRun, isDone: false, startTime: currentRun[0].created_at });
  }

  return runs;
}

function eventToStep(event: ExecutionEvent): StepInfo {
  const member = event.metadata?.member as string | undefined;
  const role = (member === 'researcher' || member === 'critic' || member === 'leader') ? member : null;

  let label = '';
  if (event.event_type === 'tool_use') {
    label = event.tool_label || event.tool_name || 'ツール実行';
  } else if (event.event_type === 'error') {
    label = event.content || 'エラー';
  } else {
    label = event.content || event.event_type;
  }

  const type: StepInfo['type'] =
    event.event_type === 'tool_use' ? 'tool' :
    event.event_type === 'error' ? 'error' : 'reasoning';

  return { label, type, role };
}

// --- Message bubble (memo化で不要な再描画を防ぐ) ---
const MessageBubble = memo(function MessageBubble({ msg }: { msg: MessageResponse }) {
  return (
    <div className={`flex ${msg.sender_type === 'human' ? 'justify-end' : 'justify-start'}`}>
      <div
        className={`max-w-[85%] rounded-lg px-3 py-2 text-sm md:text-xs leading-relaxed ${
          msg.sender_type === 'human'
            ? 'bg-primary text-primary-foreground'
            : 'bg-muted text-foreground prose prose-sm md:prose-xs prose-dan max-w-none'
        }`}
      >
        {msg.sender_type === 'human'
          ? msg.content
          : <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content || ''}</ReactMarkdown>
        }
      </div>
    </div>
  );
});

// --- Input area (分離して入力変更が他に影響しないようにする) ---
function ChatInput({
  projectId,
  roomId,
}: {
  projectId: string;
  roomId: string;
}) {
  const [message, setMessage] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const queryClient = useQueryClient();
  const user = useAuthStore((state) => state.user);
  const selectProject = useProjectStore((s) => s.selectProject);

  const { isSending } = useProcessState(projectId);
  const { setSending, setProcessing, clearLiveSteps, addLiveStep, resetProcess } = useProcessActions();

  const isTransientNetworkError = (message?: string): boolean => {
    if (!message) return false;
    const m = message.toLowerCase();
    return m.includes('networkerror') || m.includes('failed to fetch') || m.includes('network request failed');
  };

  // Textarea auto-resize
  useEffect(() => {
    const ta = textareaRef.current;
    if (!ta) return;
    if (!message.trim()) {
      ta.style.height = '32px';
      return;
    }
    ta.style.height = '32px';
    ta.style.height = `${Math.min(ta.scrollHeight, 120)}px`;
  }, [message]);

  // Send message
  const handleSendMessage = useCallback(async () => {
    if (!message.trim() || isSending) return;

    const content = message.trim();
    setMessage('');
    setSending(projectId, true);
    setProcessing(projectId, true);
    clearLiveSteps(projectId);

    // Optimistic update
    const tempUserMessageId = `temp-user-${Date.now()}`;
    const optimisticUserMessage: MessageResponse = {
      id: tempUserMessageId,
      room_id: roomId,
      sender_id: user?.id || '',
      sender_name: user?.display_name || 'You',
      sender_type: 'human',
      content,
      created_at: new Date().toISOString(),
    };

    const queryKey = ['project-messages', roomId];
    queryClient.setQueryData(queryKey, (old: { messages: MessageResponse[] } | undefined) => ({
      messages: [optimisticUserMessage, ...(old?.messages || [])],
    }));

    const controller = new AbortController();
    abortControllerRef.current = controller;

    try {
      await api.sm.sendMessageStream(
        { message: content, session_id: roomId },
        {
          onUserMessage: (msg) => {
            queryClient.setQueryData(queryKey, (old: { messages: MessageResponse[] } | undefined) => ({
              messages: [msg, ...(old?.messages || []).filter((m: MessageResponse) => m.id !== tempUserMessageId)],
            }));
          },
          onAIMessage: (msg) => {
            setProcessing(projectId, false);
            clearLiveSteps(projectId);
            queryClient.setQueryData(queryKey, (old: { messages: MessageResponse[] } | undefined) => ({
              messages: [msg, ...(old?.messages || [])],
            }));
          },
          onProcessStep: (step: ProcessStep) => {
            addLiveStep(projectId, {
              label: step.label,
              type: step.label.startsWith('🔧') ? 'tool' : 'reasoning',
            });
          },
          onComplete: () => {
            setSending(projectId, false);
            setProcessing(projectId, false);
            queryClient.invalidateQueries({ queryKey: ['project-messages', roomId] });
          },
          onError: (error) => {
            setSending(projectId, false);
            setProcessing(projectId, false);
            if (isTransientNetworkError(error)) {
              console.warn('[project-chat] transient stream error:', error);
              return;
            }
            toast.error(error || 'エラーが発生しました');
          },
          onProjectCreated: (createdProjectId) => {
            queryClient.invalidateQueries({ queryKey: ['projects'] });
            if (createdProjectId !== projectId) {
              selectProject(createdProjectId);
            }
          },
        },
        controller.signal
      );
    } catch (error) {
      setSending(projectId, false);
      setProcessing(projectId, false);
      if (error instanceof Error && error.name !== 'AbortError') {
        toast.error('メッセージの送信に失敗しました');
      }
    }
  }, [message, isSending, roomId, user?.id, user?.display_name, queryClient, projectId, selectProject, setSending, setProcessing, clearLiveSteps, addLiveStep]);

  // Cancel
  const handleCancel = useCallback(async () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }

    try {
      await api.sm.cancelSession(roomId);
    } catch (e) {
      console.error('Failed to cancel session:', e);
    }

    resetProcess(projectId);
    toast.info('処理を停止しました');
  }, [roomId, projectId, resetProcess]);

  // Keyboard
  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  }, [handleSendMessage]);

  // Esc to cancel
  useEffect(() => {
    if (!isSending) return;
    const handleEsc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        handleCancel();
      }
    };
    window.addEventListener('keydown', handleEsc);
    return () => window.removeEventListener('keydown', handleEsc);
  }, [isSending, handleCancel]);

  return (
    <div className="shrink-0 border-t border-border p-3">
      <div className="flex items-end gap-2 p-2 rounded-xl border border-border bg-input/30 focus-within:border-primary/50 transition-colors">
        <textarea
          ref={textareaRef}
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="メッセージを入力..."
          rows={1}
          className="flex-1 resize-none bg-transparent text-sm md:text-xs focus:outline-none min-h-[32px] max-h-[120px] py-1.5"
        />
        {isSending ? (
          <Button
            size="icon"
            variant="destructive"
            className="h-7 w-7 shrink-0"
            onClick={handleCancel}
            title="停止 (Escキー)"
          >
            <Square className="h-3.5 w-3.5" />
          </Button>
        ) : (
          <Button
            size="icon"
            className="h-7 w-7 shrink-0"
            onClick={handleSendMessage}
            disabled={!message.trim()}
          >
            <Send className="h-3.5 w-3.5" />
          </Button>
        )}
      </div>
    </div>
  );
}

export function ProjectChatPanel({ projectId }: ProjectChatPanelProps) {
  const queryClient = useQueryClient();
  const selectProject = useProjectStore((s) => s.selectProject);

  // プロセス状態は個別プロパティとして取得（変わった部分だけで再描画）
  const { isProcessing, liveSteps } = useProcessState(projectId);

  const messagesEndRef = useRef<HTMLDivElement>(null);

  const { data: project, isLoading } = useQuery({
    queryKey: ['project', projectId],
    queryFn: () => api.projects.get(projectId),
    enabled: !!projectId,
    retry: 1,
    refetchInterval: (query) => (query.state.error ? 15000 : 3000),
  });

  const { data: messagesData, isLoading: isLoadingMessages } = useQuery({
    queryKey: ['project-messages', project?.room_id],
    queryFn: () => api.rooms.getMessages(project!.room_id!, { limit: 500 }),
    enabled: !!project?.room_id,
    staleTime: 5 * 1000,
    retry: 1,
    refetchInterval: (query) => (query.state.error ? 15000 : 3000),
  });

  // Active execution status from backend (authoritative)
  const { data: activeStatus } = useQuery({
    queryKey: ['session-active', project?.room_id],
    queryFn: () => api.sm.getActiveStatus(project!.room_id!),
    enabled: !!project?.room_id,
    retry: 1,
    refetchInterval: (query) => (query.state.error ? 10000 : 2000),
  });

  // Execution events query (inline process monitor)
  const isActiveExecution = isProcessing || !!activeStatus?.active;
  const { data: executionEvents = [] } = useQuery({
    queryKey: ['execution-events', projectId],
    queryFn: () => api.projects.executionEvents.list(projectId),
    enabled: !!projectId,
    retry: 1,
    refetchInterval: (query) => {
      if (!isActiveExecution) return false;
      return query.state.error ? 10000 : 2000;
    },
  });

  // Proposals query
  const isProposed = project?.status === 'proposed';
  const { data: proposals } = useQuery({
    queryKey: ['project-proposals', projectId],
    queryFn: () => api.projects.proposals.list(projectId),
    enabled: !!projectId && !!project?.status,
    refetchInterval: isProposed ? 5000 : false,
  });

  const pendingProposal = proposals?.find((p: ProjectProposalResponse) => p.status === 'pending');
  const approvedProposal = proposals?.find((p: ProjectProposalResponse) => p.status === 'approved');

  // Approve/Reject mutations
  const approveMutation = useMutation({
    mutationFn: (proposalId: string) =>
      api.projects.proposals.action(projectId, proposalId, 'approve'),
    onSuccess: () => {
      toast.success('提案を承認しました。実行を開始します...');
      queryClient.invalidateQueries({ queryKey: ['project', projectId] });
      queryClient.invalidateQueries({ queryKey: ['project-proposals', projectId] });
    },
    onError: () => {
      toast.error('提案の承認に失敗しました');
    },
  });

  const rejectMutation = useMutation({
    mutationFn: (proposalId: string) =>
      api.projects.proposals.action(projectId, proposalId, 'reject'),
    onSuccess: () => {
      toast.info('提案を却下しました');
      queryClient.invalidateQueries({ queryKey: ['project', projectId] });
      queryClient.invalidateQueries({ queryKey: ['project-proposals', projectId] });
    },
    onError: () => {
      toast.error('提案の却下に失敗しました');
    },
  });

  const status = project?.status ? STATUS_LABELS[project.status] : null;
  const messages = messagesData?.messages || [];

  // Build display items: messages + execution event runs merged chronologically
  const displayItems = useMemo(() => {
    type TimedItem = { item: DisplayItem; sortKey: number; subKey: number };
    const timedItems: TimedItem[] = [];

    // Messages and their ai_context process blocks
    const chronological = [...messages].reverse();
    for (const msg of chronological) {
      const content = msg.content || '';

      // Skip legacy [実行中]/[思考中] prefixed messages
      if (msg.sender_type !== 'human' && (content.startsWith('[実行中]') || content.startsWith('[思考中]'))) {
        continue;
      }

      const msgTime = new Date(msg.created_at).getTime();

      timedItems.push({
        item: { kind: 'message', msg },
        sortKey: msgTime,
        subKey: 1,
      });
    }

    // Execution event runs (from backend polling)
    const runs = groupExecutionRuns(executionEvents);
    for (const run of runs) {
      // While streaming in this tab, prefer liveSteps block to avoid duplicate monitors.
      if (!run.isDone && isProcessing) continue;

      const steps = run.events.map(eventToStep);
      if (steps.length === 0) continue;

      // Option B: isLive only when actively executing (old data without done = completed)
      const isLive = !run.isDone && !!isActiveExecution;

      timedItems.push({
        item: { kind: 'execution-block', steps, isLive, id: `exec-${run.events[0].id}` },
        sortKey: new Date(run.startTime).getTime(),
        subKey: 0,
      });
    }

    // Sort by time, then by subKey (process blocks before their messages)
    timedItems.sort((a, b) => a.sortKey - b.sortKey || a.subKey - b.subKey);

    return timedItems.map((t) => t.item);
  }, [messages, executionEvents, isActiveExecution, isProcessing]);

  const hasAnyContent = displayItems.length > 0;

  const [proposalCollapsed, setProposalCollapsed] = useState(true);

  // Auto-scroll
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [displayItems.length, liveSteps.length, isProcessing]);

  return (
    <div className="flex flex-col h-full overflow-hidden bg-background">
      {/* Header */}
      <div className="shrink-0 flex items-center gap-3 pl-12 pr-4 md:px-4 py-3 border-b border-border">
        <FolderKanban className="h-5 w-5 text-primary shrink-0" />
        <div className="flex-1 min-w-0">
          {isLoading ? (
            <div className="flex items-center gap-2">
              <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
              <span className="text-sm text-muted-foreground">読み込み中...</span>
            </div>
          ) : (
            <>
              <h2 className="font-semibold text-sm truncate">{project?.title}</h2>
              <div className="flex items-center gap-2 mt-0.5">
                {status && (
                  <span className={`inline-block text-xs md:text-[10px] px-1.5 py-0.5 rounded-full font-medium ${status.color}`}>
                    {status.label}
                  </span>
                )}
                {project?.created_at && (
                  <span className="text-xs md:text-[10px] text-muted-foreground/60">
                    {new Date(project.created_at).toLocaleDateString('ja-JP')}
                  </span>
                )}
              </div>
            </>
          )}
        </div>
        <Button
          variant="ghost"
          size="icon"
          className="h-8 w-8 shrink-0"
          onClick={() => selectProject(null)}
        >
          <X className="h-4 w-4" />
        </Button>
      </div>

      {/* Approved proposal (collapsible) */}
      {approvedProposal && (
        <div className="shrink-0 border-b border-border">
          <button
            onClick={() => setProposalCollapsed((v) => !v)}
            className="flex items-center gap-2 w-full px-4 py-2 text-sm md:text-xs hover:bg-muted/50 transition-colors"
          >
            {proposalCollapsed ? <ChevronRight className="h-3 w-3 text-muted-foreground" /> : <ChevronDown className="h-3 w-3 text-muted-foreground" />}
            <FileText className="h-3 w-3 text-green-500" />
            <span className="text-muted-foreground">承認済みの提案</span>
            <CheckCircle2 className="h-3 w-3 text-green-500" />
          </button>
          {!proposalCollapsed && (
            <div className="px-4 pb-3 max-h-[40vh] overflow-y-auto">
              <div className="bg-muted rounded-lg px-3 py-2 text-sm md:text-xs leading-relaxed prose prose-sm md:prose-xs prose-dan max-w-none">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{approvedProposal.content || ''}</ReactMarkdown>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Messages (with inline process blocks) */}
      <div className="flex-1 overflow-y-auto">
        {isLoadingMessages ? (
          <div className="flex items-center justify-center p-6">
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          </div>
        ) : !hasAnyContent && !isProcessing ? (
          <div className="flex flex-col items-center justify-center p-6 h-full">
            <MessageSquare className="h-10 w-10 text-muted-foreground/20 mb-3" />
            <p className="text-sm md:text-xs text-muted-foreground">
              メッセージはまだありません
            </p>
          </div>
        ) : (
          <div className="flex flex-col gap-2 p-4">
            {displayItems.map((item) => {
              if (item.kind === 'execution-block') {
                return (
                  <InlineProcessBlock
                    key={item.id}
                    steps={item.steps}
                    isLive={item.isLive}
                    defaultCollapsed={!item.isLive}
                  />
                );
              }

              return <MessageBubble key={item.msg.id} msg={item.msg} />;
            })}

            {/* Live process block (during streaming) */}
            {isProcessing && (
              <InlineProcessBlock
                steps={liveSteps}
                isLive={true}
                defaultCollapsed={false}
              />
            )}

            <div ref={messagesEndRef} />
          </div>
        )}
      </div>

      {/* Proposal Action Bar */}
      {pendingProposal && project?.status === 'proposed' && (
        <div className="shrink-0 border-t border-border px-4 py-2 bg-yellow-500/5">
          <div className="flex gap-2">
            <Button
              size="sm"
              className="h-8 text-xs gap-1.5"
              onClick={() => approveMutation.mutate(pendingProposal.id)}
              disabled={approveMutation.isPending || rejectMutation.isPending}
            >
              {approveMutation.isPending ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <CheckCircle2 className="h-3.5 w-3.5" />
              )}
              承認して実行
            </Button>
            <Button
              size="sm"
              variant="outline"
              className="h-8 text-xs gap-1.5"
              onClick={() => rejectMutation.mutate(pendingProposal.id)}
              disabled={approveMutation.isPending || rejectMutation.isPending}
            >
              {rejectMutation.isPending ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <XCircle className="h-3.5 w-3.5" />
              )}
              却下
            </Button>
          </div>
        </div>
      )}

      {/* Input Area */}
      {project?.room_id && (
        <ChatInput projectId={projectId} roomId={project.room_id} />
      )}
    </div>
  );
}

