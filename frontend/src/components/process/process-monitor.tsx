'use client';

import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Activity,
  ChevronDown,
  ChevronUp,
  CheckCircle2,
  Circle,
  Loader2,
  XCircle,
  AlertCircle,
} from 'lucide-react';
import { useQuery } from '@tanstack/react-query';

import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Badge } from '@/components/ui/badge';
import {
  api,
  type TaskResponse,
  type ExecutionStatusResponse,
} from '@/lib/api-client';

// タスクタイプの日本語表示
const taskTypeLabels: Record<string, string> = {
  email: 'メール',
  line: 'LINE',
  purchase: '購入',
  payment: '支払い',
  research: '調査',
  travel: '旅行予約',
  phone: '電話',
  other: 'その他',
};

// ステータスの表示設定
const statusConfig = {
  pending: { label: '待機中', color: 'bg-muted', icon: Circle },
  analyzing: { label: '分析中', color: 'bg-blue-500/20', icon: Loader2 },
  proposed: { label: '提案済み', color: 'bg-yellow-500/20', icon: AlertCircle },
  confirmed: { label: '確認済み', color: 'bg-green-500/20', icon: CheckCircle2 },
  executing: { label: '実行中', color: 'bg-primary/20', icon: Loader2 },
  completed: { label: '完了', color: 'bg-green-500/20', icon: CheckCircle2 },
  failed: { label: '失敗', color: 'bg-destructive/20', icon: XCircle },
  cancelled: { label: 'キャンセル', color: 'bg-muted', icon: XCircle },
};

interface TaskItemProps {
  task: TaskResponse;
}

function TaskItem({ task }: TaskItemProps) {
  const [isExpanded, setIsExpanded] = useState(false);
  const isExecuting = task.status === 'executing';

  // 実行中のタスクの場合、ステータスをポーリング
  const { data: executionStatus } = useQuery({
    queryKey: ['execution-status', task.id],
    queryFn: () => api.tasks.getExecutionStatus(task.id),
    enabled: isExecuting,
    refetchInterval: isExecuting ? 2000 : false, // 2秒ごとにポーリング
  });

  const config = statusConfig[task.status] || statusConfig.pending;
  const StatusIcon = config.icon;
  const progress = executionStatus?.progress;

  return (
    <motion.div
      initial={{ opacity: 0, y: -10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -10 }}
      className="border-b border-border last:border-0"
    >
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full flex items-center gap-3 p-3 hover:bg-muted/30 transition-colors text-left"
      >
        <div className={cn('p-1.5 rounded-md', config.color)}>
          <StatusIcon
            className={cn(
              'h-4 w-4',
              isExecuting && 'animate-spin',
              task.status === 'completed' && 'text-green-500',
              task.status === 'failed' && 'text-destructive'
            )}
          />
        </div>

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <p className="text-sm font-medium truncate">
              {taskTypeLabels[task.type] || task.type}
            </p>
            <Badge variant="outline" className="text-xs px-1.5 py-0">
              {config.label}
            </Badge>
          </div>
          <p className="text-xs text-muted-foreground truncate">
            {task.original_wish.length > 40
              ? `${task.original_wish.slice(0, 40)}...`
              : task.original_wish}
          </p>
        </div>

        {isExpanded ? (
          <ChevronUp className="h-4 w-4 text-muted-foreground shrink-0" />
        ) : (
          <ChevronDown className="h-4 w-4 text-muted-foreground shrink-0" />
        )}
      </button>

      <AnimatePresence>
        {isExpanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden"
          >
            <div className="px-3 pb-3 space-y-2">
              {/* 実行ステップ */}
              {progress && (
                <div className="space-y-1.5">
                  {/* 完了したステップ */}
                  {progress.steps_completed?.map((step, index) => (
                    <div
                      key={`completed-${index}`}
                      className="flex items-center gap-2 text-xs"
                    >
                      <CheckCircle2 className="h-3.5 w-3.5 text-green-500 shrink-0" />
                      <span className="text-muted-foreground">{step}</span>
                    </div>
                  ))}

                  {/* 現在のステップ */}
                  {progress.current_step && (
                    <div className="flex items-center gap-2 text-xs">
                      <Loader2 className="h-3.5 w-3.5 text-primary animate-spin shrink-0" />
                      <span className="font-medium">{progress.current_step}</span>
                    </div>
                  )}

                  {/* 残りのステップ */}
                  {progress.steps_remaining?.map((step, index) => (
                    <div
                      key={`remaining-${index}`}
                      className="flex items-center gap-2 text-xs"
                    >
                      <Circle className="h-3.5 w-3.5 text-muted-foreground/50 shrink-0" />
                      <span className="text-muted-foreground/70">{step}</span>
                    </div>
                  ))}
                </div>
              )}

              {/* 実行中以外の場合 */}
              {!progress && (
                <div className="space-y-1.5">
                  {task.proposed_actions.map((action, index) => (
                    <div
                      key={index}
                      className="flex items-center gap-2 text-xs"
                    >
                      <Circle className="h-3.5 w-3.5 text-muted-foreground/50 shrink-0" />
                      <span className="text-muted-foreground">{action}</span>
                    </div>
                  ))}
                </div>
              )}

              {/* エラーメッセージ */}
              {executionStatus?.error_message && (
                <div className="flex items-start gap-2 p-2 rounded-md bg-destructive/10 text-xs">
                  <XCircle className="h-3.5 w-3.5 text-destructive shrink-0 mt-0.5" />
                  <span className="text-destructive">
                    {executionStatus.error_message}
                  </span>
                </div>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}

export function ProcessMonitor() {
  const [isExpanded, setIsExpanded] = useState(true);

  // アクティブなタスク（実行中または最近のタスク）を取得
  const { data: tasksData, isLoading } = useQuery({
    queryKey: ['active-tasks'],
    queryFn: () => api.tasks.list({ limit: 10 }),
    refetchInterval: 10000, // 10秒ごとに更新
  });

  // 実行中またはアクティブなタスクのみフィルター
  const activeTasks =
    tasksData?.tasks?.filter(
      (task) =>
        task.status === 'executing' ||
        task.status === 'analyzing' ||
        task.status === 'proposed' ||
        task.status === 'confirmed'
    ) || [];

  const executingCount = activeTasks.filter(
    (t) => t.status === 'executing'
  ).length;

  // タスクがなければ表示しない
  if (!isLoading && activeTasks.length === 0) {
    return null;
  }

  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.95, y: 20 }}
      animate={{ opacity: 1, scale: 1, y: 0 }}
      className="absolute bottom-4 right-80 z-40"
    >
      <div
        className={cn(
          'w-80 bg-card border border-border rounded-xl shadow-2xl overflow-hidden transition-all',
          !isExpanded && 'w-auto'
        )}
      >
        {/* Header */}
        <button
          onClick={() => setIsExpanded(!isExpanded)}
          className="w-full flex items-center justify-between p-3 hover:bg-muted/30 transition-colors"
        >
          <div className="flex items-center gap-2">
            <Activity
              className={cn(
                'h-4 w-4',
                executingCount > 0 ? 'text-primary' : 'text-muted-foreground'
              )}
            />
            <span className="text-sm font-medium">タスク</span>
            {activeTasks.length > 0 && (
              <Badge
                variant={executingCount > 0 ? 'default' : 'secondary'}
                className="h-5 px-1.5 text-xs"
              >
                {activeTasks.length}
              </Badge>
            )}
            {executingCount > 0 && (
              <span className="flex items-center gap-1 text-xs text-primary">
                <Loader2 className="h-3 w-3 animate-spin" />
                実行中
              </span>
            )}
          </div>
          {isExpanded ? (
            <ChevronDown className="h-4 w-4 text-muted-foreground" />
          ) : (
            <ChevronUp className="h-4 w-4 text-muted-foreground" />
          )}
        </button>

        {/* Tasks List */}
        <AnimatePresence>
          {isExpanded && (
            <motion.div
              initial={{ height: 0 }}
              animate={{ height: 'auto' }}
              exit={{ height: 0 }}
              className="overflow-hidden"
            >
              <ScrollArea className="max-h-80">
                {isLoading ? (
                  <div className="flex items-center justify-center p-4">
                    <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
                  </div>
                ) : activeTasks.length === 0 ? (
                  <p className="text-sm text-muted-foreground text-center p-4">
                    アクティブなタスクはありません
                  </p>
                ) : (
                  <AnimatePresence mode="popLayout">
                    {activeTasks.map((task) => (
                      <TaskItem key={task.id} task={task} />
                    ))}
                  </AnimatePresence>
                )}
              </ScrollArea>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </motion.div>
  );
}

