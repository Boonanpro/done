'use client';

import { useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  CheckCircle2, Loader2, RefreshCw, ChevronLeft, ChevronRight, GitCommit, MessageSquare,
  TerminalSquare, Eye, Link as LinkIcon, Mail, X, ArrowUpCircle, Clock,
} from 'lucide-react';
import { toast } from 'sonner';

import { MainLayout } from '@/components/layout/main-layout';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { api, type AchievementItem, type AchievementEvidence } from '@/lib/api-client';
import { useAuthStore } from '@/stores/auth-store';
import { useProjectStore } from '@/stores/project-store';
import { cn } from '@/lib/utils';

const WEEKDAYS = ['日', '月', '火', '水', '木', '金', '土'];

function fmtDay(iso: string) {
  const d = new Date(`${iso}T00:00:00+09:00`);
  return `${iso} (${WEEKDAYS[d.getDay()]})`;
}

function fmtTime(iso: string | null) {
  if (!iso) return '';
  return new Date(iso).toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Tokyo' });
}

function shiftDay(iso: string, delta: number) {
  const d = new Date(`${iso}T00:00:00+09:00`);
  d.setUTCDate(d.getUTCDate() + delta);
  return d.toLocaleDateString('sv-SE', { timeZone: 'Asia/Tokyo' });
}

function EvidenceChip({ e }: { e: AchievementEvidence }) {
  const router = useRouter();
  const selectProject = useProjectStore((s) => s.selectProject);
  const base = 'inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[11px] text-muted-foreground max-w-[260px] truncate';
  if (e.kind === 'room' && e.ref) {
    return (
      <button
        type="button"
        className={cn(base, 'hover:bg-accent hover:text-foreground')}
        onClick={() => { selectProject(e.ref); router.push(`/chat/${e.ref}`); }}
        title="その部屋を開く"
      >
        <MessageSquare className="size-3 shrink-0" />部屋: {e.label}
      </button>
    );
  }
  if (e.kind === 'url' && /^https?:\/\//.test(e.ref)) {
    return (
      <a className={cn(base, 'hover:bg-accent hover:text-foreground')} href={e.ref} target="_blank" rel="noreferrer">
        <LinkIcon className="size-3 shrink-0" />{e.label || e.ref}
      </a>
    );
  }
  const Icon = e.kind === 'commit' ? GitCommit : e.kind === 'cli' ? TerminalSquare : e.kind === 'watch' ? Eye : e.kind === 'mail' ? Mail : LinkIcon;
  const text = e.kind === 'commit' ? (e.label.startsWith(e.ref.slice(0, 7)) ? e.label : `${e.ref.slice(0, 7)} ${e.label}`) : e.label || e.ref;
  return (
    <span className={base} title={e.ref}>
      <Icon className="size-3 shrink-0" />{text}
    </span>
  );
}

function Row({ item, onPatch, busy }: { item: AchievementItem; onPatch: (p: Record<string, unknown>) => void; busy: boolean }) {
  const done = item.status === 'done';
  return (
    <li className="group flex gap-3 py-3 border-b last:border-b-0">
      <div className="w-12 shrink-0 text-xs text-muted-foreground pt-0.5 tabular-nums">
        {fmtTime(done ? item.done_at || item.first_seen : item.first_seen)}
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-start gap-2">
          <span className={cn('font-medium leading-snug', !done && 'text-foreground/80')}>{item.title}</span>
          {item.tags.map((t) => (
            <Badge key={t} variant="outline" className="text-[10px] px-1.5 py-0 h-5 shrink-0">{t}</Badge>
          ))}
        </div>
        {item.detail && <p className="text-sm text-muted-foreground mt-0.5">{item.detail}</p>}
        {item.evidence.length > 0 && (
          <div className="flex flex-wrap gap-1.5 mt-1.5">
            {item.evidence.map((e, i) => <EvidenceChip key={`${e.kind}-${e.ref}-${i}`} e={e} />)}
          </div>
        )}
      </div>
      <div className="shrink-0 flex items-start gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
        {!done ? (
          <Button variant="ghost" size="icon" className="size-7" title="成果に昇格" disabled={busy} onClick={() => onPatch({ status: 'done' })}>
            <ArrowUpCircle className="size-4" />
          </Button>
        ) : (
          <Button variant="ghost" size="icon" className="size-7" title="進行中に戻す" disabled={busy} onClick={() => onPatch({ status: 'in_progress' })}>
            <Clock className="size-4" />
          </Button>
        )}
        <Button variant="ghost" size="icon" className="size-7" title="これは成果ではない (非表示)" disabled={busy} onClick={() => onPatch({ status: 'dismissed' })}>
          <X className="size-4" />
        </Button>
      </div>
    </li>
  );
}

export default function TodayPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const hasToken = typeof window !== 'undefined' && !!localStorage.getItem('done-token');
  const [day, setDay] = useState<string | undefined>(undefined);

  useEffect(() => {
    if (!isAuthenticated && !hasToken) router.push('/login');
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAuthenticated, hasToken]);

  const q = useQuery({
    queryKey: ['achievements', day ?? 'today'],
    queryFn: () => api.achievements.list(day),
    refetchInterval: 30_000,
    refetchOnWindowFocus: true,
  });

  const data = q.data;
  const viewDay = data?.day ?? day;
  const isToday = !!data && data.day === data.today;

  // 日付が変わったら (0時) 自動で新しい今日へ
  useEffect(() => {
    if (data && day === undefined && data.day !== data.today) {
      queryClient.invalidateQueries({ queryKey: ['achievements'] });
    }
  }, [data, day, queryClient]);

  const patch = useMutation({
    mutationFn: ({ id, p }: { id: string; p: Record<string, unknown> }) => api.achievements.patch(id, p),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['achievements'] }),
    onError: () => toast.error('更新に失敗しました'),
  });

  const refresh = useMutation({
    mutationFn: () => api.achievements.refresh(),
    onSuccess: (r) => {
      queryClient.invalidateQueries({ queryKey: ['achievements'] });
      toast.success(`再判定しました (${r.changed} 件更新)`);
    },
    onError: () => toast.error('再判定に失敗しました'),
  });

  const { doneItems, wipItems } = useMemo(() => {
    const items = data?.items ?? [];
    return {
      doneItems: items.filter((i) => i.status === 'done').sort((a, b) => (a.done_at || a.first_seen).localeCompare(b.done_at || b.first_seen)),
      wipItems: items.filter((i) => i.status === 'in_progress'),
    };
  }, [data]);

  return (
    <MainLayout showNotifications={false}>
      <div className="flex flex-col h-full overflow-hidden">
        <div className="flex items-center gap-3 px-6 py-4 border-b shrink-0">
          <div className="flex-1 min-w-0">
            <h1 className="text-lg font-semibold flex items-center gap-2">
              今日やったこと
              {viewDay && <span className="text-sm font-normal text-muted-foreground">{fmtDay(viewDay)}</span>}
              {isToday && <Badge variant="secondary" className="text-[10px]">今日</Badge>}
            </h1>
            <p className="text-xs text-muted-foreground mt-0.5">
              成果 {doneItems.length} 件 ・ 進行中 {wipItems.length} 件
              {data?.last_run && <> ・ 最終判定 {fmtTime(data.last_run)}</>}
              {' '}・ 30秒ごとに自動更新、0時にリセット
            </p>
          </div>
          <div className="flex items-center gap-1">
            <Button variant="ghost" size="icon" title="前日" onClick={() => viewDay && setDay(shiftDay(viewDay, -1))}>
              <ChevronLeft className="size-4" />
            </Button>
            <Button variant="ghost" size="icon" title="翌日" disabled={isToday} onClick={() => viewDay && setDay(shiftDay(viewDay, 1))}>
              <ChevronRight className="size-4" />
            </Button>
            {!isToday && (
              <Button variant="outline" size="sm" onClick={() => setDay(undefined)}>今日へ</Button>
            )}
            {isToday && (
              <Button variant="outline" size="sm" disabled={refresh.isPending} onClick={() => refresh.mutate()} title="今日の証拠を全部読み直して再判定">
                {refresh.isPending ? <Loader2 className="size-4 animate-spin" /> : <RefreshCw className="size-4" />}
                <span className="ml-1">再判定</span>
              </Button>
            )}
          </div>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-4">
          {q.isLoading ? (
            <div className="flex items-center gap-2 text-muted-foreground text-sm"><Loader2 className="size-4 animate-spin" />読み込み中…</div>
          ) : q.isError ? (
            <p className="text-sm text-destructive">読み込みに失敗しました。ダンコアが起動しているか確認してください。</p>
          ) : (
            <div className="max-w-3xl space-y-8">
              <section>
                <h2 className="flex items-center gap-2 text-sm font-semibold mb-1">
                  <CheckCircle2 className="size-4 text-emerald-500" />成果
                </h2>
                {doneItems.length === 0 ? (
                  <p className="text-sm text-muted-foreground py-3">まだありません。作業が完了すると自動で並びます。</p>
                ) : (
                  <ul>
                    {doneItems.map((it) => (
                      <Row key={it.id} item={it} busy={patch.isPending} onPatch={(p) => patch.mutate({ id: it.id, p })} />
                    ))}
                  </ul>
                )}
              </section>
              <section>
                <h2 className="flex items-center gap-2 text-sm font-semibold mb-1">
                  <Loader2 className="size-4 text-amber-500" />進行中
                </h2>
                {wipItems.length === 0 ? (
                  <p className="text-sm text-muted-foreground py-3">進行中の件はありません。</p>
                ) : (
                  <ul>
                    {wipItems.map((it) => (
                      <Row key={it.id} item={it} busy={patch.isPending} onPatch={(p) => patch.mutate({ id: it.id, p })} />
                    ))}
                  </ul>
                )}
              </section>
              <p className="text-[11px] text-muted-foreground">
                判定基準: <code>~/.dan/workspace/ACHIEVEMENT_RULES.md</code>。直したら「再判定」で反映。行にマウスを乗せると昇格/戻す/非表示ができます。
              </p>
            </div>
          )}
        </div>
      </div>
    </MainLayout>
  );
}
