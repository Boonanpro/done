'use client';

import { useState, useEffect, useRef } from 'react';
import { Loader2, Check, AlertCircle, ChevronDown, ChevronUp, Brain, Terminal } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';

import { api, type ExecutionEvent } from '@/lib/api-client';

interface ProcessMonitorProps {
  projectId: string;
  isExecuting: boolean;
}

export function ProcessMonitor({ projectId, isExecuting }: ProcessMonitorProps) {
  const [isCollapsed, setIsCollapsed] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  const { data: events = [] } = useQuery({
    queryKey: ['execution-events', projectId],
    queryFn: () => api.projects.executionEvents.list(projectId),
    enabled: !!projectId,
    refetchInterval: isExecuting ? 2000 : false,
  });

  // 新しいイベントが来たら自動スクロール
  useEffect(() => {
    if (!isCollapsed && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [events.length, isCollapsed]);

  if (events.length === 0 && !isExecuting) {
    return null;
  }

  const toolEvents = events.filter((e) => e.event_type === 'tool_use');
  const errorEvents = events.filter((e) => e.event_type === 'error');
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
        {isExecuting && (
          <Loader2 className="h-3 w-3 animate-spin text-primary ml-auto" />
        )}
        {!isExecuting && errorEvents.length === 0 && totalSteps > 0 && (
          <Check className="h-3 w-3 text-green-500 ml-auto" />
        )}
        {!isExecuting && errorEvents.length > 0 && (
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
            {events.map((event) => (
              <EventItem key={event.id} event={event} />
            ))}
            {isExecuting && (
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

function EventItem({ event }: { event: ExecutionEvent }) {
  if (event.event_type === 'tool_use') {
    return (
      <div className="flex items-start gap-1.5 text-[10px]">
        <Check className="h-2.5 w-2.5 text-green-500 shrink-0 mt-0.5" />
        <span className="text-muted-foreground">{event.tool_label || event.tool_name || 'ツール実行'}</span>
      </div>
    );
  }

  if (event.event_type === 'reasoning') {
    return (
      <div className="flex items-start gap-1.5 text-[10px]">
        <Brain className="h-2.5 w-2.5 text-yellow-500 shrink-0 mt-0.5" />
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
