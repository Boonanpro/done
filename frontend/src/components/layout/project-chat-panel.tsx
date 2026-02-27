'use client';

import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertCircle,
  Brain,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  FileText,
  FolderKanban,
  Loader2,
  MessageSquare,
  Send,
  Square,
  Terminal,
  Trash2,
  X,
  XCircle,
} from 'lucide-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import {
  api,
  type ActiveSessionStatus,
  type ExecutionEvent,
  type MessageResponse,
  type ProcessStep,
  type ProjectProposalResponse,
  type ProjectStatusType,
} from '@/lib/api-client';
import { useProjectRecovery } from '@/hooks/useProjectRecovery';
import { useAuthStore } from '@/stores/auth-store';
import { useProjectStore, useRecoveryActions, useRecoveryState } from '@/stores/project-store';

interface ProjectChatPanelProps {
  projectId: string;
}

const STATUS_LABELS: Record<ProjectStatusType, { label: string; color: string }> = {
  planning: { label: '計画中', color: 'bg-blue-500/15 text-blue-600' },
  proposed: { label: '提案済', color: 'bg-yellow-500/15 text-yellow-600' },
  approved: { label: '承認済', color: 'bg-green-500/15 text-green-600' },
  in_progress: { label: '進行中', color: 'bg-purple-500/15 text-purple-600' },
  completed: { label: '完了', color: 'bg-gray-500/15 text-gray-600' },
  paused: { label: '一時停止', color: 'bg-orange-500/15 text-orange-600' },
  cancelled: { label: 'キャンセル', color: 'bg-red-500/15 text-red-600' },
};

type StepInfo = {
  label: string;
  type: 'tool' | 'reasoning' | 'error';
  role?: 'researcher' | 'critic' | 'leader' | null;
};

type DisplayItem =
  | { kind: 'message'; msg: MessageResponse }
  | { kind: 'execution-block'; id: string; steps: StepInfo[]; isLive: boolean };

interface ExecutionRun {
  events: ExecutionEvent[];
  isDone: boolean;
  startTime: string;
}

function MemberBadge({ role }: { role: 'researcher' | 'critic' }) {
  const config = {
    researcher: { label: 'リサーチ', color: 'text-blue-500' },
    critic: { label: 'クリティック', color: 'text-orange-500' },
  } as const;
  const current = config[role];

  return (
    <span className={`inline-flex items-center text-[9px] font-medium ${current.color} shrink-0`}>
      {current.label}
    </span>
  );
}

function ProcessStepItem({
  step,
  isLastLive,
}: {
  step: StepInfo;
  isLastLive: boolean;
}) {
  return (
    <div className="flex items-start gap-1.5 text-xs md:text-[10px] leading-relaxed">
      {step.type === 'error' ? (
        <AlertCircle className="mt-0.5 h-2.5 w-2.5 shrink-0 text-red-500" />
      ) : step.type === 'reasoning' ? (
        isLastLive ? (
          <Loader2 className="mt-0.5 h-2.5 w-2.5 shrink-0 animate-spin text-primary" />
        ) : (
          <Brain className="mt-0.5 h-2.5 w-2.5 shrink-0 text-yellow-500/70" />
        )
      ) : isLastLive ? (
        <Loader2 className="mt-0.5 h-2.5 w-2.5 shrink-0 animate-spin text-primary" />
      ) : (
        <Check className="mt-0.5 h-2.5 w-2.5 shrink-0 text-green-500" />
      )}
      {step.role && step.role !== 'leader' ? <MemberBadge role={step.role} /> : null}
      <span
        className={`whitespace-pre-wrap ${
          step.type === 'error'
            ? 'text-red-500'
            : step.type === 'reasoning'
              ? 'italic text-muted-foreground/70'
              : 'text-muted-foreground'
        }`}
      >
        {step.label}
      </span>
    </div>
  );
}

function InlineProcessBlock({
  steps,
  isLive = false,
  defaultCollapsed = true,
}: {
  steps: StepInfo[];
  isLive?: boolean;
  defaultCollapsed?: boolean;
}) {
  const [isCollapsed, setIsCollapsed] = useState(defaultCollapsed);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (isLive && steps.length > 0) {
      setIsCollapsed(false);
    }
  }, [isLive, steps.length]);

  useEffect(() => {
    if (!isCollapsed && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [isCollapsed, steps.length]);

  if (steps.length === 0 && !isLive) return null;

  return (
    <div className="my-1">
      <div className="max-w-[90%] overflow-hidden rounded-lg border border-border/40 bg-muted/20">
        <button
          onClick={() => setIsCollapsed((value) => !value)}
          className="flex w-full items-center gap-1.5 px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:bg-muted/30 md:text-[11px]"
        >
          {isCollapsed ? (
            <ChevronRight className="h-3 w-3 shrink-0" />
          ) : (
            <ChevronDown className="h-3 w-3 shrink-0" />
          )}
          <Terminal className="h-3 w-3 shrink-0 text-primary/60" />
          <span className="font-medium">
            {isLive && steps.length === 0 ? '処理中...' : `処理 (${steps.length})`}
          </span>
          {isLive ? <Loader2 className="ml-auto h-3 w-3 shrink-0 animate-spin text-primary" /> : null}
          {!isLive && steps.some((step) => step.type === 'error') ? (
            <AlertCircle className="ml-auto h-3 w-3 shrink-0 text-red-500" />
          ) : null}
          {!isLive && !steps.some((step) => step.type === 'error') && steps.length > 0 ? (
            <Check className="ml-auto h-3 w-3 shrink-0 text-green-500" />
          ) : null}
        </button>

        {!isCollapsed ? (
          <div ref={scrollRef} className="max-h-[400px] overflow-y-auto px-3 pb-2">
            <div className="space-y-0.5 border-l-2 border-primary/20 pl-2.5">
              {steps.map((step, index) => (
                <ProcessStepItem
                  key={`${step.type}-${index}`}
                  step={step}
                  isLastLive={isLive && index === steps.length - 1}
                />
              ))}
              {isLive && steps.length === 0 ? (
                <div className="flex items-center gap-1.5 text-xs text-muted-foreground md:text-[10px]">
                  <Loader2 className="h-2.5 w-2.5 animate-spin text-primary" />
                  <span>更新を待機中...</span>
                </div>
              ) : null}
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}

function groupExecutionRuns(events: ExecutionEvent[]): ExecutionRun[] {
  const runs: ExecutionRun[] = [];
  let currentRun: ExecutionEvent[] = [];

  for (const event of events) {
    if (event.event_type === 'done') {
      if (currentRun.length > 0) {
        runs.push({
          events: currentRun,
          isDone: true,
          startTime: currentRun[0].created_at,
        });
      }
      currentRun = [];
      continue;
    }

    currentRun.push(event);
  }

  if (currentRun.length > 0) {
    runs.push({
      events: currentRun,
      isDone: false,
      startTime: currentRun[0].created_at,
    });
  }

  return runs;
}

function eventToStep(event: ExecutionEvent): StepInfo {
  const member = event.metadata?.member as string | undefined;
  const role =
    member === 'researcher' || member === 'critic' || member === 'leader' ? member : null;

  if (event.event_type === 'tool_use') {
    return {
      label: event.tool_label || event.tool_name || 'ツール実行',
      type: 'tool',
      role,
    };
  }

  if (event.event_type === 'error') {
    return {
      label: event.content || 'エラー',
      type: 'error',
      role,
    };
  }

  return {
    label: event.content || event.event_type,
    type: 'reasoning',
    role,
  };
}

const MessageBubble = memo(function MessageBubble({ msg }: { msg: MessageResponse }) {
  if (msg.sender_type !== 'human') {
    const proposalMatch = (msg.content || '').match(/```proposal\n([^\n]+)\n```/);
    if (proposalMatch) {
      const filename = proposalMatch[1].trim();
      return (
        <div className="flex w-full justify-start px-1 py-1">
          <iframe
            src={`/api/v1/proposals/${filename}`}
            className="w-full rounded-xl border border-border"
            style={{ height: '600px' }}
            sandbox="allow-scripts allow-same-origin"
            title={filename}
          />
        </div>
      );
    }
  }

  if (msg.sender_type === 'human') {
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] rounded-lg bg-primary px-3 py-2 text-sm leading-relaxed text-primary-foreground md:text-xs">
          {msg.content}
        </div>
      </div>
    );
  }

  return (
    <div className="prose prose-sm prose-dan max-w-none text-sm leading-relaxed text-foreground md:prose-xs md:text-xs">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content || ''}</ReactMarkdown>
    </div>
  );
});

function ChatInput({
  projectId,
  roomId,
  isSessionActive,
}: {
  projectId: string;
  roomId: string;
  isSessionActive: boolean;
}) {
  const [message, setMessage] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const titleGeneratedRef = useRef(false);
  const queryClient = useQueryClient();
  const user = useAuthStore((state) => state.user);
  const selectProject = useProjectStore((s) => s.selectProject);
  const { isInterrupted } = useRecoveryState(projectId);
  const { resetRecovery, setInterrupted } = useRecoveryActions();

  useProjectRecovery({ projectId, roomId });

  const syncActiveStatus = useCallback(
    (active: boolean) => {
      queryClient.setQueryData<ActiveSessionStatus>(['session-active', roomId], {
        active,
        session_id: roomId,
        started_at: active ? Date.now() : null,
      });
    },
    [queryClient, roomId]
  );

  const isBusy = isInterrupted || isSessionActive;

  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;
    if (!message.trim()) {
      textarea.style.height = '32px';
      return;
    }
    textarea.style.height = '32px';
    textarea.style.height = `${Math.min(textarea.scrollHeight, 120)}px`;
  }, [message]);

  const invalidateProjectQueries = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ['session-active', roomId] });
    queryClient.invalidateQueries({ queryKey: ['project-messages', roomId] });
    queryClient.invalidateQueries({ queryKey: ['execution-events', projectId] });
    queryClient.invalidateQueries({ queryKey: ['project', projectId] });
    queryClient.invalidateQueries({ queryKey: ['project-proposals', projectId] });
  }, [projectId, queryClient, roomId]);

  const handleSendMessage = useCallback(async () => {
    if (!message.trim() || isBusy) return;

    const content = message.trim();
    setMessage('');
    syncActiveStatus(true);
    setInterrupted(projectId, false);

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
            queryClient.setQueryData(
              queryKey,
              (old: { messages: MessageResponse[] } | undefined) => ({
                messages: [
                  msg,
                  ...(old?.messages || []).filter(
                    (current: MessageResponse) => current.id !== tempUserMessageId
                  ),
                ],
              })
            );
          },
          onAIMessage: () => {
            queryClient.invalidateQueries({ queryKey: ['project-messages', roomId] });
            queryClient.invalidateQueries({ queryKey: ['execution-events', projectId] });
          },
          onProcessStep: (_step: ProcessStep) => {
            queryClient.invalidateQueries({ queryKey: ['execution-events', projectId] });
          },
          onInterrupted: () => {
            syncActiveStatus(true);
            setInterrupted(projectId, true);
            queryClient.invalidateQueries({ queryKey: ['session-active', roomId] });
            queryClient.invalidateQueries({ queryKey: ['project-messages', roomId] });
            queryClient.invalidateQueries({ queryKey: ['execution-events', projectId] });
          },
          onComplete: () => {
            syncActiveStatus(false);
            setInterrupted(projectId, false);
            invalidateProjectQueries();

            if (!titleGeneratedRef.current) {
              titleGeneratedRef.current = true;
              const cached = queryClient.getQueryData<{ title?: string }>(['project', projectId]);
              api.projects
                .suggestTitle(roomId)
                .then(({ title }) => {
                  if (title && title !== cached?.title) {
                    return api.projects.update(projectId, { title });
                  }
                  return undefined;
                })
                .then(() => {
                  queryClient.invalidateQueries({ queryKey: ['project', projectId] });
                  queryClient.invalidateQueries({ queryKey: ['projects'] });
                })
                .catch(() => {});
            }
          },
          onError: (error) => {
            syncActiveStatus(false);
            setInterrupted(projectId, false);
            toast.error(error || 'メッセージの送信に失敗しました');
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
      syncActiveStatus(false);
      setInterrupted(projectId, false);
      if (error instanceof Error && error.name !== 'AbortError') {
        toast.error('メッセージ送信中に問題が発生しました');
      }
    }
  }, [
    invalidateProjectQueries,
    isBusy,
    message,
    projectId,
    queryClient,
    roomId,
    selectProject,
    setInterrupted,
    syncActiveStatus,
    user?.display_name,
    user?.id,
  ]);

  const handleCancel = useCallback(async () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }

    try {
      await api.sm.cancelSession(roomId);
    } catch (error) {
      console.error('Failed to cancel session:', error);
    }

    syncActiveStatus(false);
    resetRecovery(projectId);
    invalidateProjectQueries();
    toast.info('処理を中断しました');
  }, [invalidateProjectQueries, projectId, resetRecovery, roomId, syncActiveStatus]);

  const handleKeyDown = useCallback(
    (event: React.KeyboardEvent) => {
      const isMobile = window.matchMedia('(max-width: 767px)').matches;
      if (event.key === 'Enter' && !event.shiftKey && !isMobile) {
        event.preventDefault();
        handleSendMessage();
      }
    },
    [handleSendMessage]
  );

  useEffect(() => {
    if (!isBusy) return;

    const handleEsc = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        handleCancel();
      }
    };

    window.addEventListener('keydown', handleEsc);
    return () => window.removeEventListener('keydown', handleEsc);
  }, [handleCancel, isBusy]);

  return (
    <div className="shrink-0 border-t border-border p-3">
      <div className="flex items-end gap-2 rounded-xl border border-border bg-input/30 p-2 transition-colors focus-within:border-primary/50">
        <textarea
          ref={textareaRef}
          value={message}
          onChange={(event) => setMessage(event.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="メッセージを入力..."
          rows={1}
          className="min-h-[32px] max-h-[120px] flex-1 resize-none bg-transparent py-1.5 text-sm focus:outline-none md:text-xs"
        />
        {isBusy ? (
          <Button
            size="icon"
            variant="destructive"
            className="h-7 w-7 shrink-0"
            onClick={handleCancel}
            title="キャンセル"
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
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const [proposalCollapsed, setProposalCollapsed] = useState(true);

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

  const { data: activeStatus } = useQuery({
    queryKey: ['session-active', project?.room_id],
    queryFn: () => api.sm.getActiveStatus(project!.room_id!),
    enabled: !!project?.room_id,
    retry: 1,
    refetchInterval: (query) => (query.state.error ? 10000 : 2000),
  });

  const isActiveExecution = !!activeStatus?.active;

  const { data: executionEvents = [] } = useQuery({
    queryKey: ['execution-events', projectId],
    queryFn: () => api.projects.executionEvents.list(projectId),
    enabled: !!projectId,
    retry: 1,
    staleTime: 30 * 1000,
    refetchInterval: (query) => (isActiveExecution ? (query.state.error ? 10000 : 2000) : false),
  });

  const isProposed = project?.status === 'proposed';
  const { data: proposals } = useQuery({
    queryKey: ['project-proposals', projectId],
    queryFn: () => api.projects.proposals.list(projectId),
    enabled: !!projectId && !!project?.status,
    refetchInterval: isProposed ? 5000 : false,
  });

  const pendingProposal = proposals?.find((item: ProjectProposalResponse) => item.status === 'pending');
  const approvedProposal = proposals?.find((item: ProjectProposalResponse) => item.status === 'approved');

  const approveMutation = useMutation({
    mutationFn: (proposalId: string) => api.projects.proposals.action(projectId, proposalId, 'approve'),
    onSuccess: () => {
      toast.success('提案を承認しました');
      queryClient.invalidateQueries({ queryKey: ['project', projectId] });
      queryClient.invalidateQueries({ queryKey: ['project-proposals', projectId] });
    },
    onError: () => {
      toast.error('提案の承認に失敗しました');
    },
  });

  const rejectMutation = useMutation({
    mutationFn: (proposalId: string) => api.projects.proposals.action(projectId, proposalId, 'reject'),
    onSuccess: () => {
      toast.info('提案を却下しました');
      queryClient.invalidateQueries({ queryKey: ['project', projectId] });
      queryClient.invalidateQueries({ queryKey: ['project-proposals', projectId] });
    },
    onError: () => {
      toast.error('提案の却下に失敗しました');
    },
  });

  const deleteProjectMutation = useMutation({
    mutationFn: () => api.projects.delete(projectId),
    onSuccess: () => {
      selectProject(null);
      queryClient.invalidateQueries({ queryKey: ['projects'] });
      toast.success('プロジェクトを削除しました');
    },
    onError: () => {
      toast.error('プロジェクトの削除に失敗しました');
    },
  });

  const handleDeleteProject = () => {
    if (window.confirm('このプロジェクトを削除しますか？')) {
      deleteProjectMutation.mutate();
    }
  };

  const status = project?.status ? STATUS_LABELS[project.status] : null;
  const messages = messagesData?.messages || [];

  const displayItems = useMemo(() => {
    type TimedItem = { item: DisplayItem; sortKey: number; subKey: number };
    const timedItems: TimedItem[] = [];
    const chronologicalMessages = [...messages].reverse();

    for (const msg of chronologicalMessages) {
      const content = msg.content || '';
      if (
        msg.sender_type !== 'human' &&
        (content.startsWith('[PROCESS]') || content.startsWith('[THINKING]'))
      ) {
        continue;
      }

      timedItems.push({
        item: { kind: 'message', msg },
        sortKey: new Date(msg.created_at).getTime(),
        subKey: 1,
      });
    }

    const runs = groupExecutionRuns(executionEvents);
    for (let index = 0; index < runs.length; index++) {
      const run = runs[index];
      const steps = run.events.map(eventToStep);
      if (steps.length === 0) continue;

      timedItems.push({
        item: {
          kind: 'execution-block',
          id: `exec-${run.events[0].id}`,
          steps,
          isLive: !run.isDone && index === runs.length - 1 && isActiveExecution,
        },
        sortKey: new Date(run.startTime).getTime(),
        subKey: 0,
      });
    }

    timedItems.sort((left, right) => left.sortKey - right.sortKey || left.subKey - right.subKey);
    return timedItems.map((item) => item.item);
  }, [executionEvents, isActiveExecution, messages]);

  const hasAnyContent = displayItems.length > 0;

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [displayItems.length, isActiveExecution]);

  return (
    <div className="flex h-full flex-col overflow-hidden bg-background">
      <div className="flex shrink-0 items-center gap-3 border-b border-border py-3 pl-12 pr-4 md:px-4">
        <FolderKanban className="h-5 w-5 shrink-0 text-primary" />
        <div className="min-w-0 flex-1">
          {isLoading ? (
            <div className="flex items-center gap-2">
              <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
              <span className="text-sm text-muted-foreground">プロジェクトを読み込み中...</span>
            </div>
          ) : (
            <>
              <div className="flex items-center gap-1.5">
                <h2 className="truncate text-sm font-semibold">{project?.title}</h2>
                <button
                  className="shrink-0 rounded p-0.5 text-muted-foreground/40 transition-colors hover:text-destructive"
                  onClick={handleDeleteProject}
                  disabled={deleteProjectMutation.isPending}
                  title="プロジェクトを削除"
                >
                  {deleteProjectMutation.isPending ? (
                    <Loader2 className="h-3 w-3 animate-spin" />
                  ) : (
                    <Trash2 className="h-3 w-3" />
                  )}
                </button>
              </div>
              <div className="mt-0.5 flex items-center gap-2">
                {status ? (
                  <span
                    className={`inline-block rounded-full px-1.5 py-0.5 text-xs font-medium md:text-[10px] ${status.color}`}
                  >
                    {status.label}
                  </span>
                ) : null}
                {project?.created_at ? (
                  <span className="text-xs text-muted-foreground/60 md:text-[10px]">
                    {new Date(project.created_at).toLocaleDateString('ja-JP')}
                  </span>
                ) : null}
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

      {approvedProposal ? (
        <div className="shrink-0 border-b border-border">
          <button
            onClick={() => setProposalCollapsed((value) => !value)}
            className="flex w-full items-center gap-2 px-4 py-2 text-sm transition-colors hover:bg-muted/50 md:text-xs"
          >
            {proposalCollapsed ? (
              <ChevronRight className="h-3 w-3 text-muted-foreground" />
            ) : (
              <ChevronDown className="h-3 w-3 text-muted-foreground" />
            )}
            <FileText className="h-3 w-3 text-green-500" />
            <span className="text-muted-foreground">承認済み提案</span>
            <CheckCircle2 className="h-3 w-3 text-green-500" />
          </button>
          {!proposalCollapsed ? (
            <div className="max-h-[40vh] overflow-y-auto px-4 pb-3">
              <div className="prose prose-sm prose-dan max-w-none rounded-lg bg-muted px-3 py-2 text-sm leading-relaxed md:prose-xs md:text-xs">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {approvedProposal.content || ''}
                </ReactMarkdown>
              </div>
            </div>
          ) : null}
        </div>
      ) : null}

      <div className="flex-1 overflow-y-auto">
        {isLoadingMessages ? (
          <div className="flex items-center justify-center p-6">
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          </div>
        ) : !hasAnyContent && !isActiveExecution ? (
          <div className="flex h-full flex-col items-center justify-center p-6">
            <MessageSquare className="mb-3 h-10 w-10 text-muted-foreground/20" />
            <p className="text-sm text-muted-foreground md:text-xs">メッセージを送信して開始してください。</p>
          </div>
        ) : (
          <div className="flex flex-col gap-2 p-4">
            {(() => {
              const lastExecutionIndex = displayItems.reduce(
                (last, item, index) => (item.kind === 'execution-block' ? index : last),
                -1
              );

              return displayItems.map((item, index) => {
                if (item.kind === 'execution-block') {
                  return (
                    <InlineProcessBlock
                      key={item.id}
                      steps={item.steps}
                      isLive={item.isLive}
                      defaultCollapsed={index !== lastExecutionIndex && !item.isLive}
                    />
                  );
                }

                return <MessageBubble key={item.msg.id} msg={item.msg} />;
              });
            })()}
            <div ref={messagesEndRef} />
          </div>
        )}
      </div>

      {pendingProposal && project?.status === 'proposed' ? (
        <div className="shrink-0 border-t border-border bg-yellow-500/5 px-4 py-2">
          <div className="flex gap-2">
            <Button
              size="sm"
              className="h-8 gap-1.5 text-xs"
              onClick={() => approveMutation.mutate(pendingProposal.id)}
              disabled={approveMutation.isPending || rejectMutation.isPending}
            >
              {approveMutation.isPending ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <CheckCircle2 className="h-3.5 w-3.5" />
              )}
              承認
            </Button>
            <Button
              size="sm"
              variant="outline"
              className="h-8 gap-1.5 text-xs"
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
      ) : null}

      {project?.room_id ? (
        <ChatInput projectId={projectId} roomId={project.room_id} isSessionActive={isActiveExecution} />
      ) : null}
    </div>
  );
}
