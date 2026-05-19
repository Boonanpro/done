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
  Reply,
  Send,
  Square,
  Terminal,
  Trash2,
  X,
  XCircle,
  Presentation,
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
  type ProjectStatusType,
  type ReplyToMessage,
} from '@/lib/api-client';
import { useRouter } from 'next/navigation';
import { useProjectRecovery } from '@/hooks/useProjectRecovery';
import { useIsMobile } from '@/hooks/useIsMobile';
import { useAuthStore } from '@/stores/auth-store';
import { useProjectStore, useRecoveryActions, useRecoveryState } from '@/stores/project-store';
import { usePreviewStore, type ArtifactRecord, type SelectedElement } from '@/stores/preview-store';
import { PreviewPane } from '@/components/preview/preview-pane';

interface ProjectChatPanelProps {
  projectId: string;
}

const INITIAL_CHAT_RENDER_COUNT = 80;
const CHAT_RENDER_INCREMENT = 80;

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
    <div className="flex items-start gap-1.5 text-sm md:text-[15px] leading-relaxed">
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

  // 自動展開なし（ユーザーが閉じたらそのまま維持）

  // 自動スクロールなし（ユーザーが自由にスクロール位置を維持できるようにする）

  if (steps.length === 0 && !isLive) return null;

  return (
    <div className="my-1">
      <div className="max-w-[90%] overflow-hidden rounded-lg border border-border/40 bg-muted/20">
        <button
          onClick={() => setIsCollapsed((value) => !value)}
          className="flex w-full items-center gap-1.5 px-3 py-1.5 text-sm text-muted-foreground transition-colors hover:bg-muted/30 md:text-[15px]"
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
                <div className="flex items-center gap-1.5 text-sm text-muted-foreground md:text-[15px]">
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

function parseMediaContent(content: string): { images: string[]; videos: string[]; files: { name: string; url: string }[]; text: string } {
  const images: string[] = [];
  const videos: string[] = [];
  const files: { name: string; url: string }[] = [];
  const text = content
    .replace(/<dan-context>[\s\S]*?<\/dan-context>/g, '')
    .replace(/\[動画分析結果\(Gemini\):\n[\s\S]*?\n\]/g, '')
    .replace(/\[添付画像: ([^\]]+)\]/g, (_, raw: string) => {
      // ブラケット内の表記揺れを吸収:
      //   "name (URL)" / "URL" / "/api/v1/files/x.png" / "C:\path\x.png" / "x.png"
      // いずれも最終的に /api/v1/files/<filename> へ正規化する。
      const urlMatch = raw.match(/https?:\/\/\S+|\/api\/\S+/);
      let token = (urlMatch ? urlMatch[0] : raw.trim().split(/\s+/).pop() || '').trim();
      // 末尾の記号（`)` `,` `.` `;` `"` `'`）を剥がす
      token = token.replace(/[)\],.;"'`]+$/, '');
      if (/^https?:\/\//.test(token)) {
        const apiMatch = token.match(/\/api\/v1\/files\/[^?#\s)]+/);
        if (apiMatch) {
          images.push(apiMatch[0]);
        } else {
          images.push(token);
        }
        return '';
      }
      if (token.startsWith('/api/')) {
        images.push(token);
        return '';
      }
      const filename = token.replace(/\\/g, '/').split('/').pop();
      if (filename) images.push(`/api/v1/files/${filename}`);
      return '';
    })
    .replace(/\[添付動画: (.+?) \((.+?)\)\](?:\s*※分析に失敗しました)?/g, (_, _name, url) => {
      videos.push(url);
      return '';
    })
    .replace(/\[添付ファイル: (.+?) \((.+?)\)\]/g, (_, name, url) => {
      if (/\.(mp4|avi|mov|mkv|webm)$/i.test(name)) {
        videos.push(url);
      } else {
        files.push({ name, url });
      }
      return '';
    })
    .trim();
  return { images, videos, files, text };
}

const ReplyQuote = memo(function ReplyQuote({ replyTo }: { replyTo: ReplyToMessage }) {
  const truncated = (replyTo.content || '').replace(/\[添付[^\]]*\]/g, '').trim().slice(0, 80);
  const label = replyTo.sender_type === 'ai' ? 'ダン' : replyTo.sender_name;

  const handleClick = useCallback(() => {
    const el = document.querySelector(`[data-message-id="${replyTo.id}"]`);
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'center' });
      el.classList.add('ring-2', 'ring-primary/50', 'rounded-lg');
      setTimeout(() => el.classList.remove('ring-2', 'ring-primary/50', 'rounded-lg'), 1500);
    }
  }, [replyTo.id]);

  return (
    <div
      onClick={handleClick}
      className="flex items-start gap-1.5 rounded-md bg-muted/60 border-l-2 border-primary/50 px-2.5 py-1.5 text-xs text-muted-foreground mb-1 max-w-full overflow-hidden cursor-pointer hover:bg-muted/80 transition-colors"
    >
      <Reply className="h-3 w-3 mt-0.5 shrink-0 rotate-180" />
      <div className="min-w-0">
        <span className="font-medium text-foreground/80">{label}</span>
        <p className="truncate">{truncated || '(メディア)'}</p>
      </div>
    </div>
  );
});

const MessageBubble = memo(function MessageBubble({ msg, onImageClick, onReply }: { msg: MessageResponse; onImageClick?: (url: string) => void; onReply?: (msg: MessageResponse) => void }) {

  if (msg.sender_type === 'human') {
    const { images, videos, files, text } = parseMediaContent(msg.content || '');
    return (
      <div className="flex flex-col items-end max-w-[85%] ml-auto">
        {msg.reply_to_message && <ReplyQuote replyTo={msg.reply_to_message} />}
        <div className="group flex items-start gap-1">
          {onReply && !msg.id.startsWith('temp-') && (
            <button
              onClick={() => onReply(msg)}
              className="mt-1.5 opacity-0 group-hover:opacity-100 transition-opacity text-muted-foreground hover:text-foreground p-1 rounded"
              title="返信"
            >
              <Reply className="h-3.5 w-3.5" />
            </button>
          )}
          <div className="flex flex-col items-end gap-1">
          {images.map((url, i) => (
            <img
              key={i}
              src={url}
              alt="添付画像"
              className="rounded-xl max-w-full max-h-64 object-contain border border-primary/20 cursor-zoom-in"
              onClick={() => onImageClick?.(url)}
            />
          ))}
          {videos.map((url, i) => (
            <video
              key={`vid-${i}`}
              src={url}
              controls
              className="rounded-xl max-w-full border border-primary/20"
              style={{ maxHeight: '300px' }}
            />
          ))}
          {files.map((f, i) => (
            <a
              key={`file-${i}`}
              href={f.url}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-2 rounded-lg border border-primary/20 bg-primary/90 px-3 py-2 text-sm text-primary-foreground transition-colors hover:bg-primary md:text-[15px]"
            >
              <FileText className="h-4 w-4 shrink-0" />
              <span className="truncate max-w-[200px]">{f.name}</span>
            </a>
          ))}
          {text && (
            <div className="rounded-lg bg-primary px-3 py-2 text-base leading-relaxed text-primary-foreground md:text-[17px] whitespace-pre-wrap">
              {text}
            </div>
          )}
          </div>
        </div>
      </div>
    );
  }

  const rawContent = msg.content || '';
  // Extract proposal blocks and split content into segments
  const proposalRegex = /```proposal\n([^\n]+)\n```/g;
  const proposals: { filename: string; url: string }[] = [];
  let match;
  while ((match = proposalRegex.exec(rawContent)) !== null) {
    const filename = match[1].trim();
    proposals.push({ filename, url: `/api/v1/proposals/${filename}` });
  }
  // Remove proposal blocks from text before passing to parseMediaContent
  const contentWithoutProposals = rawContent.replace(proposalRegex, '').trim();

  const { images: aiImages, videos: aiVideos, files: aiFiles, text: aiText } = parseMediaContent(contentWithoutProposals);
  const hasMedia = aiImages.length > 0 || aiVideos.length > 0 || aiFiles.length > 0;

  return (
    <div className="group relative">
      {onReply && !msg.id.startsWith('temp-') && (
        <button
          onClick={() => onReply(msg)}
          className="absolute -right-1 top-0 opacity-0 group-hover:opacity-100 transition-opacity text-muted-foreground hover:text-foreground p-1 rounded"
          title="返信"
        >
          <Reply className="h-3.5 w-3.5" />
        </button>
      )}
      {msg.reply_to_message && <ReplyQuote replyTo={msg.reply_to_message} />}
      {hasMedia && (
        <div className="flex flex-col gap-1.5 mb-2">
          {aiImages.map((url, i) => (
            <img
              key={i}
              src={url}
              alt="添付画像"
              className="rounded-xl max-w-full max-h-80 object-contain border border-border cursor-zoom-in"
              onClick={() => onImageClick?.(url)}
            />
          ))}
          {aiVideos.map((url, i) => (
            <video
              key={`vid-${i}`}
              src={url}
              controls
              className="rounded-xl max-w-full border border-border"
              style={{ maxHeight: '300px' }}
            />
          ))}
          {aiFiles.map((f, i) => (
            <a
              key={`file-${i}`}
              href={f.url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-2 rounded-lg border border-border bg-card px-3 py-2 text-sm text-foreground shadow-sm transition-colors hover:bg-muted md:text-[15px]"
            >
              <FileText className="h-4 w-4 shrink-0 text-primary" />
              <span className="truncate max-w-[250px]">{f.name}</span>
            </a>
          ))}
        </div>
      )}
      {aiText && (
        <div className="prose prose-base prose-dan max-w-none text-base leading-relaxed text-foreground md:prose-base md:text-[17px]">
          <ReactMarkdown remarkPlugins={[remarkGfm]} components={{ a({ href, children }) { return <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>; }, img({ src, alt }) { const imgSrc = typeof src === 'string' && src ? src : null; if (!imgSrc) return null; return <img src={imgSrc} alt={alt || ''} className="rounded-xl max-w-full max-h-80 object-contain border border-border cursor-zoom-in" onClick={() => onImageClick?.(imgSrc)} />; } }}>{aiText}</ReactMarkdown>
        </div>
      )}
      {proposals.length > 0 && (
        <div className="flex flex-wrap gap-3 mt-2">
          {proposals.map((p, i) => (
            <a
              key={`proposal-${i}`}
              href={p.url}
              target="_blank"
              rel="noopener noreferrer"
              className="group/card block w-[280px] rounded-xl border border-border bg-card shadow-sm overflow-hidden transition-all hover:shadow-md hover:border-primary/40"
            >
              <div className="relative w-full h-[180px] overflow-hidden bg-muted">
                <iframe
                  src={p.url}
                  title={p.filename}
                  className="absolute top-0 left-0 pointer-events-none"
                  style={{ width: '1400px', height: '900px', transform: 'scale(0.2)', transformOrigin: 'top left', border: 'none' }}
                  tabIndex={-1}
                  loading="lazy"
                />
                <div className="absolute inset-0 bg-gradient-to-t from-black/30 to-transparent opacity-0 group-hover/card:opacity-100 transition-opacity flex items-end justify-center pb-3">
                  <span className="text-xs text-white bg-black/50 px-2 py-1 rounded-md">クリックで開く</span>
                </div>
              </div>
              <div className="px-3 py-2.5 flex items-center gap-2">
                <FileText className="h-4 w-4 shrink-0 text-primary" />
                <span className="text-sm font-medium truncate">{p.filename.replace('.html', '')}</span>
              </div>
            </a>
          ))}
        </div>
      )}
    </div>
  );
});

type DanSkill = { name: string; display_name: string; description: string };

function ChatInput({
  projectId,
  roomId,
  isSessionActive,
  sendMessageRef,
  onSseStateChange,
  replyTo,
  onClearReply,
  onSubmitComment,
}: {
  projectId: string;
  roomId: string;
  isSessionActive: boolean;
  sendMessageRef?: React.MutableRefObject<((content: string) => void) | null>;
  onSseStateChange?: (connected: boolean) => void;
  replyTo?: MessageResponse | null;
  onClearReply?: () => void;
  onSubmitComment?: () => void;
}) {
  const inspectorElement = usePreviewStore((s) => s.selectedElement);
  const inspectorDraft = usePreviewStore((s) => s.popoverDraft);
  const previewMode = usePreviewStore((s) => s.inspectorMode);
  const clearInspectorSelection = usePreviewStore((s) => s.clearSelection);
  // ChatInput のミラーモードは「コメントモードで要素選択中」の時だけ有効
  const isCommentMode = !!inspectorElement && previewMode === 'comment';
  const [message, setMessage] = useState('');
  const [attachedFiles, setAttachedFiles] = useState<FileUploadResponse[]>([]);
  const [isUploading, setIsUploading] = useState(false);
  const [isDragging, setIsDragging] = useState(false);
  const [showSkillSuggestions, setShowSkillSuggestions] = useState(false);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const skillsCacheRef = useRef<DanSkill[] | null>(null);
  const [skills, setSkills] = useState<DanSkill[]>([]);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const pendingMessageRef = useRef<{ text: string; files: typeof attachedFiles; replyTo: typeof replyTo } | null>(null);
  const aiRespondedRef = useRef(false);
  // キャンセル後の再送信時にUPDATEすべきDBメッセージID
  const replaceMessageIdRef = useRef<string | null>(null);
  // 今回のSSEで受信したサーバー上のメッセージID
  const serverMessageIdRef = useRef<string | null>(null);
  const titleGeneratedRef = useRef(false);
  const streamRequestRef = useRef(0);
  const queryClient = useQueryClient();
  const router = useRouter();
  const user = useAuthStore((state) => state.user);
  const selectProject = useProjectStore((s) => s.selectProject);
  const { isInterrupted } = useRecoveryState(projectId);
  const { resetRecovery, setInterrupted, setWarmupMode } = useRecoveryActions();

  useProjectRecovery({ projectId, roomId });

  // プロジェクト切り替え時にreplace状態をリセット
  useEffect(() => {
    replaceMessageIdRef.current = null;
    serverMessageIdRef.current = null;
  }, [roomId]);

  // Focus textarea when reply is selected
  useEffect(() => {
    if (replyTo) {
      textareaRef.current?.focus();
    }
  }, [replyTo]);

  // Skill suggestions for slash commands
  const fetchSkills = useCallback(async () => {
    if (skillsCacheRef.current) {
      setSkills(skillsCacheRef.current);
      return;
    }
    try {
      const res = await fetch(`${window.location.origin}/api/v1/chat/dan/skills`, {
        credentials: 'include',
      });
      if (res.ok) {
        const data = await res.json();
        skillsCacheRef.current = data.skills || [];
        setSkills(skillsCacheRef.current!);
      }
    } catch {
      // ignore
    }
  }, []);

  const skillFilter = message.startsWith('/') ? message.slice(1).toLowerCase() : '';
  const filteredSkills = useMemo(
    () =>
      showSkillSuggestions
        ? skills.filter(
            (s) =>
              s.name.toLowerCase().includes(skillFilter) ||
              s.display_name.toLowerCase().includes(skillFilter)
          )
        : [],
    [showSkillSuggestions, skills, skillFilter]
  );

  const insertSkill = useCallback(
    (skill: DanSkill) => {
      setMessage(`/${skill.name} `);
      setShowSkillSuggestions(false);
      setSelectedIndex(0);
      textareaRef.current?.focus();
    },
    []
  );

  // SSEストリーム接続中はポーリングを無効化するためのフラグ
  const sseConnectedRef = useRef(false);
  // ローカルのアクティブ状態（propsの遅延を回避）
  const [localActive, setLocalActive] = useState(false);

  const syncActiveStatus = useCallback(
    (active: boolean) => {
      sseConnectedRef.current = active;
      setLocalActive(active);
      queryClient.setQueryData<ActiveSessionStatus>(['session-active', roomId], {
        active,
        session_id: roomId,
        started_at: active ? Date.now() : null,
      });
    },
    [queryClient, roomId]
  );

  // ローカル状態を優先。ローカルがfalseならpropsに関係なくfalse
  const isBusy = isInterrupted || localActive;

  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;
    if (!message.trim()) {
      textarea.style.height = '32px';
      return;
    }
    textarea.style.height = '32px';
    textarea.style.height = `${Math.min(textarea.scrollHeight, 480)}px`;
  }, [message]);

  const invalidateProjectQueries = useCallback(() => {
    // session-active はSSEイベントで直接制御するためinvalidateしない
    // (invalidateするとバックエンドにrefetchされ、プロセスクリーンアップ中にactive=trueが返る)
    queryClient.refetchQueries({ queryKey: ['project-messages', roomId] });
    queryClient.invalidateQueries({ queryKey: ['current-run', projectId] });
    queryClient.invalidateQueries({ queryKey: ['execution-events', projectId] });
    queryClient.invalidateQueries({ queryKey: ['project', projectId] });
    queryClient.invalidateQueries({ queryKey: ['chat-artifacts', projectId] });
  }, [projectId, queryClient, roomId]);

  const uploadFiles = useCallback(async (fileList: File[]) => {
    if (fileList.length === 0) return;
    setIsUploading(true);
    let currentFile: File | undefined;
    try {
      const uploaded: FileUploadResponse[] = [];
      for (const file of fileList) {
        currentFile = file;
        if (file.size > 100 * 1024 * 1024) {
          toast.error(`${file.name} は100MB以上のファイルは添付できません`);
          continue;
        }
        uploaded.push(await api.files.upload(file));
      }
      setAttachedFiles(prev => [...prev, ...uploaded]);
    } catch (err: unknown) {
      // PWA等で詳細不明エラーを切り分けるため、原因情報を最大限可視化する
      const errAny = err as {
        status?: number;
        statusText?: string;
        message?: string;
        name?: string;
        data?: { body?: string; server?: string; via?: string; cfRay?: string };
      };
      const errParts: string[] = [];
      if (errAny?.status !== undefined) errParts.push(`HTTP ${errAny.status}${errAny.statusText ? ' ' + errAny.statusText : ''}`);
      if (errAny?.name && errAny.name !== 'Error') errParts.push(errAny.name);
      if (errAny?.message) errParts.push(errAny.message);
      const errSummary = errParts.length > 0 ? errParts.join(' | ') : String(err);
      const fileSummary = currentFile
        ? `${currentFile.name || '(no name)'} [${currentFile.type || 'no-type'}, ${currentFile.size}B]`
        : '(no file)';
      const origin = typeof window !== 'undefined' ? window.location.origin : '?';
      const d = errAny?.data;
      const respParts: string[] = [];
      if (d?.server) respParts.push(`server=${d.server}`);
      if (d?.via) respParts.push(`via=${d.via}`);
      if (d?.cfRay) respParts.push(`cf=${d.cfRay}`);
      const respHeader = respParts.length > 0 ? `\nresp: ${respParts.join(' / ')}` : '';
      const respBody = d?.body ? `\nbody: ${d.body.slice(0, 200)}` : '';
      console.error('[uploadFiles] failed:', err, currentFile, 'origin=', origin);
      toast.error(
        `アップロード失敗: ${errSummary}\norigin: ${origin}\nfile: ${fileSummary}${respHeader}${respBody}`,
        { duration: 30000 },
      );
    } finally {
      setIsUploading(false);
    }
  }, []);

  const handleFileSelect = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files || files.length === 0) return;
    await uploadFiles(Array.from(files));
    if (fileInputRef.current) fileInputRef.current.value = '';
  }, [uploadFiles]);

  const handlePaste = useCallback(async (e: React.ClipboardEvent) => {
    const items = e.clipboardData?.items;
    if (!items) return;
    const files: File[] = [];
    for (const item of Array.from(items)) {
      if (item.kind === 'file') {
        const file = item.getAsFile();
        if (file) files.push(file);
      }
    }
    if (files.length > 0) {
      e.preventDefault();
      await uploadFiles(files);
    }
  }, [uploadFiles]);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    // Only reset if leaving the container (not entering a child)
    if (!e.currentTarget.contains(e.relatedTarget as Node)) {
      setIsDragging(false);
    }
  }, []);

  const handleDrop = useCallback(async (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
    const files = Array.from(e.dataTransfer.files);
    if (files.length > 0) {
      await uploadFiles(files);
    }
  }, [uploadFiles]);

  const handleRemoveFile = useCallback((fileId: string) => {
    setAttachedFiles(prev => prev.filter(f => f.id !== fileId));
  }, []);

  const handleClickAttach = useCallback(() => {
    fileInputRef.current?.click();
  }, []);

  const sendMessageCore = useCallback(async (content: string, imageUrls: string[] = [], fileUrls: { name: string; url: string }[] = [], replyToMsg?: MessageResponse | null) => {
    if (!content.trim() && imageUrls.length === 0 && fileUrls.length === 0) return;

    const imagePrefix = imageUrls.map(url => `[添付画像: ${url}]`).join('\n');
    const filePrefix = fileUrls.map(f => `[添付ファイル: ${f.name} (${f.url})]`).join('\n');
    const mediaParts = [imagePrefix, filePrefix].filter(Boolean).join('\n');
    const optimisticContent = mediaParts
      ? (content ? `${mediaParts}\n\n${content}` : mediaParts)
      : content;
    const requestId = streamRequestRef.current + 1;
    streamRequestRef.current = requestId;

    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }

    syncActiveStatus(true);
    onSseStateChange?.(true);
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
      ...(replyToMsg ? {
        reply_to_id: replyToMsg.id,
        reply_to_message: {
          id: replyToMsg.id,
          sender_name: replyToMsg.sender_name,
          sender_type: replyToMsg.sender_type,
          content: replyToMsg.content,
          created_at: replyToMsg.created_at,
        },
      } : {}),
    };

    const queryKey = ['project-messages', roomId];
    const currentReplaceId = replaceMessageIdRef.current;
    if (currentReplaceId) {
      // 再送信: 既存メッセージの内容を楽観的に上書き
      queryClient.setQueryData(queryKey, (old: { messages: MessageResponse[] } | undefined) => ({
        messages: (old?.messages || []).map((m: MessageResponse) =>
          m.id === currentReplaceId ? { ...m, content: optimisticContent } : m
        ),
      }));
      replaceMessageIdRef.current = null;
    } else {
      // 新規送信: 楽観的メッセージを追加
      queryClient.setQueryData(queryKey, (old: { messages: MessageResponse[] } | undefined) => ({
        messages: [optimisticUserMessage, ...(old?.messages || [])],
      }));
    }

    const controller = new AbortController();
    abortControllerRef.current = controller;

    try {
      await api.sm.sendMessageStream(
        { message: content, session_id: roomId, ...(imageUrls.length > 0 ? { image_urls: imageUrls } : {}), ...(fileUrls.length > 0 ? { file_urls: fileUrls } : {}), ...(replyToMsg ? { reply_to_id: replyToMsg.id } : {}), ...(currentReplaceId ? { replace_message_id: currentReplaceId } : {}) },
        {
          onUserMessage: (msg) => {
            if (streamRequestRef.current !== requestId) return;
            serverMessageIdRef.current = msg.id;
            if (currentReplaceId) {
              // replace: 既存メッセージの内容をサーバー版で上書き
              queryClient.setQueryData(
                queryKey,
                (old: { messages: MessageResponse[] } | undefined) => ({
                  messages: (old?.messages || []).map((m: MessageResponse) =>
                    m.id === currentReplaceId ? msg : m
                  ),
                })
              );
            } else {
              // 新規: tempメッセージをサーバー版で置換
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
            }
          },
          onAIMessage: () => {
            if (streamRequestRef.current !== requestId) return;
            syncActiveStatus(false);
            setWarmupMode(projectId, null);
            queryClient.invalidateQueries({ queryKey: ['project-messages', roomId] });
            queryClient.invalidateQueries({ queryKey: ['current-run', projectId] });
            queryClient.invalidateQueries({ queryKey: ['execution-events', projectId] });
            queryClient.invalidateQueries({ queryKey: ['projects'] });
          },
          onProcessStep: (_step: ProcessStep) => {
            if (streamRequestRef.current !== requestId) return;
            aiRespondedRef.current = true;
            pendingMessageRef.current = null;
            replaceMessageIdRef.current = null;
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
            onSseStateChange?.(false);
            invalidateProjectQueries();

            if (!titleGeneratedRef.current) {
              const cached = queryClient.getQueryData<{ title?: string }>(['project', projectId]);
              const currentTitle = cached?.title ?? '';
              const isDefaultTitle = !currentTitle || currentTitle === '新しいプロジェクト';

              // すでにカスタムタイトルがある場合は以降チェック不要
              if (!isDefaultTitle) {
                titleGeneratedRef.current = true;
              } else {
                // 1往復（=2件）以上でタイトルを生成する
                const msgs = queryClient.getQueryData<{ messages: unknown[] }>(['project-messages', roomId]);
                const msgCount = msgs?.messages?.length ?? 0;
                if (msgCount >= 2) {
                  titleGeneratedRef.current = true;
                  api.projects
                    .suggestTitle(roomId)
                    .then(({ title }) => {
                      if (title && title !== '新しいプロジェクト') {
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
              }
            }
          },
          onError: (error) => {
            if (streamRequestRef.current !== requestId) return;
            syncActiveStatus(false);
            setInterrupted(projectId, false);
            setWarmupMode(projectId, null);
            onSseStateChange?.(false);
            toast.error(error || 'メッセージの送信に失敗しました');
          },
          onProjectCreated: (createdProjectId) => {
            if (streamRequestRef.current !== requestId) return;
            queryClient.invalidateQueries({ queryKey: ['projects'] });
            if (createdProjectId !== projectId) {
              selectProject(createdProjectId);
              router.push(`/chat/${createdProjectId}`);
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

    const isImageFile = (name: string) => /\.(png|jpg|jpeg|gif|webp|bmp)$/i.test(name);
    const imageUrls = attachedFiles.filter(f => isImageFile(f.filename)).map(f => f.url);
    const fileUrls = attachedFiles.filter(f => !isImageFile(f.filename)).map(f => ({ name: f.filename, url: f.url }));

    const content = message.trim();
    const currentReplyTo = replyTo;
    pendingMessageRef.current = { text: message, files: [...attachedFiles], replyTo };
    aiRespondedRef.current = false;
    serverMessageIdRef.current = null;
    setMessage('');
    setAttachedFiles([]);
    onClearReply?.();
    // Immediately bump this project to top of sidebar
    queryClient.invalidateQueries({ queryKey: ['projects'] });
    await sendMessageCore(content, imageUrls, fileUrls, currentReplyTo);
  }, [attachedFiles, message, sendMessageCore, queryClient, replyTo, onClearReply]);

  const handleCancel = useCallback(async () => {
    const pending = pendingMessageRef.current;
    const wasBeforeAI = !aiRespondedRef.current && !!pending;

    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }

    // AI未応答キャンセル → テキストを入力欄に復元 + 次回送信でUPDATEするIDを記録
    if (wasBeforeAI) {
      setMessage(pending.text);
      setAttachedFiles(pending.files);
      if (serverMessageIdRef.current) {
        replaceMessageIdRef.current = serverMessageIdRef.current;
      }
    }
    pendingMessageRef.current = null;
    serverMessageIdRef.current = null;

    try {
      await api.sm.cancelSession(roomId);
    } catch (error) {
      console.error('Failed to cancel session:', error);
    }

    syncActiveStatus(false);
    onSseStateChange?.(false);
    resetRecovery(projectId);
    setWarmupMode(projectId, null);
    invalidateProjectQueries();
    if (!wasBeforeAI) {
      toast.info('処理を中断しました');
    }
  }, [invalidateProjectQueries, onSseStateChange, projectId, resetRecovery, roomId, setWarmupMode, syncActiveStatus]);

  const handleKeyDown = useCallback(
    (event: React.KeyboardEvent) => {
      if (showSkillSuggestions && filteredSkills.length > 0) {
        if (event.key === 'ArrowDown') {
          event.preventDefault();
          setSelectedIndex((prev) => (prev + 1) % filteredSkills.length);
          return;
        }
        if (event.key === 'ArrowUp') {
          event.preventDefault();
          setSelectedIndex((prev) => (prev - 1 + filteredSkills.length) % filteredSkills.length);
          return;
        }
        if (event.key === 'Enter' || event.key === 'Tab') {
          event.preventDefault();
          insertSkill(filteredSkills[selectedIndex]);
          return;
        }
      }
      if (event.key === 'Escape' && showSkillSuggestions) {
        event.preventDefault();
        setShowSkillSuggestions(false);
        return;
      }
      const isMobile = window.matchMedia('(max-width: 767px)').matches;
      if (event.key === 'Enter' && !event.shiftKey && !isMobile) {
        event.preventDefault();
        handleSendMessage();
      }
    },
    [handleSendMessage, showSkillSuggestions, filteredSkills, selectedIndex, insertSkill]
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
    <div
      className={`relative shrink-0 border-t p-3 transition-colors ${isDragging ? 'border-primary bg-primary/5' : 'border-border'}`}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      {isDragging && (
        <div className="pointer-events-none absolute inset-0 z-50 flex items-center justify-center rounded-lg border-2 border-dashed border-primary bg-primary/10">
          <span className="text-sm font-medium text-primary">ファイルをドロップして添付</span>
        </div>
      )}
      {replyTo && (
        <div className="mb-2 flex items-center gap-2 rounded-lg border border-primary/30 bg-primary/5 px-3 py-2">
          <Reply className="h-3.5 w-3.5 shrink-0 text-primary" />
          <div className="min-w-0 flex-1">
            <span className="text-xs font-medium text-primary">
              {replyTo.sender_type === 'ai' ? 'ダン' : replyTo.sender_name}に返信
            </span>
            <p className="truncate text-xs text-muted-foreground">
              {(replyTo.content || '').replace(/\[添付[^\]]*\]/g, '').trim().slice(0, 100) || '(メディア)'}
            </p>
          </div>
          <button
            onClick={onClearReply}
            className="shrink-0 text-muted-foreground hover:text-foreground"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      )}
      {showSkillSuggestions && filteredSkills.length > 0 && (
        <div className="absolute bottom-full left-3 right-3 mb-1 max-h-[200px] overflow-y-auto rounded-lg border border-border bg-popover shadow-lg z-50">
          {filteredSkills.map((skill, idx) => (
            <button
              key={skill.name}
              ref={(el) => {
                if (idx === selectedIndex && el) {
                  el.scrollIntoView({ block: 'nearest' });
                }
              }}
              className={`flex w-full items-start gap-2 px-3 py-2 text-left text-base transition-colors hover:bg-accent md:text-[17px] ${
                idx === selectedIndex ? 'bg-accent' : ''
              }`}
              onMouseEnter={() => setSelectedIndex(idx)}
              onMouseDown={(e) => {
                e.preventDefault();
                insertSkill(skill);
              }}
            >
              <span className="font-medium text-foreground shrink-0">/{skill.name}</span>
              <span className="text-muted-foreground truncate">{skill.description}</span>
            </button>
          ))}
        </div>
      )}
      {attachedFiles.length > 0 && (
        <div className="mb-2 flex flex-wrap gap-2">
          {attachedFiles.map((file) => {
            const isImg = /\.(png|jpg|jpeg|gif|webp|bmp)$/i.test(file.filename);
            const isVideo = /\.(mp4|avi|mov|mkv|webm)$/i.test(file.filename);
            return isImg ? (
              <div key={file.id} className="relative group">
                <img src={file.url} alt={file.filename} className="h-14 w-14 object-cover rounded-md border border-border" />
                <button onClick={() => handleRemoveFile(file.id)} className="absolute -top-1 -right-1 bg-background border border-border rounded-full p-0.5 opacity-0 group-hover:opacity-100 hover:text-destructive transition-opacity">
                  <X className="h-3 w-3" />
                </button>
              </div>
            ) : isVideo ? (
              <div key={file.id} className="relative group">
                <video src={file.url} className="h-14 w-14 object-cover rounded-md border border-border" muted />
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
      {isCommentMode && inspectorElement && (
        <div className="mb-2 flex items-center gap-1.5 rounded-md border border-primary/40 bg-primary/5 px-2 py-1 text-xs">
          <span className="rounded bg-primary/20 px-1.5 py-0.5 font-mono font-medium text-primary">
            @{inspectorElement.refId}
          </span>
          <span className="truncate text-muted-foreground">
            &lt;{inspectorElement.tagName}&gt;
            {inspectorElement.text ? ` "${inspectorElement.text}"` : ''}
          </span>
          <button
            onClick={clearInspectorSelection}
            className="ml-auto shrink-0 text-muted-foreground hover:text-foreground"
            title="選択解除 (Esc)"
          >
            <X className="h-3 w-3" />
          </button>
        </div>
      )}
      <div className={`flex items-end gap-2 rounded-xl border bg-input/30 p-2 transition-colors ${isCommentMode ? 'border-primary/40' : 'border-border focus-within:border-primary/50'}`}>
        <input ref={fileInputRef} type="file" multiple className="hidden" onChange={handleFileSelect} accept="*/*" />
        <Button variant="ghost" size="icon" className="h-7 w-7 shrink-0 text-muted-foreground hover:text-foreground" onClick={handleClickAttach} disabled={isUploading || isCommentMode} title="ファイルを添付">
          {isUploading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Paperclip className="h-3.5 w-3.5" />}
        </Button>
        <textarea
          ref={textareaRef}
          value={isCommentMode ? inspectorDraft : message}
          readOnly={isCommentMode}
          onChange={(event) => {
            if (isCommentMode) return;
            const val = event.target.value;
            setMessage(val);
            if (val.startsWith('/') && !val.includes(' ')) {
              setShowSkillSuggestions(true);
              setSelectedIndex(0);
              fetchSkills();
            } else {
              setShowSkillSuggestions(false);
            }
          }}
          onKeyDown={(event) => {
            if (isCommentMode) {
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault();
                if (inspectorDraft.trim()) onSubmitComment?.();
              }
              return;
            }
            handleKeyDown(event);
          }}
          onPaste={handlePaste}
          placeholder={isCommentMode ? '右ペインのコメント欄で入力...' : 'メッセージを入力...'}
          rows={1}
          className={`min-h-[32px] max-h-[480px] flex-1 resize-none bg-transparent py-1.5 text-base focus:outline-none md:text-[17px] ${isCommentMode ? 'cursor-not-allowed text-foreground/90' : ''}`}
        />
        {isCommentMode ? (
          <Button
            size="icon"
            className="h-7 w-7 shrink-0"
            onClick={() => onSubmitComment?.()}
            disabled={!inspectorDraft.trim()}
            title="コメント送信"
          >
            <Send className="h-3.5 w-3.5" />
          </Button>
        ) : message.trim() || attachedFiles.length > 0 ? (
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

function slugToFilePath(slug: string, previewUrl: string): string {
  // /demo/xxx → frontend/src/app/demo/xxx/page.tsx
  const normalized = previewUrl
    .replace(new RegExp(`^/preview/${slug}(?:/.*)?$`), `/artifacts/${slug}`)
    .replace(new RegExp(`^/artifacts/${slug}(?:/.*)?$`), `/artifacts/${slug}`);
  const trimmed = normalized.replace(/^\//, '');
  return `frontend/src/app/${trimmed}/page.tsx`;
}

function composeCommentMessage(
  text: string,
  element: SelectedElement,
  artifact: ArtifactRecord | null
): string {
  const lines: string[] = ['<dan-context>'];
  lines.push('kind: element-comment');
  lines.push('note: |');
  lines.push('  ユーザーは成果物上で要素を選択し、その要素について発言している。');
  lines.push('  発言の意図は文面から判断: 修正要望 / 質問 / 議論 / 提案 など自由。');
  lines.push('  修正を依頼された場合のみファイルを編集する。');
  if (artifact) {
    lines.push('artifact:');
    lines.push(`  slug: ${artifact.slug}`);
    lines.push(`  label: ${artifact.label || artifact.slug}`);
    lines.push(`  file: ${slugToFilePath(artifact.slug, artifact.preview_url)}`);
    lines.push(`  preview-url: ${artifact.preview_url}`);
  }
  if (element.tagName === 'img' || element.tagName === 'video' || (element.className || '').match(/bg-\[url/)) {
    lines.push('intent-hint: |');
    lines.push('  選択要素は視覚メディア (<img> / <video> / 背景画像)。');
    lines.push('  文面が「画像を〜に変えて」なら image-gen スキル (/api/v1/images/edit) 経由で差し替え。');
    lines.push('  文面が「動画にして」「動かして」「アニメーションに」なら video-gen スキル');
    lines.push('  (/api/v1/videos/generate + reference_image_url で image-to-video) を使い、');
    lines.push('  対象ファイルの <img> を <video autoPlay loop muted playsInline> に書き換える。');
    lines.push('  文面が曖昧なら内容を優先して判断（静止画の修正 vs 動きが欲しい）。');
  }
  lines.push('selection:');
  lines.push(`  ref: @${element.refId}`);
  lines.push(`  tag: ${element.tagName}`);
  if (element.className) lines.push(`  class: ${JSON.stringify(element.className)}`);
  if (element.bgColor) lines.push(`  computed-background: ${element.bgColor}`);
  if (element.ancestors?.length) {
    lines.push(`  ancestors: ${element.ancestors.join(' > ')}`);
  }
  lines.push(
    `  bounding-rect: { x: ${Math.round(element.rect.x)}, y: ${Math.round(element.rect.y)}, w: ${Math.round(element.rect.width)}, h: ${Math.round(element.rect.height)} }`
  );
  if (element.text) lines.push(`  text-content: ${JSON.stringify(element.text)}`);
  if (element.outerHtmlSnippet) {
    lines.push('  html: |');
    element.outerHtmlSnippet.split('\n').forEach((ln) => {
      lines.push(`    ${ln}`);
    });
  }
  lines.push('</dan-context>');
  return `${lines.join('\n')}\n\n${text}`;
}

export function ProjectChatPanel({ projectId }: ProjectChatPanelProps) {
  const queryClient = useQueryClient();
  const router = useRouter();
  const isMobile = useIsMobile();
  // SSE接続中はポーリングを無効化
  const sseConnectedRef = useRef(false);
  const selectProject = useProjectStore((s) => s.selectProject);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const sendMessageRef = useRef<((content: string) => void) | null>(null);
  const isNearBottomRef = useRef(true);
  const [visibleItemCount, setVisibleItemCount] = useState(INITIAL_CHAT_RENDER_COUNT);
  const [hasNewMessages, setHasNewMessages] = useState(false);
  const [lightboxImage, setLightboxImage] = useState<string | null>(null);
  const [replyTo, setReplyTo] = useState<MessageResponse | null>(null);
  const { warmupMode } = useRecoveryState(projectId);

  // Preview pane state
  const previewProjectId = usePreviewStore((s) => s.projectId);
  const previewArtifact = usePreviewStore((s) => s.artifact);
  const selectedElement = usePreviewStore((s) => s.selectedElement);
  const popoverDraft = usePreviewStore((s) => s.popoverDraft);
  const openArtifact = usePreviewStore((s) => s.openArtifact);
  const closePreview = usePreviewStore((s) => s.closePreview);
  const consumeDraft = usePreviewStore((s) => s.consumeDraft);
  const isPreviewOpenForProject =
    !!previewArtifact && previewProjectId === projectId;

  // Auto-close preview when switching projects
  useEffect(() => {
    if (previewProjectId && previewProjectId !== projectId) {
      closePreview();
    }
  }, [projectId, previewProjectId, closePreview]);

  // Artifacts for the header opener button
  const { data: artifacts = [] } = useQuery<ArtifactRecord[]>({
    queryKey: ['chat-artifacts', projectId],
    queryFn: async () => {
      const res = await fetch(`/api/v1/chat-artifact?project_id=${projectId}`, {
        credentials: 'include',
      });
      if (!res.ok) return [];
      return res.json();
    },
    enabled: !!projectId,
    staleTime: 10_000,
  });
  const [artifactMenuOpen, setArtifactMenuOpen] = useState(false);

  // Auto-open newly created artifacts
  const seenArtifactIdsRef = useRef<Set<string>>(new Set());
  useEffect(() => {
    if (!artifacts.length) return;
    const seen = seenArtifactIdsRef.current;
    if (seen.size === 0) {
      // First load: just record current state, don't auto-open
      artifacts.forEach((a) => seen.add(a.id));
      return;
    }
    const newOnes = artifacts.filter((a) => !seen.has(a.id));
    if (newOnes.length > 0) {
      // Most recent first (already sorted desc by created_at)
      openArtifact(projectId, newOnes[0]);
      newOnes.forEach((a) => seen.add(a.id));
    }
  }, [artifacts, projectId, openArtifact]);

  // Chat/Preview pane resize
  const [chatWidth, setChatWidth] = useState(520);
  const [isResizing, setIsResizing] = useState(false);

  const handleResizeStart = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      const startX = e.clientX;
      const startWidth = chatWidth;
      setIsResizing(true);
      document.body.style.cursor = 'col-resize';
      document.body.style.userSelect = 'none';

      const onMouseMove = (evt: MouseEvent) => {
        const delta = evt.clientX - startX;
        const containerWidth = window.innerWidth;
        setChatWidth(
          Math.max(280, Math.min(containerWidth - 400, startWidth + delta))
        );
      };
      const onMouseUp = () => {
        setIsResizing(false);
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
        window.removeEventListener('mousemove', onMouseMove);
        window.removeEventListener('mouseup', onMouseUp);
      };
      window.addEventListener('mousemove', onMouseMove);
      window.addEventListener('mouseup', onMouseUp);
    },
    [chatWidth]
  );

  const handleSubmitComment = useCallback(async () => {
    const { text, element } = consumeDraft();
    if (!element || !text.trim()) return;
    const composed = composeCommentMessage(text, element, previewArtifact);
    sendMessageRef.current?.(composed);
  }, [consumeDraft, previewArtifact]);

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

  const latestMessageId = messagesData?.messages?.[0]?.id;

  useEffect(() => {
    if (!project?.room_id) return;
    api.rooms.markAsRead(project.room_id)
      .then(() => {
        queryClient.invalidateQueries({ queryKey: ['projects'] });
      })
      .catch(() => null);
  }, [latestMessageId, project?.room_id, queryClient]);

  const { data: activeStatus } = useQuery({
    queryKey: ['session-active', project?.room_id],
    queryFn: () => api.sm.getActiveStatus(project!.room_id!),
    enabled: !!project?.room_id,
    retry: 1,
    // SSE接続中はポーリング不要（SSEイベントでキャッシュを直接更新する）
    // SSE未接続時のみポーリングで状態を確認
    refetchInterval: () => (sseConnectedRef.current ? false : 3000),
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

  const transitionLabel = 'Thinking...';
  const currentRunEvents = currentRun
    ? allExecutionEvents.filter((e) => e.run_id === currentRun.id)
    : [];
  // warmupMode はメッセージ送信時にフロントエンドが即座にセットし、
  // SSEイベント受信時にクリアされる。isActiveExecution はバックエンドへの
  // ポーリング結果に依存するため、バックエンドの登録処理が完了するまでの
  // 0〜2秒間に false が返ってきて「Thinking...」が一瞬消える問題がある。
  // warmupMode がセットされている間はフロントエンド側の状態を信頼する。
  const showWarmupBlock =
    (isActiveExecution || !!warmupMode) &&
    (!!warmupMode || (!!currentRun && currentRun.state === 'running')) &&
    currentRunEvents.length === 0;

  const deleteProjectMutation = useMutation({
    mutationFn: () => api.projects.delete(projectId),
    onSuccess: () => {
      selectProject(null);
      router.push('/chat');
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
      // 最新のhumanメッセージの時刻に紐づけて位置を固定する
      // (Date.now()を使うと再計算のたびにずれてメッセージとの前後が入れ替わる)
      const lastHumanMsg = chronologicalMessages.findLast((m) => m.sender_type === 'human');
      const anchorTime = lastHumanMsg ? new Date(lastHumanMsg.created_at).getTime() : 0;
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
        sortKey: anchorTime,
        subKey: 2,
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
          subKey: 2,
        });
      }
    }

    timedItems.sort((left, right) => left.sortKey - right.sortKey || left.subKey - right.subKey);
    return timedItems.map((item) => item.item);
  }, [allExecutionEvents, currentRun, isActiveExecution, messages, projectId, showWarmupBlock, transitionLabel]);

  const hasAnyContent = displayItems.length > 0;

  useEffect(() => {
    isNearBottomRef.current = true;
    const frame = requestAnimationFrame(() => {
      setVisibleItemCount(INITIAL_CHAT_RENDER_COUNT);
      setHasNewMessages(false);
    });
    return () => cancelAnimationFrame(frame);
  }, [projectId]);

  const visibleDisplayItems = useMemo(() => {
    const start = Math.max(0, displayItems.length - visibleItemCount);
    return displayItems.slice(start);
  }, [displayItems, visibleItemCount]);

  const hiddenOlderCount = Math.max(0, displayItems.length - visibleDisplayItems.length);

  useEffect(() => {
    if (isNearBottomRef.current) {
      requestAnimationFrame(() => {
        const el = scrollContainerRef.current;
        if (el) el.scrollTop = el.scrollHeight;
      });
    } else {
      requestAnimationFrame(() => setHasNewMessages(true));
    }
  }, [displayItems.length]);

  const handleScroll = useCallback(() => {
    const el = scrollContainerRef.current;
    if (!el) return;
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 100;
    isNearBottomRef.current = nearBottom;
    if (nearBottom) setHasNewMessages(false);
    if (el.scrollTop < 240) {
      setVisibleItemCount((count) =>
        count >= displayItems.length
          ? count
          : Math.min(displayItems.length, count + CHAT_RENDER_INCREMENT)
      );
    }
  }, [displayItems.length]);

  const scrollToBottom = useCallback(() => {
    const el = scrollContainerRef.current;
    if (el) {
      el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' });
    }
    setHasNewMessages(false);
  }, []);

  return (
    <div className="relative flex h-full w-full overflow-hidden">
    <div
      className={`flex h-full shrink-0 flex-col overflow-hidden bg-background ${
        isMobile && isPreviewOpenForProject ? 'hidden' : isPreviewOpenForProject ? '' : 'w-full'
      }`}
      style={!isMobile && isPreviewOpenForProject ? { width: chatWidth } : undefined}
    >
      <div className="flex shrink-0 items-center gap-3 border-b border-border py-3 pl-12 pr-16 md:pl-4 md:pr-16">
        <FolderKanban className="h-5 w-5 shrink-0 text-primary" />
        {artifacts.length > 0 && (
          <div className="relative shrink-0">
            <button
              onClick={() => {
                if (isPreviewOpenForProject) {
                  closePreview();
                  return;
                }
                if (artifacts.length === 1) {
                  openArtifact(projectId, artifacts[0]);
                } else {
                  setArtifactMenuOpen((v) => !v);
                }
              }}
              className={`flex items-center gap-1 rounded-md border px-2 py-1 text-xs font-medium transition-colors ${
                isPreviewOpenForProject
                  ? 'border-primary bg-primary/10 text-primary'
                  : 'border-border bg-background hover:bg-muted'
              }`}
              title="プレビューを開く"
            >
              <Presentation className="h-3.5 w-3.5" />
              <span>成果物 ({artifacts.length})</span>
            </button>
            {artifactMenuOpen && (
              <>
                <div
                  className="fixed inset-0 z-30"
                  onClick={() => setArtifactMenuOpen(false)}
                />
                <div className="absolute left-0 top-full z-40 mt-1 w-[300px] rounded-md border border-border bg-popover p-1 shadow-lg">
                  {artifacts.map((a) => (
                    <button
                      key={a.id}
                      onClick={() => {
                        openArtifact(projectId, a);
                        setArtifactMenuOpen(false);
                      }}
                      className="block w-full truncate rounded px-2 py-1.5 text-left text-sm hover:bg-muted"
                    >
                      <div className="truncate font-medium">{a.label || a.slug}</div>
                      <div className="truncate text-xs text-muted-foreground">
                        {a.preview_url}
                      </div>
                    </button>
                  ))}
                </div>
              </>
            )}
          </div>
        )}
        <div className="min-w-0 flex-1">
          {isLoading ? (
            <div className="flex items-center gap-2">
              <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
              <span className="text-base text-muted-foreground md:text-[17px]">プロジェクトを読み込み中...</span>
            </div>
          ) : (
            <>
              <div className="flex items-center gap-1.5">
                <h2 className="truncate text-base font-semibold md:text-[17px]">{project?.title}</h2>
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
              {project?.created_at ? (
                <div className="mt-0.5">
                  <span className="text-sm text-muted-foreground/60 md:text-[15px]">
                    {new Date(project.created_at).toLocaleDateString('ja-JP')}
                  </span>
                </div>
              ) : null}
            </>
          )}
        </div>
      </div>

      <div ref={scrollContainerRef} onScroll={handleScroll} className="relative flex-1 overflow-y-auto">
        {hasNewMessages && (
          <button
            onClick={scrollToBottom}
            className="sticky top-[calc(100%-3rem)] z-10 mx-auto flex items-center gap-1.5 rounded-full bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground shadow-lg transition-opacity hover:opacity-90"
            style={{ display: 'block', marginLeft: 'auto', marginRight: 'auto', width: 'fit-content' }}
          >
            <ChevronDown className="h-3.5 w-3.5" />
            新しいメッセージ
          </button>
        )}
        {isLoadingMessages ? (
          <div className="flex items-center justify-center p-6">
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          </div>
        ) : !hasAnyContent && !isActiveExecution ? (
          <div className="flex h-full flex-col items-center justify-center p-6">
            <MessageSquare className="mb-3 h-10 w-10 text-muted-foreground/20" />
            <p className="text-base text-muted-foreground md:text-[17px]">メッセージを送信して開始してください。</p>
          </div>
        ) : (
          <div className="flex flex-col gap-2 p-4">
            {(() => {
              const lastExecutionIndex = visibleDisplayItems.reduce(
                (last, item, index) => (item.kind === 'execution-block' ? index : last),
                -1
              );

              return visibleDisplayItems.map((item, index) => {
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

                return <div key={item.msg.id} data-message-id={item.msg.id}><MessageBubble msg={item.msg} onImageClick={setLightboxImage} onReply={setReplyTo} /></div>;
              });
            })()}
            {hiddenOlderCount > 0 ? (
              <div className="h-1" aria-hidden="true" />
            ) : null}
            <div ref={messagesEndRef} />
          </div>
        )}
      </div>

      {/* 承認/却下ボタンは廃止。チャットでの承認を観察者が検知して計画を記録する */}

      {project?.room_id ? (
        <ChatInput
          projectId={projectId}
          roomId={project.room_id}
          isSessionActive={isActiveExecution}
          sendMessageRef={sendMessageRef}
          onSseStateChange={(connected) => { sseConnectedRef.current = connected; }}
          replyTo={replyTo}
          onClearReply={() => setReplyTo(null)}
          onSubmitComment={handleSubmitComment}
        />
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
    {isPreviewOpenForProject && isMobile && (
      <div className="h-full w-full min-w-0">
        <PreviewPane onSubmitComment={handleSubmitComment} />
      </div>
    )}
    {isPreviewOpenForProject && !isMobile && (
      <>
        <div
          className="group relative h-full w-1 shrink-0 cursor-col-resize bg-border"
          onMouseDown={handleResizeStart}
          title="ドラッグで幅調整"
        >
          <div className="absolute inset-y-0 -left-1 w-3 group-hover:bg-primary/30 transition-colors" />
        </div>
        <div className="min-w-0 flex-1">
          <PreviewPane onSubmitComment={handleSubmitComment} />
        </div>
      </>
    )}
    {isResizing && (
      <div className="fixed inset-0 z-50 cursor-col-resize" />
    )}
    </div>
  );
}
