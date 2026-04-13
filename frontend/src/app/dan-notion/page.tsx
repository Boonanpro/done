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
  ChevronRight, ChevronDown, ChevronUp, History, Sparkles, AlertCircle, Search,
  Send, MessageSquare, Brain, Wrench, CheckCircle2, XCircle, RotateCcw,
} from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { ScrollArea } from '@/components/ui/scroll-area';
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
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json() as Promise<T>;
}

/**
 * SSE で agent_traces を購読する Hook
 * fetch + ReadableStream で Authorization ヘッダ対応
 */
function useTraceStream(runId: string | null): { traces: Trace[]; done: boolean } {
  const [traces, setTraces] = useState<Trace[]>([]);
  const [done, setDone] = useState(false);

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

    (async () => {
      try {
        const res = await fetch(`${API}/runs/${runId}/traces/stream`, {
          headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}) },
          signal: ctrl.signal,
        });
        if (!res.body) return;
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
            } catch {}
          }
        }
        setDone(true);
      } catch (e) {
        if ((e as any)?.name !== 'AbortError') console.warn('SSE error', e);
      }
    })();

    return () => ctrl.abort();
  }, [runId]);

  return { traces, done };
}

function DanNotionInner() {
  const qc = useQueryClient();
  const [selectedPageId, setSelectedPageId] = useState<string | null>(null);
  const [newPageTitle, setNewPageTitle] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<Array<{ block_id: string; similarity: number; summary: string | null }> | null>(null);
  const [notifOpen, setNotifOpen] = useState(false);

  const runSearch = async () => {
    if (!searchQuery.trim()) {
      setSearchResults(null);
      return;
    }
    try {
      const data = await fetchJSON<Array<{ block_id: string; similarity: number; summary: string | null }>>(
        `${API}/search`,
        { method: 'POST', body: JSON.stringify({ query: searchQuery, limit: 20 }) }
      );
      setSearchResults(data);
    } catch (e) {
      setSearchResults([]);
    }
  };

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

  const selectedPage = useMemo(
    () => pagesQ.data?.find((p) => p.id === selectedPageId) || null,
    [pagesQ.data, selectedPageId]
  );

  const unreadCount = notifQ.data?.filter((n) => !n.read_at).length || 0;

  // ===== Active run / Gantt / Chat 状態 =====
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [ganttExpanded, setGanttExpanded] = useState(false);
  const [chatOpen, setChatOpen] = useState(false);
  const [chatHistory, setChatHistory] = useState<ChatMessage[]>([]);
  const [chatInput, setChatInput] = useState('');
  const [chatSending, setChatSending] = useState(false);

  const { traces, done: traceDone } = useTraceStream(activeRunId);

  // 直近の run 一覧 (切替ドロップダウン用)
  const recentRunsQ = useQuery({
    queryKey: ['dan-notion', 'recent-runs'],
    queryFn: () => fetchJSON<RunSummary[]>(`${API}/runs/recent?limit=10`),
    refetchInterval: 10_000,
  });

  // run 完了時に assistant メッセージを履歴に追加
  useEffect(() => {
    if (!traceDone || !activeRunId) return;
    const completeTrace = [...traces].reverse().find((t) => t.event_type === 'complete');
    if (!completeTrace) return;
    setChatHistory((prev) => {
      const exists = prev.some((m) => m.run_id === activeRunId && m.role === 'assistant');
      if (exists) return prev;
      return [
        ...prev,
        {
          id: `assistant-${activeRunId}`,
          role: 'assistant',
          text: completeTrace.content?.result || '(完了)',
          run_id: activeRunId,
          ts: Date.now(),
        },
      ];
    });
    qc.invalidateQueries({ queryKey: ['dan-notion'] });
  }, [traceDone, activeRunId, traces, qc]);

  const sendChat = async () => {
    const msg = chatInput.trim();
    if (!msg || chatSending) return;
    setChatSending(true);
    setChatInput('');
    const userMsg: ChatMessage = {
      id: `user-${Date.now()}`,
      role: 'user',
      text: msg,
      ts: Date.now(),
    };
    setChatHistory((prev) => [...prev, userMsg]);
    try {
      const res = await fetchJSON<{ run_id: string }>(`${API}/chat`, {
        method: 'POST',
        body: JSON.stringify({ message: msg }),
      });
      setActiveRunId(res.run_id);
      setGanttExpanded(true);
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

  return (
    <div className="flex flex-col h-screen bg-white text-slate-900">
      {/* ========== 上: ガントタイムライン ========== */}
      <GanttTimeline
        traces={traces}
        runId={activeRunId}
        runs={recentRunsQ.data || []}
        onSelectRun={setActiveRunId}
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
        <ScrollArea className="flex-1">
          <div className="p-2 space-y-1">
            {pagesQ.isLoading && (
              <div className="p-3 text-sm text-slate-500 flex items-center gap-2">
                <Loader2 className="h-3 w-3 animate-spin" /> 読込中...
              </div>
            )}
            {pagesQ.error && (
              <div className="p-3 text-sm text-red-600">
                APIエラー: マイグレーション 036 を適用してください
              </div>
            )}
            {pagesQ.data?.map((p) => (
              <button
                key={p.id}
                onClick={() => setSelectedPageId(p.id)}
                className={cn(
                  'w-full flex items-center gap-2 px-3 py-2 rounded-md text-sm text-left transition-colors',
                  selectedPageId === p.id
                    ? 'bg-white border border-slate-200 shadow-sm text-slate-900'
                    : 'hover:bg-slate-100 text-slate-700'
                )}
              >
                <span>{p.icon || '📄'}</span>
                <span className="truncate flex-1">
                  {p.properties?.title || '無題'}
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
        </ScrollArea>
      </aside>

      {/* ========== 中央: ブロックエディタ ========== */}
      <main className="flex-1 flex flex-col min-w-0 bg-white">
        {/* 自然言語検索バー + 通知ベル */}
        <div className="border-b border-slate-200 p-3 flex items-center gap-2 relative">
          <Search className="h-4 w-4 text-slate-500" />
          <Input
            placeholder="自然言語検索 (例: 前回の請求書を見せて)"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && runSearch()}
            className="h-8 text-sm bg-white border-slate-200"
          />
          <Button size="sm" variant="outline" onClick={runSearch} className="bg-white border-slate-200 text-slate-700">
            検索
          </Button>
          {searchResults !== null && (
            <Button size="sm" variant="ghost" onClick={() => { setSearchResults(null); setSearchQuery(''); }}>
              クリア
            </Button>
          )}

          {/* 通知ベル */}
          <div className="ml-2 relative">
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

        {searchResults !== null ? (
          <ScrollArea className="flex-1">
            <div className="max-w-3xl mx-auto p-6 space-y-2">
              <h2 className="text-sm font-semibold text-slate-500 mb-2">
                検索結果: {searchResults.length}件
              </h2>
              {searchResults.length === 0 && (
                <p className="text-sm text-slate-500">
                  該当なし。pgvector インデックスに登録された後に再試行してください。
                </p>
              )}
              {searchResults.map((r) => (
                <Card key={r.block_id} className="p-3 bg-white border-slate-200">
                  <div className="flex items-center justify-between mb-1">
                    <Badge variant="secondary" className="text-[10px] bg-slate-100 text-slate-700">
                      類似度 {(r.similarity * 100).toFixed(0)}%
                    </Badge>
                    <span className="text-[10px] text-slate-500">{r.block_id.slice(0, 8)}</span>
                  </div>
                  <p className="text-sm">{r.summary || '(要約なし)'}</p>
                </Card>
              ))}
            </div>
          </ScrollArea>
        ) : !selectedPage ? (
          <div className="flex-1 flex flex-col items-center justify-center text-slate-400 gap-2">
            <Notebook className="h-12 w-12 opacity-30" />
            <p className="text-sm">左からページを選択するか、新規作成してください</p>
          </div>
        ) : (
          <>
            <div className="border-b border-slate-200 p-6 flex items-start justify-between">
              <div className="flex items-start gap-3">
                <span className="text-3xl">{selectedPage.icon || '📄'}</span>
                <div>
                  <h1 className="text-2xl font-bold text-slate-900">
                    {selectedPage.properties?.title || '無題'}
                  </h1>
                  <p className="text-xs text-slate-500 mt-1">
                    v{selectedPage.version} ・ 更新:{' '}
                    {new Date(selectedPage.updated_at).toLocaleString('ja-JP')}
                  </p>
                </div>
              </div>
              <div className="flex gap-2">
                <Button size="sm" variant="outline" onClick={() => addBlock.mutate('paragraph')} className="bg-white border-slate-200 text-slate-700">
                  <Plus className="h-4 w-4 mr-1" /> テキスト
                </Button>
                <Button size="sm" variant="outline" onClick={() => addBlock.mutate('checklist')} className="bg-white border-slate-200 text-slate-700">
                  <Plus className="h-4 w-4 mr-1" /> タスク
                </Button>
                <Button size="sm" variant="outline" onClick={() => addBlock.mutate('heading')} className="bg-white border-slate-200 text-slate-700">
                  <Plus className="h-4 w-4 mr-1" /> 見出し
                </Button>
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

            <ScrollArea className="flex-1">
              <div className="max-w-3xl mx-auto p-6 space-y-2">
                {blocksQ.isLoading && (
                  <Loader2 className="h-5 w-5 animate-spin text-slate-400" />
                )}
                {blocksQ.data?.length === 0 && (
                  <p className="text-sm text-slate-500">
                    上のボタンからブロックを追加してください
                  </p>
                )}
                {blocksQ.data?.map((b) => (
                  <BlockRow
                    key={b.id}
                    block={b}
                    onUpdate={(content) => updateBlock.mutate({ id: b.id, content })}
                    onDelete={() => removeBlock.mutate(b.id)}
                  />
                ))}
              </div>
            </ScrollArea>

            {/* バージョン履歴 */}
            {versionsQ.data && versionsQ.data.length > 0 && (
              <div className="border-t border-slate-200 p-3 flex items-center gap-2 text-xs text-slate-500">
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
        <ScrollArea className="flex-1 px-3 pb-3 pt-3">
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
        </ScrollArea>
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

  const totalMs = Math.max(endMs - startMs, 1000);

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
              {/* 時刻グリッド (5本) */}
              {[0, 1, 2, 3, 4].map((i) => (
                <div
                  key={i}
                  className="absolute top-0 bottom-0 border-l border-slate-200"
                  style={{ left: `${(i / 4) * 100}%` }}
                />
              ))}

              {/* 各エージェント行 */}
              {[...rows.entries()].map(([agentName, rowIdx]) => (
                <div
                  key={agentName}
                  className="absolute left-0 right-0 flex items-center"
                  style={{ top: rowIdx * rowHeight + 4, height: rowHeight }}
                >
                  <span className="absolute left-2 text-[10px] text-slate-500 z-10 bg-slate-50 px-1 truncate max-w-[140px]">
                    {agentName.replace('autopilot:', '').replace('__manual_chat__', 'チャット')}
                  </span>
                </div>
              ))}

              {/* イベントバー */}
              {traces.map((t, i) => {
                const ts = new Date(t.created_at).getTime();
                const startPct = ((ts - startMs) / totalMs) * 100;
                const nextSameAgent = traces.slice(i + 1).find((x) => x.agent_name === t.agent_name);
                const endTs = nextSameAgent ? new Date(nextSameAgent.created_at).getTime() : ts + 800;
                const widthPct = Math.max(((endTs - ts) / totalMs) * 100, 1);
                const rowIdx = rows.get(t.agent_name) || 0;
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
                      left: `calc(${Math.min(startPct, 99)}% + 150px)`,
                      width: `max(${Math.min(widthPct, 99 - startPct)}%, 6px)`,
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
}: {
  open: boolean;
  onToggle: () => void;
  history: ChatMessage[];
  input: string;
  onInputChange: (v: string) => void;
  onSend: () => void;
  sending: boolean;
  runId: string | null;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [history.length, open]);

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
          >
            <div
              className={cn(
                'max-w-[80%] rounded-2xl px-3 py-2 text-sm whitespace-pre-wrap break-words',
                m.role === 'user'
                  ? 'bg-indigo-600 text-white rounded-br-sm'
                  : 'bg-slate-100 text-slate-900 border border-slate-200 rounded-bl-sm'
              )}
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

      {/* 入力欄 */}
      <div className="border-t border-slate-200 p-3 flex gap-2 bg-white">
        <Input
          placeholder="メッセージを入力 (Enter で送信)"
          value={input}
          onChange={(e) => onInputChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              onSend();
            }
          }}
          disabled={sending}
          className="bg-white border-slate-200"
          autoFocus
        />
        <Button
          onClick={onSend}
          disabled={sending || !input.trim()}
          className="bg-indigo-600 hover:bg-indigo-700 text-white"
        >
          <Send className="h-4 w-4" />
        </Button>
      </div>
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
}: {
  block: Block;
  onUpdate: (content: any) => void;
  onDelete: () => void;
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
