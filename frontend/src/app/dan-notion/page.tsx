'use client';

/**
 * ダン用Notion トップページ
 *
 * 構成:
 *   - 左: ページツリー (root pages)
 *   - 中央: 選択ページのブロックエディタ
 *   - 右: Autopilot トレース + 通知センター
 */
import { useState, useMemo } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Notebook, Plus, Loader2, Bell, Activity, FileText, Trash2,
  ChevronRight, History, Sparkles, AlertCircle, Search,
} from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Badge } from '@/components/ui/badge';
import { Card } from '@/components/ui/card';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
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

function DanNotionInner() {
  const qc = useQueryClient();
  const [selectedPageId, setSelectedPageId] = useState<string | null>(null);
  const [newPageTitle, setNewPageTitle] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<Array<{ block_id: string; similarity: number; summary: string | null }> | null>(null);

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

  return (
    <div className="flex h-screen bg-background text-foreground">
      {/* ========== 左: ページツリー ========== */}
      <aside className="w-64 border-r border-border flex flex-col">
        <div className="p-4 border-b border-border">
          <div className="flex items-center gap-2 mb-3">
            <Notebook className="h-5 w-5 text-primary" />
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
              <div className="p-3 text-sm text-muted-foreground flex items-center gap-2">
                <Loader2 className="h-3 w-3 animate-spin" /> 読込中...
              </div>
            )}
            {pagesQ.error && (
              <div className="p-3 text-sm text-destructive">
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
                    ? 'bg-accent text-accent-foreground'
                    : 'hover:bg-accent/50'
                )}
              >
                <span>{p.icon || '📄'}</span>
                <span className="truncate flex-1">
                  {p.properties?.title || '無題'}
                </span>
                <Badge variant="secondary" className="text-[10px] h-4">
                  v{p.version}
                </Badge>
              </button>
            ))}
            {pagesQ.data?.length === 0 && (
              <div className="p-3 text-sm text-muted-foreground">
                ページがありません。上から作成してください。
              </div>
            )}
          </div>
        </ScrollArea>
      </aside>

      {/* ========== 中央: ブロックエディタ ========== */}
      <main className="flex-1 flex flex-col min-w-0">
        {/* 自然言語検索バー */}
        <div className="border-b border-border p-3 flex items-center gap-2">
          <Search className="h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="自然言語検索 (例: 前回の請求書を見せて)"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && runSearch()}
            className="h-8 text-sm"
          />
          <Button size="sm" variant="outline" onClick={runSearch}>
            検索
          </Button>
          {searchResults !== null && (
            <Button size="sm" variant="ghost" onClick={() => { setSearchResults(null); setSearchQuery(''); }}>
              クリア
            </Button>
          )}
        </div>

        {searchResults !== null ? (
          <ScrollArea className="flex-1">
            <div className="max-w-3xl mx-auto p-6 space-y-2">
              <h2 className="text-sm font-semibold text-muted-foreground mb-2">
                検索結果: {searchResults.length}件
              </h2>
              {searchResults.length === 0 && (
                <p className="text-sm text-muted-foreground">
                  該当なし。pgvector インデックスに登録された後に再試行してください。
                </p>
              )}
              {searchResults.map((r) => (
                <Card key={r.block_id} className="p-3">
                  <div className="flex items-center justify-between mb-1">
                    <Badge variant="secondary" className="text-[10px]">
                      類似度 {(r.similarity * 100).toFixed(0)}%
                    </Badge>
                    <span className="text-[10px] text-muted-foreground">{r.block_id.slice(0, 8)}</span>
                  </div>
                  <p className="text-sm">{r.summary || '(要約なし)'}</p>
                </Card>
              ))}
            </div>
          </ScrollArea>
        ) : !selectedPage ? (
          <div className="flex-1 flex flex-col items-center justify-center text-muted-foreground gap-2">
            <Notebook className="h-12 w-12 opacity-30" />
            <p className="text-sm">左からページを選択するか、新規作成してください</p>
          </div>
        ) : (
          <>
            <div className="border-b border-border p-6 flex items-start justify-between">
              <div className="flex items-start gap-3">
                <span className="text-3xl">{selectedPage.icon || '📄'}</span>
                <div>
                  <h1 className="text-2xl font-bold">
                    {selectedPage.properties?.title || '無題'}
                  </h1>
                  <p className="text-xs text-muted-foreground mt-1">
                    v{selectedPage.version} ・ 更新:{' '}
                    {new Date(selectedPage.updated_at).toLocaleString('ja-JP')}
                  </p>
                </div>
              </div>
              <div className="flex gap-2">
                <Button size="sm" variant="outline" onClick={() => addBlock.mutate('paragraph')}>
                  <Plus className="h-4 w-4 mr-1" /> テキスト
                </Button>
                <Button size="sm" variant="outline" onClick={() => addBlock.mutate('checklist')}>
                  <Plus className="h-4 w-4 mr-1" /> タスク
                </Button>
                <Button size="sm" variant="outline" onClick={() => addBlock.mutate('heading')}>
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
                  <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
                )}
                {blocksQ.data?.length === 0 && (
                  <p className="text-sm text-muted-foreground">
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
              <div className="border-t border-border p-3 flex items-center gap-2 text-xs text-muted-foreground">
                <History className="h-3 w-3" />
                {versionsQ.data.length} 件の編集履歴 (自動世代管理)
              </div>
            )}
          </>
        )}
      </main>

      {/* ========== 右: Autopilot + 通知 ========== */}
      <aside className="w-80 border-l border-border flex flex-col">
        <Tabs defaultValue="autopilot" className="flex-1 flex flex-col">
          <TabsList className="m-3 grid grid-cols-2">
            <TabsTrigger value="autopilot">
              <Activity className="h-3 w-3 mr-1" />
              Autopilot
            </TabsTrigger>
            <TabsTrigger value="notifications">
              <Bell className="h-3 w-3 mr-1" />
              通知
              {notifQ.data && notifQ.data.filter((n) => !n.read_at).length > 0 && (
                <Badge variant="destructive" className="ml-1 h-4 text-[10px]">
                  {notifQ.data.filter((n) => !n.read_at).length}
                </Badge>
              )}
            </TabsTrigger>
          </TabsList>

          <TabsContent value="autopilot" className="flex-1 mt-0">
            <ScrollArea className="h-full px-3 pb-3">
              <div className="space-y-3">
                <div>
                  <h3 className="text-xs font-semibold text-muted-foreground uppercase mb-2">
                    トリガー ({triggersQ.data?.length || 0})
                  </h3>
                  {triggersQ.data?.length === 0 && (
                    <p className="text-xs text-muted-foreground">
                      トリガー未設定
                    </p>
                  )}
                  {triggersQ.data?.map((t) => (
                    <Card key={t.id} className="p-2 mb-2">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2 min-w-0">
                          <Sparkles className="h-3 w-3 text-primary shrink-0" />
                          <span className="text-xs truncate">{t.name}</span>
                        </div>
                        <Badge variant={t.is_enabled ? 'default' : 'secondary'} className="text-[10px] h-4">
                          {t.kind}
                        </Badge>
                      </div>
                      <p className="text-[10px] text-muted-foreground mt-1">
                        実行: {t.fire_count}回
                      </p>
                    </Card>
                  ))}
                </div>

                <div>
                  <h3 className="text-xs font-semibold text-muted-foreground uppercase mb-2">
                    最近の実行
                  </h3>
                  {runsQ.data?.length === 0 && (
                    <p className="text-xs text-muted-foreground">実行履歴なし</p>
                  )}
                  {runsQ.data?.slice(0, 5).map((r) => (
                    <Card key={r.id} className="p-2 mb-2">
                      <div className="flex items-center justify-between">
                        <Badge
                          variant={
                            r.status === 'succeeded'
                              ? 'default'
                              : r.status === 'failed'
                              ? 'destructive'
                              : 'secondary'
                          }
                          className="text-[10px] h-4"
                        >
                          {r.status}
                        </Badge>
                        <span className="text-[10px] text-muted-foreground">
                          {new Date(r.started_at).toLocaleTimeString('ja-JP')}
                        </span>
                      </div>
                    </Card>
                  ))}
                </div>
              </div>
            </ScrollArea>
          </TabsContent>

          <TabsContent value="notifications" className="flex-1 mt-0">
            <ScrollArea className="h-full px-3 pb-3">
              <div className="space-y-2">
                {notifQ.data?.length === 0 && (
                  <p className="text-xs text-muted-foreground">通知なし</p>
                )}
                {notifQ.data?.map((n) => (
                  <Card
                    key={n.id}
                    className={cn(
                      'p-3',
                      !n.read_at && 'border-primary',
                      n.severity === 'urgent' && 'border-destructive'
                    )}
                  >
                    <div className="flex items-start gap-2">
                      {n.severity === 'urgent' && (
                        <AlertCircle className="h-4 w-4 text-destructive shrink-0 mt-0.5" />
                      )}
                      <div className="min-w-0 flex-1">
                        <p className="text-xs font-medium">{n.title}</p>
                        {n.body && (
                          <p className="text-[10px] text-muted-foreground mt-1">
                            {n.body}
                          </p>
                        )}
                        {n.due_at && (
                          <p className="text-[10px] text-muted-foreground mt-1">
                            期限: {new Date(n.due_at).toLocaleString('ja-JP')}
                          </p>
                        )}
                      </div>
                    </div>
                  </Card>
                ))}
              </div>
            </ScrollArea>
          </TabsContent>
        </Tabs>
      </aside>
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
