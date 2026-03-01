'use client';

import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertCircle,
  Brain,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  File,
  FileText,
  FolderKanban,
  Loader2,
  MessageSquare,
  Paperclip,
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
  type FileUploadResponse,
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

function parseHumanContent(content: string): { images: string[]; text: string } {
  const images: string[] = [];
  const text = content.replace(/\[添付画像: ([^\]]+)\]/g, (_, path) => {
    const filename = path.replace(/\\/g, '/').split('/').pop();
    if (filename) images.push(`/api/v1/files/${filename}`);
    return '';
  }).trim();
  return { images, text };
}

const MessageBubble = memo(function MessageBubble({ msg, onImageClick }: { msg: MessageResponse; onImageClick?: (url: string) => void }) {
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
    const { images, text } = parseHumanContent(msg.content || '');
    return (
      <div className="flex justify-end">
        <div className="max-w-[85%] flex flex-col items-end gap-1">
          {images.map((url, i) => (
            <img
              key={i}
              src={url}
              alt="添付画像"
              className="rounded-xl max-w-full max-h-64 object-contain border border-primary/20 cursor-zoom-in"
              onClick={() => onImageClick?.(url)}
            />
          ))}
          {text && (
            <div className="rounded-lg bg-primary px-3 py-2 text-sm leading-relaxed text-primary-foreground md:text-xs">
              {text}
            </div>
          )}
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
  sendMessageRef,
}: {
  projectId: string;
  roomId: string;
  isSessionActive: boolean;
  sendMessageRef?: React.MutableRefObject<((content: string) => void) | null>;
}) {
  const [message, setMessage] = useState('');
  const [attachedFiles, setAttachedFiles] = useState<FileUploadResponse[]>([]);
  const [isUploading, setIsUploading] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const titleGeneratedRef = useRef(false);
  const streamRequestRef = useRef(0);
  const queryClient = useQueryClient();
  const user = useAuthStore((state) => state.user);
  const selectProject = useProjectStore((s) => s.selectProject);
  const { isInterrupted } = useRecoveryState(projectId);
  const { resetRecovery, setInterrupted, setWarmupMode } = useRecoveryActions();

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
    // project-messages は refetch で即座に再取得（SSE断線で見逃したメッセージを確実に表示）
    queryClient.refetchQueries({ queryKey: ['project-messages', roomId] });
    queryClient.invalidateQueries({ queryKey: ['current-run', projectId] });
    queryClient.invalidateQueries({ queryKey: ['execution-events', projectId] });
    queryClient.invalidateQueries({ queryKey: ['project', projectId] });
    queryClient.invalidateQueries({ queryKey: ['project-proposals', projectId] });
  }, [projectId, queryClient, roomId]);

  const handleFileSelect = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files || files.length === 0) return;
    setIsUploading(true);
    try {
      const uploaded: FileUploadResponse[] = [];
      for (const file of Array.from(files)) {
        if (file.size > 10 * 1024 * 1024) {
          toast.error(`${file.name} は10MB以上のファイルは添付できません`);
          continue;
        }
        uploaded.push(await api.files.upload(file));
      }
      setAttachedFiles(prev => [...prev, ...uploaded]);
    } catch {
      toast.error('ファイルのアップロードに失敗しました');
    } finally {
      setIsUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  }, []);

  const handleRemoveFile = useCallback((fileId: string) => {
    setAttachedFiles(prev => prev.filter(f => f.id !== fileId));
  }, []);

  const handleClickAttach = useCallback(() => {
    fileInputRef.current?.click();
  }, []);

  const sendMessageCore = useCallback(async (content: string, imageUrls: string[] = []) => {
    if (!content.trim() && imageUrls.length === 0) return;

    const imagePrefix = imageUrls.map(url => `[添付画像: ${url}]`).join('\n');
    const optimisticContent = imagePrefix
      ? (content ? `${imagePrefix}\n\n${content}` : imagePrefix)
      : content;
    const requestId = streamRequestRef.current + 1;
    streamRequestRef.current = requestId;

    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }

    syncActiveStatus(true);
    setInterrupted(projectId, false);
    setWarmupMode(projectId, isBusy ? 'switching' : 'thinking');

    const tempUserMessageId = `temp-user-${Date.now()}`;
    const optimisticUserMessage: MessageResponse = {
      id: tempUserMessageId,
      room_id: roomId,
      sender_id: user?.id || '',
      sender_name: user?.display_name || 'You',
      sender_type: 'human',
      content: optimisticContent,
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
        { message: content, session_id: roomId, ...(imageUrls.length > 0 ? { image_urls: imageUrls } : {}) },
        {
          onUserMessage: (msg) => {
            if (streamRequestRef.current !== requestId) return;
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
            if (streamRequestRef.current !== requestId) return;
            setWarmupMode(projectId, null);
            queryClient.invalidateQueries({ queryKey: ['project-messages', roomId] });
            queryClient.invalidateQueries({ queryKey: ['current-run', projectId] });
            queryClient.invalidateQueries({ queryKey: ['execution-events', projectId] });
          },
          onProcessStep: (_step: ProcessStep) => {
            if (streamRequestRef.current !== requestId) return;
            setWarmupMode(projectId, null);
            queryClient.invalidateQueries({ queryKey: ['current-run', projectId] });
            queryClient.invalidateQueries({ queryKey: ['execution-events', projectId] });
          },
          onInterrupted: () => {
            if (streamRequestRef.current !== requestId) return;
            syncActiveStatus(true);
            setInterrupted(projectId, true);
            setWarmupMode(projectId, null);
            queryClient.invalidateQueries({ queryKey: ['session-active', roomId] });
            // project-messages は refetch で即座に再取得（SSE断線で見逃したメッセージを確実に表示）
            queryClient.refetchQueries({ queryKey: ['project-messages', roomId] });
            queryClient.invalidateQueries({ queryKey: ['current-run', projectId] });
            queryClient.invalidateQueries({ queryKey: ['execution-events', projectId] });
          },
          onComplete: () => {
            if (streamRequestRef.current !== requestId) return;
            syncActiveStatus(false);
            setInterrupted(projectId, false);
            setWarmupMode(projectId, null);
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
            if (streamRequestRef.current !== requestId) return;
            syncActiveStatus(false);
            setInterrupted(projectId, false);
            setWarmupMode(projectId, null);
            toast.error(error || 'メッセージの送信に失敗しました');
          },
          onProjectCreated: (createdProjectId) => {
            if (streamRequestRef.current !== requestId) return;
            queryClient.invalidateQueries({ queryKey: ['projects'] });
            if (createdProjectId !== projectId) {
              selectProject(createdProjectId);
            }
          },
        },
        controller.signal
      );
    } catch (error) {
      if (streamRequestRef.current !== requestId) return;
      syncActiveStatus(false);
      setInterrupted(projectId, false);
      setWarmupMode(projectId, null);
      if (error instanceof Error && error.name !== 'AbortError') {
        toast.error('メッセージ送信中に問題が発生しました');
      }
    }
  }, [
    invalidateProjectQueries,
    isBusy,
    projectId,
    queryClient,
    roomId,
    selectProject,
    setInterrupted,
    setWarmupMode,
    syncActiveStatus,
    user?.display_name,
    user?.id,
  ]);

  // 親コンポーネントから sendMessageCore を呼べるようにする
  useEffect(() => {
    if (sendMessageRef) {
      sendMessageRef.current = (content: string) => { sendMessageCore(content); };
      return () => { sendMessageRef.current = null; };
    }
  }, [sendMessageRef, sendMessageCore]);

  const handleSendMessage = useCallback(async () => {
    if (!message.trim() && attachedFiles.length === 0) return;

    const content = message.trim();
    const imageUrls = attachedFiles
      .filter(f => /\.(png|jpg|jpeg|gif|webp|bmp)$/i.test(f.filename))
      .map(f => f.url);
    setMessage('');
    setAttachedFiles([]);
    await sendMessageCore(content, imageUrls);
  }, [attachedFiles, message, sendMessageCore]);

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
    setWarmupMode(projectId, null);
    invalidateProjectQueries();
    toast.info('処理を中断しました');
  }, [invalidateProjectQueries, projectId, resetRecovery, roomId, setWarmupMode, syncActiveStatus]);

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
      {attachedFiles.length > 0 && (
        <div className="mb-2 flex flex-wrap gap-2">
          {attachedFiles.map((file) => {
            const isImg = /\.(png|jpg|jpeg|gif|webp|bmp)$/i.test(file.filename);
            return isImg ? (
              <div key={file.id} className="relative group">
                <img src={file.url} alt={file.filename} className="h-14 w-14 object-cover rounded-md border border-border" />
                <button onClick={() => handleRemoveFile(file.id)} className="absolute -top-1 -right-1 bg-background border border-border rounded-full p-0.5 opacity-0 group-hover:opacity-100 hover:text-destructive transition-opacity">
                  <X className="h-3 w-3" />
                </button>
              </div>
            ) : (
              <div key={file.id} className="flex items-center gap-1.5 px-2 py-1 rounded-md bg-muted border border-border text-xs">
                <File className="h-3 w-3 text-muted-foreground" />
                <span className="max-w-[120px] truncate">{file.filename}</span>
                <button onClick={() => handleRemoveFile(file.id)} className="ml-1 hover:text-destructive">
                  <X className="h-3 w-3" />
                </button>
              </div>
            );
          })}
        </div>
      )}
      <div className="flex items-end gap-2 rounded-xl border border-border bg-input/30 p-2 transition-colors focus-within:border-primary/50">
        <input ref={fileInputRef} type="file" multiple className="hidden" onChange={handleFileSelect} accept="image/*,video/*,.pdf,.txt,.doc,.docx" />
        <Button variant="ghost" size="icon" className="h-7 w-7 shrink-0 text-muted-foreground hover:text-foreground" onClick={handleClickAttach} disabled={isUploading} title="ファイルを添付">
          {isUploading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Paperclip className="h-3.5 w-3.5" />}
        </Button>
        <textarea
          ref={textareaRef}
          value={message}
          onChange={(event) => setMessage(event.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="メッセージを入力..."
          rows={1}
          className="min-h-[32px] max-h-[120px] flex-1 resize-none bg-transparent py-1.5 text-sm focus:outline-none md:text-xs"
        />
        {message.trim() || attachedFiles.length > 0 ? (
          <Button
            size="icon"
            className="h-7 w-7 shrink-0"
            onClick={handleSendMessage}
          >
            <Send className="h-3.5 w-3.5" />
          </Button>
        ) : isBusy ? (
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
            disabled={!message.trim() && attachedFiles.length === 0}
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
  const sendMessageRef = useRef<((content: string) => void) | null>(null);
  const [proposalCollapsed, setProposalCollapsed] = useState(true);
  const [lightboxImage, setLightboxImage] = useState<string | null>(null);
  const { warmupMode } = useRecoveryState(projectId);

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

  const { data: currentRun } = useQuery({
    queryKey: ['current-run', projectId],
    queryFn: () => api.projects.currentRun(projectId),
    enabled: !!projectId,
    retry: false,
    refetchInterval: (query) => (isActiveExecution ? (query.state.error ? 10000 : 2000) : false),
  });

  const { data: allExecutionEvents = [] } = useQuery({
    queryKey: ['execution-events', projectId],
    queryFn: () => api.projects.executionEvents.list(projectId, 500),
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

  const pendingProposal =
    proposals?.find(
      (item: ProjectProposalResponse) =>
        item.status === 'pending' &&
        (!currentRun?.active_proposal_id || item.id === currentRun.active_proposal_id)
    ) ??
    proposals?.find((item: ProjectProposalResponse) => item.status === 'pending');

  const approvedProposal =
    proposals?.find(
      (item: ProjectProposalResponse) =>
        item.status === 'approved' && (!currentRun?.id || item.run_id === currentRun.id)
    ) ??
    proposals?.find((item: ProjectProposalResponse) => item.status === 'approved');
  const transitionLabel = 'Thinking...';
  const currentRunEvents = currentRun
    ? allExecutionEvents.filter((e) => e.run_id === currentRun.id)
    : [];
  const showWarmupBlock =
    isActiveExecution &&
    (!!warmupMode || (!!currentRun && currentRun.state === 'running')) &&
    currentRunEvents.length === 0;

  const approveMutation = useMutation({
    mutationFn: (proposalId: string) => api.projects.proposals.action(projectId, proposalId, 'approve'),
    onSuccess: () => {
      toast.success('提案を承認しました');
      queryClient.invalidateQueries({ queryKey: ['project', projectId] });
      queryClient.invalidateQueries({ queryKey: ['project-proposals', projectId] });
      // 承認メッセージを自動送信 → 通常のチャットSSEフローで実行開始
      sendMessageRef.current?.('提案を承認します。計画に従って実行を開始してください。');
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

    // Warmup block for current live run that has no events yet
    if (showWarmupBlock) {
      timedItems.push({
        item: {
          kind: 'execution-block',
          id: `warmup-${projectId}`,
          steps: [
            {
              label: transitionLabel,
              type: 'reasoning',
            },
          ],
          isLive: true,
        },
        sortKey: Date.now(),
        subKey: 0,
      });
    }

    // Group all execution events by run_id and create a block per run
    const eventsByRun = new Map<string, ExecutionEvent[]>();
    for (const event of allExecutionEvents) {
      const rid = event.run_id || 'unknown';
      if (!eventsByRun.has(rid)) eventsByRun.set(rid, []);
      eventsByRun.get(rid)!.push(event);
    }

    for (const [runId, events] of eventsByRun) {
      const steps = events
        .filter((event) => event.event_type !== 'done' && event.event_type !== 'phase')
        .map(eventToStep);

      if (steps.length > 0) {
        const isLiveRun =
          !!currentRun &&
          runId === currentRun.id &&
          isActiveExecution &&
          currentRun.state === 'running';

        timedItems.push({
          item: {
            kind: 'execution-block',
            id: `exec-${runId}`,
            steps,
            isLive: isLiveRun,
          },
          sortKey: new Date(events[0].created_at).getTime(),
          subKey: 0,
        });
      }
    }

    timedItems.sort((left, right) => left.sortKey - right.sortKey || left.subKey - right.subKey);
    return timedItems.map((item) => item.item);
  }, [allExecutionEvents, currentRun, isActiveExecution, messages, projectId, showWarmupBlock, transitionLabel]);

  const hasAnyContent = displayItems.length > 0;

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [displayItems]);

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

      {pendingProposal ? (
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
            <FileText className="h-3 w-3 text-yellow-600" />
            <span className="text-muted-foreground">承認待ちの提案</span>
            <Loader2 className="h-3 w-3 text-yellow-600" />
          </button>
          {!proposalCollapsed ? (
            <div className="max-h-[40vh] overflow-y-auto px-4 pb-3">
              <div className="prose prose-sm prose-dan max-w-none rounded-lg bg-yellow-500/5 px-3 py-2 text-sm leading-relaxed md:prose-xs md:text-xs">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {pendingProposal.content || ''}
                </ReactMarkdown>
              </div>
            </div>
          ) : null}
        </div>
      ) : null}

      {approvedProposal && !pendingProposal ? (
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

      <div className="relative flex-1 overflow-y-auto">
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

                return <MessageBubble key={item.msg.id} msg={item.msg} onImageClick={setLightboxImage} />;
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
        <ChatInput projectId={projectId} roomId={project.room_id} isSessionActive={isActiveExecution} sendMessageRef={sendMessageRef} />
      ) : null}

      {lightboxImage && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/90"
          onClick={() => setLightboxImage(null)}
        >
          <div
            className="overflow-auto max-h-screen max-w-screen-xl p-4"
            onClick={(e) => e.stopPropagation()}
          >
            <img
              src={lightboxImage}
              alt="拡大表示"
              className="max-w-full max-h-[90vh] object-contain rounded-lg cursor-zoom-out"
              style={{ touchAction: 'pan-x pan-y pinch-zoom' }}
              onClick={() => setLightboxImage(null)}
            />
          </div>
        </div>
      )}
    </div>
  );
}
