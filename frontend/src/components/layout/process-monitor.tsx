'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import { Loader2, Check, AlertCircle, ChevronDown, ChevronUp, Brain, Terminal } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';

import { api, type ExecutionEvent } from '@/lib/api-client';

interface ProcessMonitorProps {
  projectId: string;
  isExecuting: boolean;
}

// メンバーロール判定
type MemberRole = 'researcher' | 'critic' | 'leader' | null;

function getMemberRole(event: ExecutionEvent): MemberRole {
  const member = event.metadata?.member as string | undefined;
  if (member === 'researcher') return 'researcher';
  if (member === 'critic') return 'critic';
  if (member === 'leader') return 'leader';
  return null;
}

// ロール別の設定
const ROLE_CONFIG = {
  researcher: { emoji: '🔬', color: 'text-blue-500', label: 'リサーチャー' },
  critic: { emoji: '🔍', color: 'text-orange-500', label: 'クリティック' },
  leader: { emoji: '', color: '', label: '' },
} as const;

export function ProcessMonitor({ projectId, isExecuting }: ProcessMonitorProps) {
  const [isCollapsed, setIsCollapsed] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  const { data: events = [], refetch } = useQuery({
    queryKey: ['execution-events', projectId],
    queryFn: () => api.projects.executionEvents.list(projectId),
    enabled: !!projectId,
    // isExecuting が true、またはイベントに done がなければポーリング
    refetchInterval: isExecuting ? 2000 : false,
  });

  // done イベントがなければ自動ポーリング開始
  const hasDoneEvent = events.some((e) => e.event_type === 'done');
  const hasActiveEvents = events.length > 0 && !hasDoneEvent;

  const { data: autoPolledEvents } = useQuery({
    queryKey: ['execution-events-auto', projectId],
    queryFn: () => api.projects.executionEvents.list(projectId),
    enabled: !!projectId && !isExecuting && hasActiveEvents,
    refetchInterval: hasActiveEvents ? 3000 : false,
  });

  const displayEvents = (isExecuting ? events : autoPolledEvents) || events;

  // タブ復帰時に即座に再取得
  const handleVisibilityChange = useCallback(() => {
    if (document.visibilityState === 'visible' && projectId) {
      refetch();
    }
  }, [projectId, refetch]);

  useEffect(() => {
    document.addEventListener('visibilitychange', handleVisibilityChange);
    return () => {
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, [handleVisibilityChange]);

  // 新しいイベントが来たら自動スクロール
  useEffect(() => {
    if (!isCollapsed && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [displayEvents.length, isCollapsed]);

  const isActive = isExecuting || hasActiveEvents;

  if (displayEvents.length === 0 && !isActive) {
    return null;
  }

  const toolEvents = displayEvents.filter((e) => e.event_type === 'tool_use');
  const errorEvents = displayEvents.filter((e) => e.event_type === 'error');
  const totalSteps = toolEvents.length;

  return (
    <div className="shrink-0 border-b border-border bg-muted/30">
      {/* Header */}
      <button
        onClick={() => setIsCollapsed((v) => !v)}
        className="flex items-center gap-2 w-full px-4 py-2 text-xs hover:bg-muted/50 transition-colors"
      >
        {isCollapsed ? (
          <ChevronDown className="h-3 w-3 text-muted-foreground" />
        ) : (
          <ChevronUp className="h-3 w-3 text-muted-foreground" />
        )}
        <Terminal className="h-3 w-3 text-primary" />
        <span className="text-muted-foreground font-medium">
          実行プロセス
        </span>
        <span className="text-muted-foreground/60">
          ({totalSteps}ステップ{errorEvents.length > 0 ? ` / ${errorEvents.length}エラー` : ''})
        </span>
        {isActive && (
          <Loader2 className="h-3 w-3 animate-spin text-primary ml-auto" />
        )}
        {!isActive && errorEvents.length === 0 && totalSteps > 0 && (
          <Check className="h-3 w-3 text-green-500 ml-auto" />
        )}
        {!isActive && errorEvents.length > 0 && (
          <AlertCircle className="h-3 w-3 text-red-500 ml-auto" />
        )}
      </button>

      {/* Event List */}
      {!isCollapsed && (
        <div
          ref={scrollRef}
          className="max-h-[200px] overflow-y-auto px-4 pb-3"
        >
          <div className="border-l-2 border-primary/30 pl-3 space-y-1">
            {displayEvents.map((event) => (
              <EventItem key={event.id} event={event} />
            ))}
            {isActive && (
              <div className="flex items-center gap-1.5 text-[10px] text-muted-foreground">
                <Loader2 className="h-2.5 w-2.5 animate-spin text-primary" />
                <span>実行中...</span>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function MemberBadge({ role }: { role: MemberRole }) {
  if (!role || role === 'leader') return null;
  const config = ROLE_CONFIG[role];
  return (
    <span className={`inline-flex items-center gap-0.5 text-[9px] font-medium ${config.color} bg-opacity-10 rounded px-1`}>
      {config.emoji} {config.label}
    </span>
  );
}

function EventItem({ event }: { event: ExecutionEvent }) {
  const role = getMemberRole(event);

  if (event.event_type === 'tool_use') {
    return (
      <div className="flex items-start gap-1.5 text-[10px]">
        <Check className="h-2.5 w-2.5 text-green-500 shrink-0 mt-0.5" />
        {role && role !== 'leader' && <MemberBadge role={role} />}
        <span className="text-muted-foreground">{event.tool_label || event.tool_name || 'ツール実行'}</span>
      </div>
    );
  }

  if (event.event_type === 'reasoning') {
    return (
      <div className="flex items-start gap-1.5 text-[10px]">
        <Brain className="h-2.5 w-2.5 text-yellow-500 shrink-0 mt-0.5" />
        {role && role !== 'leader' && <MemberBadge role={role} />}
        <span className="text-muted-foreground/80 italic">
          {event.content || '思考中...'}
        </span>
      </div>
    );
  }

  if (event.event_type === 'error') {
    return (
      <div className="flex items-start gap-1.5 text-[10px]">
        <AlertCircle className="h-2.5 w-2.5 text-red-500 shrink-0 mt-0.5" />
        <span className="text-red-600">{event.content || 'エラー'}</span>
      </div>
    );
  }

  // phase or unknown
  return (
    <div className="flex items-start gap-1.5 text-[10px]">
      <span className="text-muted-foreground">{event.content || event.event_type}</span>
    </div>
  );
}
