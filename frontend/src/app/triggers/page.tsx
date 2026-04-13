'use client';

import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Plus, Play, Trash2, Loader2, Zap } from 'lucide-react';

import { MainLayout } from '@/components/layout/main-layout';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { ScrollArea } from '@/components/ui/scroll-area';
import {
  createTrigger,
  deleteTrigger,
  fireTrigger,
  listAgentTraces,
  listTriggerRuns,
  listTriggers,
  type AgentTrace,
  type TriggerKind,
  type TriggerResponse,
} from '@/lib/api-client';

const KINDS: TriggerKind[] = ['gmail', 'calendar', 'file', 'cron', 'collab', 'chat_command'];

export default function TriggersPage() {
  const qc = useQueryClient();
  const [selected, setSelected] = useState<string | null>(null);
  const [newName, setNewName] = useState('');
  const [newKind, setNewKind] = useState<TriggerKind>('chat_command');

  const triggers = useQuery({
    queryKey: ['triggers'],
    queryFn: () => listTriggers(),
  });

  const runs = useQuery({
    queryKey: ['trigger-runs', selected],
    queryFn: () => (selected ? listTriggerRuns(selected) : Promise.resolve({ runs: [] })),
    enabled: !!selected,
  });

  const traces = useQuery({
    queryKey: ['agent-traces', selected],
    queryFn: () => listAgentTraces(undefined, 100),
    refetchInterval: 3000,
  });

  const create = useMutation({
    mutationFn: () =>
      createTrigger({
        name: newName || '無題トリガー',
        kind: newKind,
        actions: [{ type: 'classify' }, { type: 'organize' }, { type: 'notify' }],
      }),
    onSuccess: () => {
      setNewName('');
      qc.invalidateQueries({ queryKey: ['triggers'] });
    },
  });

  const fire = useMutation({
    mutationFn: (id: string) => fireTrigger(id, { text: 'テスト実行' }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['trigger-runs', selected] });
      qc.invalidateQueries({ queryKey: ['agent-traces'] });
    },
  });

  const del = useMutation({
    mutationFn: (id: string) => deleteTrigger(id),
    onSuccess: () => {
      setSelected(null);
      qc.invalidateQueries({ queryKey: ['triggers'] });
    },
  });

  const list: TriggerResponse[] = triggers.data?.triggers ?? [];
  const current = list.find((t) => t.id === selected) ?? null;

  return (
    <MainLayout>
      <div className="flex h-full">
        <aside className="w-80 border-r bg-muted/20 flex flex-col">
          <div className="p-3 border-b space-y-2">
            <h2 className="text-sm font-semibold flex items-center gap-2">
              <Zap className="w-4 h-4" /> トリガー
            </h2>
            <Input
              placeholder="新しいトリガー名"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              className="h-8 text-xs"
            />
            <select
              value={newKind}
              onChange={(e) => setNewKind(e.target.value as TriggerKind)}
              className="w-full h-8 text-xs border rounded px-2 bg-background"
            >
              {KINDS.map((k) => (
                <option key={k} value={k}>
                  {k}
                </option>
              ))}
            </select>
            <Button
              size="sm"
              className="w-full h-8"
              onClick={() => create.mutate()}
              disabled={create.isPending}
            >
              {create.isPending ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Plus className="w-3.5 h-3.5" />}
              作成
            </Button>
          </div>
          <ScrollArea className="flex-1">
            <div className="p-2 space-y-0.5">
              {list.map((t) => (
                <button
                  key={t.id}
                  onClick={() => setSelected(t.id)}
                  className={`w-full flex items-center justify-between px-2 py-1.5 rounded text-left text-sm hover:bg-muted ${
                    t.id === selected ? 'bg-muted font-medium' : ''
                  }`}
                >
                  <div className="min-w-0">
                    <div className="truncate">{t.name}</div>
                    <div className="text-[10px] text-muted-foreground">
                      {t.kind} · 発火 {t.fire_count}
                    </div>
                  </div>
                  {t.is_enabled ? (
                    <span className="text-[10px] text-green-600">ON</span>
                  ) : (
                    <span className="text-[10px] text-muted-foreground">OFF</span>
                  )}
                </button>
              ))}
              {list.length === 0 && !triggers.isLoading && (
                <div className="text-xs text-muted-foreground px-2 py-4 text-center">
                  まだトリガーがありません
                </div>
              )}
            </div>
          </ScrollArea>
        </aside>

        <main className="flex-1 overflow-auto p-6 space-y-6">
          {!current && (
            <div className="h-full flex items-center justify-center text-muted-foreground text-sm">
              左のリストからトリガーを選択してください
            </div>
          )}
          {current && (
            <>
              <div className="flex items-start justify-between">
                <div>
                  <h1 className="text-2xl font-bold">{current.name}</h1>
                  <p className="text-xs text-muted-foreground mt-1">
                    {current.kind} · 発火 {current.fire_count} 回 · {current.is_enabled ? '有効' : '無効'}
                  </p>
                </div>
                <div className="flex gap-2">
                  <Button
                    size="sm"
                    onClick={() => fire.mutate(current.id)}
                    disabled={fire.isPending}
                  >
                    {fire.isPending ? (
                      <Loader2 className="w-4 h-4 animate-spin" />
                    ) : (
                      <Play className="w-4 h-4" />
                    )}
                    手動発火
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => {
                      if (confirm('削除しますか？')) del.mutate(current.id);
                    }}
                  >
                    <Trash2 className="w-4 h-4 text-destructive" />
                  </Button>
                </div>
              </div>

              <section>
                <h3 className="text-sm font-semibold mb-2">アクション</h3>
                <pre className="text-xs bg-muted rounded p-3 overflow-auto">
                  {JSON.stringify(current.actions, null, 2)}
                </pre>
              </section>

              <section>
                <h3 className="text-sm font-semibold mb-2">実行履歴</h3>
                <div className="space-y-1">
                  {(runs.data?.runs ?? []).map((r) => (
                    <div key={r.id} className="text-xs border rounded p-2">
                      <div className="flex justify-between">
                        <span className="font-mono">{r.status}</span>
                        <span className="text-muted-foreground">
                          {new Date(r.started_at).toLocaleString('ja-JP')}
                        </span>
                      </div>
                      {r.error && <div className="text-destructive mt-1">{r.error}</div>}
                    </div>
                  ))}
                  {(runs.data?.runs ?? []).length === 0 && (
                    <div className="text-xs text-muted-foreground">実行履歴なし</div>
                  )}
                </div>
              </section>

              <section>
                <h3 className="text-sm font-semibold mb-2">エージェントトレース（最新）</h3>
                <div className="space-y-1 max-h-96 overflow-auto">
                  {(traces.data?.traces ?? []).slice(-30).map((t: AgentTrace) => (
                    <div key={t.id} className="text-[11px] font-mono border-l-2 border-primary pl-2 py-0.5">
                      <span className="text-primary">[{t.agent_name}]</span>{' '}
                      <span className="text-muted-foreground">{t.event_type}</span>{' '}
                      {JSON.stringify(t.content).slice(0, 120)}
                    </div>
                  ))}
                </div>
              </section>
            </>
          )}
        </main>
      </div>
    </MainLayout>
  );
}
