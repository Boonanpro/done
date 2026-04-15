'use client';

/**
 * ダン用Notion トップページ
 *
 * 構成:
 *   - 左: ページツリー (root pages)
 *   - 中央: 選択ページのブロックエディタ
 *   - 右: Autopilot トレース + 通知センター
 */
import { useState, useMemo, useEffect, useRef, useCallback } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Notebook, Plus, Loader2, Bell, Activity, FileText, Trash2,
  ChevronRight, ChevronDown, ChevronUp, History, Sparkles, AlertCircle,
  Send, MessageSquare, Brain, Wrench, CheckCircle2, XCircle, RotateCcw,
  LayoutGrid, List as ListIcon, Target,
} from 'lucide-react';
import { TasksView } from './tasks-view';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Card } from '@/components/ui/card';
import { cn } from '@/lib/utils';

const API = '/api/v1/dan-notion';

type Block = {
  id: string;
  user_id: string;
  parent_id: string | null;
  type: string;
  order_key: string;
  properties: Record<string, any>;
  content: any;
  icon: string | null;
  cover_url: string | null;
  is_starred: boolean;
  tags: string[];
  version: number;
  created_at: string;
  updated_at: string;
};

type Trigger = {
  id: string;
  name: string;
  kind: string;
  is_enabled: boolean;
  fire_count: number;
  last_fired_at: string | null;
};

type Notification = {
  id: string;
  kind: string;
  title: string;
  body: string | null;
  severity: 'info' | 'warning' | 'urgent';
  due_at: string | null;
  read_at: string | null;
  created_at: string;
};

type Trace = {
  id: string;
  trigger_run_id: string | null;
  agent_name: string;
  event_type: 'thinking' | 'tool_call' | 'tool_result' | 'message' | 'decision' | 'error' | 'complete' | 'sub_agent_start' | 'self_repair';
  content: Record<string, any>;
  parent_trace_id: string | null;
  created_at: string;
};

type RunSummary = {
  id: string;
  status: string;
  started_at: string;
  finished_at: string | null;
};

type ChatMessage = {
  id: string;
  role: 'user' | 'assistant';
  text: string;
  run_id?: string;
  ts: number;
};

/**
 * タイトル先頭に絵文字がありかつ icon も設定されている場合、絵文字を除去して返す
 * 例: title="📥 受信箱", icon="📥" → "受信箱"
 */
function stripLeadingEmoji(title: string, hasIcon: boolean): string {
  if (!hasIcon || !title) return title;
  // Unicode emoji の範囲 + 空白を先頭から除去
  return title.replace(/^[\p{Emoji_Presentation}\p{Extended_Pictographic}\u{FE0F}\u{200D}]+\s*/u, '').trim() || title;
}

function displayTitle(block: Block): string {
  const t = block.properties?.title || '';
  return stripLeadingEmoji(t, !!block.icon);
}


class FetchError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function fetchJSON<T>(url: string, init?: RequestInit): Promise<T> {
  const token = typeof window !== 'undefined' ? localStorage.getItem('done-token') : null;
  const res = await fetch(url, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init?.headers || {}),
    },
  });
  if (!res.ok) {
    let detail = '';
    try {
      const j = await res.clone().json();
      detail = j?.detail || '';
    } catch {}
    throw new FetchError(res.status, `${res.status} ${res.statusText}${detail ? ': ' + detail : ''}`);
  }
  return res.json() as Promise<T>;
}

/**
 * SSE で agent_traces を購読する Hook
 * - fetch + ReadableStream で Authorization ヘッダ対応
 * - complete trace を受信したら onComplete(runId, text) を呼ぶ (1 run につき1回)
 * - stale state 問題回避のため onComplete は useRef 経由
 */
function useTraceStream(
  runId: string | null,
  onComplete?: (runId: string, text: string) => void
): { traces: Trace[]; done: boolean } {
  const [traces, setTraces] = useState<Trace[]>([]);
  const [done, setDone] = useState(false);

  // onComplete は毎レンダで新しい関数インスタンスでも effect を再実行しない
  const onCompleteRef = useRef(onComplete);
  onCompleteRef.current = onComplete;

  useEffect(() => {
    if (!runId) {
      setTraces([]);
      setDone(false);
      return;
    }
    setTraces([]);
    setDone(false);

    const ctrl = new AbortController();
    const token = typeof window !== 'undefined' ? localStorage.getItem('done-token') : null;
    const headers = token ? { Authorization: `Bearer ${token}` } : {};

    let pollTimer: ReturnType<typeof setInterval> | null = null;
    // 有効な complete が見つかるたびに更新して親へ送る。
    // 最新の成功テキストで親側の history が上書きされるため、試行1 の空 complete は無視される
    let bestCompleteText: string | null = null;

    const maybeFireComplete = (trace: Trace) => {
      if (trace.event_type !== 'complete') return;
      const text = trace.content?.result || '';
      const isError = trace.content?.is_error === true;
      if (!text || isError) return;
      bestCompleteText = text;
      onCompleteRef.current?.(runId, text);
    };

    const fireFromPollFetch = (text: string) => {
      if (!text) return;
      bestCompleteText = text;
      onCompleteRef.current?.(runId, text);
    };

    // Fallback: run status を polling し、succeeded/failed を検出したら done=true
    const startStatusPoll = () => {
      if (pollTimer) return;
      pollTimer = setInterval(async () => {
        try {
          const res = await fetch(`${API}/trigger-runs?limit=10`, { headers });
          if (!res.ok) return;
          const runs = await res.json();
          const match = runs.find?.((r: any) => r.id === runId);
          if (match && ['succeeded', 'failed', 'cancelled'].includes(match.status)) {
            setDone(true);
            // polling で気付いた場合、有効な complete trace を取得
            if (!bestCompleteText) {
              try {
                const tracesRes = await fetch(`${API}/trigger-runs/${runId}/traces`, { headers });
                if (tracesRes.ok) {
                  const trs = await tracesRes.json();
                  // 有効 (is_error=false かつ text 非空) な最後の complete を探す
                  const validComp = [...(trs || [])]
                    .reverse()
                    .find(
                      (t: any) =>
                        t.event_type === 'complete' &&
                        t.content?.result &&
                        t.content?.is_error !== true
                    );
                  if (validComp) {
                    fireFromPollFetch(validComp.content?.result || '');
                  }
                }
              } catch {}
            }
          }
        } catch {}
      }, 5000);
    };

    (async () => {
      try {
        const res = await fetch(`${API}/runs/${runId}/traces/stream`, {
          headers,
          signal: ctrl.signal,
        });
        if (!res.body) {
          startStatusPoll();
          return;
        }
        startStatusPoll();
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buf = '';
        while (true) {
          const { value, done: streamDone } = await reader.read();
          if (streamDone) break;
          buf += decoder.decode(value, { stream: true });
          const events = buf.split('\n\n');
          buf = events.pop() || '';
          for (const ev of events) {
            const lines = ev.split('\n');
            let dataLine = '';
            let isDone = false;
            for (const l of lines) {
              if (l.startsWith('event: done')) isDone = true;
              if (l.startsWith('data: ')) dataLine = l.slice(6);
            }
            if (isDone) {
              setDone(true);
              continue;
            }
            if (!dataLine) continue;
            try {
              const trace = JSON.parse(dataLine) as Trace;
              setTraces((prev) => {
                if (prev.some((t) => t.id === trace.id)) return prev;
                return [...prev, trace];
              });
              maybeFireComplete(trace);
            } catch {}
          }
        }
      } catch (e) {
        if ((e as any)?.name !== 'AbortError') console.warn('SSE error', e);
      }
    })();

    return () => {
      ctrl.abort();
      if (pollTimer) clearInterval(pollTimer);
    };
  }, [runId]);

  return { traces, done };
}

function DanNotionInner() {
  const qc = useQueryClient();
  const [selectedPageId, setSelectedPageId] = useState<string | null>(null);
  const [showTasksView, setShowTasksView] = useState(false);
  const [newPageTitle, setNewPageTitle] = useState('');
  const [notifOpen, setNotifOpen] = useState(false);

  // ページ一覧
  const pagesQ = useQuery({
    queryKey: ['dan-notion', 'pages'],
    queryFn: () => fetchJSON<Block[]>(`${API}/pages`),
  });

  // 選択ページの子ブロック
  const blocksQ = useQuery({
    queryKey: ['dan-notion', 'blocks', selectedPageId],
    queryFn: () =>
      selectedPageId
        ? fetchJSON<Block[]>(`${API}/blocks/${selectedPageId}/children`)
        : Promise.resolve([] as Block[]),
    enabled: !!selectedPageId,
  });

  // バージョン履歴
  const versionsQ = useQuery({
    queryKey: ['dan-notion', 'versions', selectedPageId],
    queryFn: () =>
      selectedPageId
        ? fetchJSON<any[]>(`${API}/blocks/${selectedPageId}/versions`)
        : Promise.resolve([] as any[]),
    enabled: !!selectedPageId,
  });

  // トリガー一覧
  const triggersQ = useQuery({
    queryKey: ['dan-notion', 'triggers'],
    queryFn: () => fetchJSON<Trigger[]>(`${API}/triggers`),
  });

  // 通知一覧
  const notifQ = useQuery({
    queryKey: ['dan-notion', 'notifications'],
    queryFn: () => fetchJSON<Notification[]>(`${API}/notifications?limit=20`),
    refetchInterval: 30_000,
  });

  // 直近のtrigger_runs
  const runsQ = useQuery({
    queryKey: ['dan-notion', 'runs'],
    queryFn: () => fetchJSON<any[]>(`${API}/trigger-runs?limit=10`),
    refetchInterval: 15_000,
  });

  const createPage = useMutation({
    mutationFn: (title: string) =>
      fetchJSON<Block>(`${API}/blocks`, {
        method: 'POST',
        body: JSON.stringify({
          type: 'page',
          properties: { title },
          content: [],
          icon: '📄',
        }),
      }),
    onSuccess: (block) => {
      qc.invalidateQueries({ queryKey: ['dan-notion', 'pages'] });
      setSelectedPageId(block.id);
      setNewPageTitle('');
    },
  });

  const deletePage = useMutation({
    mutationFn: (id: string) =>
      fetchJSON(`${API}/blocks/${id}`, { method: 'DELETE' }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['dan-notion', 'pages'] });
      setSelectedPageId(null);
    },
  });

  const addBlock = useMutation({
    mutationFn: (type: string) =>
      fetchJSON<Block>(`${API}/blocks`, {
        method: 'POST',
        body: JSON.stringify({
          type,
          parent_id: selectedPageId,
          properties: {},
          content: [],
        }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['dan-notion', 'blocks', selectedPageId] });
    },
  });

  // 指定ブロックの直後に新規ブロックを挿入 (inline + ボタン用)
  const insertBlock = useMutation({
    mutationFn: ({ after_block_id, type }: { after_block_id: string | null; type: string }) => {
      const defaultsByType: Record<string, any> = {
        page: {
          properties: { title: '新規フォルダ', is_folder: true, view_mode: 'grid' },
          icon: '📁',
        },
        heading: { properties: {} },
        paragraph: { properties: {} },
        checklist: { properties: { checked: false } },
      };
      const base = defaultsByType[type] || { properties: {} };
      return fetchJSON<Block>(`${API}/blocks`, {
        method: 'POST',
        body: JSON.stringify({
          type,
          parent_id: selectedPageId,
          content: [],
          after_block_id: after_block_id || undefined,
          ...base,
        }),
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['dan-notion', 'blocks', selectedPageId] });
    },
  });

  const updateBlock = useMutation({
    mutationFn: ({ id, content }: { id: string; content: any }) =>
      fetchJSON<Block>(`${API}/blocks/${id}`, {
        method: 'PATCH',
        body: JSON.stringify({ content }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['dan-notion', 'blocks', selectedPageId] });
      qc.invalidateQueries({ queryKey: ['dan-notion', 'versions', selectedPageId] });
    },
  });

  const removeBlock = useMutation({
    mutationFn: (id: string) =>
      fetchJSON(`${API}/blocks/${id}`, { method: 'DELETE' }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['dan-notion', 'blocks', selectedPageId] });
    },
  });

  // 選択中のページ: root pages に含まれていなければ API から取得
  const selectedPageFromRoot = useMemo(
    () => pagesQ.data?.find((p) => p.id === selectedPageId) || null,
    [pagesQ.data, selectedPageId]
  );
  const selectedSubPageQ = useQuery({
    queryKey: ['dan-notion', 'block', selectedPageId],
    queryFn: () =>
      selectedPageId ? fetchJSON<Block>(`${API}/blocks/${selectedPageId}`) : Promise.resolve(null),
    enabled: !!selectedPageId && !selectedPageFromRoot,
  });
  const selectedPage: Block | null = selectedPageFromRoot || selectedSubPageQ.data || null;

  // フォルダのみ view_mode を持つ。フォルダでない場合は常に list (= テキスト文書表示)
  const viewMode: 'list' | 'grid' =
    selectedPage?.properties?.is_folder
      ? (selectedPage?.properties?.view_mode === 'grid' ? 'grid' : 'list')
      : 'list';

  const togglePageViewMode = useMutation({
    mutationFn: (mode: 'list' | 'grid') =>
      fetchJSON<Block>(`${API}/blocks/${selectedPageId}`, {
        method: 'PATCH',
        body: JSON.stringify({
          properties: { ...(selectedPage?.properties || {}), view_mode: mode },
        }),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['dan-notion', 'pages'] });
      qc.invalidateQueries({ queryKey: ['dan-notion', 'block', selectedPageId] });
    },
  });

  const unreadCount = notifQ.data?.filter((n) => !n.read_at).length || 0;

  // ===== Active run / Gantt / Chat 状態 =====
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [ganttExpanded, setGanttExpanded] = useState(false);
  const [chatOpen, setChatOpen] = useState(false);
  const [chatHistory, setChatHistory] = useState<ChatMessage[]>([]);
  const [chatInput, setChatInput] = useState('');
  const [chatSending, setChatSending] = useState(false);
  // ガントドロップダウンで run 選んだ時にチャットを該当メッセージへスクロールさせる指令
  const [scrollToRunId, setScrollToRunId] = useState<string | null>(null);

  // onComplete: run_id を使って履歴を確実に更新 (レース条件なし)
  const handleRunComplete = useCallback((runId: string, text: string) => {
    setChatHistory((prev) => {
      // 既に assistant メッセージが入っていたら上書き (text が揃ったケース)
      const idx = prev.findIndex((m) => m.run_id === runId && m.role === 'assistant');
      const newMsg: ChatMessage = {
        id: `assistant-${runId}`,
        role: 'assistant',
        text: text || '(完了)',
        run_id: runId,
        ts: Date.now(),
      };
      if (idx >= 0) {
        const copy = [...prev];
        copy[idx] = newMsg;
        return copy;
      }
      return [...prev, newMsg];
    });
    qc.invalidateQueries({ queryKey: ['dan-notion'] });
  }, [qc]);

  const { traces, done: traceDone } = useTraceStream(activeRunId, handleRunComplete);

  // 直近の run 一覧 (切替ドロップダウン用)
  const recentRunsQ = useQuery({
    queryKey: ['dan-notion', 'recent-runs'],
    queryFn: () => fetchJSON<RunSummary[]>(`${API}/runs/recent?limit=10`),
    refetchInterval: 10_000,
  });

  // チャット履歴を DB から復元 (mount 時 + 完了時に再取得)
  const chatHistoryQ = useQuery({
    queryKey: ['dan-notion', 'chat-history'],
    queryFn: () =>
      fetchJSON<Array<{
        run_id: string;
        status: string;
        started_at: string;
        user_text: string | null;
        assistant_text: string | null;
      }>>(`${API}/chat/history?limit=50`),
    refetchInterval: 10_000,
  });

  // DB 履歴を chatHistory に反映 (ローカルの optimistic msg は保持、既存は差し替え)
  useEffect(() => {
    if (!chatHistoryQ.data) return;
    const dbMessages: ChatMessage[] = [];
    for (const r of chatHistoryQ.data) {
      if (r.user_text) {
        dbMessages.push({
          id: `user-${r.run_id}`,
          role: 'user',
          text: r.user_text,
          run_id: r.run_id,
          ts: new Date(r.started_at).getTime(),
        });
      }
      if (r.assistant_text) {
        dbMessages.push({
          id: `assistant-${r.run_id}`,
          role: 'assistant',
          text: r.assistant_text,
          run_id: r.run_id,
          ts: new Date(r.started_at).getTime() + 1,
        });
      }
    }
    setChatHistory((prev) => {
      // DB にない optimistic msg (run_id 未設定 or DB に未反映) を末尾に残す
      const dbRunIds = new Set(dbMessages.map((m) => m.run_id));
      const optimistic = prev.filter(
        (m) => !m.run_id || (m.run_id && !dbRunIds.has(m.run_id))
      );
      return [...dbMessages, ...optimistic];
    });
  }, [chatHistoryQ.data]);

  const sendChat = async () => {
    const msg = chatInput.trim();
    if (!msg || chatSending) return;
    setChatSending(true);
    setChatInput('');
    // optimistic: ローカルに即表示 (run_id はまだ不明)
    const tempId = `pending-user-${Date.now()}`;
    setChatHistory((prev) => [
      ...prev,
      { id: tempId, role: 'user', text: msg, ts: Date.now() },
    ]);
    try {
      const res = await fetchJSON<{ run_id: string }>(`${API}/chat`, {
        method: 'POST',
        body: JSON.stringify({ message: msg }),
      });
      setActiveRunId(res.run_id);
      setGanttExpanded(true);
      // pending を run_id 付きに更新 (以降 DB 履歴が追いつけば差し替えられる)
      setChatHistory((prev) =>
        prev.map((m) =>
          m.id === tempId
            ? { ...m, id: `user-${res.run_id}`, run_id: res.run_id }
            : m
        )
      );
    } catch (e) {
      setChatHistory((prev) => [
        ...prev,
        {
          id: `error-${Date.now()}`,
          role: 'assistant',
          text: `エラー: ${(e as Error).message}`,
          ts: Date.now(),
        },
      ]);
    } finally {
      setChatSending(false);
    }
  };

  // ガントドロップダウンで run 選択 → チャットを該当メッセージへスクロール要求
  const selectRunFromGantt = useCallback((runId: string) => {
    setActiveRunId(runId);
    setScrollToRunId(runId);
    setChatOpen(true);
  }, []);

  return (
    <div className="flex flex-col h-screen bg-white text-slate-900">
      {/* ========== 上: ガントタイムライン ========== */}
      <GanttTimeline
        traces={traces}
        runId={activeRunId}
        runs={recentRunsQ.data || []}
        onSelectRun={selectRunFromGantt}
        expanded={ganttExpanded}
        onToggle={() => setGanttExpanded((e) => !e)}
        running={!traceDone && !!activeRunId}
      />

      {/* ========== 中央 3ペイン ========== */}
      <div className="flex flex-1 min-h-0">
      {/* ========== 左: ページツリー ========== */}
      <aside className="w-64 border-r border-slate-200 flex flex-col bg-slate-50">
        <div className="p-4 border-b border-slate-200">
          <div className="flex items-center gap-2 mb-3">
            <Notebook className="h-5 w-5 text-indigo-600" />
            <h2 className="font-semibold">ダン用Notion</h2>
          </div>
          <div className="flex gap-2">
            <Input
              placeholder="新規ページ名"
              value={newPageTitle}
              onChange={(e) => setNewPageTitle(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && newPageTitle.trim()) {
                  createPage.mutate(newPageTitle.trim());
                }
              }}
              className="h-8 text-sm"
            />
            <Button
              size="sm"
              onClick={() => newPageTitle.trim() && createPage.mutate(newPageTitle.trim())}
              disabled={createPage.isPending || !newPageTitle.trim()}
            >
              <Plus className="h-4 w-4" />
            </Button>
          </div>
        </div>
        <div className="flex-1 min-h-0 overflow-y-auto">
          <div className="p-2 space-y-1">
            {/* やりたいことリストボタン */}
            <button
              onClick={() => { setShowTasksView(true); setSelectedPageId(null); }}
              className={cn(
                'w-full flex items-center gap-2 px-3 py-2 rounded-md text-sm text-left transition-colors',
                showTasksView
                  ? 'bg-white border border-indigo-200 shadow-sm text-indigo-700'
                  : 'hover:bg-slate-100 text-slate-700'
              )}
            >
              <Target className="h-4 w-4" />
              <span className="font-medium">やりたいこと</span>
            </button>
            <div className="h-px bg-slate-200 my-1" />
            {pagesQ.isLoading && (
              <div className="p-3 text-sm text-slate-500 flex items-center gap-2">
                <Loader2 className="h-3 w-3 animate-spin" /> 読込中...
              </div>
            )}
            {pagesQ.error && (
              <div className="p-3 text-xs text-red-600 space-y-2">
                <div className="font-semibold">APIエラー</div>
                <div className="text-[10px] text-red-500 break-words">
                  {(pagesQ.error as any)?.message || String(pagesQ.error)}
                </div>
                {((pagesQ.error as any)?.status === 401 ||
                  (pagesQ.error as any)?.status === 403) && (
                  <div className="text-[10px] text-slate-600 border-t border-red-200 pt-2">
                    認証切れの可能性があります。メインタブ (http://localhost:3000/chat) を再読み込みして再ログインし、このタブもリロードしてください。
                  </div>
                )}
                <button
                  onClick={() => pagesQ.refetch()}
                  className="text-[10px] px-2 py-1 rounded bg-red-100 hover:bg-red-200 text-red-700"
                >
                  再試行
                </button>
              </div>
            )}
            {pagesQ.data?.map((p) => (
              <button
                key={p.id}
                onClick={() => { setSelectedPageId(p.id); setShowTasksView(false); }}
                className={cn(
                  'w-full flex items-center gap-2 px-3 py-2 rounded-md text-sm text-left transition-colors',
                  selectedPageId === p.id
                    ? 'bg-white border border-slate-200 shadow-sm text-slate-900'
                    : 'hover:bg-slate-100 text-slate-700'
                )}
              >
                <span>{p.icon || '📄'}</span>
                <span className="truncate flex-1">
                  {displayTitle(p) || '無題'}
                </span>
                <Badge variant="secondary" className="text-[10px] h-4 bg-slate-200 text-slate-600">
                  v{p.version}
                </Badge>
              </button>
            ))}
            {pagesQ.data?.length === 0 && (
              <div className="p-3 text-sm text-slate-500">
                ページがありません。上から作成してください。
              </div>
            )}
          </div>
        </div>
      </aside>

      {/* ========== 中央: ブロックエディタ ========== */}
      <main className="flex-1 flex flex-col min-w-0 bg-white overflow-hidden">
        {/* ツールバー (通知ベルのみ) */}
        <div className="border-b border-slate-200 px-3 py-2 flex items-center gap-2 relative shrink-0">
          <div className="flex-1" />

          {/* 通知ベル */}
          <div className="relative">
            <button
              onClick={() => setNotifOpen((o) => !o)}
              className="relative p-2 rounded-md hover:bg-slate-100 text-slate-600"
              aria-label="通知"
            >
              <Bell className="h-4 w-4" />
              {unreadCount > 0 && (
                <span className="absolute -top-0.5 -right-0.5 h-4 min-w-4 px-1 rounded-full bg-red-500 text-white text-[10px] font-bold flex items-center justify-center">
                  {unreadCount}
                </span>
              )}
            </button>

            {notifOpen && (
              <>
                <div
                  className="fixed inset-0 z-40"
                  onClick={() => setNotifOpen(false)}
                />
                <div className="absolute right-0 top-full mt-2 w-96 max-h-[70vh] overflow-y-auto bg-white border border-slate-200 rounded-lg shadow-xl z-50">
                  <div className="p-3 border-b border-slate-200 flex items-center justify-between">
                    <h3 className="font-semibold text-sm text-slate-900">通知</h3>
                    <span className="text-[10px] text-slate-500">
                      未読 {unreadCount} / 全 {notifQ.data?.length || 0}
                    </span>
                  </div>
                  <div className="p-2 space-y-2">
                    {notifQ.data?.length === 0 && (
                      <p className="text-xs text-slate-500 p-3">通知なし</p>
                    )}
                    {notifQ.data?.map((n) => (
                      <div
                        key={n.id}
                        className={cn(
                          'p-3 rounded-md border',
                          !n.read_at ? 'border-indigo-300 bg-indigo-50' : 'border-slate-200 bg-white',
                          n.severity === 'urgent' && 'border-red-400 bg-red-50'
                        )}
                      >
                        <div className="flex items-start gap-2">
                          {n.severity === 'urgent' && (
                            <AlertCircle className="h-4 w-4 text-red-600 shrink-0 mt-0.5" />
                          )}
                          <div className="min-w-0 flex-1">
                            <p className="text-xs font-medium text-slate-900">{n.title}</p>
                            {n.body && (
                              <p className="text-[11px] text-slate-600 mt-1">{n.body}</p>
                            )}
                            {n.due_at && (
                              <p className="text-[10px] text-slate-500 mt-1">
                                期限: {new Date(n.due_at).toLocaleString('ja-JP')}
                              </p>
                            )}
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </>
            )}
          </div>
        </div>

        {showTasksView ? (
          <TasksView />
        ) : !selectedPage ? (
          <div className="flex-1 flex flex-col items-center justify-center text-slate-400 gap-2">
            <Notebook className="h-12 w-12 opacity-30" />
            <p className="text-sm">左からページを選択するか、新規作成してください</p>
          </div>
        ) : (
          <>
            <div className="border-b border-slate-200 p-6 flex items-start justify-between shrink-0">
              <div className="flex items-start gap-3">
                <span className="text-3xl">{selectedPage.icon || '📄'}</span>
                <div>
                  {selectedPage.parent_id && (
                    <button
                      onClick={() => setSelectedPageId(selectedPage.parent_id)}
                      className="text-xs text-indigo-600 hover:underline flex items-center gap-1 mb-1"
                    >
                      <ChevronRight className="h-3 w-3 rotate-180" />
                      親ページへ戻る
                    </button>
                  )}
                  <h1 className="text-2xl font-bold text-slate-900">
                    {displayTitle(selectedPage) || '無題'}
                  </h1>
                  <p className="text-xs text-slate-500 mt-1">
                    v{selectedPage.version} ・ 更新:{' '}
                    {new Date(selectedPage.updated_at).toLocaleString('ja-JP')} ・ 配下 {blocksQ.data?.length || 0} 件
                  </p>
                </div>
              </div>
              <div className="flex items-center gap-2">
                {/* ビュー切替: フォルダのみ表示 */}
                {selectedPage.properties?.is_folder && (
                  <div className="inline-flex rounded-md border border-slate-200 overflow-hidden mr-2">
                    <button
                      onClick={() => togglePageViewMode.mutate('list')}
                      className={cn(
                        'px-2 py-1 text-[11px] flex items-center gap-1 transition',
                        viewMode === 'list'
                          ? 'bg-indigo-600 text-white'
                          : 'bg-white text-slate-600 hover:bg-slate-50'
                      )}
                      title="リスト表示"
                    >
                      <ListIcon className="h-3 w-3" />
                      リスト
                    </button>
                    <button
                      onClick={() => togglePageViewMode.mutate('grid')}
                      className={cn(
                        'px-2 py-1 text-[11px] flex items-center gap-1 border-l border-slate-200 transition',
                        viewMode === 'grid'
                          ? 'bg-indigo-600 text-white'
                          : 'bg-white text-slate-600 hover:bg-slate-50'
                      )}
                      title="サムネイル表示"
                    >
                      <LayoutGrid className="h-3 w-3" />
                      サムネ
                    </button>
                  </div>
                )}
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    if (confirm('このページを削除しますか？')) {
                      deletePage.mutate(selectedPage.id);
                    }
                  }}
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
            </div>

            {/* 本文 - 直接 overflow-y-auto でスクロール確実化 */}
            <div className="flex-1 min-h-0 overflow-y-auto">
              <div className="max-w-6xl mx-auto p-6">
                {blocksQ.isLoading && (
                  <Loader2 className="h-5 w-5 animate-spin text-slate-400" />
                )}
                {blocksQ.data?.length === 0 && (
                  <p className="text-sm text-slate-500 mb-3">
                    左側 + ボタンから最初のブロックを追加してください
                  </p>
                )}

                {/* 混在レンダリング: テキスト/タスク/見出しは常にインライン、
                    メディア(image/video/pdf/file/page)は viewMode に従う */}
                <BlockList
                  blocks={blocksQ.data || []}
                  viewMode={viewMode}
                  onUpdate={(id, content) => updateBlock.mutate({ id, content })}
                  onDelete={(b) => {
                    if (b.type === 'page') {
                      if (!confirm(`ページ「${displayTitle(b) || '無題'}」を削除しますか？\n配下のブロックも一緒に非表示になります（元に戻せます）。`)) return;
                    }
                    removeBlock.mutate(b.id);
                  }}
                  onOpenPage={(id) => setSelectedPageId(id)}
                  onInsertAfter={(afterId, type) => {
                    insertBlock.mutate({ after_block_id: afterId, type });
                  }}
                  parentPageId={selectedPage.id}
                  onCreateFirst={(type) => insertBlock.mutate({ after_block_id: null, type })}
                />
              </div>
            </div>

            {/* バージョン履歴 */}
            {versionsQ.data && versionsQ.data.length > 0 && (
              <div className="border-t border-slate-200 p-3 flex items-center gap-2 text-xs text-slate-500 shrink-0">
                <History className="h-3 w-3" />
                {versionsQ.data.length} 件の編集履歴 (自動世代管理)
              </div>
            )}
          </>
        )}
      </main>

      {/* ========== 右: Autopilot ========== */}
      <aside className="w-80 border-l border-slate-200 flex flex-col bg-slate-50">
        <div className="p-3 border-b border-slate-200 flex items-center gap-2">
          <Activity className="h-4 w-4 text-indigo-600" />
          <h3 className="font-semibold text-sm text-slate-900">Autopilot</h3>
        </div>
        <div className="flex-1 min-h-0 overflow-y-auto px-3 pb-3 pt-3">
          <div className="space-y-3">
            <div>
              <h4 className="text-[10px] font-semibold text-slate-500 uppercase mb-2">
                トリガー ({triggersQ.data?.length || 0})
              </h4>
              {triggersQ.data?.length === 0 && (
                <p className="text-xs text-slate-500">トリガー未設定</p>
              )}
              {triggersQ.data?.map((t) => (
                <Card key={t.id} className="p-2 mb-2 bg-white border-slate-200">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2 min-w-0">
                      <Sparkles className="h-3 w-3 text-indigo-600 shrink-0" />
                      <span className="text-xs truncate text-slate-900">{t.name}</span>
                    </div>
                    <Badge
                      className={cn(
                        'text-[10px] h-4',
                        t.is_enabled
                          ? 'bg-indigo-100 text-indigo-700'
                          : 'bg-slate-200 text-slate-600'
                      )}
                    >
                      {t.kind}
                    </Badge>
                  </div>
                  <p className="text-[10px] text-slate-500 mt-1">
                    実行: {t.fire_count}回
                  </p>
                </Card>
              ))}
            </div>

            <div>
              <h4 className="text-[10px] font-semibold text-slate-500 uppercase mb-2">
                最近の実行
              </h4>
              {runsQ.data?.length === 0 && (
                <p className="text-xs text-slate-500">実行履歴なし</p>
              )}
              {runsQ.data?.slice(0, 5).map((r) => (
                <Card key={r.id} className="p-2 mb-2 bg-white border-slate-200">
                  <div className="flex items-center justify-between">
                    <Badge
                      className={cn(
                        'text-[10px] h-4',
                        r.status === 'succeeded' && 'bg-emerald-100 text-emerald-700',
                        r.status === 'failed' && 'bg-red-100 text-red-700',
                        r.status === 'running' && 'bg-amber-100 text-amber-700'
                      )}
                    >
                      {r.status}
                    </Badge>
                    <span className="text-[10px] text-slate-500">
                      {new Date(r.started_at).toLocaleTimeString('ja-JP')}
                    </span>
                  </div>
                </Card>
              ))}
            </div>
          </div>
        </div>
      </aside>
      </div>

      {/* ========== 下: チャットドック ========== */}
      <ChatDock
        open={chatOpen}
        onToggle={() => setChatOpen((o) => !o)}
        history={chatHistory}
        input={chatInput}
        onInputChange={setChatInput}
        onSend={sendChat}
        sending={chatSending}
        runId={activeRunId}
        scrollToRunId={scrollToRunId}
        onDidScroll={() => setScrollToRunId(null)}
        onSelectMessage={(runId) => {
          setActiveRunId(runId);
          setGanttExpanded(true);
        }}
      />
    </div>
  );
}

/* ========================================================== */
/*  上部ガントタイムライン                                    */
/* ========================================================== */
function GanttTimeline({
  traces,
  runId,
  runs,
  onSelectRun,
  expanded,
  onToggle,
  running,
}: {
  traces: Trace[];
  runId: string | null;
  runs: RunSummary[];
  onSelectRun: (id: string) => void;
  expanded: boolean;
  onToggle: () => void;
  running: boolean;
}) {
  // エージェント行 (agent_name -> row index)
  const rows = useMemo(() => {
    const seen = new Map<string, number>();
    traces.forEach((t) => {
      if (!seen.has(t.agent_name)) seen.set(t.agent_name, seen.size);
    });
    return seen;
  }, [traces]);

  // 時間範囲
  const startMs = useMemo(() => {
    if (traces.length === 0) return Date.now();
    return new Date(traces[0].created_at).getTime();
  }, [traces]);

  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (!running) return;
    const id = setInterval(() => setNow(Date.now()), 250);
    return () => clearInterval(id);
  }, [running]);

  const endMs = useMemo(() => {
    if (!running && traces.length > 0) {
      const last = traces[traces.length - 1];
      return new Date(last.created_at).getTime() + 1000;
    }
    return Math.max(now, startMs + 5000);
  }, [now, running, traces, startMs]);

  const autoTotalMs = Math.max(endMs - startMs, 1000);

  // ===== zoom + pan =====
  // viewStart/viewEnd が null なら自動フィット、値ありならその範囲
  const [viewStart, setViewStart] = useState<number | null>(null);
  const [viewEnd, setViewEnd] = useState<number | null>(null);
  const isZoomed = viewStart !== null && viewEnd !== null;

  // run/traces が変わったら zoom リセット
  useEffect(() => {
    setViewStart(null);
    setViewEnd(null);
  }, [runId]);

  const effectiveStart = isZoomed ? (viewStart as number) : startMs;
  const effectiveEnd = isZoomed ? (viewEnd as number) : endMs;
  const totalMs = Math.max(effectiveEnd - effectiveStart, 100);

  const barAreaRef = useRef<HTMLDivElement | null>(null);

  // ズーム関連の state を ref に逃がして native listener から参照
  const zoomStateRef = useRef({ effectiveStart, totalMs, autoTotalMs, isZoomed });
  zoomStateRef.current = { effectiveStart, totalMs, autoTotalMs, isZoomed };

  // wheel ハンドラを ref に保持 (再定義されても listener は同じ参照を使う)
  const wheelHandlerRef = useRef<((e: WheelEvent) => void) | null>(null);
  if (!wheelHandlerRef.current) {
    wheelHandlerRef.current = (e: WheelEvent) => {
      const area = barAreaRef.current;
      if (!area) return;
      const { effectiveStart: es, totalMs: tm, autoTotalMs: auto } = zoomStateRef.current;
      e.preventDefault();
      e.stopPropagation();
      const rect = area.getBoundingClientRect();
      const cursorX = Math.max(0, Math.min(rect.width, e.clientX - rect.left));
      const cursorPct = rect.width > 0 ? cursorX / rect.width : 0;
      const cursorMs = es + cursorPct * tm;

      const zoomFactor = e.deltaY < 0 ? 0.82 : 1.22;
      const minTotal = 200;
      const maxTotal = auto * 1.2;
      let newTotal = tm * zoomFactor;
      newTotal = Math.max(minTotal, Math.min(maxTotal, newTotal));

      const newStart = cursorMs - cursorPct * newTotal;
      const newEnd = newStart + newTotal;

      if (newTotal >= auto) {
        setViewStart(null);
        setViewEnd(null);
      } else {
        setViewStart(newStart);
        setViewEnd(newEnd);
      }
    };
  }

  // コールバック ref: 要素がマウントされた瞬間に {passive:false} で listener を付ける
  const setBarAreaRef = useCallback((el: HTMLDivElement | null) => {
    if (barAreaRef.current && wheelHandlerRef.current) {
      barAreaRef.current.removeEventListener('wheel', wheelHandlerRef.current);
    }
    barAreaRef.current = el;
    if (el && wheelHandlerRef.current) {
      el.addEventListener('wheel', wheelHandlerRef.current, { passive: false });
    }
  }, []);

  const dragRef = useRef<{ startX: number; startVS: number; startVE: number } | null>(null);
  const [isDragging, setIsDragging] = useState(false);

  // ドラッグ中の global state 参照用
  const dragBoundsRef = useRef({ globalStart: 0, globalEnd: 0 });
  dragBoundsRef.current = {
    globalStart: startMs - autoTotalMs * 0.1,
    globalEnd: endMs + autoTotalMs * 0.1,
  };

  const handleMouseDown = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!zoomStateRef.current.isZoomed || e.button !== 0) return;
    const vs = zoomStateRef.current.effectiveStart;
    const ve = vs + zoomStateRef.current.totalMs;
    e.preventDefault();
    dragRef.current = {
      startX: e.clientX,
      startVS: vs,
      startVE: ve,
    };
    setIsDragging(true);
  };

  // ドラッグ中 global listener (deps を isDragging のみに絞る)
  useEffect(() => {
    if (!isDragging) return;
    const onMove = (e: MouseEvent) => {
      const d = dragRef.current;
      const area = barAreaRef.current;
      if (!d || !area) return;
      const rect = area.getBoundingClientRect();
      const dx = e.clientX - d.startX;
      const range = d.startVE - d.startVS;
      const shift = -(dx / rect.width) * range;
      const { globalStart, globalEnd } = dragBoundsRef.current;
      let ns = d.startVS + shift;
      let ne = d.startVE + shift;
      if (ns < globalStart) {
        ns = globalStart;
        ne = ns + range;
      }
      if (ne > globalEnd) {
        ne = globalEnd;
        ns = ne - range;
      }
      setViewStart(ns);
      setViewEnd(ne);
    };
    const onUp = () => {
      dragRef.current = null;
      setIsDragging(false);
    };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    return () => {
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
  }, [isDragging]);

  const resetZoom = () => {
    setViewStart(null);
    setViewEnd(null);
  };

  const colorFor = (et: Trace['event_type']) => {
    switch (et) {
      case 'thinking': return 'bg-indigo-400';
      case 'tool_call': return 'bg-blue-500';
      case 'tool_result': return 'bg-emerald-400';
      case 'message': return 'bg-slate-400';
      case 'decision': return 'bg-violet-400';
      case 'self_repair': return 'bg-amber-400';
      case 'error': return 'bg-red-500';
      case 'complete': return 'bg-emerald-600';
      default: return 'bg-slate-300';
    }
  };

  const iconFor = (et: Trace['event_type']) => {
    switch (et) {
      case 'thinking': return <Brain className="h-3 w-3" />;
      case 'tool_call': return <Wrench className="h-3 w-3" />;
      case 'tool_result': return <CheckCircle2 className="h-3 w-3" />;
      case 'error': return <XCircle className="h-3 w-3" />;
      case 'self_repair': return <RotateCcw className="h-3 w-3" />;
      default: return null;
    }
  };

  const [hoveredTrace, setHoveredTrace] = useState<Trace | null>(null);

  const rowHeight = 28;
  const headerHeight = 36;
  const ganttHeight = expanded ? Math.max(180, headerHeight + rows.size * rowHeight + 20) : 56;

  return (
    <div
      className="border-b border-slate-200 bg-slate-50 transition-all duration-200 overflow-hidden"
      style={{ height: ganttHeight }}
    >
      {/* ヘッダー */}
      <div className="flex items-center gap-3 px-4 py-2 border-b border-slate-200 bg-white">
        <button
          onClick={onToggle}
          className="flex items-center gap-1 text-sm font-medium text-slate-700 hover:text-slate-900"
        >
          {expanded ? <ChevronDown className="h-4 w-4" /> : <ChevronUp className="h-4 w-4" />}
          <Activity className="h-4 w-4 text-indigo-600" />
          <span>エージェント活動</span>
        </button>

        {running && (
          <span className="flex items-center gap-1 text-xs text-amber-700">
            <span className="h-1.5 w-1.5 rounded-full bg-amber-500 animate-pulse" />
            実行中...
          </span>
        )}

        {!running && runId && (
          <span className="text-xs text-emerald-700 flex items-center gap-1">
            <CheckCircle2 className="h-3 w-3" />完了
          </span>
        )}

        <div className="flex-1" />

        <span className="text-xs text-slate-500">
          {traces.length} イベント
        </span>

        {isZoomed && (
          <button
            onClick={resetZoom}
            className="text-[10px] px-2 py-0.5 rounded bg-indigo-50 hover:bg-indigo-100 text-indigo-700 border border-indigo-200"
            title="ズーム解除 (全体表示)"
          >
            🔍 全体
          </button>
        )}

        {runs.length > 0 && (
          <select
            value={runId || ''}
            onChange={(e) => e.target.value && onSelectRun(e.target.value)}
            className="text-xs border border-slate-200 rounded px-2 py-1 bg-white"
          >
            <option value="">直近の実行を選択...</option>
            {runs.map((r) => (
              <option key={r.id} value={r.id}>
                {new Date(r.started_at).toLocaleTimeString('ja-JP')} ・ {r.status}
              </option>
            ))}
          </select>
        )}
      </div>

      {/* タイムライン本体 */}
      {expanded && (
        <div className="relative h-full overflow-y-auto" style={{ paddingTop: 4 }}>
          {traces.length === 0 ? (
            <div className="px-4 py-6 text-xs text-slate-500">
              {runId ? '待機中...' : '下のチャットからダンに話しかけると、ここに思考プロセスが時系列で表示されます'}
            </div>
          ) : (
            <div className="relative px-2" style={{ height: rows.size * rowHeight + 8 }}>
              {/* 各エージェント行のラベル領域 (左 150px) */}
              {[...rows.entries()].map(([agentName, rowIdx]) => (
                <div
                  key={agentName}
                  className="absolute flex items-center"
                  style={{ top: rowIdx * rowHeight + 4, height: rowHeight, left: 0, width: 150 }}
                >
                  <span className="text-[10px] text-slate-500 px-2 truncate">
                    {agentName.replace('autopilot:', '').replace('__manual_chat__', 'チャット')}
                  </span>
                </div>
              ))}

              {/* バー描画領域: 150px offset + right 2px padding、この中で 0-100% 計算 */}
              {/* wheel で zoom (callback ref で native listener)、drag で pan */}
              <div
                ref={setBarAreaRef}
                onMouseDown={handleMouseDown}
                className={cn(
                  'absolute top-0 bottom-0 overflow-hidden',
                  isZoomed && (isDragging ? 'cursor-grabbing' : 'cursor-grab'),
                  !isZoomed && 'cursor-default'
                )}
                style={{ left: 150, right: 8 }}
              >
                {/* 時刻グリッド (5本) */}
                {[0, 1, 2, 3, 4].map((i) => (
                  <div
                    key={i}
                    className="absolute top-0 bottom-0 border-l border-slate-200"
                    style={{ left: `${(i / 4) * 100}%` }}
                  />
                ))}

                {/* イベントバー (effectiveStart/totalMs ベース、zoom対応) */}
                {traces.map((t, i) => {
                  const ts = new Date(t.created_at).getTime();
                  const startPct = ((ts - effectiveStart) / totalMs) * 100;
                  const nextSameAgent = traces.slice(i + 1).find((x) => x.agent_name === t.agent_name);
                  const endTs = nextSameAgent ? new Date(nextSameAgent.created_at).getTime() : ts + 800;
                  const endPct = ((endTs - effectiveStart) / totalMs) * 100;
                  const rowIdx = rows.get(t.agent_name) || 0;
                  // 完全に画面外のバーはスキップ
                  if (endPct < -5 || startPct > 105) return null;
                  // クリップ (ただし overflow-hidden があるのでオーバーでも切られる)
                  const clampedStart = Math.max(startPct, -5);
                  const clampedEnd = Math.min(endPct, 105);
                  const clampedWidth = Math.max(clampedEnd - clampedStart, 0.3);
                  return (
                    <div
                      key={t.id}
                      onMouseEnter={() => setHoveredTrace(t)}
                      onMouseLeave={() => setHoveredTrace((h) => (h?.id === t.id ? null : h))}
                      className={cn(
                        'absolute rounded-sm cursor-pointer border border-white/40 hover:scale-y-110 transition-transform',
                        colorFor(t.event_type)
                      )}
                      style={{
                        left: `${clampedStart}%`,
                        width: `calc(max(${clampedWidth}%, 6px))`,
                        top: rowIdx * rowHeight + 8,
                        height: rowHeight - 12,
                      }}
                      title={`${t.event_type}: ${JSON.stringify(t.content).slice(0, 200)}`}
                    >
                      <span className="absolute inset-0 flex items-center justify-start pl-1 text-white">
                        {iconFor(t.event_type)}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* 凡例 */}
          <div className="px-4 py-2 flex items-center gap-3 text-[10px] text-slate-600 border-t border-slate-200">
            <span className="flex items-center gap-1"><span className="w-3 h-2 bg-indigo-400 rounded-sm" />思考</span>
            <span className="flex items-center gap-1"><span className="w-3 h-2 bg-blue-500 rounded-sm" />ツール呼び出し</span>
            <span className="flex items-center gap-1"><span className="w-3 h-2 bg-emerald-400 rounded-sm" />結果</span>
            <span className="flex items-center gap-1"><span className="w-3 h-2 bg-amber-400 rounded-sm" />自己修復</span>
            <span className="flex items-center gap-1"><span className="w-3 h-2 bg-red-500 rounded-sm" />エラー</span>
            {hoveredTrace && (
              <span className="ml-auto text-slate-700 truncate max-w-[60%]">
                {hoveredTrace.event_type}: {JSON.stringify(hoveredTrace.content).slice(0, 120)}
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

/* ========================================================== */
/*  下部チャットドック                                        */
/* ========================================================== */
/**
 * Notion AI ライクの右下フローティングチャット。
 * 閉じている時: 円形 FAB (右下固定)
 * 開いている時: 384x520 のパネル (右下から上に展開)
 */
function ChatDock({
  open,
  onToggle,
  history,
  input,
  onInputChange,
  onSend,
  sending,
  runId,
  scrollToRunId,
  onDidScroll,
  onSelectMessage,
}: {
  open: boolean;
  onToggle: () => void;
  history: ChatMessage[];
  input: string;
  onInputChange: (v: string) => void;
  onSend: () => void;
  sending: boolean;
  runId: string | null;
  scrollToRunId?: string | null;
  onDidScroll?: () => void;
  onSelectMessage?: (runId: string) => void;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const msgRefs = useRef<Record<string, HTMLDivElement | null>>({});

  // callback を ref に逃がして effect の deps から外す (不要な再実行防止)
  const onDidScrollRef = useRef(onDidScroll);
  onDidScrollRef.current = onDidScroll;
  const onSendRef = useRef(onSend);
  onSendRef.current = onSend;

  // 最新の scrollToRunId を ref で参照 (末尾スクロール抑制用)
  const scrollToRunIdRef = useRef(scrollToRunId);
  scrollToRunIdRef.current = scrollToRunId;

  // 末尾スクロール (history.length 増加時のみ)
  // scrollToRunId を deps から除外: 完了後の null 化でスクロールを上書きしないため
  const prevLenRef = useRef(0);
  useEffect(() => {
    if (!scrollRef.current) return;
    const prev = prevLenRef.current;
    prevLenRef.current = history.length;
    // history が実際に増えた時のみ末尾へ、ただしターゲット指定中はスキップ
    if (history.length > prev && !scrollToRunIdRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [history.length]);

  // open が閉→開に変わった時、ターゲット指定が無ければ末尾へ
  const prevOpenRef = useRef(open);
  useEffect(() => {
    const wasOpen = prevOpenRef.current;
    prevOpenRef.current = open;
    if (!wasOpen && open && !scrollToRunIdRef.current) {
      requestAnimationFrame(() => {
        if (scrollRef.current && !scrollToRunIdRef.current) {
          scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
        }
      });
    }
  }, [open]);

  // ガントから指定された run の位置へスクロール
  // onDidScroll を deps から除外して毎レンダの再実行を防ぐ
  useEffect(() => {
    if (!scrollToRunId || !open) return;
    let cancelled = false;
    let retries = 0;
    const doScroll = () => {
      if (cancelled) return;
      const el = msgRefs.current[scrollToRunId];
      const container = scrollRef.current;
      if (el && container && container.clientHeight > 0) {
        const elRect = el.getBoundingClientRect();
        const containerRect = container.getBoundingClientRect();
        const relativeTop = elRect.top - containerRect.top + container.scrollTop;
        const targetScroll = relativeTop - container.clientHeight / 2 + elRect.height / 2;
        container.scrollTo({ top: Math.max(0, targetScroll), behavior: 'smooth' });
        el.classList.add('ring-2', 'ring-indigo-400', 'ring-offset-2');
        setTimeout(() => el.classList.remove('ring-2', 'ring-indigo-400', 'ring-offset-2'), 1800);
        onDidScrollRef.current?.();
      } else if (retries < 20) {
        retries++;
        setTimeout(doScroll, 50);
      } else {
        onDidScrollRef.current?.();
      }
    };
    const rafId = requestAnimationFrame(() => setTimeout(doScroll, 80));
    return () => {
      cancelled = true;
      cancelAnimationFrame(rafId);
    };
  }, [scrollToRunId, open]);

  if (!open) {
    return (
      <button
        onClick={onToggle}
        className="fixed bottom-6 right-6 z-50 h-14 w-14 rounded-full bg-indigo-600 hover:bg-indigo-700 text-white shadow-lg shadow-indigo-600/30 flex items-center justify-center transition-all hover:scale-105"
        aria-label="ダンに話しかける"
      >
        <Sparkles className="h-6 w-6" />
        {sending && (
          <span className="absolute -top-1 -right-1 h-3 w-3 rounded-full bg-amber-400 animate-pulse" />
        )}
      </button>
    );
  }

  return (
    <div
      className="fixed bottom-6 right-6 z-50 w-96 h-[520px] bg-white border border-slate-200 rounded-xl shadow-2xl flex flex-col overflow-hidden"
      style={{ maxHeight: 'calc(100vh - 48px)' }}
    >
      {/* ヘッダー */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-200 bg-gradient-to-r from-indigo-50 to-violet-50">
        <div className="flex items-center gap-2 min-w-0">
          <div className="h-7 w-7 rounded-full bg-indigo-600 flex items-center justify-center shrink-0">
            <Sparkles className="h-4 w-4 text-white" />
          </div>
          <div className="min-w-0">
            <p className="text-sm font-semibold text-slate-900 truncate">ダンに話しかける</p>
            <p className="text-[10px] text-slate-500 truncate">
              {sending ? '実行中…' : runId ? `run: ${runId.slice(0, 8)}` : 'Notion風 AI アシスタント'}
            </p>
          </div>
        </div>
        <button
          onClick={onToggle}
          className="h-7 w-7 rounded-md hover:bg-white/60 text-slate-600 flex items-center justify-center"
          aria-label="閉じる"
        >
          <ChevronDown className="h-4 w-4" />
        </button>
      </div>

      {/* メッセージ履歴 */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
        {history.length === 0 && (
          <div className="text-xs text-slate-500 space-y-2">
            <p className="font-medium text-slate-700">何でも聞いてください:</p>
            <ul className="space-y-1 list-disc pl-4">
              <li>「今日の議事録ページを作って」</li>
              <li>「請求書ブロックを期限順に並べて」</li>
              <li>「税理士宛の下書きを作って」</li>
              <li>「経理ページの未読タスクを一覧化して」</li>
            </ul>
          </div>
        )}
        {history.map((m) => (
          <div
            key={m.id}
            className={cn('flex gap-2', m.role === 'user' ? 'justify-end' : 'justify-start')}
            ref={(el) => {
              if (m.run_id) msgRefs.current[m.run_id] = el;
            }}
          >
            <div
              onClick={() => m.run_id && onSelectMessage?.(m.run_id)}
              className={cn(
                'max-w-[80%] rounded-2xl px-3 py-2 text-sm whitespace-pre-wrap break-words transition-shadow',
                m.run_id && 'cursor-pointer hover:shadow-md',
                m.role === 'user'
                  ? 'bg-indigo-600 text-white rounded-br-sm'
                  : 'bg-slate-100 text-slate-900 border border-slate-200 rounded-bl-sm',
                m.run_id === runId && m.role === 'assistant' && 'ring-1 ring-indigo-300'
              )}
              title={m.run_id ? `クリックで run ${m.run_id.slice(0, 8)} をガントで表示` : undefined}
            >
              {m.text}
            </div>
          </div>
        ))}
        {sending && (
          <div className="flex justify-start">
            <div className="bg-slate-100 border border-slate-200 rounded-2xl rounded-bl-sm px-3 py-2 text-xs text-slate-500 flex items-center gap-2">
              <Loader2 className="h-3 w-3 animate-spin" />
              ダンが考えています...
            </div>
          </div>
        )}
      </div>

      {/* 入力欄 (デスクトップ: Enter 送信/Shift+Enter 改行、モバイル: Enter 改行/ボタンで送信) */}
      <div className="border-t border-slate-200 p-3 flex gap-2 items-end bg-white">
        <textarea
          placeholder={
            typeof window !== 'undefined' && window.matchMedia('(pointer: coarse)').matches
              ? 'メッセージを入力 (送信ボタンで送信)'
              : 'メッセージを入力 (Enter 送信 / Shift+Enter 改行)'
          }
          value={input}
          onChange={(e) => onInputChange(e.target.value)}
          onKeyDown={(e) => {
            // モバイル (touch device) では Enter = 改行のみ、送信はボタンのみ
            const isMobile =
              typeof window !== 'undefined' &&
              (window.matchMedia('(pointer: coarse)').matches || 'ontouchstart' in window);
            if (isMobile) return;
            if (
              e.key === 'Enter' &&
              !e.shiftKey &&
              !e.isComposing &&
              !(e.nativeEvent as any).isComposing
            ) {
              e.preventDefault();
              onSendRef.current?.();
            }
          }}
          disabled={sending}
          rows={Math.min(6, Math.max(1, input.split('\n').length))}
          className="flex-1 resize-none bg-white border border-slate-200 rounded-md px-3 py-2 text-sm outline-none focus:border-indigo-400 focus:ring-1 focus:ring-indigo-200 min-h-[36px] max-h-[144px]"
          autoFocus
        />
        <Button
          onClick={onSend}
          disabled={sending || !input.trim()}
          className="bg-indigo-600 hover:bg-indigo-700 text-white shrink-0"
        >
          <Send className="h-4 w-4" />
        </Button>
      </div>
    </div>
  );
}

/* ========================================================== */
/*  BlockList: 混在レンダリング + inline + ボタン            */
/* ========================================================== */
const MEDIA_TYPES = new Set(['image', 'video', 'pdf', 'file', 'audio', 'page']);

function BlockList({
  blocks,
  viewMode,
  onUpdate,
  onDelete,
  onOpenPage,
  onInsertAfter,
  onCreateFirst,
  parentPageId,
}: {
  blocks: Block[];
  viewMode: 'list' | 'grid';
  onUpdate: (id: string, content: any) => void;
  onDelete: (block: Block) => void;
  onOpenPage: (id: string) => void;
  onInsertAfter: (afterId: string, type: string) => void;
  onCreateFirst: (type: string) => void;
  parentPageId: string;
}) {
  // サムネホバー時のツールチップ表示用 (Rules of Hooks: 早期returnより前で宣言)
  const [hoveredTitle, setHoveredTitle] = useState<string | null>(null);

  // ブロックを「リストとして縦積み」と「メディアをグリッドでまとめる」に分離
  // grid mode: メディアブロックを連続するグループごとにまとめてグリッド描画
  // list mode: 全部そのまま縦積み
  if (viewMode === 'list') {
    return (
      <div className="max-w-3xl mx-auto space-y-0.5">
        {blocks.length === 0 && (
          <InlineInsertMenu onInsert={onCreateFirst} label="最初のブロックを追加" />
        )}
        {blocks.map((b) => (
          <div key={b.id} className="group/row relative flex items-start gap-1 py-0.5">
            {/* 左側ホバーで inline + ボタン */}
            <div className="absolute -left-8 top-1 opacity-0 group-hover/row:opacity-100 transition">
              <InlineInsertMenu
                onInsert={(type) => onInsertAfter(b.id, type)}
                size="sm"
              />
            </div>
            <div className="flex-1 min-w-0">
              <BlockRow
                block={b}
                onUpdate={(c) => onUpdate(b.id, c)}
                onDelete={() => onDelete(b)}
                onOpenPage={onOpenPage}
                onInsertAfter={(type) => onInsertAfter(b.id, type)}
              />
            </div>
          </div>
        ))}
        {/* 末尾への追加 */}
        {blocks.length > 0 && (
          <div className="pt-3 pl-1">
            <InlineInsertMenu
              onInsert={(type) => onInsertAfter(blocks[blocks.length - 1].id, type)}
              label="ブロックを追加"
            />
          </div>
        )}
      </div>
    );
  }

  // grid mode: 連続するメディアブロックをまとめてグリッド化、テキスト系は間に挟む
  const segments: Array<
    { kind: 'text'; block: Block } | { kind: 'grid'; items: Block[] }
  > = [];
  for (const b of blocks) {
    if (MEDIA_TYPES.has(b.type)) {
      const last = segments[segments.length - 1];
      if (last && last.kind === 'grid') last.items.push(b);
      else segments.push({ kind: 'grid', items: [b] });
    } else {
      segments.push({ kind: 'text', block: b });
    }
  }

  return (
    <div className="space-y-3">
      {blocks.length === 0 && (
        <div className="max-w-3xl mx-auto">
          <InlineInsertMenu onInsert={onCreateFirst} label="最初のブロックを追加" />
        </div>
      )}
      {segments.map((seg, i) => {
        if (seg.kind === 'text') {
          return (
            <div key={`text-${seg.block.id}`} className="max-w-3xl mx-auto">
              <div className="group/row relative flex items-start gap-1 py-0.5">
                <div className="absolute -left-8 top-1 opacity-0 group-hover/row:opacity-100 transition">
                  <InlineInsertMenu
                    onInsert={(type) => onInsertAfter(seg.block.id, type)}
                    size="sm"
                  />
                </div>
                <div className="flex-1 min-w-0">
                  <BlockRow
                    block={seg.block}
                    onUpdate={(c) => onUpdate(seg.block.id, c)}
                    onDelete={() => onDelete(seg.block)}
                    onOpenPage={onOpenPage}
                    onInsertAfter={(type) => onInsertAfter(seg.block.id, type)}
                  />
                </div>
              </div>
            </div>
          );
        }
        return (
          <div key={`grid-${i}`} className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-4">
            {seg.items.map((b) => (
              <ThumbnailCard
                key={b.id}
                block={b}
                onOpenPage={onOpenPage}
                onDelete={() => onDelete(b)}
                onInsertAfter={(type) => onInsertAfter(b.id, type)}
                onHover={setHoveredTitle}
              />
            ))}
          </div>
        );
      })}
      {/* 末尾への追加 */}
      {blocks.length > 0 && (
        <div className="max-w-3xl mx-auto pt-3 pl-1">
          <InlineInsertMenu
            onInsert={(type) => onInsertAfter(blocks[blocks.length - 1].id, type)}
            label="ブロックを追加"
          />
        </div>
      )}
      {hoveredTitle && (
        <div className="fixed bottom-4 left-1/2 -translate-x-1/2 z-50 px-4 py-2 rounded-lg bg-slate-900 text-white text-sm shadow-lg max-w-md text-center break-words animate-in fade-in duration-150">
          {hoveredTitle}
        </div>
      )}
    </div>
  );
}

/**
 * Inline + ボタン + ブロック型選択メニュー
 */
function InlineInsertMenu({
  onInsert,
  label = '',
  size = 'md',
}: {
  onInsert: (type: string) => void;
  label?: string;
  size?: 'sm' | 'md';
}) {
  const [open, setOpen] = useState(false);
  const types = [
    { type: 'paragraph', icon: '📝', label: 'テキスト' },
    { type: 'heading', icon: '📌', label: '見出し' },
    { type: 'checklist', icon: '☑️', label: 'タスク' },
    { type: 'page', icon: '📁', label: 'フォルダ (メディア整理用)' },
    { type: 'bullet_list', icon: '•', label: '箇条書き' },
    { type: 'quote', icon: '❝', label: '引用' },
    { type: 'divider', icon: '—', label: '区切り線' },
  ];

  return (
    <div className="relative inline-block">
      <button
        onClick={() => setOpen((o) => !o)}
        className={cn(
          'flex items-center gap-1 rounded-md text-slate-400 hover:text-indigo-600 hover:bg-slate-100 transition',
          size === 'sm' ? 'h-5 w-5 text-xs' : 'h-6 px-2 text-xs'
        )}
        title="ブロックを挿入"
      >
        <Plus className={size === 'sm' ? 'h-3 w-3' : 'h-4 w-4'} />
        {label && <span>{label}</span>}
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div className="absolute left-0 top-full mt-1 z-50 w-52 bg-white border border-slate-200 rounded-lg shadow-xl py-1">
            {types.map((t) => (
              <button
                key={t.type}
                onClick={() => {
                  onInsert(t.type);
                  setOpen(false);
                }}
                className="w-full flex items-center gap-2 px-3 py-2 text-sm text-slate-700 hover:bg-indigo-50 hover:text-indigo-700 text-left"
              >
                <span className="text-base">{t.icon}</span>
                <span>{t.label}</span>
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

/**
 * サムネイル/カードビュー用
 */
function ThumbnailCard({
  block,
  onOpenPage,
  onDelete,
  onInsertAfter,
  onHover,
}: {
  block: Block;
  onOpenPage: (id: string) => void;
  onDelete: () => void;
  onInsertAfter?: (type: string) => void;
  onHover?: (title: string | null) => void;
}) {
  const title =
    displayTitle(block) ||
    block.properties?.original_name ||
    (Array.isArray(block.content) && block.content[0]?.text) ||
    `${block.type} ${block.id.slice(0, 6)}`;
  const url = block.properties?.url || block.properties?.storage_path;

  const isPage = block.type === 'page';
  const isImage = block.type === 'image';
  const isVideo = block.type === 'video';
  const isPdf = block.type === 'pdf';

  const handleClick = () => {
    if (isPage) onOpenPage(block.id);
    else if (url) window.open(url, '_blank', 'noopener,noreferrer');
  };

  return (
    <div
      className="group relative rounded-lg border border-slate-200 bg-white overflow-hidden hover:shadow-md hover:border-indigo-300 transition cursor-pointer"
      onMouseEnter={() => onHover?.(title)}
      onMouseLeave={() => onHover?.(null)}
    >
      <button
        onClick={handleClick}
        className="w-full text-left"
      >
        {/* プレビューエリア */}
        <div className="aspect-square bg-slate-100 flex items-center justify-center relative overflow-hidden">
          {isImage && url ? (
            <img
              src={url}
              alt={title}
              className="w-full h-full object-cover"
              loading="lazy"
              onError={(e) => {
                (e.target as HTMLImageElement).style.display = 'none';
              }}
            />
          ) : isVideo && url ? (
            <>
              <video
                src={url}
                className="w-full h-full object-cover"
                preload="metadata"
                muted
              />
              <div className="absolute inset-0 flex items-center justify-center bg-black/20">
                <div className="h-10 w-10 rounded-full bg-white/90 flex items-center justify-center">
                  <svg className="h-5 w-5 text-slate-900 ml-0.5" fill="currentColor" viewBox="0 0 24 24">
                    <path d="M8 5v14l11-7z" />
                  </svg>
                </div>
              </div>
            </>
          ) : isPdf && url ? (
            <>
              {/* PDF の 1ページ目プレビュー (browser native) */}
              <iframe
                src={`${url}#toolbar=0&navpanes=0&scrollbar=0&view=FitH`}
                className="w-full h-full pointer-events-none"
                title={title}
              />
              <div className="absolute top-1 right-1 bg-red-500 text-white text-[9px] font-bold px-1.5 py-0.5 rounded shadow">
                PDF
              </div>
            </>
          ) : isPdf ? (
            <div className="flex flex-col items-center gap-1 text-slate-500">
              <span className="text-4xl">📄</span>
              <span className="text-[10px] font-bold">PDF</span>
            </div>
          ) : isPage ? (
            <div className="flex flex-col items-center gap-2 text-slate-600">
              <span className="text-5xl">{block.icon || (block.properties?.is_folder ? '📁' : '📄')}</span>
              {block.properties?.is_folder && (
                <span className="text-[9px] font-bold text-indigo-600 uppercase">フォルダ</span>
              )}
            </div>
          ) : (
            <div className="flex flex-col items-center gap-1 text-slate-500">
              <span className="text-3xl">
                {block.type === 'audio' ? '🎵' : block.type === 'file' ? '📎' : '📝'}
              </span>
              <span className="text-[10px] uppercase">{block.type}</span>
            </div>
          )}
        </div>
        {/* タイトル */}
        <div className="px-3 py-2 border-t border-slate-100">
          <p className="text-xs font-medium text-slate-900 truncate">{title}</p>
          <p className="text-[10px] text-slate-500 mt-0.5">
            {new Date(block.updated_at).toLocaleDateString('ja-JP')}
          </p>
        </div>
      </button>

      {/* 削除ボタン */}
      <button
        onClick={(e) => {
          e.stopPropagation();
          onDelete();
        }}
        className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 p-1.5 bg-white/90 rounded-md text-slate-600 hover:text-red-600 shadow transition"
        title="削除"
      >
        <Trash2 className="h-3 w-3" />
      </button>
    </div>
  );
}


/**
 * 個別ブロック表示・編集
 */
function BlockRow({
  block,
  onUpdate,
  onDelete,
  onOpenPage,
  onInsertAfter,
}: {
  block: Block;
  onUpdate: (content: any) => void;
  onDelete: () => void;
  onOpenPage?: (pageId: string) => void;
  onInsertAfter?: (type: string) => void;
}) {
  const initialText = useMemo(() => {
    if (typeof block.content === 'string') return block.content;
    if (Array.isArray(block.content) && block.content.length > 0) {
      return block.content.map((c) => (typeof c === 'string' ? c : c?.text || '')).join('');
    }
    return '';
  }, [block.content]);

  const [text, setText] = useState(initialText);
  const [checked, setChecked] = useState(!!block.properties?.checked);

  const commit = () => {
    if (text !== initialText) onUpdate([{ type: 'text', text }]);
  };

  // ページ型: クリックで遷移するナビリンクとして表示
  if (block.type === 'page') {
    const title = displayTitle(block) || '無題のページ';
    return (
      <div className="group flex items-center gap-2 rounded-md hover:bg-slate-50 border border-transparent hover:border-slate-200 transition">
        <button
          onClick={() => onOpenPage?.(block.id)}
          className="flex items-center gap-2 flex-1 text-left px-3 py-2 min-w-0"
        >
          <span className="text-lg shrink-0">{block.icon || '📄'}</span>
          <span className="text-sm font-medium text-slate-800 truncate">{title}</span>
          <ChevronRight className="h-4 w-4 text-slate-400 shrink-0" />
        </button>
        <button
          onClick={(e) => {
            e.stopPropagation();
            onDelete();
          }}
          className="opacity-0 group-hover:opacity-100 p-1.5 mr-2 text-slate-400 hover:text-red-600 transition"
          title="ページを削除"
        >
          <Trash2 className="h-3 w-3" />
        </button>
      </div>
    );
  }

  // ファイル系: 読み取り専用プレビュー
  if (['image', 'video', 'pdf', 'file', 'audio'].includes(block.type)) {
    const title =
      displayTitle(block) ||
      block.properties?.original_name ||
      (Array.isArray(block.content) && block.content[0]?.text) ||
      `${block.type} ${block.id.slice(0, 8)}`;
    const url = block.properties?.url || block.properties?.storage_path;
    const icon =
      block.type === 'image' ? '🖼️' :
      block.type === 'video' ? '🎬' :
      block.type === 'pdf' ? '📄' :
      block.type === 'audio' ? '🎵' : '📎';
    return (
      <div className="group flex items-center gap-2 rounded-md border border-slate-200 bg-slate-50 px-3 py-2">
        <span className="text-lg shrink-0">{icon}</span>
        <div className="flex-1 min-w-0">
          {url ? (
            <a href={url} target="_blank" rel="noopener noreferrer" className="text-sm text-indigo-600 hover:underline truncate block">
              {title}
            </a>
          ) : (
            <span className="text-sm text-slate-700 truncate block">{title}</span>
          )}
          <span className="text-[10px] text-slate-500">{block.type}</span>
        </div>
        <button
          onClick={onDelete}
          className="opacity-0 group-hover:opacity-100 p-1 text-slate-400 hover:text-red-600 transition"
        >
          <Trash2 className="h-3 w-3" />
        </button>
      </div>
    );
  }

  if (block.type === 'heading') {
    return (
      <div className="group flex items-center gap-2">
        <input
          type="text"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onBlur={commit}
          placeholder="見出し"
          className="flex-1 text-xl font-bold bg-transparent outline-none border-none"
        />
        <button
          onClick={onDelete}
          className="opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-destructive transition"
        >
          <Trash2 className="h-3 w-3" />
        </button>
      </div>
    );
  }

  if (block.type === 'checklist' || block.type === 'task') {
    return (
      <div className="group flex items-center gap-2">
        <input
          type="checkbox"
          checked={checked}
          onChange={(e) => {
            setChecked(e.target.checked);
            // properties.checked を更新（簡略化のため content と一緒に送らない）
            fetch(`${API}/blocks/${block.id}`, {
              method: 'PATCH',
              headers: {
                'Content-Type': 'application/json',
                Authorization: `Bearer ${typeof window !== 'undefined' ? localStorage.getItem('done-token') : ''}`,
              },
              body: JSON.stringify({ properties: { ...block.properties, checked: e.target.checked } }),
            });
          }}
        />
        <input
          type="text"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onBlur={commit}
          placeholder="タスク"
          className={cn(
            'flex-1 bg-transparent outline-none border-none text-sm',
            checked && 'line-through text-muted-foreground'
          )}
        />
        <button
          onClick={onDelete}
          className="opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-destructive transition"
        >
          <Trash2 className="h-3 w-3" />
        </button>
      </div>
    );
  }

  // paragraph (default)
  return (
    <div className="group flex items-start gap-2">
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        onBlur={commit}
        placeholder="テキストを入力..."
        rows={Math.max(1, text.split('\n').length)}
        className="flex-1 bg-transparent outline-none border-none text-sm resize-none"
      />
      <button
        onClick={onDelete}
        className="opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-destructive transition mt-1"
      >
        <Trash2 className="h-3 w-3" />
      </button>
    </div>
  );
}

export default function DanNotionPage() {
  return <DanNotionInner />;
}
