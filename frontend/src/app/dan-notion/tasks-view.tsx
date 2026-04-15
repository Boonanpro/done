'use client';

/**
 * やりたいことリスト
 * - 全ページから type=task のブロックを収集して一覧表示
 * - 各タスクの下にコメントスレッド（ユーザーとダンのやり取り）
 * - タスクの追加・完了切り替え
 */
import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  CheckCircle2, Circle, Plus, Send, Loader2, MessageSquare,
  ChevronDown, ChevronRight, Sparkles,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';

const API = '/api/v1/dan-notion';

type Block = {
  id: string;
  parent_id: string | null;
  type: string;
  properties: Record<string, any>;
  content: any;
  created_by: string;
  created_at: string;
  updated_at: string;
};

async function fetchJSON<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
    credentials: 'include',
  });
  if (!res.ok) throw new Error(`${res.status}`);
  return res.json();
}

// コメントスレッド
function CommentThread({ taskId }: { taskId: string }) {
  const queryClient = useQueryClient();
  const [input, setInput] = useState('');

  const { data: comments = [], isLoading } = useQuery({
    queryKey: ['task-comments', taskId],
    queryFn: () => fetchJSON<Block[]>(`${API}/blocks/${taskId}/children`),
  });

  const addComment = useMutation({
    mutationFn: (text: string) =>
      fetchJSON<Block>(`${API}/blocks`, {
        method: 'POST',
        body: JSON.stringify({
          parent_id: taskId,
          type: 'paragraph',
          properties: { text },
          content: [],
          created_by: 'user',
        }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['task-comments', taskId] });
      setInput('');
    },
  });

  const handleSend = () => {
    const text = input.trim();
    if (!text) return;
    addComment.mutate(text);
  };

  return (
    <div className="ml-8 mt-2 space-y-2">
      {isLoading && <Loader2 className="h-3 w-3 animate-spin text-muted-foreground" />}

      {comments.map((comment) => {
        const isAI = comment.created_by === 'ai';
        const text = comment.properties?.text || '';
        return (
          <div
            key={comment.id}
            className={cn(
              'flex gap-2 items-start text-sm',
              isAI ? 'text-blue-400' : 'text-foreground/80'
            )}
          >
            {isAI ? (
              <Sparkles className="h-3.5 w-3.5 mt-0.5 shrink-0 text-blue-400" />
            ) : (
              <MessageSquare className="h-3.5 w-3.5 mt-0.5 shrink-0 text-muted-foreground" />
            )}
            <div>
              <span className="font-medium text-xs mr-2">
                {isAI ? 'ダン' : 'あなた'}
              </span>
              <span>{text}</span>
            </div>
          </div>
        );
      })}

      <div className="flex gap-2">
        <Input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              handleSend();
            }
          }}
          placeholder="コメントを追加..."
          className="h-7 text-sm"
        />
        <Button
          size="sm"
          variant="ghost"
          onClick={handleSend}
          disabled={addComment.isPending || !input.trim()}
          className="h-7 px-2"
        >
          <Send className="h-3 w-3" />
        </Button>
      </div>
    </div>
  );
}

// タスク1件
function TaskItem({ task, onToggle }: { task: Block; onToggle: () => void }) {
  const [expanded, setExpanded] = useState(false);
  const isDone = task.properties?.checked === true;
  const title = task.properties?.title || task.properties?.text || '(無題)';
  const parentTitle = task.properties?.parent_page_title;

  return (
    <div className="border-b border-border/50 py-3">
      <div className="flex items-start gap-2">
        {/* チェックボックス */}
        <button onClick={onToggle} className="mt-0.5 shrink-0">
          {isDone ? (
            <CheckCircle2 className="h-5 w-5 text-green-500" />
          ) : (
            <Circle className="h-5 w-5 text-muted-foreground hover:text-foreground" />
          )}
        </button>

        {/* タイトル */}
        <div className="flex-1 min-w-0">
          <div className={cn('text-sm', isDone && 'line-through text-muted-foreground')}>
            {title}
          </div>
          {parentTitle && (
            <div className="text-xs text-muted-foreground mt-0.5">
              📄 {parentTitle}
            </div>
          )}
        </div>

        {/* コメント展開トグル */}
        <button
          onClick={() => setExpanded(!expanded)}
          className="text-muted-foreground hover:text-foreground"
        >
          {expanded ? (
            <ChevronDown className="h-4 w-4" />
          ) : (
            <ChevronRight className="h-4 w-4" />
          )}
        </button>
      </div>

      {/* コメントスレッド */}
      {expanded && <CommentThread taskId={task.id} />}
    </div>
  );
}

// メインビュー
export function TasksView() {
  const queryClient = useQueryClient();
  const [newTask, setNewTask] = useState('');
  const [filter, setFilter] = useState<'all' | 'open' | 'done'>('all');

  // 全ページからtype=taskのブロックを取得
  // 既存APIには全taskを取得するエンドポイントがないので、pagesを取得して各ページのchildrenからtaskを集める
  // → 簡易的にsearch APIを使う（typeでフィルタできるなら）
  // → なければ全pages取得→children取得のカスケード
  // ここでは /search を使って type=task を検索する
  const { data: tasks = [], isLoading } = useQuery({
    queryKey: ['all-tasks', filter],
    queryFn: async () => {
      // search APIにtype filterがあるか試す。なければ全pagesからフィルタ
      try {
        const res = await fetch(`${API}/search`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({ query: '', type_filter: 'task' }),
        });
        if (res.ok) {
          const hits = await res.json();
          // SearchHitからBlockを抽出
          return hits.map((h: any) => h.block || h).filter((b: Block) => b.type === 'task');
        }
      } catch {}

      // フォールバック: 全root pagesを取得して各ページのchildrenからtask抽出
      const pages = await fetchJSON<Block[]>(`${API}/pages`);
      const allTasks: Block[] = [];
      for (const page of pages) {
        try {
          const children = await fetchJSON<Block[]>(`${API}/blocks/${page.id}/children`);
          const pageTasks = children.filter((c) => c.type === 'task');
          // 親ページのタイトルを付与
          pageTasks.forEach((t) => {
            t.properties = { ...t.properties, parent_page_title: page.properties?.title };
          });
          allTasks.push(...pageTasks);
        } catch {}
      }
      return allTasks;
    },
  });

  const filteredTasks = tasks.filter((t: Block) => {
    if (filter === 'open') return !t.properties?.checked;
    if (filter === 'done') return t.properties?.checked === true;
    return true;
  });

  const toggleTask = useMutation({
    mutationFn: (task: Block) =>
      fetchJSON<Block>(`${API}/blocks/${task.id}`, {
        method: 'PATCH',
        body: JSON.stringify({
          properties: { ...task.properties, checked: !task.properties?.checked },
        }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['all-tasks'] });
    },
  });

  const addTask = useMutation({
    mutationFn: (title: string) =>
      fetchJSON<Block>(`${API}/blocks`, {
        method: 'POST',
        body: JSON.stringify({
          parent_id: null, // root level task
          type: 'task',
          properties: { title, checked: false },
          content: [],
        }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['all-tasks'] });
      setNewTask('');
    },
  });

  const handleAdd = () => {
    const text = newTask.trim();
    if (!text) return;
    addTask.mutate(text);
  };

  return (
    <div className="flex flex-col h-full">
      {/* ヘッダー */}
      <div className="p-4 border-b border-border">
        <h2 className="text-lg font-semibold text-foreground mb-3">やりたいこと</h2>

        {/* 新規タスク追加 */}
        <div className="flex gap-2 mb-3">
          <Input
            value={newTask}
            onChange={(e) => setNewTask(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                handleAdd();
              }
            }}
            placeholder="やりたいことを追加..."
            className="text-sm"
          />
          <Button
            size="sm"
            onClick={handleAdd}
            disabled={addTask.isPending || !newTask.trim()}
          >
            <Plus className="h-4 w-4 mr-1" />
            追加
          </Button>
        </div>

        {/* フィルター */}
        <div className="flex gap-1">
          {(['all', 'open', 'done'] as const).map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={cn(
                'px-3 py-1 rounded-full text-xs transition-colors',
                filter === f
                  ? 'bg-primary text-primary-foreground'
                  : 'text-muted-foreground hover:text-foreground hover:bg-secondary'
              )}
            >
              {f === 'all' ? 'すべて' : f === 'open' ? '未完了' : '完了'}
              {f === 'all' && ` (${tasks.length})`}
              {f === 'open' && ` (${tasks.filter((t: Block) => !t.properties?.checked).length})`}
              {f === 'done' && ` (${tasks.filter((t: Block) => t.properties?.checked).length})`}
            </button>
          ))}
        </div>
      </div>

      {/* タスクリスト */}
      <div className="flex-1 overflow-y-auto px-4">
        {isLoading ? (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
          </div>
        ) : filteredTasks.length === 0 ? (
          <div className="text-center py-12 text-muted-foreground text-sm">
            {filter === 'all' ? 'やりたいことを追加してください' : '該当するタスクがありません'}
          </div>
        ) : (
          filteredTasks.map((task: Block) => (
            <TaskItem
              key={task.id}
              task={task}
              onToggle={() => toggleTask.mutate(task)}
            />
          ))
        )}
      </div>
    </div>
  );
}
