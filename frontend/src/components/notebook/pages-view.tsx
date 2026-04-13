'use client';

import { useMemo, useState } from 'react';
import dynamic from 'next/dynamic';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  FileText,
  Database as DatabaseIcon,
  Plus,
  Star,
  Trash2,
  Loader2,
  Search as SearchIcon,
} from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { ScrollArea } from '@/components/ui/scroll-area';
import {
  createBlock,
  deleteBlock,
  getBlock,
  getBlockTree,
  updateBlock,
  type BlockResponse,
  type BlockTreeNode,
} from '@/lib/api-client';

const WorkspaceEditor = dynamic(
  () => import('@/components/workspace/workspace-editor').then((m) => m.WorkspaceEditor),
  { ssr: false, loading: () => <div className="text-sm text-muted-foreground">エディタ読込中…</div> }
);

export function PagesView() {
  const queryClient = useQueryClient();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [search, setSearch] = useState('');

  const treeQuery = useQuery({ queryKey: ['workspace', 'tree'], queryFn: getBlockTree });
  const blockQuery = useQuery({
    queryKey: ['workspace', 'block', selectedId],
    queryFn: () => (selectedId ? getBlock(selectedId) : Promise.resolve(null)),
    enabled: !!selectedId,
  });

  const createPage = useMutation({
    mutationFn: () => createBlock({ type: 'page', properties: { title: '新しいページ' }, content: [] }),
    onSuccess: (block) => {
      queryClient.invalidateQueries({ queryKey: ['workspace', 'tree'] });
      setSelectedId(block.id);
    },
  });

  const updateMutation = useMutation({
    mutationFn: (payload: Parameters<typeof updateBlock>[1]) => updateBlock(selectedId!, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['workspace', 'tree'] });
      queryClient.invalidateQueries({ queryKey: ['workspace', 'block', selectedId] });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => deleteBlock(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['workspace', 'tree'] });
      setSelectedId(null);
    },
  });

  const filteredNodes: BlockTreeNode[] = useMemo(() => {
    const nodes = treeQuery.data?.nodes ?? [];
    if (!search.trim()) return nodes;
    const q = search.toLowerCase();
    return nodes.filter((n) => n.title.toLowerCase().includes(q));
  }, [treeQuery.data, search]);

  const currentTitle = (blockQuery.data?.properties?.title as string | undefined) ?? '';

  return (
    <div className="flex h-full">
      <aside className="w-72 border-r bg-muted/20 flex flex-col">
        <div className="p-3 border-b space-y-2">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold">ページ</h2>
            <Button size="sm" variant="ghost" onClick={() => createPage.mutate()} disabled={createPage.isPending}>
              {createPage.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />}
            </Button>
          </div>
          <div className="relative">
            <SearchIcon className="absolute left-2 top-2.5 w-3.5 h-3.5 text-muted-foreground" />
            <Input placeholder="検索..." className="pl-7 h-8 text-xs" value={search} onChange={(e) => setSearch(e.target.value)} />
          </div>
        </div>
        <ScrollArea className="flex-1">
          <div className="p-2 space-y-0.5">
            {treeQuery.isLoading && <div className="text-xs text-muted-foreground px-2 py-4 text-center">読込中…</div>}
            {!treeQuery.isLoading && filteredNodes.length === 0 && (
              <div className="text-xs text-muted-foreground px-2 py-4 text-center">ページがありません。＋ で作成</div>
            )}
            {filteredNodes.map((node) => {
              const Icon = node.type === 'database' ? DatabaseIcon : FileText;
              const isActive = node.id === selectedId;
              return (
                <button
                  key={node.id}
                  onClick={() => setSelectedId(node.id)}
                  className={`w-full flex items-center gap-2 px-2 py-1.5 rounded text-left text-sm hover:bg-muted ${isActive ? 'bg-muted font-medium' : ''}`}
                >
                  {node.icon ? <span className="text-base">{node.icon}</span> : <Icon className="w-4 h-4 text-muted-foreground shrink-0" />}
                  <span className="truncate flex-1">{node.title}</span>
                  {node.is_starred && <Star className="w-3 h-3 fill-yellow-400 text-yellow-400" />}
                </button>
              );
            })}
          </div>
        </ScrollArea>
      </aside>

      <main className="flex-1 overflow-auto">
        {!selectedId && (
          <div className="h-full flex items-center justify-center text-muted-foreground text-sm">
            左のリストからページを選択、または ＋ で新規作成
          </div>
        )}
        {selectedId && blockQuery.isLoading && <div className="p-8 text-muted-foreground">読込中…</div>}
        {selectedId && blockQuery.data && (
          <div className="max-w-3xl mx-auto px-8 py-10">
            <div className="flex items-start justify-between mb-6">
              <input
                value={currentTitle}
                onChange={(e) =>
                  updateMutation.mutate({
                    properties: { ...(blockQuery.data!.properties as Record<string, unknown>), title: e.target.value },
                  })
                }
                className="text-4xl font-bold bg-transparent outline-none flex-1"
                placeholder="Untitled"
              />
              <div className="flex gap-1">
                <Button size="sm" variant="ghost" onClick={() => updateMutation.mutate({ is_starred: !blockQuery.data!.is_starred })}>
                  <Star className={`w-4 h-4 ${blockQuery.data.is_starred ? 'fill-yellow-400 text-yellow-400' : ''}`} />
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    if (confirm('このページを削除しますか？')) deleteMutation.mutate(selectedId);
                  }}
                >
                  <Trash2 className="w-4 h-4 text-destructive" />
                </Button>
              </div>
            </div>
            <WorkspaceEditor
              key={blockQuery.data.id}
              block={blockQuery.data as BlockResponse}
              onChange={(content) => updateMutation.mutate({ content })}
            />
          </div>
        )}
      </main>
    </div>
  );
}
