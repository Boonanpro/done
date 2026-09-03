'use client';

import { memo, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import {
  AlertCircle,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clapperboard,
  File,
  FileText,
  FolderKanban,
  Loader2,
  MessageSquare,
  MessageSquarePlus,
  Mic,
  Paperclip,
  Plus,
  Reply,
  Search,
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
  type MessagesListResponse,
  type ProcessStep,
  type ProjectListResponse,
  type ProjectResponse,
  type ProjectStatusType,
  type ReplyToMessage,
  type TurnBlock,
} from '@/lib/api-client';
import { useRouter } from 'next/navigation';
import { useProjectRecovery } from '@/hooks/useProjectRecovery';
import { useIsMobile } from '@/hooks/useIsMobile';
import { useAuthStore } from '@/stores/auth-store';
import { useProjectStore, useRecoveryActions, useRecoveryState } from '@/stores/project-store';
import {
  usePreviewStore,
  type ArtifactRecord,
  type PendingComment,
  type SelectedElement,
} from '@/stores/preview-store';
import { PreviewPane } from '@/components/preview/preview-pane';
import { OutboundMessageCard, OutboundEventLine, parseOutboundCardMarker, isOutboundEventContent, isCollabLogContent } from '@/components/chat/outbound-message-card';
import { RoomBoard } from '@/components/chat/room-board';
import { MediaGrid } from '@/components/chat/media-grid';
import { VoiceSession } from '@/components/voice/voice-session';
import { ProductionWorkspace } from '@/components/production/production-workspace';

interface ProjectChatPanelProps {
  projectId: string;
}

const INITIAL_CHAT_RENDER_COUNT = 80;
const CHAT_RENDER_INCREMENT = 80;
// 部屋を開いた時に取る件数と、上端まで遡った時に追加で取る件数。
// ダンの記憶（reseed）は UI の取得件数と無関係なので、画面は「一画面ぶん＋少し」で足りる。
// 従来は毎回 500 件（大きい部屋で数MB）を丸ごと取っていて、部屋切替の主な重さだった。
const CHAT_INITIAL_FETCH_LIMIT = 20;
const CHAT_OLDER_FETCH_LIMIT = 100;

type StepInfo = {
  label: string;
  type: 'tool' | 'reasoning' | 'error';
  role?: 'researcher' | 'critic' | 'leader' | null;
};

type DisplayItem =
  | { kind: 'message'; msg: MessageResponse }
  | { kind: 'execution-block'; id: string; steps: StepInfo[]; isLive: boolean };

// Phase 2: the live in-progress turn renders with the SAME inline timeline as
// a finished turn (text segments + a collapsible tool group), so there's no
// separate "process monitor" box anymore. The tool group starts collapsed even
// while live（「〇件の作業」をタップで開ける）; a spinner trails the steps as the
// working indicator. Once the run finishes this block is dropped and the saved
// message's blocks take over (also collapsed).
function InlineProcessBlock({
  steps,
  isLive = false,
}: {
  steps: StepInfo[];
  isLive?: boolean;
  defaultCollapsed?: boolean; // kept for call-site compatibility (unused)
}) {
  if (steps.length === 0 && !isLive) return null;
  const blocks = stepsToBlocks(steps);

  return (
    <div className="my-1">
      {blocks.length > 0 ? <AiTurnBlocks blocks={blocks} /> : null}
      {isLive ? (
        <div className="mt-1 flex items-center gap-1.5 text-xs text-muted-foreground">
          <Loader2 className="h-3 w-3 shrink-0 animate-spin text-primary" />
          <span>{steps.length === 0 ? '考えています…' : '実行中…'}</span>
        </div>
      ) : null}
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

// Build a short snippet around the matched keyword, with the match highlighted,
// for the search hit-list. Strips attachment/tool markup so the text reads clean.
function highlightSnippet(content: string, query: string): React.ReactNode {
  const clean = (content || '')
    .replace(/\[(添付[^\]]*|画像生成[^\]]*|TOOL:[^\]]*)\]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
  const q = query.trim();
  if (!q) return clean.slice(0, 160);
  const idx = clean.toLowerCase().indexOf(q.toLowerCase());
  if (idx === -1) return clean.slice(0, 160) + (clean.length > 160 ? '…' : '');
  const start = Math.max(0, idx - 50);
  const end = Math.min(clean.length, idx + q.length + 90);
  return (
    <>
      {start > 0 ? '…' : ''}
      {clean.slice(start, idx)}
      <mark className="rounded bg-yellow-300/70 px-0.5 text-foreground">{clean.slice(idx, idx + q.length)}</mark>
      {clean.slice(idx + q.length, end)}
      {end < clean.length ? '…' : ''}
    </>
  );
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

// --- Inline turn timeline (Claude Code / Codex style) -------------------
// Renders an AI turn from its ordered blocks: text segments show as the
// answer; runs of tool/reasoning blocks collapse into one expandable group
// so the flow stays readable.

// Strip raw tool-call markup that sometimes leaks into a text block
// (`<invoke …>`, `<parameter …>`, `<function_calls>` …). It's internal
// plumbing, never meant to be shown as the answer. Handles unclosed tags
// (truncated/streamed) by deleting from the opening tag to the end.
function stripToolMarkup(s: string): string {
  return s
    .replace(/<function_calls\b[\s\S]*?(<\/function_calls>|$)/gi, '')
    .replace(/<invoke\b[\s\S]*?(<\/invoke>|$)/gi, '')
    .replace(/<\/?(invoke|parameter|function_calls|antml:[a-z_]+)\b[^>]*>/gi, '')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
}

// Tailwind arbitrary variants: keep big code blocks from flooding the chat —
// cap their height and let them scroll.
const PROSE_CLASS =
  'prose prose-base prose-dan max-w-none text-base leading-relaxed text-foreground md:prose-base md:text-[17px] ' +
  '[&_pre]:max-h-72 [&_pre]:overflow-auto [&_pre]:text-sm';

// Muted style for "narration" text ("○○を調べます" between tools): smaller,
// dimmer — clearly secondary so the real answer stands out.
const MUTED_PROSE_CLASS =
  'prose prose-sm prose-dan max-w-none text-sm leading-relaxed text-muted-foreground/80 ' +
  '[&_p]:my-1 [&_pre]:max-h-60 [&_pre]:overflow-auto [&_pre]:text-xs';

const AiMarkdown = memo(function AiMarkdown({ text, onImageClick, muted = false }: { text: string; onImageClick?: (url: string) => void; muted?: boolean }) {
  return (
    <div className={muted ? MUTED_PROSE_CLASS : PROSE_CLASS}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a({ href, children }) { return <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>; },
          img({ src, alt }) { const imgSrc = typeof src === 'string' && src ? src : null; if (!imgSrc) return null; return <img src={imgSrc} alt={alt || ''} className="rounded-xl max-w-full max-h-80 object-contain border border-border cursor-zoom-in" onClick={() => onImageClick?.(imgSrc)} />; },
        }}
      >{text}</ReactMarkdown>
    </div>
  );
});

const TurnTextSegment = memo(function TurnTextSegment({ text, onImageClick, muted = false }: { text: string; onImageClick?: (url: string) => void; muted?: boolean }) {
  const { images, videos, files, text: clean } = parseMediaContent(stripToolMarkup(text));
  return (
    <>
      {(images.length > 0 || videos.length > 0 || files.length > 0) && (
        <div className="flex flex-col gap-1.5 my-2">
          <MediaGrid items={[...images.map((url) => ({ url, kind: 'image' as const })), ...videos.map((url) => ({ url, kind: 'video' as const }))]} onImageClick={onImageClick} />
          {files.map((f, i) => (<a key={`f${i}`} href={f.url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-2 rounded-lg border border-border bg-card px-3 py-2 text-sm text-foreground shadow-sm transition-colors hover:bg-muted md:text-[15px]"><FileText className="h-4 w-4 shrink-0 text-primary" /><span className="truncate max-w-[250px]">{f.name}</span></a>))}
        </div>
      )}
      {clean.trim() && <AiMarkdown text={clean} onImageClick={onImageClick} muted={muted} />}
    </>
  );
});

function TurnToolRow({ block }: { block: TurnBlock }) {
  const [show, setShow] = useState(false);
  const label = ('label' in block && block.label) || ('name' in block && block.name)
    || (block.type === 'reasoning' ? (block.text || '思考') : block.type === 'error' ? (block.text || 'エラー') : 'ツール実行');
  const detail = (block.type === 'tool' && block.detail) ? block.detail
    : (block.type === 'reasoning' || block.type === 'error') ? (block.text || '') : '';
  const isErr = block.type === 'error';
  const hasDetail = !!detail && detail !== label;
  return (
    <div>
      <button
        type="button"
        onClick={() => hasDetail && setShow((s) => !s)}
        className={`flex w-full items-start gap-1.5 text-left text-xs ${hasDetail ? 'cursor-pointer hover:text-foreground' : 'cursor-default'} ${isErr ? 'text-red-600' : 'text-muted-foreground'}`}
      >
        {isErr ? <AlertCircle className="h-3 w-3 text-red-500 shrink-0 mt-0.5" /> : <Check className="h-3 w-3 text-green-500 shrink-0 mt-0.5" />}
        <span className="flex-1">{label}</span>
        {hasDetail && (show ? <ChevronDown className="h-3 w-3 shrink-0 mt-0.5" /> : <ChevronRight className="h-3 w-3 shrink-0 mt-0.5" />)}
      </button>
      {show && hasDetail && (
        <pre className="mt-1 ml-4 max-h-72 overflow-auto whitespace-pre-wrap rounded-md bg-muted/60 p-2 text-[11px] leading-relaxed text-muted-foreground">{detail}</pre>
      )}
    </div>
  );
}

function TurnToolGroup({ items, defaultOpen = false }: { items: TurnBlock[]; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="my-2">
      <button type="button" onClick={() => setOpen((o) => !o)} className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors">
        {open ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
        <Terminal className="h-3 w-3 text-primary" />
        <span>{items.length}件の作業{open ? '' : ' を表示'}</span>
      </button>
      {open && (
        <div className="mt-1 ml-4 border-l-2 border-primary/20 pl-3 space-y-1.5">
          {items.map((it, i) => <TurnToolRow key={i} block={it} />)}
        </div>
      )}
    </div>
  );
}

const AiTurnBlocks = memo(function AiTurnBlocks({ blocks, onImageClick, toolsOpen = false }: { blocks: TurnBlock[]; onImageClick?: (url: string) => void; toolsOpen?: boolean }) {
  const grouped: Array<{ kind: 'text'; text: string } | { kind: 'tools'; items: TurnBlock[] }> = [];
  for (const b of blocks) {
    if (b.type === 'text') {
      if (!b.text?.trim()) continue;
      grouped.push({ kind: 'text', text: b.text });
    } else {
      const last = grouped[grouped.length - 1];
      if (last && last.kind === 'tools') last.items.push(b);
      else grouped.push({ kind: 'tools', items: [b] });
    }
  }
  // The substantive answer is the LAST text segment (after the tools). Earlier
  // text segments are mid-work narration ("○○を調べます") → render them muted
  // so the real answer stands out.
  const lastTextIndex = grouped.reduce((acc, g, i) => (g.kind === 'text' ? i : acc), -1);
  return (
    <div className="flex flex-col">
      {grouped.map((g, i) => (g.kind === 'text'
        ? <TurnTextSegment key={i} text={g.text} onImageClick={onImageClick} muted={i !== lastTextIndex} />
        : <TurnToolGroup key={i} items={g.items} defaultOpen={toolsOpen} />))}
    </div>
  );
});

// Live in-progress steps (execution events) → the same block shape so the
// live turn renders with the identical inline-timeline UI as the finished one.
function stepsToBlocks(steps: StepInfo[]): TurnBlock[] {
  return steps.map((s) => {
    if (s.type === 'tool') return { type: 'tool', label: s.label };
    if (s.type === 'error') return { type: 'error', text: s.label };
    // reasoning step = Dan's intermediate Japanese text → show as answer text
    return { type: 'text', text: s.label };
  });
}

// 追い連絡（ダン作業中の途中送信）機能のフロント側ゲート。
// バックエンドの DAN_STREAMING_INPUT と揃えて有効化する（OFF時は従来挙動）。
const STREAMING_INPUT = process.env.NEXT_PUBLIC_DAN_STREAMING_INPUT === '1';

/** LINE風の送信時刻（例: 9:41 / 14:23）。日付は日付セパレータ側が担当する。 */
function formatMessageTime(createdAt: string | undefined): string | null {
  if (!createdAt) return null;
  const d = new Date(createdAt);
  if (isNaN(d.getTime())) return null;
  return `${d.getHours()}:${String(d.getMinutes()).padStart(2, '0')}`;
}

/** LINE風の日付区切りラベル。今日/昨日、それ以外は「8月7日(木)」（年が違えば年も）。 */
function formatDateSeparator(d: Date): string {
  const now = new Date();
  const startOfDay = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const diffDays = Math.round((startOfDay(now) - startOfDay(d)) / 86_400_000);
  if (diffDays === 0) return '今日';
  if (diffDays === 1) return '昨日';
  const weekday = ['日', '月', '火', '水', '木', '金', '土'][d.getDay()];
  const base = `${d.getMonth() + 1}月${d.getDate()}日(${weekday})`;
  return d.getFullYear() === now.getFullYear() ? base : `${d.getFullYear()}年${base}`;
}

const MessageBubble = memo(function MessageBubble({ msg, onImageClick, onReply }: { msg: MessageResponse; onImageClick?: (url: string) => void; onReply?: (msg: MessageResponse) => void }) {

  // 追い連絡の仮送信状態（クライアント側フラグ）。半透明＋バッジで表示。
  const pending = !!msg.pendingFollowup;
  const timeLabel = formatMessageTime(msg.created_at);

  // ダンのリアクション応答: 本文が「👍」だけのAIメッセージは吹き出しにせず、
  // 直前のユーザー発言に押されたLINE風リアクションとして右寄せの小さな
  // スタンプで描画する（純粋な了解・受領に定型文を返さないための仕組み。
  // 履歴上は通常のAI応答なので送受信ペアは壊れない）。
  if (msg.sender_type === 'ai' && (msg.content || '').trim() === '👍') {
    return (
      <div className="-mt-2 flex justify-end pr-1">
        <span
          className="inline-flex items-center rounded-full border border-border bg-muted px-2 py-0.5 text-sm leading-none shadow-sm"
          title="ダンが確認しました"
        >
          👍
        </span>
      </div>
    );
  }

  if (msg.sender_type === 'human') {
    const { images, videos, files, text } = parseMediaContent(msg.content || '');
    // 長文・URL・英数字の連続など折り返せない塊があると、items-end の
    // flex 列では吹き出しが左へはみ出して左サイドバーの下に潜る。
    // min-w-0 + break-words(anywhere) で必ず枠内で折り返す。
    return (
      <div className={`flex min-w-0 max-w-[85%] ml-auto flex-col items-end${pending ? ' opacity-50' : ''}`}>
        {msg.reply_to_message && <ReplyQuote replyTo={msg.reply_to_message} />}
        <div className="group flex max-w-full min-w-0 items-start gap-1">
          {onReply && !msg.id.startsWith('temp-') && (
            <button
              onClick={() => onReply(msg)}
              className="mt-1.5 opacity-0 group-hover:opacity-100 transition-opacity text-muted-foreground hover:text-foreground p-1 rounded"
              title="返信"
            >
              <Reply className="h-3.5 w-3.5" />
            </button>
          )}
          {timeLabel && (
            <span className="self-end mb-0.5 shrink-0 text-[10px] leading-none text-muted-foreground">
              {timeLabel}
            </span>
          )}
          <div className="flex min-w-0 flex-col items-end gap-1">
          <MediaGrid items={[...images.map((url) => ({ url, kind: 'image' as const })), ...videos.map((url) => ({ url, kind: 'video' as const }))]} onImageClick={onImageClick} />
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
            <div className="max-w-full min-w-0 rounded-lg bg-primary px-3 py-2 text-base leading-relaxed text-primary-foreground md:text-[17px] whitespace-pre-wrap break-words [overflow-wrap:anywhere]">
              {text}
            </div>
          )}
          </div>
        </div>
        {pending && (
          <span className="mt-0.5 mr-1 text-[11px] text-muted-foreground">仮送信・次の区切りで反映</span>
        )}
      </div>
    );
  }

  // 送信案カード（compose_message）: `[送信案: <id>]` はカードとして描画する。
  // 送信済み/破棄イベント（📤/🗑）は折り畳みの控えめな行にする。
  // collab（外部窓口）のカードは本体チャットでは薄い1行に折り畳む（主戦場はコミュニケーションタブ）。
  const outboundCardId = parseOutboundCardMarker(msg.content);
  if (outboundCardId) {
    return <OutboundMessageCard proposalId={outboundCardId} foldCollab />;
  }
  if (isOutboundEventContent(msg.content)) {
    return <OutboundEventLine content={msg.content || ''} />;
  }
  // 外部窓口対応の作業ログ（「窓口ログ:」で始まるai発言）も折り畳みの控えめな行にする。
  if (msg.sender_type === 'ai' && isCollabLogContent(msg.content)) {
    return <OutboundEventLine content={msg.content || ''} />;
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

  const { images: aiImages, videos: aiVideos, files: aiFiles, text: aiText } = parseMediaContent(stripToolMarkup(contentWithoutProposals));
  const hasMedia = aiImages.length > 0 || aiVideos.length > 0 || aiFiles.length > 0;

  // Inline timeline when the turn carries ordered blocks with tools or with
  // more than one text segment (so intermediate text isn't lost). A single
  // text block with no tools renders fine via the plain path below.
  const turnBlocks = msg.ai_context?.blocks;
  const useTimeline = !!turnBlocks && turnBlocks.length > 0
    && (turnBlocks.some((b) => b.type === 'tool' || b.type === 'error')
      || turnBlocks.filter((b) => b.type === 'text').length > 1);

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
      {useTimeline && <AiTurnBlocks blocks={turnBlocks!} onImageClick={onImageClick} />}
      {!useTimeline && hasMedia && (
        <div className="flex flex-col gap-1.5 mb-2">
          <MediaGrid items={[...aiImages.map((url) => ({ url, kind: 'image' as const })), ...aiVideos.map((url) => ({ url, kind: 'video' as const }))]} onImageClick={onImageClick} />
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
      {!useTimeline && aiText && <AiMarkdown text={aiText} onImageClick={onImageClick} />}
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
      {timeLabel && (
        <div className="mt-1 text-[10px] leading-none text-muted-foreground">{timeLabel}</div>
      )}
    </div>
  );
});

type DanSkill = { name: string; display_name: string; description: string };
type TimelineReference = { content_id: string; title: string; updated_at?: string };

const chatDraftKey = (projectId: string) => `dan-chat-draft:${projectId}`;

function ChatInput({
  projectId,
  roomId,
  isSessionActive,
  activeOriginMessageId,
  sendMessageRef,
  onSseStateChange,
  replyTo,
  onClearReply,
  onAddComment,
  onEditPendingComment,
}: {
  projectId: string;
  roomId: string;
  isSessionActive: boolean;
  activeOriginMessageId?: string | null;
  sendMessageRef?: React.MutableRefObject<((content: string) => void) | null>;
  onSseStateChange?: (connected: boolean) => void;
  replyTo?: MessageResponse | null;
  onClearReply?: () => void;
  onAddComment?: () => void;
  onEditPendingComment?: (id: string) => void;
}) {
  const inspectorElement = usePreviewStore((s) => s.selectedElement);
  const inspectorElements = usePreviewStore((s) => s.selectedElements);
  const inspectorDraft = usePreviewStore((s) => s.popoverDraft);
  const previewMode = usePreviewStore((s) => s.inspectorMode);
  const clearInspectorSelection = usePreviewStore((s) => s.clearSelection);
  const allPendingComments = usePreviewStore((s) => s.pendingComments);
  // コメントはルーム別に保持される（別ルームに移動しても消えず、戻ると再表示）。
  // このルームで表示・送信するのは自ルーム分だけ。projectId 無しの古いデータは
  // どのルームでも見える（取り残して消せなくなるよりまし）。
  const pendingComments = useMemo(
    () => allPendingComments.filter((c) => !c.projectId || c.projectId === projectId),
    [allPendingComments, projectId]
  );
  const removePendingComment = usePreviewStore((s) => s.removePendingComment);
  const clearPendingComments = usePreviewStore((s) => s.clearPendingComments);
  const editingCommentId = usePreviewStore((s) => s.editingCommentId);
  const previewArtifactForComments = usePreviewStore((s) => s.artifact);
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
  const [timelineRefs, setTimelineRefs] = useState<TimelineReference[]>([]);
  const [timelineChoices, setTimelineChoices] = useState<TimelineReference[]>([]);
  const [timelineMenuOpen, setTimelineMenuOpen] = useState(false);
  const [timelineLoading, setTimelineLoading] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  // 追い連絡の下書きがある時、1回目の Esc は停止せず下書きを保持（armed）、
  // 2回目の Esc で本当に停止する。escStopHint は「もう一度Escで停止」表示。
  const [escStopHint, setEscStopHint] = useState(false);
  const escArmedRef = useRef(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const pendingMessageRef = useRef<{ text: string; files: typeof attachedFiles; replyTo: typeof replyTo } | null>(null);
  const aiRespondedRef = useRef(false);
  // キャンセル後の再送信時にUPDATEすべきDBメッセージID
  const replaceMessageIdRef = useRef<string | null>(null);
  // 今回のSSEで受信したサーバー上のメッセージID
  const serverMessageIdRef = useRef<string | null>(null);
  const optimisticMessageIdRef = useRef<string | null>(null);
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
    optimisticMessageIdRef.current = null;
  }, [roomId]);

  // 入力中の下書きをプロジェクトごとに永続化する。
  // パネルは key={selectedProjectId} で切替のたびアンマウントされるため、
  // state だけだと書きかけのメッセージが消える → localStorage に退避・復元。
  // 注意: 復元effectを保存effectより先に宣言すること（マウント直後の
  // message='' で保存effectが先にキーを消すと下書きを読む前に失われる）。
  useEffect(() => {
    try {
      const saved = localStorage.getItem(chatDraftKey(projectId));
      if (saved) setMessage((cur) => cur || saved);
    } catch {
      // localStorage が使えない環境では下書き保存なしで動く
    }
  }, [projectId]);

  useEffect(() => {
    try {
      if (message) localStorage.setItem(chatDraftKey(projectId), message);
      else localStorage.removeItem(chatDraftKey(projectId));
    } catch {
      // ignore
    }
  }, [message, projectId]);

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

  const openTimelineMenu = useCallback(async () => {
    setTimelineMenuOpen((open) => !open);
    if (timelineChoices.length || timelineLoading) return;
    setTimelineLoading(true);
    try {
      const res = await fetch(`/api/v1/production-assets/contents?room_id=${encodeURIComponent(roomId)}`, { credentials: 'include' });
      if (!res.ok) throw new Error(await res.text());
      const rows = await res.json();
      setTimelineChoices((Array.isArray(rows) ? rows : []).map((row) => ({
        content_id: String(row.id), title: String(row.title || 'Untitled timeline'), updated_at: row.updated_at,
      })));
    } catch (error) {
      toast.error('タイムライン一覧を取得できませんでした', { description: String(error).slice(0, 140) });
    } finally {
      setTimelineLoading(false);
    }
  }, [roomId, timelineChoices.length, timelineLoading]);

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
  const isBusy = isInterrupted || localActive || isSessionActive;

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
    queryClient.invalidateQueries({ queryKey: ['chat-artifacts', roomId] });
  }, [projectId, queryClient, roomId]);

  const invalidateProjectChrome = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ['current-run', projectId] });
    queryClient.invalidateQueries({ queryKey: ['execution-events', projectId] });
    queryClient.invalidateQueries({ queryKey: ['project', projectId] });
    queryClient.invalidateQueries({ queryKey: ['chat-artifacts', roomId] });
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

  const sendMessageCore = useCallback(async (content: string, imageUrls: string[] = [], fileUrls: { name: string; url: string }[] = [], replyToMsg?: MessageResponse | null, refs: TimelineReference[] = []) => {
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

    // 完全形: 送信の瞬間にフロントが本物のUUIDを発行し、サーバーはこれを
    // そのまま行IDにする。キャンセルはいつでもこのIDで確実に削除できる。
    const tempUserMessageId =
      typeof crypto !== 'undefined' && 'randomUUID' in crypto
        ? crypto.randomUUID()
        : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
    optimisticMessageIdRef.current = tempUserMessageId;
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
    await queryClient.cancelQueries({ queryKey });
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
        { message: content, session_id: roomId, client_message_id: tempUserMessageId, ...(imageUrls.length > 0 ? { image_urls: imageUrls } : {}), ...(fileUrls.length > 0 ? { file_urls: fileUrls } : {}), ...(replyToMsg ? { reply_to_id: replyToMsg.id } : {}), ...(currentReplaceId ? { replace_message_id: currentReplaceId } : {}), ...(refs.length ? { timeline_refs: refs } : {}) },
        {
          onUserMessage: (msg) => {
            if (streamRequestRef.current !== requestId) return;
            serverMessageIdRef.current = msg.id;
            optimisticMessageIdRef.current = msg.id;
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
          onAIMessage: (msg) => {
            if (streamRequestRef.current !== requestId) return;
            queryClient.setQueryData(
              queryKey,
              (old: { messages: MessageResponse[] } | undefined) => ({
                messages: [
                  msg,
                  ...(old?.messages || []).filter(
                    (current: MessageResponse) => current.id !== msg.id
                  ),
                ],
              })
            );
            // NOTE: ここで project-messages を invalidate/refetch しない。
            // 直上で SSE の実メッセージ（DB保存済み・実ID）をキャッシュへ挿入
            // 済みであり、直後の再取得は保存ラグの古いスナップショットで最新
            // 回答を数秒消す事故の温床だった（queryFn の一方通行マージが二重の
            // 保険だが、そもそも即時再取得に意味がない）。
            queryClient.invalidateQueries({ queryKey: ['current-run', projectId] });
            queryClient.invalidateQueries({ queryKey: ['execution-events', projectId] });
            queryClient.invalidateQueries({ queryKey: ['projects'] });
            // ダンが応答した = 仮送信中の追い連絡は読まれて反映された → 不透明化
            queryClient.setQueryData(
              ['project-messages', roomId],
              (old: { messages: MessageResponse[] } | undefined) =>
                old ? { messages: old.messages.map((m) => (m.pendingFollowup ? { ...m, pendingFollowup: false } : m)) } : old
            );
          },
          onProcessStep: (_step: ProcessStep) => {
            if (streamRequestRef.current !== requestId) return;
            aiRespondedRef.current = true;
            pendingMessageRef.current = null;
            replaceMessageIdRef.current = null;
            optimisticMessageIdRef.current = null;
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
            invalidateProjectChrome();

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
            // 送信失敗 → 楽観点灯した「ダンが作業中…」をサーバー真実で即消す
            queryClient.invalidateQueries({ queryKey: ['projects'] });
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
        // 送信失敗 → 楽観点灯した「ダンが作業中…」をサーバー真実で即消す
        queryClient.invalidateQueries({ queryKey: ['projects'] });
        toast.error('メッセージ送信中に問題が発生しました');
      }
    } finally {
      // ストリームが終わったら必ず ref を破棄する（残骸が「ダン作業中」と
      // 誤判定され、停止後の送信が追い連絡に誤ルーティングされるのを防ぐ）。
      // 次の送信がすでに新しい controller をセットしている場合は触らない。
      if (abortControllerRef.current === controller) {
        abortControllerRef.current = null;
      }
    }
  }, [
    invalidateProjectChrome,
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

  // 追い連絡（DAN_STREAMING_INPUT）: ダンの作業中に送る途中メッセージ。
  // 進行中のSSEストリームを中断せず、別リクエストで送信する。即 followup_queued で
  // ackされ、回答（次の境界以降のターン）は継続中の最初のストリームが onAIMessage で届ける。
  const sendFollowup = useCallback(async (
    content: string,
    imageUrls: string[] = [],
    fileUrls: { name: string; url: string }[] = [],
    replyToMsg?: MessageResponse | null,
  ) => {
    if (!content.trim() && imageUrls.length === 0 && fileUrls.length === 0) return;
    const imagePrefix = imageUrls.map(url => `[添付画像: ${url}]`).join('\n');
    const filePrefix = fileUrls.map(f => `[添付ファイル: ${f.name} (${f.url})]`).join('\n');
    const mediaParts = [imagePrefix, filePrefix].filter(Boolean).join('\n');
    const optimisticContent = mediaParts ? (content ? `${mediaParts}\n\n${content}` : mediaParts) : content;

    const tempId = `temp-followup-${Date.now()}`;
    const queryKey = ['project-messages', roomId];
    const optimistic: MessageResponse = {
      id: tempId,
      room_id: roomId,
      sender_id: user?.id || '',
      sender_name: user?.display_name || 'You',
      sender_type: 'human',
      content: optimisticContent,
      created_at: new Date().toISOString(),
      pendingFollowup: true,
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
    queryClient.setQueryData(queryKey, (old: { messages: MessageResponse[] } | undefined) => ({
      messages: [optimistic, ...(old?.messages || [])],
    }));

    const controller = new AbortController();
    try {
      await api.sm.sendMessageStream(
        { message: content, session_id: roomId, ...(imageUrls.length > 0 ? { image_urls: imageUrls } : {}), ...(fileUrls.length > 0 ? { file_urls: fileUrls } : {}), ...(replyToMsg ? { reply_to_id: replyToMsg.id } : {}) },
        {
          onUserMessage: (msg) => {
            // temp をサーバ版で置換しつつ、読まれるまでは仮送信フラグを保持する。
            queryClient.setQueryData(queryKey, (old: { messages: MessageResponse[] } | undefined) => ({
              messages: (old?.messages || []).map((m: MessageResponse) => (m.id === tempId ? { ...msg, pendingFollowup: true } : m)),
            }));
          },
          // 受領確認。ダンの応答が届くまで「仮送信」（半透明）のまま。
          onFollowupQueued: () => {},
          // 本リクエストは即終了する。メインストリームのスピナー等には触れない。
          onComplete: () => {},
          onError: (error) => {
            queryClient.setQueryData(queryKey, (old: { messages: MessageResponse[] } | undefined) => ({
              messages: (old?.messages || []).filter((m: MessageResponse) => m.id !== tempId),
            }));
            toast.error(error || '追い連絡の送信に失敗しました');
          },
        },
        controller.signal,
      );
    } catch (error) {
      if (error instanceof Error && error.name !== 'AbortError') {
        toast.error('追い連絡の送信中に問題が発生しました');
      }
    }
  }, [queryClient, roomId, user?.id, user?.display_name]);

  const handleSendMessage = useCallback(async () => {
    if (!message.trim() && attachedFiles.length === 0 && pendingComments.length === 0) return;

    const isImageFile = (name: string) => /\.(png|jpg|jpeg|gif|webp|bmp)$/i.test(name);
    const imageUrls = attachedFiles.filter(f => isImageFile(f.filename)).map(f => f.url);
    const fileUrls = attachedFiles.filter(f => !isImageFile(f.filename)).map(f => ({ name: f.filename, url: f.url }));

    // 溜めておいた要素コメントは、ここで初めて1通のメッセージに畳まれる。
    // （1件ずつ送るとその都度ダンが走り出してしまうのでこの形にしている）
    const content = pendingComments.length
      ? composeCommentsMessage(pendingComments, previewArtifactForComments, message.trim())
      : message.trim();
    if (pendingComments.length) clearPendingComments(projectId);
    const currentReplyTo = replyTo;

    // 追い連絡: ダン作業中（進行中ストリームあり）の途中送信は、ストリームを
    // 中断せず別経路で送る。メインストリームの ref 群には触れない。
    if (STREAMING_INPUT && abortControllerRef.current !== null) {
      setMessage('');
      setAttachedFiles([]);
      onClearReply?.();
      escArmedRef.current = false;
      setEscStopHint(false);
      await sendFollowup(content, imageUrls, fileUrls, currentReplyTo);
      return;
    }

    // キャンセル後の再送は「畳んだ後」の本文で行う（要素コメントを失わないため）
    pendingMessageRef.current = { text: content, files: [...attachedFiles], replyTo };
    aiRespondedRef.current = false;
    serverMessageIdRef.current = null;
    setMessage('');
    setAttachedFiles([]);
    onClearReply?.();
    // サイドバーの「ダンが作業中…」を送信の瞬間に点灯させる楽観更新。
    // 即時 invalidate だとサーバーの run 作成(送信後 約1.1〜1.4s)より先に
    // refetch が着いて has_active_run=false を持ち帰り、次の10sポーリング
    // まで点灯しなかった。キャッシュを直接 true にし、run 作成完了後の
    // 遅延 invalidate でサーバー真実（run状態＋並び順）に収束させる。
    queryClient.setQueryData(
      ['projects'],
      (old: ProjectListResponse | undefined) =>
        old
          ? {
              ...old,
              projects: old.projects.map((p) =>
                p.id === projectId ? { ...p, has_active_run: true } : p
              ),
            }
          : old
    );
    setTimeout(() => {
      queryClient.invalidateQueries({ queryKey: ['projects'] });
    }, 2000);
    const refs = timelineRefs;
    setTimelineRefs([]);
    await sendMessageCore(content, imageUrls, fileUrls, currentReplyTo, refs);
  }, [attachedFiles, message, sendMessageCore, sendFollowup, queryClient, projectId, replyTo, onClearReply, timelineRefs, pendingComments, clearPendingComments, previewArtifactForComments]);

  const handleCancel = useCallback(async () => {
    const pending = pendingMessageRef.current;
    const restoredMessage = !pending && activeOriginMessageId
      ? queryClient.getQueryData<{ messages: MessageResponse[] }>(['project-messages', roomId])?.messages
        .find((m) => m.id === activeOriginMessageId && m.sender_type === 'human')
      : null;
    const wasBeforeAI = !aiRespondedRef.current && (!!pending || !!restoredMessage);
    const userMessageIdToRemove = serverMessageIdRef.current || optimisticMessageIdRef.current || activeOriginMessageId || null;

    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }

    // 自分の操作は自分が真実（ターミナルのEscと同じ）: サーバーへの取消依頼を
    // 待たず、押した瞬間に thinking/ライブ表示を消す。従来はサーバー往復後に
    // 消灯し、さらに run 状態キャッシュが次のポーリング(2s)まで running のままで
    // 「キャンセルしたのにthinkingが数秒流れる」見た目になっていた。
    syncActiveStatus(false);
    setWarmupMode(projectId, null);
    queryClient.setQueryData(
      ['current-run', projectId],
      (old: { state?: string } | null | undefined) =>
        old && old.state === 'running' ? { ...old, state: 'paused' } : old
    );

    // AI未応答キャンセル → テキストを入力欄に復元 + 次回送信でUPDATEするIDを記録
    if (wasBeforeAI) {
      setMessage(pending?.text ?? restoredMessage?.content ?? '');
      setAttachedFiles(pending?.files ?? []);
      replaceMessageIdRef.current = null;
      if (userMessageIdToRemove) {
        queryClient.setQueryData(
          ['project-messages', roomId],
          (old: { messages: MessageResponse[] } | undefined) =>
            old
              ? { messages: old.messages.filter((m) => m.id !== userMessageIdToRemove) }
              : old
        );
      }
    }
    pendingMessageRef.current = null;
    serverMessageIdRef.current = null;
    optimisticMessageIdRef.current = null;

    try {
      await api.sm.cancelSession(roomId, {
        cancelledUserMessageId: wasBeforeAI ? userMessageIdToRemove : null,
      });
    } catch (error) {
      console.error('Failed to cancel session:', error);
    }

    syncActiveStatus(false);
    onSseStateChange?.(false);
    resetRecovery(projectId);
    setWarmupMode(projectId, null);
    invalidateProjectQueries();
    // 取消完了 → サイドバーの「ダンが作業中…」も次ポーリングを待たず消灯
    queryClient.invalidateQueries({ queryKey: ['projects'] });
    if (!wasBeforeAI) {
      toast.info('処理を中断しました');
    }
  }, [activeOriginMessageId, invalidateProjectQueries, onSseStateChange, projectId, queryClient, resetRecovery, roomId, setWarmupMode, syncActiveStatus]);

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
    if (!isBusy) {
      escArmedRef.current = false;
      setEscStopHint(false);
      return;
    }

    const handleEsc = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      // 追い連絡の下書きを書いている最中（入力欄に文字あり）は、1回目の Esc で
      // 作業を止めない。下書きはそのまま編集を続けられ、「もう一度Escで停止」を表示。
      // 2回目の Esc（armed）で本当に停止する。下書きが無ければ従来どおり即停止。
      const hasDraft = message.trim().length > 0;
      if (hasDraft && !escArmedRef.current) {
        event.preventDefault();
        escArmedRef.current = true;
        setEscStopHint(true);
        textareaRef.current?.focus();
        return;
      }
      event.preventDefault();
      escArmedRef.current = false;
      setEscStopHint(false);
      handleCancel();
    };

    window.addEventListener('keydown', handleEsc);
    return () => window.removeEventListener('keydown', handleEsc);
  }, [handleCancel, isBusy, message]);

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
          {inspectorElements.length > 1 ? (
            <>
              <span className="shrink-0 rounded bg-primary/20 px-1.5 py-0.5 font-mono font-medium text-primary">
                {inspectorElements.length}要素
              </span>
              <span className="truncate text-muted-foreground">
                {inspectorElements.map((el) => `<${el.tagName}>`).join(' ')}
              </span>
            </>
          ) : (
            <>
              <span className="rounded bg-primary/20 px-1.5 py-0.5 font-mono font-medium text-primary">
                @{inspectorElement.refId}
              </span>
              <span className="truncate text-muted-foreground">
                &lt;{inspectorElement.tagName}&gt;
                {inspectorElement.text ? ` "${inspectorElement.text}"` : ''}
              </span>
            </>
          )}
          <button
            onClick={clearInspectorSelection}
            className="ml-auto shrink-0 text-muted-foreground hover:text-foreground"
            title="選択解除 (Esc)"
          >
            <X className="h-3 w-3" />
          </button>
        </div>
      )}
      {pendingComments.length > 0 && (
        <div className="mb-1.5 space-y-1 rounded-lg border border-primary/30 bg-primary/5 p-2">
          <div className="flex items-center gap-1.5 px-0.5 text-xs text-muted-foreground">
            <MessageSquarePlus className="h-3.5 w-3.5 text-primary" />
            <span>
              要素コメント {pendingComments.length}件 — 送信ボタンでまとめて1通で送ります
            </span>
            <button
              type="button"
              onClick={() => clearPendingComments(projectId)}
              className="ml-auto shrink-0 hover:text-foreground"
            >
              すべて削除
            </button>
          </div>
          {pendingComments.map((c, i) => (
            <div
              key={c.id}
              onClick={() => onEditPendingComment?.(c.id)}
              role="button"
              title="クリックで要素を再選択して編集"
              className={`flex cursor-pointer items-start gap-1.5 rounded-md px-2 py-1.5 text-xs transition-colors ${
                editingCommentId === c.id
                  ? 'bg-primary/15 ring-1 ring-primary/50'
                  : 'bg-background/60 hover:bg-background'
              }`}
            >
              <span className="mt-px shrink-0 font-mono text-[10px] text-primary">{i + 1}</span>
              {c.artifact && c.artifact.slug !== previewArtifactForComments?.slug && (
                <span
                  className="max-w-[7rem] shrink-0 truncate rounded bg-muted px-1 font-mono text-[10px] text-muted-foreground"
                  title={`成果物: ${c.artifact.label || c.artifact.slug}`}
                >
                  {c.artifact.slug}
                </span>
              )}
              <span className="shrink-0 rounded bg-primary/15 px-1 font-mono text-[10px] text-primary">
                {c.elements.length > 1
                  ? `${c.elements.length}要素`
                  : `<${c.elements[0]?.tagName}>`}
              </span>
              {c.elements.length > 1 ? (
                <span className="max-w-[9rem] shrink-0 truncate text-muted-foreground">
                  {c.elements.map((el) => `<${el.tagName}>`).join(' ')}
                </span>
              ) : c.elements[0]?.text ? (
                <span className="max-w-[9rem] shrink-0 truncate text-muted-foreground">
                  &quot;{c.elements[0].text}&quot;
                </span>
              ) : null}
              <span className="min-w-0 flex-1 break-words">{c.text}</span>
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  removePendingComment(c.id);
                }}
                className="mt-px shrink-0 text-muted-foreground hover:text-foreground"
                aria-label="このコメントを外す"
              >
                <X className="h-3 w-3" />
              </button>
            </div>
          ))}
        </div>
      )}
      {escStopHint && (
        <div className="mb-1.5 flex items-center gap-1.5 px-1 text-xs text-muted-foreground">
          <span>編集を続けられます。</span>
          <kbd className="rounded border bg-muted px-1 font-mono text-[10px]">Esc</kbd>
          <span>をもう一度押すと作業を停止します。</span>
        </div>
      )}
      {timelineRefs.length > 0 && (
        <div className="mb-1.5 flex flex-wrap gap-1.5 px-1">
          {timelineRefs.map((ref) => (
            <span key={ref.content_id} className="inline-flex items-center gap-1 rounded-full border border-primary/30 bg-primary/10 px-2 py-1 text-xs text-foreground">
              <Clapperboard className="h-3 w-3 text-primary" />@{ref.title}
              <button type="button" onClick={() => setTimelineRefs((current) => current.filter((item) => item.content_id !== ref.content_id))} className="text-muted-foreground hover:text-foreground" aria-label="タイムライン参照を外す"><X className="h-3 w-3" /></button>
            </span>
          ))}
        </div>
      )}
      {timelineMenuOpen && (
        <div className="mb-1.5 max-h-44 overflow-y-auto rounded-lg border bg-popover p-1 shadow-lg">
          {timelineLoading ? <div className="px-2 py-2 text-xs text-muted-foreground">タイムラインを読み込み中…</div> : timelineChoices.length ? timelineChoices.map((ref) => (
            <button key={ref.content_id} type="button" className="flex w-full items-center gap-2 rounded px-2 py-2 text-left text-sm hover:bg-muted" onClick={() => { setTimelineRefs([ref]); setTimelineMenuOpen(false); }}>
              <Clapperboard className="h-3.5 w-3.5 text-primary" /><span className="truncate">{ref.title}</span>
            </button>
          )) : <div className="px-2 py-2 text-xs text-muted-foreground">参照できるタイムラインはありません</div>}
        </div>
      )}
      <div className={`flex items-end gap-2 rounded-xl border bg-input/30 p-2 transition-colors ${isCommentMode ? 'border-primary/40' : 'border-border focus-within:border-primary/50'}`}>
        <input ref={fileInputRef} type="file" multiple className="hidden" onChange={handleFileSelect} accept="*/*" />
        <Button variant="ghost" size="icon" className="h-7 w-7 shrink-0 text-muted-foreground hover:text-foreground" onClick={() => void openTimelineMenu()} disabled={isCommentMode} title="タイムラインをメンション">
          <Clapperboard className="h-3.5 w-3.5" />
        </Button>
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
                if (inspectorDraft.trim()) onAddComment?.();
              }
              return;
            }
            handleKeyDown(event);
          }}
          onPaste={handlePaste}
          placeholder={
            isCommentMode
              ? '右ペインのコメント欄で入力...'
              : pendingComments.length > 0
                ? '補足があれば入力（なくてもそのまま送れます）...'
                : 'メッセージを入力...'
          }
          rows={1}
          className={`min-h-[32px] max-h-[480px] flex-1 resize-none bg-transparent py-1.5 text-base focus:outline-none md:text-[17px] ${isCommentMode ? 'cursor-not-allowed text-foreground/90' : ''}`}
        />
        {isCommentMode ? (
          <Button
            size="icon"
            className="h-7 w-7 shrink-0"
            onClick={() => onAddComment?.()}
            disabled={!inspectorDraft.trim()}
            title="コメントを追加（まだ送信されません）"
          >
            <Plus className="h-3.5 w-3.5" />
          </Button>
        ) : message.trim() || attachedFiles.length > 0 || pendingComments.length > 0 ? (
          <Button
            size="icon"
            className="h-7 w-7 shrink-0 transition-transform active:scale-90"
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
            className="h-7 w-7 shrink-0 transition-transform active:scale-90"
            onClick={handleSendMessage}
            disabled={!message.trim() && attachedFiles.length === 0 && pendingComments.length === 0}
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

/**
 * 溜めた要素コメントを1通のメッセージに畳む。
 *
 * 1件でも複数件でも同じ形（selections の配列）にする。ダン側から見て
 * 「この指示はこの要素に対応する」が1対1で読めることが要点で、
 * 番号を振ってあるので複数箇所を1回の実行でまとめて直せる。
 */
function composeCommentsMessage(
  items: PendingComment[],
  artifact: ArtifactRecord | null,
  tail: string
): string {
  const lines: string[] = ['<dan-context>'];
  lines.push('kind: element-comment');
  lines.push(`count: ${items.length}`);
  lines.push('note: |');
  lines.push('  ユーザーは成果物上で要素を選択し、その要素について発言している。');
  lines.push('  発言の意図は文面から判断: 修正要望 / 質問 / 議論 / 提案 など自由。');
  lines.push('  修正を依頼された場合のみファイルを編集する。');
  if (items.length > 1) {
    lines.push(`  今回は ${items.length} 件の指示がまとめて送られている。`);
    lines.push('  それぞれ対応する要素が selections に番号付きで入っているので、');
    lines.push('  指示されていない箇所には手を出さず、全件を1回の作業でまとめて処理する。');
  }
  if (items.some((it) => it.elements.length > 1)) {
    lines.push('  複数要素を選択して書かれた指示がある（targets に複数入っている）。');
    lines.push('  その instruction は targets 内の全要素に対する1つの指示なので、');
    lines.push('  全対象要素に同じ変更/回答を適用すること（1要素だけ直して終わりにしない）。');
  }
  // 成果物情報はコメント追加時のスナップショットを最優先する。プレビューを
  // 閉じた後や別成果物に切り替えた後の送信でも、コメントした時の成果物に紐づく。
  const snapArtifacts = items
    .map((it) => it.artifact)
    .filter((a): a is NonNullable<PendingComment['artifact']> => !!a);
  const uniqueSlugs = [...new Set(snapArtifacts.map((a) => a.slug))];
  const headerArtifact =
    uniqueSlugs.length === 1
      ? snapArtifacts[0]
      : uniqueSlugs.length === 0 && artifact
        ? { slug: artifact.slug, label: artifact.label, preview_url: artifact.preview_url }
        : null;
  if (headerArtifact) {
    lines.push('artifact:');
    lines.push(`  slug: ${headerArtifact.slug}`);
    lines.push(`  label: ${headerArtifact.label || headerArtifact.slug}`);
    lines.push(`  file: ${slugToFilePath(headerArtifact.slug, headerArtifact.preview_url)}`);
    lines.push(`  preview-url: ${headerArtifact.preview_url}`);
  } else if (uniqueSlugs.length > 1) {
    lines.push('note-artifacts: |');
    lines.push('  複数の成果物にまたがるコメントが含まれる。');
    lines.push('  各 selection の artifact-slug / file を見て対象ファイルを取り違えないこと。');
  }
  const isMedia = (el: SelectedElement) =>
    el.tagName === 'img' || el.tagName === 'video' || (el.className || '').match(/bg-\[url/);
  if (items.some((it) => it.elements.some(isMedia))) {
    lines.push('intent-hint: |');
    lines.push('  選択要素に視覚メディア (<img> / <video> / 背景画像) が含まれる。');
    lines.push('  文面が「画像を〜に変えて」なら image-gen スキル (/api/v1/images/edit) 経由で差し替え。');
    lines.push('  文面が「動画にして」「動かして」「アニメーションに」なら video-gen スキル');
    lines.push('  (/api/v1/videos/generate + reference_image_url で image-to-video) を使い、');
    lines.push('  対象ファイルの <img> を <video autoPlay loop muted playsInline> に書き換える。');
    lines.push('  文面が曖昧なら内容を優先して判断（静止画の修正 vs 動きが欲しい）。');
  }
  // 1要素の詳細を YAML 行に書き出す（indent はネスト位置に合わせる）。
  const pushElementLines = (element: SelectedElement, indent: string, listItem: boolean) => {
    const pad = (first: boolean) => (listItem && first ? `${indent}- ` : listItem ? `${indent}  ` : indent);
    let first = true;
    const push = (line: string) => {
      lines.push(`${pad(first)}${line}`);
      first = false;
    };
    push(`ref: @${element.refId}`);
    push(`tag: ${element.tagName}`);
    if (element.elementKey?.startsWith('@')) push(`edit-id: ${JSON.stringify(element.elementKey)}`);
    if (element.className) push(`class: ${JSON.stringify(element.className)}`);
    if (element.bgColor) push(`computed-background: ${element.bgColor}`);
    if (element.ancestors?.length) {
      push(`ancestors: ${element.ancestors.join(' > ')}`);
    }
    push(
      `bounding-rect: { x: ${Math.round(element.rect.x)}, y: ${Math.round(element.rect.y)}, w: ${Math.round(element.rect.width)}, h: ${Math.round(element.rect.height)} }`
    );
    if (element.text) push(`text-content: ${JSON.stringify(element.text)}`);
    if (element.outerHtmlSnippet) {
      push('html: |');
      const htmlIndent = listItem ? `${indent}  ` : indent;
      element.outerHtmlSnippet.split('\n').forEach((ln) => {
        lines.push(`${htmlIndent}  ${ln}`);
      });
    }
  };

  lines.push('selections:');
  items.forEach(({ elements, text, artifact: itemArtifact }, i) => {
    lines.push(`  - no: ${i + 1}`);
    if (uniqueSlugs.length > 1 && itemArtifact) {
      lines.push(`    artifact-slug: ${itemArtifact.slug}`);
      lines.push(`    file: ${slugToFilePath(itemArtifact.slug, itemArtifact.preview_url)}`);
    }
    if (elements.length > 1) {
      // 複数要素への1指示: targets に全要素を列挙する。
      lines.push(`    target-count: ${elements.length}`);
      lines.push('    targets:');
      elements.forEach((element) => pushElementLines(element, '      ', true));
    } else if (elements[0]) {
      // 単一要素は従来のフラットな形（後方互換）。
      pushElementLines(elements[0], '    ', false);
    }
    lines.push('    instruction: |');
    text.split('\n').forEach((ln) => lines.push(`      ${ln}`));
  });
  lines.push('</dan-context>');

  // 本文側にも人間が読める形で並べる（チャット履歴を見返した時に何を頼んだか分かる）
  const body = items
    .map(({ elements, text }, i) => {
      const labelOf = (element: SelectedElement) =>
        element.text
          ? `<${element.tagName}> "${element.text.slice(0, 30)}"`
          : `<${element.tagName}>`;
      const label =
        elements.length > 1
          ? `${elements.map(labelOf).join(' + ')}（${elements.length}要素まとめて）`
          : elements[0]
            ? labelOf(elements[0])
            : '';
      return `${items.length > 1 ? `${i + 1}. ` : ''}${label}\n${text}`;
    })
    .join('\n\n');
  const suffix = tail.trim() ? `\n\n${tail.trim()}` : '';
  return `${lines.join('\n')}\n\n${body}${suffix}`;
}

/**
 * サーバー取得(fresh)をキャッシュ(old)へ「追いつき」として結合する純関数。
 * 画面にしか無い新しい行（SSE直挿入・楽観表示）を消さず、変わっていない行は
 * 同じオブジェクトを使い回して再描画を最小にする。通常のクエリと、部屋を開く
 * 束ね応答の投入、両方から使う。
 */
function mergeFreshMessages(
  old: { messages: MessageResponse[] } | undefined,
  fresh: { messages: MessageResponse[] },
): { messages: MessageResponse[] } {
  if (!old?.messages?.length) return fresh;
  // オブジェクト同一性の安定化: 内容が変わっていない行は「前回と同じ
  // オブジェクト」を使い回す。これが無いとポーリングのたびに全行が新しい
  // オブジェクトになり、MessageBubble の memo が全滅して毎回500件を再描画・
  // マークダウン再解析していた（長い部屋で送信直後に自分のメッセージが
  // 数秒遅れて出る/全体が重い、の主犯）。再描画は変わった行だけになる。
  const prevById = new Map(old.messages.map((m) => [m.id, m]));
  const stabilized = fresh.messages.map((m) => {
    const prev = prevById.get(m.id);
    return prev
      && prev.content === m.content
      && prev.pendingFollowup === m.pendingFollowup
      && prev.reply_to_id === m.reply_to_id
      ? prev
      : m;
  });
  const freshIds = new Set(fresh.messages.map((m) => m.id));
  // 生き残り条件: 直近2分の行だけ（保存ラグでfetchがまだ知らない可能性の
  // ある窓）。それより古いのに fresh に無い行はサーバーで削除された行
  // （取り消した送信等）なので落とす——落とさないと永遠に画面に残る。
  // 遡り読み込みで足した行は fresh の取得窓（最新N件）より古いので fresh に
  // 含まれないが、削除された訳ではない。窓の下端より古い行は無条件で残す。
  const cutoff = Date.now() - 120_000;
  const oldestFresh = fresh.messages.length
    ? Math.min(...fresh.messages.map((m) => new Date(m.created_at).getTime()))
    : Infinity;
  const localOnly = old.messages.filter((m) => {
    if (freshIds.has(m.id)) return false;
    const t = new Date(m.created_at).getTime();
    return t >= cutoff || t < oldestFresh;
  });
  if (localOnly.length === 0) return { messages: stabilized };
  const merged = [...stabilized, ...localOnly].sort(
    (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
  );
  return { messages: merged };
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
  const pendingPrependScrollRef = useRef<{ height: number; top: number } | null>(null);
  // 遡り読み込み（APK と同じ方式）。上端まで来たら before=最古の created_at で
  // 追加取得し、キャッシュの末尾に足す。取得中の二重発火と、無い時の再要求を防ぐ。
  const hasMoreOlderRef = useRef(true);
  const isLoadingOlderRef = useRef(false);
  const [visibleItemCount, setVisibleItemCount] = useState(INITIAL_CHAT_RENDER_COUNT);
  const [hasNewMessages, setHasNewMessages] = useState(false);
  // 最下部から離れているか（「最新へ」ジャンプボタンの表示用）
  const [isAwayFromBottom, setIsAwayFromBottom] = useState(false);
  const messagesContentRef = useRef<HTMLDivElement>(null);
  const [lightboxImage, setLightboxImage] = useState<string | null>(null);
  const [replyTo, setReplyTo] = useState<MessageResponse | null>(null);
  const [voiceOpen, setVoiceOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<MessageResponse[] | null>(null);
  const [searchLoading, setSearchLoading] = useState(false);
  const [workspaceMode, setWorkspaceMode] = useState<'chat' | 'production'>(() => {
    if (typeof window === 'undefined') return 'chat';
    const params = new URLSearchParams(window.location.search);
    return params.get('production') === '1' || params.has('content_id') ? 'production' : 'chat';
  });
  const pendingJumpRef = useRef<string | null>(null);
  const { warmupMode } = useRecoveryState(projectId);

  // Preview pane state
  const previewProjectId = usePreviewStore((s) => s.projectId);
  const previewArtifact = usePreviewStore((s) => s.artifact);
  const openArtifact = usePreviewStore((s) => s.openArtifact);
  const closePreview = usePreviewStore((s) => s.closePreview);
  const addPendingComment = usePreviewStore((s) => s.addPendingComment);
  const isPreviewOpenForProject =
    !!previewArtifact && previewProjectId === projectId;

  // Auto-close preview when switching projects
  useEffect(() => {
    if (previewProjectId && previewProjectId !== projectId) {
      closePreview();
    }
  }, [projectId, previewProjectId, closePreview]);

  const [artifactMenuOpen, setArtifactMenuOpen] = useState(false);

  const seenArtifactIdsRef = useRef<Set<string>>(new Set());

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

  // コメントは「追加」して溜めるだけ。実際の送信はチャットの送信ボタン
  // （ChatInput.handleSendMessage）で、溜まった全件を1通にして行う。
  const handleAddComment = useCallback(() => {
    addPendingComment();
  }, [addPendingComment]);

  const [openState, setOpenState] = useState<'pending' | 'done' | 'failed'>('pending');
  const queriesReleased = openState !== 'pending';
  const { data: project, isLoading } = useQuery({
    queryKey: ['project', projectId],
    queryFn: () => api.projects.get(projectId),
    enabled: !!projectId && queriesReleased,
    // サイドバーの一覧キャッシュには room_id を含む同型のプロジェクトが既に
    // あるので、それを種にして即座に立ち上げる。これが無いと「プロジェクト
    // 取得→room_id判明→メッセージ取得」の直列2段になり、1段目の間は
    // メッセージクエリが disabled=データ無し扱いで「メッセージを送信して
    // 開始してください」が一瞬表示される（誤った空判定）。
    // updatedAt=0 で即 stale 扱いにし、正式な取得は必ず裏で走る。
    initialData: () =>
      queryClient
        .getQueryData<ProjectListResponse>(['projects'])
        ?.projects?.find((p) => p.id === projectId),
    initialDataUpdatedAt: 0,
    retry: 1,
    refetchInterval: (query) => (query.state.error ? 15000 : 3000),
  });

  // 部屋を開く一式を1往復で取り、各クエリのキャッシュへ一括投入する。
  // 従来は project / messages / artifacts / active / current-run / execution-events を
  // 別々に投げ、実行中の部屋では一番遅い1本（events 500件 ≒1s）が切替時間を決めていた。
  // 束ね応答が届くまで個別クエリは止めておき（二重取得しない）、届いたら解放する。
  // 束ねが失敗/遅延した時は個別クエリに戻す（従来経路が保険）。
  const initialRoomId = project?.room_id;
  useEffect(() => {
    if (!projectId || !initialRoomId) return;
    let cancelled = false;
    const timer = window.setTimeout(() => { if (!cancelled) setOpenState((s) => (s === 'pending' ? 'failed' : s)); }, 6000);
    // fetchQuery で in-flight を共有する（StrictMode の二重 effect や連打で同じ束ねを二度投げない）
    queryClient
      .fetchQuery({
        queryKey: ['room-open', initialRoomId, projectId],
        queryFn: () => api.rooms.open(initialRoomId, projectId, CHAT_INITIAL_FETCH_LIMIT),
        staleTime: 1500,
        gcTime: 0,
      })
      .then((data) => {
        if (cancelled) return;
        if (data.project) queryClient.setQueryData(['project', projectId], data.project);
        if (data.messages) {
          if (data.messages.length < CHAT_INITIAL_FETCH_LIMIT) hasMoreOlderRef.current = false;
          const fresh = { messages: data.messages };
          queryClient.setQueryData(['project-messages', initialRoomId], (old?: { messages: MessageResponse[] }) =>
            mergeFreshMessages(old, fresh),
          );
        }
        queryClient.setQueryData(['chat-artifacts', initialRoomId], (data.artifacts ?? []) as ArtifactRecord[]);
        if (data.active) queryClient.setQueryData(['session-active', initialRoomId], data.active);
        queryClient.setQueryData(['current-run', projectId], data.current_run);
        // 待機中の部屋は events が同梱されない（null）。空で種を撒いておけば
        // 実行が始まった時だけ refetchInterval が取りに行く。
        queryClient.setQueryData(['execution-events', projectId], data.execution_events ?? []);
        setOpenState('done');
      })
      .catch(() => { if (!cancelled) setOpenState('failed'); })
      .finally(() => window.clearTimeout(timer));
    return () => { cancelled = true; window.clearTimeout(timer); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, initialRoomId]);

  // Artifacts for the header opener button
  const { data: artifacts = [] } = useQuery<ArtifactRecord[]>({
    queryKey: ['chat-artifacts', project?.room_id],
    queryFn: async () => {
      const res = await fetch(`/api/v1/chat-artifact?room_id=${project!.room_id}`, {
        credentials: 'include',
      });
      if (!res.ok) return [];
      return res.json();
    },
    enabled: !!project?.room_id && queriesReleased,
    staleTime: 10_000,
  });

  // Auto-open newly created artifacts
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

  // たまりコメントのクリック = 編集モード。コメント元の成果物が閉じていれば
  // 開き直してから、要素の再選択＋本文の下書き復元を行う。
  const handleEditPendingComment = useCallback(
    (id: string) => {
      const st = usePreviewStore.getState();
      const comment = st.pendingComments.find((c) => c.id === id);
      if (!comment) return;
      const slug = comment.artifact?.slug;
      if (slug && (!st.artifact || st.artifact.slug !== slug)) {
        const record = artifacts.find((a) => a.slug === slug);
        if (record) openArtifact(projectId, record);
      }
      usePreviewStore.getState().beginEditPendingComment(id);
    },
    [artifacts, openArtifact, projectId]
  );

  const { data: messagesData } = useQuery({
    queryKey: ['project-messages', project?.room_id],
    // 画面＝実体の一方通行マージ。サーバー取得は「追いつき」専用で、画面に既に
    // ある新しい内容をスナップショットの古さで消してはならない。SSEで直接挿入
    // した直後の refetch が保存直後の行をまだ含まないスナップショットを返し、
    // 丸ごと置換で最新回答が数秒消える（→次のポーリングで復元）のがこれまでの
    // 「一瞬消える」画面バグの正体だった。fetch結果はキャッシュと id で結合し、
    // ローカルにしか無い行（SSE直挿入・楽観表示）は必ず生き残る。
    queryFn: async () => {
      const fresh = await api.rooms.getMessages(project!.room_id!, { limit: CHAT_INITIAL_FETCH_LIMIT });
      // 初回応答が上限未満なら、それより古い行はサーバーに無い。
      if (fresh.messages.length < CHAT_INITIAL_FETCH_LIMIT) hasMoreOlderRef.current = false;
      return mergeFreshMessages(queryClient.getQueryData<{ messages: MessageResponse[] }>(['project-messages', project?.room_id]), fresh);
    },
    enabled: !!project?.room_id && queriesReleased,
    staleTime: 5 * 1000,
    retry: 1,
    refetchInterval: (query) => (
      sseConnectedRef.current || warmupMode ? false : (query.state.error ? 15000 : 3000)
    ),
  });

  const latestMessageId = messagesData?.messages?.[0]?.id;

  // 既読は「未読がある時」だけ送る。従来は最新IDが変わるたび（開いた直後だけで
  // 3〜4回）送り、成功のたびに一覧（/projects 114KB）を丸ごと取り直していて、
  // 本命のメッセージ取得と帯域・DBを奪い合っていた。未読数は手元のキャッシュを
  // 直接ゼロにする（見た目のタイミングは同じ、手段だけ変える）。
  const markedReadRoomRef = useRef<string | null>(null);
  useEffect(() => {
    const roomId = project?.room_id;
    if (!roomId) return;
    const list = queryClient.getQueryData<ProjectListResponse>(['projects']);
    const inList = list?.projects?.find((p) => p.id === projectId);
    const unread = inList?.unread_count ?? project?.unread_count ?? 0;
    const firstForRoom = markedReadRoomRef.current !== roomId;
    if (!firstForRoom && unread <= 0) return;
    markedReadRoomRef.current = roomId;
    api.rooms.markAsRead(roomId)
      .then(() => {
        const zero = <T extends { unread_count?: number }>(p: T): T => ({ ...p, unread_count: 0 });
        queryClient.setQueryData<ProjectListResponse>(['projects'], (cur) =>
          cur ? { ...cur, projects: cur.projects.map((p) => (p.id === projectId ? zero(p) : p)) } : cur,
        );
        queryClient.setQueryData<ProjectResponse>(['project', projectId], (cur) => (cur ? zero(cur) : cur));
      })
      .catch(() => null);
  }, [latestMessageId, project?.room_id, project?.unread_count, projectId, queryClient]);

  const { data: activeStatus } = useQuery({
    queryKey: ['session-active', project?.room_id],
    queryFn: () => api.sm.getActiveStatus(project!.room_id!),
    enabled: !!project?.room_id && queriesReleased,
    retry: 1,
    // SSE未接続時は 3s ポーリング。SSE接続中もイベントでキャッシュ更新するが、
    // 追い連絡/cancel等でSSEがデシンク（接続扱いのまま無音）すると active 状態が
    // 更新源を失い「Thinking...」のまま固着しうる。10s のバックストップで必ず
    // backend の実状態に追従させ、固着を自己回復させる。
    refetchInterval: () => (sseConnectedRef.current ? 10000 : 3000),
  });

  const isBackendSessionActive = !!activeStatus?.active;

  const { data: currentRun } = useQuery({
    queryKey: ['current-run', projectId],
    queryFn: () => api.projects.currentRun(projectId),
    enabled: !!projectId && queriesReleased,
    retry: false,
    // session-active はコアのin-memory状態のみで、SSE切断後の常駐セッション
    // 継続ターンを見失う。自分のレスポンス(run.state)も実行中の根拠にして、
    // チャットを開き直してもライブ表示とポーリングが止まらないようにする。
    refetchInterval: (query) => (
      (isBackendSessionActive || query.state.data?.state === 'running')
        ? (query.state.error ? 10000 : 2000)
        : false
    ),
  });

  // 「実行中」= バックエンドのセッション状態 or DBのrun状態のどちらか。
  // 前者はSSE切断や常駐セッション経路で false になりうるが、後者(DB)は
  // 処理がsinkで続いている限り running なので、開き直し後も表示が消えない。
  const isActiveExecution = isBackendSessionActive || currentRun?.state === 'running';

  const { data: allExecutionEvents = [] } = useQuery({
    queryKey: ['execution-events', projectId],
    queryFn: () => api.projects.executionEvents.list(projectId, 500),
    enabled: !!projectId && queriesReleased,
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
  // Keep the send-time Thinking block visible until the final AI message,
  // interruption, or error. Process/tool events should not make it flicker.
  const showWarmupBlock = !!warmupMode || (
    isActiveExecution &&
    !!currentRun &&
    currentRun.state === 'running' &&
    currentRunEvents.length === 0
  );

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
    const lastHumanMsg = chronologicalMessages.findLast((m) => m.sender_type === 'human');
    const liveAnchorTime = lastHumanMsg ? new Date(lastHumanMsg.created_at).getTime() : 0;
    const liveAnchorMessageTime = liveAnchorTime;
    // Anchor the live execution block to the current RUN's start, not the last
    // human message. Without this, a follow-up sent mid-run (a newer human msg)
    // drags the live block below it, so Dan's in-progress output appears to jump
    // ABOVE the follow-up. Anchoring to the run start keeps chronological order:
    // [starting message] → [Dan's live output] → [follow-up].
    //
    // ただし RUN が実際に RUNNING の時だけ。送信直後（新runがまだ無い瞬間）に
    // ここへ「前回のrun」の開始時刻が入り、thinkingが過去に括り付けられて
    // 送信メッセージの上に出ていた（2026-07-24 実測）。トリガーとなった
    // メッセージと同じ時刻(liveAnchorTime)+subKeyで直下に固定するのが原則。
    const runStart = (currentRun as { created_at?: string } | null)?.created_at;
    const runIsLiveNow = !!currentRun && isActiveExecution && currentRun.state === 'running';
    const liveBlockSortKey = runIsLiveNow && runStart ? new Date(runStart).getTime() : liveAnchorTime;

    for (const msg of chronologicalMessages) {
      const content = msg.content || '';
      if (
        msg.sender_type !== 'human' &&
        (content.startsWith('[PROCESS]') || content.startsWith('[THINKING]'))
      ) {
        continue;
      }
      if (
        !!warmupMode &&
        msg.sender_type === 'ai' &&
        liveAnchorMessageTime > 0 &&
        new Date(msg.created_at).getTime() >= liveAnchorMessageTime
      ) {
        continue;
      }

      timedItems.push({
        item: { kind: 'message', msg },
        sortKey: new Date(msg.created_at).getTime(),
        subKey: 1,
      });
    }

    let liveBlockRendered = false;

    const savedTurnIds = new Set(
      chronologicalMessages
        .filter((msg) => msg.sender_type === 'ai' && msg.ai_context?.turn_id)
        .map((msg) => msg.ai_context!.turn_id!)
    );
    const isCurrentRunLive = runIsLiveNow;

    if (isCurrentRunLive) {
      const eventsByTurn = new Map<string, ExecutionEvent[]>();
      for (const event of allExecutionEvents) {
        if (event.run_id !== currentRun.id) continue;
        if (event.event_type === 'done' || event.event_type === 'phase') continue;
        const turnId = event.turn_id || (typeof event.metadata?.turn_id === 'string' ? event.metadata.turn_id : null);
        if (turnId && savedTurnIds.has(turnId)) continue;
        const key = turnId || `run:${event.run_id || 'unknown'}`;
        const list = eventsByTurn.get(key);
        if (list) list.push(event);
        else eventsByTurn.set(key, [event]);
      }

      const liveGroups = [...eventsByTurn.entries()]
        .map(([key, events]) => ({
          key,
          events: [...events].sort(
            (left, right) =>
              (left.seq ?? 0) - (right.seq ?? 0) ||
              new Date(left.created_at).getTime() - new Date(right.created_at).getTime()
          ),
        }))
        .sort((left, right) => {
          const leftTime = new Date(left.events[0]?.created_at || '').getTime() || liveBlockSortKey;
          const rightTime = new Date(right.events[0]?.created_at || '').getTime() || liveBlockSortKey;
          return leftTime - rightTime;
        });

      liveGroups.forEach((group, index) => {
        const steps = group.events.map(eventToStep);
        if (steps.length === 0) return;
        liveBlockRendered = true;
        timedItems.push({
          item: {
            kind: 'execution-block',
            id: `live-${projectId}-${group.key}`,
            steps,
            isLive: index === liveGroups.length - 1,
          },
          sortKey: new Date(group.events[0]?.created_at || '').getTime() || liveBlockSortKey,
          subKey: 2,
        });
      });
    }

    if (!liveBlockRendered && (showWarmupBlock || isCurrentRunLive)) {
      timedItems.push({
        item: {
          kind: 'execution-block',
          id: `live-${projectId}`,
          steps: [{
            label: transitionLabel,
            type: 'reasoning',
          }],
          isLive: true,
        },
        sortKey: showWarmupBlock ? liveBlockSortKey : liveAnchorTime,
        subKey: 2,
      });
    }

    timedItems.sort((left, right) => left.sortKey - right.sortKey || left.subKey - right.subKey);
    return timedItems.map((item) => item.item);
  }, [allExecutionEvents, currentRun, isActiveExecution, messages, projectId, showWarmupBlock, transitionLabel, warmupMode]);

  const hasAnyContent = displayItems.length > 0;

  // 初回読み込み中（下のJSXでスピナーを出す条件と同一）。メッセージだけ先に
  // 届いた時点ではまだリストがDOMに無いので、この間に「最下部へ」を発火させると
  // スピナー相手に空振りして二度と発火しない。リスト描画後に揃えるための旗。
  // run状態・作業イベントの初回取得を待つのは「実行中の部屋」だけ。待機中の
  // 部屋は後から挿入される要素が無いので、メッセージが揃った時点で表示する。
  // 実行中かどうかは一覧（サイドバー）が既に持つ has_active_run で判定し、
  // 追加取得はしない。従来は待機中の部屋でも4本の完了を待っていて、一番遅い
  // 1本（詰まった current-run 等）に切替時間が引きずられていた。
  // run状態・作業イベントは待たない。メッセージが揃った時点で描き、実行中の
  // 表示は後から到着した時に差し込む（束ね応答なら同時に届く）。
  const isBooting = !project || (!!project.room_id && messagesData === undefined);

  useEffect(() => {
    isNearBottomRef.current = true;
    hasMoreOlderRef.current = true;
    isLoadingOlderRef.current = false;
    const frame = requestAnimationFrame(() => {
      setVisibleItemCount(INITIAL_CHAT_RENDER_COUNT);
      setHasNewMessages(false);
      setIsAwayFromBottom(false);
    });
    return () => cancelAnimationFrame(frame);
  }, [projectId]);

  // 部屋ボードが有効な部屋は、履歴の代わりにボードを主役にして
  // チャットは「直前1ターン」（最後のユーザー発言以降）だけを表示する。
  const boardEnabled = !!(project?.metadata as Record<string, unknown> | null | undefined)?.board_enabled;

  const visibleDisplayItems = useMemo(() => {
    if (boardEnabled) {
      // 1セット表示: 「最後のユーザー発言」を起点に、そこから末尾まで全部を残す。
      // ダンは1ターンで複数メッセージ（返信＋送信案カード＋続報など）を返すことが
      // あるので、遡って最初のAIで打ち切る旧実装だとユーザー発言や途中のカードが
      // 切り落とされていた。起点をユーザー発言に固定すれば、そのターンのダンの
      // 出力が何通でも全部同じセットに残る。追い連絡（連続送信）も両方残る。
      // 新しいメッセージを送れば、それが新しい起点になって前のセットは引っ込む。
      let start = -1;
      for (let i = displayItems.length - 1; i >= 0; i--) {
        const item = displayItems[i];
        if (item.kind === 'message' && item.msg.sender_type !== 'ai') {
          start = i;
          break;
        }
      }
      return start >= 0 ? displayItems.slice(start) : displayItems.slice(-2);
    }
    const start = Math.max(0, displayItems.length - visibleItemCount);
    return displayItems.slice(start);
  }, [displayItems, visibleItemCount, boardEnabled]);

  const hiddenOlderCount = Math.max(0, displayItems.length - visibleDisplayItems.length);

  useLayoutEffect(() => {
    const pending = pendingPrependScrollRef.current;
    if (!pending) return;
    pendingPrependScrollRef.current = null;
    const el = scrollContainerRef.current;
    if (!el) return;
    el.scrollTop = pending.top + (el.scrollHeight - pending.height);
  }, [visibleItemCount]);

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

  // チャットを開いた瞬間に最新（一番下）を表示する。ペイント前に位置を
  // 決めるので、上の方が一瞬見えてから飛ぶちらつきが無い。
  // isBooting を依存に含めるのが要: メッセージ取得完了(hasAnyContent=true)は
  // run/イベント取得完了より先に来ることがあり、その時点ではまだスピナー表示中で
  // リストがDOMに無い。スピナーが消えた後のコミットでもう一度発火させる。
  useLayoutEffect(() => {
    if (isBooting || !hasAnyContent) return;
    const el = scrollContainerRef.current;
    if (el && isNearBottomRef.current) el.scrollTop = el.scrollHeight;
  }, [projectId, hasAnyContent, isBooting]);

  // 開いた直後の「最下部へ合わせたのに途中で止まる」の根治。画像・動画・
  // マークダウンの遅延レイアウトで後から中身の高さが伸びると、一度合わせた
  // 位置が相対的に上へずれる。ユーザーが自分で上へスクロールするまで
  // （isNearBottomRef が true の間）は、高さが変わるたび最下部へ貼り直す。
  useEffect(() => {
    if (isBooting) return;
    const content = messagesContentRef.current;
    const el = scrollContainerRef.current;
    // スピナー表示中は messagesContentRef が null で observer 登録に失敗する。
    // isBooting を依存に含め、リスト描画後に必ず登録し直す。
    if (!content || !el) return;
    const observer = new ResizeObserver(() => {
      if (isNearBottomRef.current) el.scrollTop = el.scrollHeight;
    });
    observer.observe(content);
    return () => observer.disconnect();
  }, [projectId, hasAnyContent, isBooting]);

  const handleScroll = useCallback(() => {
    const el = scrollContainerRef.current;
    if (!el) return;
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 100;
    isNearBottomRef.current = nearBottom;
    setIsAwayFromBottom(!nearBottom);
    if (nearBottom) setHasNewMessages(false);
    if (el.scrollTop < 240) {
      pendingPrependScrollRef.current = {
        height: el.scrollHeight,
        top: el.scrollTop,
      };
      setVisibleItemCount((count) =>
        count >= displayItems.length
          ? count
          : Math.min(displayItems.length, count + CHAT_RENDER_INCREMENT)
      );
      // 手元の行を全部描画し終えていて、まだサーバーに古い行があるなら取りに行く。
      const roomId = project?.room_id;
      if (
        roomId
        && visibleItemCount >= displayItems.length
        && hasMoreOlderRef.current
        && !isLoadingOlderRef.current
      ) {
        const queryKey = ['project-messages', roomId];
        const cached = queryClient.getQueryData<{ messages: MessageResponse[] }>(queryKey);
        const oldest = cached?.messages?.length
          ? cached.messages.reduce((a, b) => (a.created_at < b.created_at ? a : b))
          : null;
        if (oldest) {
          isLoadingOlderRef.current = true;
          api.rooms.getMessages(roomId, { limit: CHAT_OLDER_FETCH_LIMIT, before: oldest.created_at })
            .then((older) => {
              if (older.messages.length < CHAT_OLDER_FETCH_LIMIT) hasMoreOlderRef.current = false;
              if (older.messages.length === 0) return;
              pendingPrependScrollRef.current = { height: el.scrollHeight, top: el.scrollTop };
              queryClient.setQueryData<{ messages: MessageResponse[] }>(queryKey, (cur) => {
                const have = new Set((cur?.messages ?? []).map((m) => m.id));
                const add = older.messages.filter((m) => !have.has(m.id));
                return { messages: [...(cur?.messages ?? []), ...add] };
              });
              // 足した分もそのまま描画対象にする（描画窓は別途スクロールで広がる）。
              setVisibleItemCount((count) => count + older.messages.length);
            })
            .catch(() => null)
            .finally(() => { isLoadingOlderRef.current = false; });
        }
      }
    }
  }, [displayItems.length, visibleItemCount, project?.room_id, queryClient]);

  // 初回20件が画面に収まってしまうとスクロールが発生せず遡れない。描画後に
  // 画面が埋まっていなければ一度だけ handleScroll を通し、遡り読み込みを起動する。
  useEffect(() => {
    if (isBooting || !hasAnyContent) return;
    const el = scrollContainerRef.current;
    if (el && el.scrollHeight <= el.clientHeight + 240) handleScroll();
  }, [projectId, isBooting, hasAnyContent, handleScroll]);

  const scrollToBottom = useCallback(() => {
    const el = scrollContainerRef.current;
    if (el) {
      el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' });
    }
    setHasNewMessages(false);
  }, []);

  const highlightAndScroll = useCallback((id: string) => {
    const el = document.querySelector(`[data-message-id="${id}"]`);
    if (!el) return false;
    el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    el.classList.add('ring-2', 'ring-primary/60', 'rounded-lg');
    setTimeout(() => el.classList.remove('ring-2', 'ring-primary/60', 'rounded-lg'), 1800);
    return true;
  }, []);

  const runSearch = useCallback(
    async (q: string) => {
      const roomId = project?.room_id;
      if (!roomId || !q.trim()) {
        setSearchResults(null);
        return;
      }
      setSearchLoading(true);
      try {
        const res = await api.rooms.searchMessages(roomId, q.trim(), 50);
        setSearchResults(res.messages);
      } catch {
        toast.error('検索に失敗しました');
        setSearchResults([]);
      } finally {
        setSearchLoading(false);
      }
    },
    [project?.room_id]
  );

  // Jump to a search hit. The message may not be in the rendered window — or not
  // even in the loaded history (older than the fetched 500) — so expand the
  // window / merge a context fetch, then scroll+highlight once it's on screen.
  const jumpToMessage = useCallback(
    async (msg: MessageResponse) => {
      const roomId = project?.room_id;
      setSearchOpen(false);
      if (highlightAndScroll(msg.id)) return;
      const loaded = messages.some((m) => m.id === msg.id);
      if (loaded) {
        setVisibleItemCount(displayItems.length);
        pendingJumpRef.current = msg.id;
        return;
      }
      if (!roomId) return;
      try {
        const before = new Date(new Date(msg.created_at).getTime() + 2000).toISOString();
        const ctx = await api.rooms.getMessages(roomId, { limit: 100, before });
        queryClient.setQueryData<MessagesListResponse>(['project-messages', roomId], (prev) => {
          const map = new Map<string, MessageResponse>();
          for (const m of prev?.messages || []) map.set(m.id, m);
          for (const m of ctx.messages) map.set(m.id, m);
          const merged = [...map.values()].sort((a, b) => (a.created_at < b.created_at ? 1 : -1));
          return { messages: merged };
        });
        setVisibleItemCount((c) => c + 200);
        pendingJumpRef.current = msg.id;
      } catch {
        toast.error('メッセージへ移動できませんでした');
      }
    },
    [project?.room_id, messages, displayItems.length, highlightAndScroll, queryClient]
  );

  // Complete a pending jump after the list re-renders (window expand / merge).
  useEffect(() => {
    if (!pendingJumpRef.current) return;
    const id = pendingJumpRef.current;
    const frame = requestAnimationFrame(() => {
      if (highlightAndScroll(id)) pendingJumpRef.current = null;
    });
    return () => cancelAnimationFrame(frame);
  }, [visibleDisplayItems, highlightAndScroll]);

  return (
    <div className="relative flex h-full w-full overflow-hidden">
    {voiceOpen && project?.room_id && (
      <div className="fixed bottom-4 right-4 z-50 w-[360px] max-w-[calc(100vw-2rem)] max-h-[80vh] overflow-y-auto rounded-2xl border border-neutral-800 bg-neutral-950 shadow-2xl">
        <VoiceSession
          roomId={project.room_id}
          chatTitle={project.title || undefined}
          onClose={() => setVoiceOpen(false)}
        />
      </div>
    )}
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
        {project?.room_id && (
          <button
            onClick={async () => {
              // 制作 = launch the desktop production app for this room ONLY (no inline browser
              // workspace, no chat toggle). First choice: ask the backend (same machine as the
              // editor) to spawn the app directly — no browser "open this app?" dialog, no
              // silent no-op. The done:// deep link stays as a fallback for when the backend
              // is unreachable.
              const rid = project?.room_id;
              if (!rid) return;
              const token = typeof window !== 'undefined' ? localStorage.getItem('done-token') || '' : '';
              try {
                const res = await fetch('/api/v1/production-assets/launch-editor', {
                  method: 'POST',
                  headers: {
                    'Content-Type': 'application/json',
                    ...(token ? { Authorization: `Bearer ${token}` } : {}),
                  },
                  body: JSON.stringify({ room_id: rid }),
                });
                if (res.ok) {
                  const j = await res.json().catch(() => null);
                  if (j?.launched) return;
                }
              } catch {
                /* backend unreachable — fall through to the protocol link */
              }
              try {
                const a = document.createElement('a');
                a.href = `done://production?room_id=${rid}&token=${encodeURIComponent(token)}`;
                document.body.appendChild(a);
                a.click();
                a.remove();
              } catch {
                /* app not installed */
              }
            }}
            className="flex shrink-0 items-center gap-1 rounded-md border border-border bg-background px-2 py-1 text-xs font-medium text-foreground transition-colors hover:bg-muted"
            title="制作アプリで開く"
          >
            <Clapperboard className="h-3.5 w-3.5" />
            <span className="hidden sm:inline">制作</span>
          </button>
        )}
        {project?.room_id && (
          <button
            onClick={() => setSearchOpen((v) => !v)}
            className={`flex shrink-0 items-center gap-1 rounded-md border px-2 py-1 text-xs font-medium transition-colors ${
              searchOpen
                ? 'border-primary bg-primary/10 text-primary'
                : 'border-border bg-background text-foreground hover:bg-muted'
            }`}
            title="チャット内をワード検索（過去の発言を探す）"
          >
            <Search className="h-3.5 w-3.5" />
            <span className="hidden sm:inline">検索</span>
          </button>
        )}
        {project?.room_id && (
          <button
            onClick={() => setVoiceOpen((v) => !v)}
            className={`flex shrink-0 items-center gap-1 rounded-md border px-2 py-1 text-xs font-medium transition-colors ${
              voiceOpen
                ? 'border-emerald-700 bg-emerald-900/30 text-emerald-200 hover:bg-emerald-900/50'
                : 'border-border bg-background text-foreground hover:bg-muted'
            }`}
            title="このチャットの文脈で音声開発（パネルを開閉。delegate はこのチャットに書き戻されます）"
          >
            <Mic className="h-3.5 w-3.5" />
            <span>音声</span>
          </button>
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

      {searchOpen && workspaceMode === 'chat' && (
        <div className="shrink-0 border-b border-border bg-background px-3 py-2">
          <div className="flex items-center gap-2">
            <Search className="h-4 w-4 shrink-0 text-muted-foreground" />
            <input
              autoFocus
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') runSearch(searchQuery);
                if (e.key === 'Escape') setSearchOpen(false);
              }}
              placeholder="チャット内をワード検索…（Enterで検索）"
              className="flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
            />
            {searchLoading && <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />}
            <button
              onClick={() => runSearch(searchQuery)}
              className="shrink-0 rounded-md border border-border px-2 py-1 text-xs font-medium hover:bg-muted"
            >
              検索
            </button>
            <button
              onClick={() => setSearchOpen(false)}
              className="shrink-0 rounded p-1 text-muted-foreground hover:text-foreground"
              title="閉じる"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
          {searchResults && (
            <div className="mt-2 max-h-[42vh] overflow-y-auto rounded-md border border-border">
              {searchResults.length === 0 ? (
                <div className="px-3 py-4 text-center text-sm text-muted-foreground">
                  一致するメッセージはありません
                </div>
              ) : (
                <>
                  <div className="border-b border-border/50 px-3 py-1.5 text-xs text-muted-foreground">
                    {searchResults.length}件ヒット（新しい順）
                  </div>
                  {searchResults.map((m) => (
                    <button
                      key={m.id}
                      onClick={() => jumpToMessage(m)}
                      className="block w-full border-b border-border/40 px-3 py-2 text-left last:border-b-0 hover:bg-muted"
                    >
                      <div className="flex items-center gap-2 text-xs text-muted-foreground">
                        <span className="font-medium text-foreground/80">
                          {m.sender_type === 'ai' ? 'ダン' : m.sender_name}
                        </span>
                        <span>{new Date(m.created_at).toLocaleString('ja-JP')}</span>
                      </div>
                      <div className="mt-0.5 line-clamp-2 text-sm">
                        {highlightSnippet(m.content, searchQuery)}
                      </div>
                    </button>
                  ))}
                </>
              )}
            </div>
          )}
        </div>
      )}

      {workspaceMode === 'production' && project?.room_id ? (
        <div className="min-h-0 flex-1 overflow-hidden">
          <ProductionWorkspace
            roomId={project.room_id}
          />
        </div>
      ) : (
      <div ref={scrollContainerRef} onScroll={handleScroll} className="relative flex-1 overflow-y-auto">
        {/* 新着が無くても、上へスクロール中は常に「最新へ」ジャンプを出す */}
        {(hasNewMessages || isAwayFromBottom) && (
          <button
            onClick={scrollToBottom}
            className="sticky top-[calc(100%-3rem)] z-10 mx-auto flex items-center gap-1.5 rounded-full bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground shadow-lg transition-opacity hover:opacity-90"
            style={{ display: 'block', marginLeft: 'auto', marginRight: 'auto', width: 'fit-content' }}
          >
            <ChevronDown className="h-3.5 w-3.5" />
            {hasNewMessages ? '新しいメッセージ' : '最新へ'}
          </button>
        )}
        {/* 部屋ボード: 有効な部屋では履歴の代わりに現在地ボードを主役表示。
            isBooting で外すと送信のたびに再マウント→付箋アニメ再生になるので、
            ロード状態に関わらずマウントし続ける（ボード自身がスピナーを持つ） */}
        {/* ボードの取得/SSE はメッセージを描いた後に始める（部屋を開く1往復と DB を取り合わない） */}
        {boardEnabled && !isBooting ? <RoomBoard projectId={projectId} /> : null}
        {/* 「空の部屋」の文言は、取得が成功して本当に0件だった時だけ出す。
            プロジェクト情報の取得中（=メッセージクエリが未開始）や
            メッセージ初回取得中は「読み込み中」であって「空」ではない。
            従来は未開始状態を空と誤判定し、チャット切替のたびに
            「メッセージを送信して開始してください」が一瞬表示されていた。 */}
        {/* run状態・作業イベントの初回取得も待ってから一発で描画する。
            メッセージだけ先に出すと、後から「実行中…」→「〇件の作業」が
            順に挿入されて画面が組み変わって見える（到着順のバラつき）。
            isLoading は初回取得中のみ true なので、以降のポーリングや
            キャッシュ済みの開き直しではスピナーに戻らない。 */}
        {isBooting ? (
          <div className="flex items-center justify-center p-6">
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          </div>
        ) : !hasAnyContent && !isActiveExecution ? (
          <div className="flex h-full flex-col items-center justify-center p-6">
            <MessageSquare className="mb-3 h-10 w-10 text-muted-foreground/20" />
            <p className="text-base text-muted-foreground md:text-[17px]">メッセージを送信して開始してください。</p>
          </div>
        ) : (
          <div ref={messagesContentRef} className="flex flex-col gap-2 p-4">
            {(() => {
              const lastExecutionIndex = visibleDisplayItems.reduce(
                (last, item, index) => (item.kind === 'execution-block' ? index : last),
                -1
              );

              // LINE風の日付区切り: 日付が変わった最初のメッセージの前にだけ
              // 「今日」「昨日」「8月7日(木)」のチップを挟む。作業ブロックは
              // 日付を持たないので判定を進めない（前後のメッセージに任せる）。
              let prevDateKey: string | null = null;
              const nodes: ReactNode[] = [];
              visibleDisplayItems.forEach((item, index) => {
                if (item.kind === 'execution-block') {
                  nodes.push(
                    <InlineProcessBlock
                      key={item.id}
                      steps={item.steps}
                      isLive={item.isLive}
                      defaultCollapsed={index !== lastExecutionIndex && !item.isLive}
                    />
                  );
                  return;
                }

                const d = item.msg.created_at ? new Date(item.msg.created_at) : null;
                // ボード部屋は1セット表示なので日付チップは出さない
                if (d && !isNaN(d.getTime()) && !boardEnabled) {
                  const dateKey = `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
                  if (dateKey !== prevDateKey) {
                    nodes.push(
                      <div key={`date-${dateKey}`} className="my-2 flex justify-center">
                        <span className="rounded-full bg-muted px-3 py-1 text-[11px] text-muted-foreground">
                          {formatDateSeparator(d)}
                        </span>
                      </div>
                    );
                    prevDateKey = dateKey;
                  }
                }

                nodes.push(
                  <div key={item.msg.id} data-message-id={item.msg.id} className="animate-in fade-in slide-in-from-bottom-3 zoom-in-95 duration-200 motion-reduce:animate-none"><MessageBubble msg={item.msg} onImageClick={setLightboxImage} onReply={setReplyTo} /></div>
                );
              });
              return nodes;
            })()}
            {hiddenOlderCount > 0 ? (
              <div className="h-1" aria-hidden="true" />
            ) : null}
            <div ref={messagesEndRef} />
          </div>
        )}
      </div>
      )}

      {/* 承認/却下ボタンは廃止。チャットでの承認を観察者が検知して計画を記録する */}

      {project?.room_id && workspaceMode === 'chat' ? (
        <ChatInput
          projectId={projectId}
          roomId={project.room_id}
          isSessionActive={isActiveExecution}
          activeOriginMessageId={activeStatus?.origin_message_id}
          sendMessageRef={sendMessageRef}
          onSseStateChange={(connected) => { sseConnectedRef.current = connected; }}
          replyTo={replyTo}
          onClearReply={() => setReplyTo(null)}
          onAddComment={handleAddComment}
          onEditPendingComment={handleEditPendingComment}
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
        <PreviewPane onAddComment={handleAddComment} />
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
          <PreviewPane onAddComment={handleAddComment} />
        </div>
      </>
    )}
    {isResizing && (
      <div className="fixed inset-0 z-50 cursor-col-resize" />
    )}
    </div>
  );
}
