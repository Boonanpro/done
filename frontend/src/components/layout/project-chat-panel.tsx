'use client';

import { useState, useRef, useEffect, useCallback } from 'react';
import { X, FolderKanban, Loader2, Clock, MessageSquare, Send, Square } from 'lucide-react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

import { Button } from '@/components/ui/button';
import { api, type MessageResponse, type ProjectStatusType } from '@/lib/api-client';
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

export function ProjectChatPanel({ projectId }: ProjectChatPanelProps) {
  const queryClient = useQueryClient();
  const selectProject = useProjectStore((s) => s.selectProject);
  const user = useAuthStore((state) => state.user);

  const [message, setMessage] = useState('');
  const [isSending, setIsSending] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const refetchMessagesRef = useRef<(() => void) | null>(null);

  const { data: project, isLoading } = useQuery({
    queryKey: ['project', projectId],
    queryFn: () => api.projects.get(projectId),
    enabled: !!projectId,
  });

  const { data: messagesData, isLoading: isLoadingMessages, refetch: refetchMessages } = useQuery({
    queryKey: ['project-messages', project?.room_id],
    queryFn: () => api.rooms.getMessages(project!.room_id!, { limit: 50 }),
    enabled: !!project?.room_id,
    staleTime: 5 * 1000,
    refetchInterval: 3000,
  });

  useEffect(() => { refetchMessagesRef.current = refetchMessages; }, [refetchMessages]);

  const status = project?.status ? STATUS_LABELS[project.status] : null;
  const messages = messagesData?.messages || [];

  // メッセージを古い順に表示
  const displayMessages = [...messages].reverse();

  // 自動スクロール
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isProcessing]);

  // テキストエリア自動リサイズ
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 120)}px`;
    }
  }, [message]);

  // メッセージ送信
  const handleSendMessage = useCallback(async () => {
    if (!message.trim() || isSending || !project?.room_id) return;

    const content = message.trim();
    const roomId = project.room_id;
    setMessage('');
    setIsSending(true);
    setIsProcessing(true);

    // 楽観的更新: ユーザーメッセージを即座に表示
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
            queryClient.setQueryData(queryKey, (old: typeof messagesData) => ({
              messages: [msg, ...(old?.messages || [])],
            }));
          },
          onProcessStep: () => {
            // 簡易版: 処理中フラグのみ（詳細ステップ表示は省略）
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
            // プロジェクトチャット内で別プロジェクトが作られた場合のみ切り替え
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

  // キャンセル
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

  // キーボード操作
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  };

  // Escでキャンセル
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
    <div className="flex flex-col h-full overflow-hidden border-r border-border bg-background">
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
              {status && (
                <span className={`inline-block text-[10px] px-1.5 py-0.5 rounded-full font-medium mt-0.5 ${status.color}`}>
                  {status.label}
                </span>
              )}
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

      {/* Project info */}
      {project?.description && (
        <div className="shrink-0 px-4 py-3 border-b border-border">
          <p className="text-xs text-muted-foreground leading-relaxed">
            {project.description}
          </p>
          {project.created_at && (
            <div className="flex items-center gap-1 mt-2 text-[10px] text-muted-foreground/60">
              <Clock className="h-3 w-3" />
              <span>{new Date(project.created_at).toLocaleDateString('ja-JP')}</span>
            </div>
          )}
        </div>
      )}

      {/* Messages */}
      <div className="flex-1 overflow-y-auto">
        {isLoadingMessages ? (
          <div className="flex items-center justify-center p-6">
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          </div>
        ) : displayMessages.length === 0 && !isProcessing ? (
          <div className="flex flex-col items-center justify-center p-6 h-full">
            <MessageSquare className="h-10 w-10 text-muted-foreground/20 mb-3" />
            <p className="text-xs text-muted-foreground">
              メッセージはまだありません
            </p>
          </div>
        ) : (
          <div className="flex flex-col gap-3 p-4">
            {displayMessages.map((msg: MessageResponse) => (
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
            ))}
            {/* 処理中インジケータ */}
            {isProcessing && (
              <div className="flex justify-start">
                <div className="flex items-center gap-2 bg-muted rounded-lg px-3 py-2">
                  <Loader2 className="h-3 w-3 animate-spin text-primary" />
                  <span className="text-xs text-muted-foreground">処理中...</span>
                </div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>
        )}
      </div>

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
