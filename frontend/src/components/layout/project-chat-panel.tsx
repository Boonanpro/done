'use client';

import { useState, useRef, useEffect, useCallback } from 'react';
import { X, FolderKanban, Loader2, MessageSquare, Send, Square, CheckCircle2, XCircle, ChevronDown, ChevronRight, Check, FileText, Terminal, Brain, AlertCircle } from 'lucide-react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

import { Button } from '@/components/ui/button';
import { api, type MessageResponse, type ProjectStatusType, type ProjectProposalResponse, type ProcessStep } from '@/lib/api-client';
import { useProjectStore } from '@/stores/project-store';
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

// --- Inline Process Block ---
function InlineProcessBlock({
  steps,
  isLive = false,
  defaultCollapsed = true,
}: {
  steps: { label: string; type: 'tool' | 'reasoning' | 'error' }[];
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

  return (
    <div className="my-1">
      <div className="max-w-[90%] rounded-lg border border-border/40 bg-muted/20 overflow-hidden">
        {/* Header */}
        <button
          onClick={() => setIsCollapsed((v) => !v)}
          className="flex items-center gap-1.5 w-full px-3 py-1.5 text-[11px] text-muted-foreground hover:bg-muted/30 transition-colors"
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
            className="max-h-[200px] overflow-y-auto px-3 pb-2"
          >
            <div className="border-l-2 border-primary/20 pl-2.5 space-y-0.5">
              {steps.map((step, i) => {
                const isLastLive = isLive && i === steps.length - 1;
                return (
                  <div key={i} className="flex items-start gap-1.5 text-[10px] leading-relaxed">
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
                    <span
                      className={
                        step.type === 'error'
                          ? 'text-red-500'
                          : step.type === 'reasoning'
                            ? 'text-muted-foreground/70 italic'
                            : 'text-muted-foreground'
                      }
                    >
                      {step.label}
                    </span>
                  </div>
                );
              })}
              {isLive && steps.length === 0 && (
                <div className="flex items-center gap-1.5 text-[10px] text-muted-foreground">
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

// --- Helper: reasoning_steps を分類 ---
function classifyStep(label: string): 'tool' | 'reasoning' | 'error' {
  if (label.startsWith('🔧') || label.startsWith('[tool]')) return 'tool';
  if (label.startsWith('[error]') || label.startsWith('❌')) return 'error';
  return 'reasoning';
}

// --- Display item types ---
type DisplayItem =
  | { kind: 'message'; msg: MessageResponse }
  | { kind: 'process-block'; steps: { label: string; type: 'tool' | 'reasoning' | 'error' }[]; id: string };

export function ProjectChatPanel({ projectId }: ProjectChatPanelProps) {
  const queryClient = useQueryClient();
  const selectProject = useProjectStore((s) => s.selectProject);
  const user = useAuthStore((state) => state.user);

  const [message, setMessage] = useState('');
  const [isSending, setIsSending] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const [liveSteps, setLiveSteps] = useState<{ label: string; type: 'tool' | 'reasoning' | 'error' }[]>([]);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const refetchMessagesRef = useRef<(() => void) | null>(null);

  const { data: project, isLoading } = useQuery({
    queryKey: ['project', projectId],
    queryFn: () => api.projects.get(projectId),
    enabled: !!projectId,
    refetchInterval: 3000,
  });

  const { data: messagesData, isLoading: isLoadingMessages, refetch: refetchMessages } = useQuery({
    queryKey: ['project-messages', project?.room_id],
    queryFn: () => api.rooms.getMessages(project!.room_id!, { limit: 500 }),
    enabled: !!project?.room_id,
    staleTime: 5 * 1000,
    refetchInterval: 3000,
  });

  useEffect(() => { refetchMessagesRef.current = refetchMessages; }, [refetchMessages]);

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

  // Build display items: messages + inline process blocks from ai_context
  const displayItems: DisplayItem[] = (() => {
    const chronological = [...messages].reverse();
    const items: DisplayItem[] = [];

    for (const msg of chronological) {
      const content = msg.content || '';

      // Skip legacy [実行中]/[思考中] prefixed messages
      if (msg.sender_type !== 'human' && (content.startsWith('[実行中]') || content.startsWith('[思考中]'))) {
        continue;
      }

      // For AI messages: insert process block from ai_context before the message
      if (msg.sender_type === 'ai' && msg.ai_context?.reasoning_steps?.length) {
        const steps = msg.ai_context.reasoning_steps.map((s: string) => ({
          label: s,
          type: classifyStep(s),
        }));
        items.push({ kind: 'process-block', steps, id: `pb-${msg.id}` });
      }

      items.push({ kind: 'message', msg });
    }

    return items;
  })();

  const hasAnyContent = displayItems.length > 0;

  const [proposalCollapsed, setProposalCollapsed] = useState(true);

  // Auto-scroll
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [displayItems.length, liveSteps.length, isProcessing]);

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
    if (!message.trim() || isSending || !project?.room_id) return;

    const content = message.trim();
    const roomId = project.room_id;
    setMessage('');
    setIsSending(true);
    setIsProcessing(true);
    setLiveSteps([]);

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
    queryClient.setQueryData(queryKey, (old: typeof messagesData) => ({
      messages: [optimisticUserMessage, ...(old?.messages || [])],
    }));

    const controller = new AbortController();
    abortControllerRef.current = controller;

    try {
      await api.sm.sendMessageStream(
        { message: content, session_id: roomId },
        {
          onUserMessage: (msg) => {
            queryClient.setQueryData(queryKey, (old: typeof messagesData) => ({
              messages: [msg, ...(old?.messages || []).filter((m: MessageResponse) => m.id !== tempUserMessageId)],
            }));
          },
          onAIMessage: (msg) => {
            setIsProcessing(false);
            setLiveSteps([]);
            queryClient.setQueryData(queryKey, (old: typeof messagesData) => ({
              messages: [msg, ...(old?.messages || [])],
            }));
          },
          onProcessStep: (step: ProcessStep) => {
            setLiveSteps((prev) => [
              ...prev,
              {
                label: step.label,
                type: step.label.startsWith('🔧') ? 'tool' : 'reasoning',
              },
            ]);
          },
          onComplete: () => {
            setIsSending(false);
            setIsProcessing(false);
            refetchMessagesRef.current?.();
          },
          onError: (error) => {
            setIsSending(false);
            setIsProcessing(false);
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
      setIsSending(false);
      setIsProcessing(false);
      if (error instanceof Error && error.name !== 'AbortError') {
        toast.error('メッセージの送信に失敗しました');
      }
    }
  }, [message, isSending, project?.room_id, user?.id, user?.display_name, queryClient, messagesData, projectId, selectProject]);

  // Cancel
  const handleCancel = useCallback(async () => {
    if (!project?.room_id) return;

    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }

    try {
      await api.sm.cancelSession(project.room_id);
    } catch (e) {
      console.error('Failed to cancel session:', e);
    }

    setIsSending(false);
    setIsProcessing(false);
    toast.info('処理を停止しました');
  }, [project?.room_id]);

  // Keyboard
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  };

  // Esc to cancel
  useEffect(() => {
    const handleEsc = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && isSending) {
        e.preventDefault();
        handleCancel();
      }
    };
    window.addEventListener('keydown', handleEsc);
    return () => window.removeEventListener('keydown', handleEsc);
  }, [isSending, handleCancel]);

  return (
    <div className="flex flex-col h-full overflow-hidden bg-background">
      {/* Header */}
      <div className="shrink-0 flex items-center gap-3 px-4 py-3 border-b border-border">
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
                  <span className={`inline-block text-[10px] px-1.5 py-0.5 rounded-full font-medium ${status.color}`}>
                    {status.label}
                  </span>
                )}
                {project?.created_at && (
                  <span className="text-[10px] text-muted-foreground/60">
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
            className="flex items-center gap-2 w-full px-4 py-2 text-xs hover:bg-muted/50 transition-colors"
          >
            {proposalCollapsed ? <ChevronRight className="h-3 w-3 text-muted-foreground" /> : <ChevronDown className="h-3 w-3 text-muted-foreground" />}
            <FileText className="h-3 w-3 text-green-500" />
            <span className="text-muted-foreground">承認済みの提案</span>
            <CheckCircle2 className="h-3 w-3 text-green-500" />
          </button>
          {!proposalCollapsed && (
            <div className="px-4 pb-3 max-h-[40vh] overflow-y-auto">
              <div className="bg-muted rounded-lg px-3 py-2 text-xs leading-relaxed prose prose-xs prose-dan max-w-none">
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
            <p className="text-xs text-muted-foreground">
              メッセージはまだありません
            </p>
          </div>
        ) : (
          <div className="flex flex-col gap-2 p-4">
            {displayItems.map((item) => {
              if (item.kind === 'process-block') {
                return (
                  <InlineProcessBlock
                    key={item.id}
                    steps={item.steps}
                    isLive={false}
                    defaultCollapsed={true}
                  />
                );
              }

              const msg = item.msg;
              return (
                <div
                  key={msg.id}
                  className={`flex ${msg.sender_type === 'human' ? 'justify-end' : 'justify-start'}`}
                >
                  <div
                    className={`max-w-[85%] rounded-lg px-3 py-2 text-xs leading-relaxed ${
                      msg.sender_type === 'human'
                        ? 'bg-primary text-primary-foreground'
                        : 'bg-muted text-foreground prose prose-xs prose-dan max-w-none'
                    }`}
                  >
                    {msg.sender_type === 'human'
                      ? msg.content
                      : <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content || ''}</ReactMarkdown>
                    }
                  </div>
                </div>
              );
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
        <div className="shrink-0 border-t border-border p-3">
          <div className="flex items-end gap-2 p-2 rounded-xl border border-border bg-input/30 focus-within:border-primary/50 transition-colors">
            <textarea
              ref={textareaRef}
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="メッセージを入力..."
              rows={1}
              className="flex-1 resize-none bg-transparent text-xs focus:outline-none min-h-[32px] max-h-[120px] py-1.5"
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
      )}
    </div>
  );
}
