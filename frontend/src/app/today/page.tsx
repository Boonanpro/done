'use client';

import { useEffect, useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  Loader2, RefreshCw, ChevronLeft, ChevronRight, MessageSquare,
  Mail, X, ArrowUpCircle, Clock, Rocket, Wrench, Hammer, Search, Banknote, FileText,
  MessagesSquare, Palette, Clapperboard, KeyRound, Sparkles, Image as ImageIcon, ImageOff,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { toast } from 'sonner';

import { MainLayout } from '@/components/layout/main-layout';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { api, type AchievementItem } from '@/lib/api-client';
import { useAuthStore } from '@/stores/auth-store';
import { useProjectStore } from '@/stores/project-store';
import { cn } from '@/lib/utils';

const WEEKDAYS = ['日', '月', '火', '水', '木', '金', '土'];
const ILLUST_PREF_KEY = 'today-illust';

const ICONS: Record<string, { Icon: LucideIcon; label: string }> = {
  mail: { Icon: Mail, label: '連絡' },
  publish: { Icon: Rocket, label: '公開・提出' },
  fix: { Icon: Wrench, label: '修正' },
  build: { Icon: Hammer, label: '実装' },
  research: { Icon: Search, label: '調査' },
  money: { Icon: Banknote, label: 'お金' },
  doc: { Icon: FileText, label: '書類' },
  talk: { Icon: MessagesSquare, label: '相談' },
  design: { Icon: Palette, label: 'デザイン' },
  video: { Icon: Clapperboard, label: '制作' },
  login: { Icon: KeyRound, label: '認証' },
  other: { Icon: Sparkles, label: 'その他' },
};

function fmtDay(iso: string) {
  const d = new Date(`${iso}T00:00:00+09:00`);
  return `${iso} (${WEEKDAYS[d.getDay()]})`;
}

function fmtTime(iso: string | null) {
  if (!iso) return '';
  return new Date(iso).toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Tokyo' });
}

/** JST の 0:00 からの経過分 (0..1440) */
function jstMinutes(iso: string) {
  const d = new Date(iso);
  const parts = new Intl.DateTimeFormat('en-GB', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'Asia/Tokyo' }).formatToParts(d);
  const h = Number(parts.find((p) => p.type === 'hour')?.value ?? 0) % 24;
  const m = Number(parts.find((p) => p.type === 'minute')?.value ?? 0);
  return h * 60 + m;
}

function shiftDay(iso: string, delta: number) {
  const d = new Date(`${iso}T00:00:00+09:00`);
  d.setUTCDate(d.getUTCDate() + delta);
  return d.toLocaleDateString('sv-SE', { timeZone: 'Asia/Tokyo' });
}

function itemTime(it: AchievementItem) {
  return it.status === 'done' ? it.done_at || it.first_seen : it.first_seen;
}

// ---------------------------------------------------------------- 24h clock

function polar(cx: number, cy: number, r: number, minutes: number) {
  const a = (minutes / 1440) * Math.PI * 2 - Math.PI / 2; // 0:00 を真上、時計回り
  return { x: cx + r * Math.cos(a), y: cy + r * Math.sin(a) };
}

function DayClock({ items, isToday, activeId, onHover }: {
  items: AchievementItem[]; isToday: boolean; activeId: string | null; onHover: (id: string | null) => void;
}) {
  const [nowMin, setNowMin] = useState(() => jstMinutes(new Date().toISOString()));
  useEffect(() => {
    const t = setInterval(() => setNowMin(jstMinutes(new Date().toISOString())), 30_000);
    return () => clearInterval(t);
  }, []);
  const size = 300, cx = size / 2, cy = size / 2, r = 110;
  const doneCount = items.filter((i) => i.status === 'done').length;
  const wipCount = items.length - doneCount;
  const nowPt = polar(cx, cy, r, nowMin);

  return (
    <svg viewBox={`0 0 ${size} ${size}`} className="w-[300px] h-[300px] select-none" role="img" aria-label="24時間の時計">
      {/* 文字盤 */}
      <circle cx={cx} cy={cy} r={r} className="fill-none stroke-border" strokeWidth={10} />
      {/* 経過した時間帯 (今日のみ) */}
      {isToday && nowMin > 0 && (
        <path
          d={`M ${polar(cx, cy, r, 0).x} ${polar(cx, cy, r, 0).y} A ${r} ${r} 0 ${nowMin > 720 ? 1 : 0} 1 ${nowPt.x} ${nowPt.y}`}
          className="fill-none stroke-foreground/15" strokeWidth={10}
        />
      )}
      {/* 目盛り */}
      {Array.from({ length: 24 }, (_, h) => {
        const p1 = polar(cx, cy, r + 9, h * 60), p2 = polar(cx, cy, r + (h % 6 === 0 ? 18 : 13), h * 60);
        const lp = polar(cx, cy, r + 27, h * 60);
        return (
          <g key={h}>
            <line x1={p1.x} y1={p1.y} x2={p2.x} y2={p2.y} className="stroke-muted-foreground/50" strokeWidth={h % 6 === 0 ? 1.5 : 1} />
            {h % 6 === 0 && (
              <text x={lp.x} y={lp.y} textAnchor="middle" dominantBaseline="middle" className="fill-muted-foreground text-[10px]">{h}</text>
            )}
          </g>
        );
      })}
      {/* 現在時刻の針 */}
      {isToday && (
        <line x1={cx} y1={cy} x2={nowPt.x} y2={nowPt.y} className="stroke-foreground/60" strokeWidth={1.5} strokeLinecap="round" />
      )}
      {/* 出来事の点 */}
      {items.map((it) => {
        const t = itemTime(it);
        const p = polar(cx, cy, r, jstMinutes(t));
        const done = it.status === 'done';
        const active = activeId === it.id;
        return (
          <g key={it.id} onMouseEnter={() => onHover(it.id)} onMouseLeave={() => onHover(null)} className="cursor-pointer">
            <circle cx={p.x} cy={p.y} r={active ? 9 : 6} className={cn('stroke-background', done ? 'fill-emerald-500' : 'fill-amber-400')} strokeWidth={2} />
            {!done && <circle cx={p.x} cy={p.y} r={9} className="fill-none stroke-amber-400/60 animate-ping" style={{ transformOrigin: `${p.x}px ${p.y}px` }} />}
            <title>{fmtTime(t)} {it.title}</title>
          </g>
        );
      })}
      {/* 中央 */}
      <text x={cx} y={cy - 10} textAnchor="middle" className="fill-foreground text-[30px] font-semibold">{doneCount}</text>
      <text x={cx} y={cy + 12} textAnchor="middle" className="fill-muted-foreground text-[11px]">成果</text>
      {wipCount > 0 && <text x={cx} y={cy + 30} textAnchor="middle" className="fill-amber-500 text-[11px]">進行中 {wipCount}</text>}
    </svg>
  );
}

// ---------------------------------------------------------------- card

function AchievementCard({ item, showIllust, active, onHover, onPatch, onIllustrate, busy }: {
  item: AchievementItem; showIllust: boolean; active: boolean; onHover: (id: string | null) => void;
  onPatch: (p: Record<string, unknown>) => void; onIllustrate: () => void; busy: boolean;
}) {
  const router = useRouter();
  const selectProject = useProjectStore((s) => s.selectProject);
  const done = item.status === 'done';
  const { Icon, label } = ICONS[item.icon] ?? ICONS.other;
  const [imgFailed, setImgFailed] = useState(false);
  const hasIllust = showIllust && done && item.illustration_status === 'done' && !imgFailed;
  const room = item.evidence.find((e) => e.kind === 'room' && e.ref);

  return (
    <li className={cn('group rounded-xl border overflow-hidden bg-card transition-shadow', active && 'ring-2 ring-emerald-500/60', !done && 'border-dashed border-amber-400/60')}
        onMouseEnter={() => onHover(item.id)} onMouseLeave={() => onHover(null)}>
      {/* 画像 */}
      <div className={cn('relative aspect-[4/3] bg-muted/40 flex items-center justify-center', !showIllust && 'aspect-auto h-14')}>
        {hasIllust ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={api.achievements.illustrationUrl(item.id, item.updated_at)} alt="" className="absolute inset-0 w-full h-full object-cover" onError={() => setImgFailed(true)} />
        ) : showIllust && done && item.illustration_status === 'pending' ? (
          <Loader2 className="size-5 animate-spin text-muted-foreground" />
        ) : showIllust && done ? (
          <button type="button" className="text-xs text-muted-foreground flex flex-col items-center gap-1 hover:text-foreground" disabled={busy} onClick={onIllustrate} title="挿絵を生成 (約3円)">
            <ImageIcon className="size-6" />生成
          </button>
        ) : (
          <Icon className={cn('size-8', done ? 'text-emerald-500/70' : 'text-amber-400/70')} />
        )}
        {/* 時刻・種別バッジ */}
        <div className="absolute top-2 left-2 flex items-center gap-1.5">
          <span className={cn('inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium backdrop-blur',
            done ? 'bg-emerald-600/90 text-white' : 'bg-amber-500/90 text-black')}>
            <Icon className="size-3" />{fmtTime(itemTime(item))}
          </span>
          {!done && <span className="rounded-full bg-black/60 text-amber-300 px-2 py-0.5 text-[11px] backdrop-blur">進行中</span>}
          {item.tags.map((t) => <span key={t} className="rounded-full bg-black/60 text-white px-2 py-0.5 text-[11px] backdrop-blur">{t}</span>)}
        </div>
        {/* 操作 (hover) */}
        <div className="absolute top-2 right-2 flex gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
          {room && (
            <Button variant="secondary" size="icon" className="size-7" title={`部屋を開く: ${room.label}`}
              onClick={() => { selectProject(room.ref); router.push(`/chat/${room.ref}`); }}>
              <MessageSquare className="size-3.5" />
            </Button>
          )}
          {!done ? (
            <Button variant="secondary" size="icon" className="size-7" title="成果に昇格" disabled={busy} onClick={() => onPatch({ status: 'done' })}><ArrowUpCircle className="size-3.5" /></Button>
          ) : (
            <Button variant="secondary" size="icon" className="size-7" title="進行中に戻す" disabled={busy} onClick={() => onPatch({ status: 'in_progress' })}><Clock className="size-3.5" /></Button>
          )}
          <Button variant="secondary" size="icon" className="size-7" title="これは成果ではない (非表示)" disabled={busy} onClick={() => onPatch({ status: 'dismissed' })}><X className="size-3.5" /></Button>
        </div>
      </div>
      {/* 見出し */}
      <div className="px-3 py-2.5">
        <h3 className={cn('font-medium leading-snug text-[15px]', !done && 'text-foreground/75')} title={item.detail ?? undefined}>{item.title}</h3>
        <p className="text-[11px] text-muted-foreground mt-1">{label}</p>
      </div>
    </li>
  );
}

// ---------------------------------------------------------------- page

export default function TodayPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const user = useAuthStore((s) => s.user);
  const setUser = useAuthStore((s) => s.setUser);
  // サイドバーの部屋一覧はオーナー判定 (user.id) が要る。/chat 以外から直接開いた時も
  // ユーザー情報を読み込む (トークンはあるが user が未ロードのケース)。
  useEffect(() => {
    if (user) return;
    const t = typeof window !== 'undefined' ? localStorage.getItem('done-token') : null;
    if (!t) return;
    api.auth.me().then((u) => setUser(u)).catch(() => { /* 未ログインなら下の redirect に任せる */ });
  }, [user, setUser]);
  const hasToken = typeof window !== 'undefined' && !!localStorage.getItem('done-token');
  const [day, setDay] = useState<string | undefined>(undefined);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [showIllust, setShowIllust] = useState(true);

  useEffect(() => {
    if (!isAuthenticated && !hasToken) router.push('/login');
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAuthenticated, hasToken]);

  useEffect(() => {
    try { const v = localStorage.getItem(ILLUST_PREF_KEY); if (v !== null) setShowIllust(v === '1'); } catch { /* noop */ }
  }, []);
  const toggleIllust = () => {
    setShowIllust((v) => { try { localStorage.setItem(ILLUST_PREF_KEY, v ? '0' : '1'); } catch { /* noop */ } return !v; });
  };

  const q = useQuery({
    queryKey: ['achievements', day ?? 'today'],
    queryFn: () => api.achievements.list(day),
    refetchInterval: 30_000,
    refetchOnWindowFocus: true,
  });
  const data = q.data;
  const viewDay = data?.day ?? day;
  const isToday = !!data && data.day === data.today;

  useEffect(() => {
    if (data && day === undefined && data.day !== data.today) {
      queryClient.invalidateQueries({ queryKey: ['achievements'] });
    }
  }, [data, day, queryClient]);

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['achievements'] });
  const patch = useMutation({
    mutationFn: ({ id, p }: { id: string; p: Record<string, unknown> }) => api.achievements.patch(id, p),
    onSuccess: invalidate, onError: () => toast.error('更新に失敗しました'),
  });
  const illustrate = useMutation({
    mutationFn: (id: string) => api.achievements.illustrate(id),
    onSuccess: invalidate, onError: () => toast.error('挿絵の生成に失敗しました'),
  });
  const refresh = useMutation({
    mutationFn: () => api.achievements.refresh(),
    onSuccess: (r) => { invalidate(); toast.success(`再判定しました (${r.changed} 件更新)`); },
    onError: () => toast.error('再判定に失敗しました'),
  });

  const items = useMemo(() => {
    const list = (data?.items ?? []).filter((i) => i.status !== 'dismissed');
    return [...list].sort((a, b) => itemTime(a).localeCompare(itemTime(b)));
  }, [data]);
  const doneCount = items.filter((i) => i.status === 'done').length;

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
              成果 {doneCount} 件 ・ 進行中 {items.length - doneCount} 件
              {data?.last_run && <> ・ 最終判定 {fmtTime(data.last_run)}</>}
              {' '}・ 30秒ごとに自動更新、0時にリセット
            </p>
          </div>
          <div className="flex items-center gap-1">
            <Button variant={showIllust ? 'secondary' : 'ghost'} size="sm" onClick={toggleIllust} title="挿絵の表示/非表示">
              {showIllust ? <ImageIcon className="size-4" /> : <ImageOff className="size-4" />}
              <span className="ml-1">イラスト</span>
            </Button>
            <Button variant="ghost" size="icon" title="前日" onClick={() => viewDay && setDay(shiftDay(viewDay, -1))}>
              <ChevronLeft className="size-4" />
            </Button>
            <Button variant="ghost" size="icon" title="翌日" disabled={isToday} onClick={() => viewDay && setDay(shiftDay(viewDay, 1))}>
              <ChevronRight className="size-4" />
            </Button>
            {!isToday && <Button variant="outline" size="sm" onClick={() => setDay(undefined)}>今日へ</Button>}
            {isToday && (
              <Button variant="outline" size="sm" disabled={refresh.isPending} onClick={() => refresh.mutate()} title="今日の証拠を全部読み直して再判定">
                {refresh.isPending ? <Loader2 className="size-4 animate-spin" /> : <RefreshCw className="size-4" />}
                <span className="ml-1">再判定</span>
              </Button>
            )}
          </div>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-6">
          {q.isLoading ? (
            <div className="flex items-center gap-2 text-muted-foreground text-sm"><Loader2 className="size-4 animate-spin" />読み込み中…</div>
          ) : q.isError ? (
            <p className="text-sm text-destructive">読み込みに失敗しました。ダンコアが起動しているか確認してください。</p>
          ) : (
            <div className="flex gap-8 items-start">
              <div className="sticky top-0 shrink-0 hidden md:block">
                <DayClock items={items} isToday={isToday} activeId={activeId} onHover={setActiveId} />
                <p className="text-[11px] text-muted-foreground text-center mt-1">
                  <span className="inline-block size-2 rounded-full bg-emerald-500 mr-1 align-middle" />成果
                  <span className="inline-block size-2 rounded-full bg-amber-400 ml-3 mr-1 align-middle" />進行中
                </p>
              </div>
              <div className="flex-1 min-w-0">
                {items.length === 0 ? (
                  <p className="text-sm text-muted-foreground py-3">まだありません。作業が進むと自動で並びます。</p>
                ) : (
                  <ul className="grid gap-4 grid-cols-1 sm:grid-cols-2 xl:grid-cols-3">
                    {items.map((it) => (
                      <AchievementCard key={it.id} item={it} showIllust={showIllust} active={activeId === it.id} onHover={setActiveId}
                        busy={patch.isPending || illustrate.isPending}
                        onPatch={(p) => patch.mutate({ id: it.id, p })}
                        onIllustrate={() => illustrate.mutate(it.id)} />
                    ))}
                  </ul>
                )}
                <p className="text-[11px] text-muted-foreground mt-8">
                  判定基準: <code>~/.dan/workspace/ACHIEVEMENT_RULES.md</code>。直したら「再判定」。カードにマウスを乗せると 部屋を開く/昇格/戻す/非表示。見出しにマウスを乗せると詳細。挿絵は成果になった件だけ自動生成（1枚約3円）。
                </p>
              </div>
            </div>
          )}
        </div>
      </div>
    </MainLayout>
  );
}
