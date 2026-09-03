'use client';

import { useState, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';
import { toast } from 'sonner';
import { Plus, Users, User, Archive, Trash2, MessagesSquare } from 'lucide-react';
import { api, type CollabRoomResponse } from '@/lib/api-client';
import { useUnreadStore } from '@/stores/unread-store';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog';

// メッセンジャー流の時刻表示: 今日=HH:MM / 昨日 / 1週間以内=曜日 / それ以前=M/D
function formatListTime(dateStr?: string | null): string {
  if (!dateStr) return '';
  const d = new Date(dateStr);
  if (Number.isNaN(d.getTime())) return '';
  const now = new Date();
  if (d.toDateString() === now.toDateString()) {
    return d.toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit' });
  }
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (d.toDateString() === yesterday.toDateString()) return '昨日';
  if (now.getTime() - d.getTime() < 7 * 24 * 60 * 60 * 1000) {
    return ['日', '月', '火', '水', '木', '金', '土'][d.getDay()] + '曜日';
  }
  return `${d.getMonth() + 1}/${d.getDate()}`;
}

const AVATAR_GRADIENTS = [
  'from-sky-500 to-blue-600',
  'from-violet-500 to-purple-600',
  'from-emerald-500 to-teal-600',
  'from-amber-500 to-orange-500',
  'from-rose-500 to-pink-600',
  'from-indigo-500 to-blue-700',
];

function avatarGradient(seed: string): string {
  let h = 0;
  for (let i = 0; i < seed.length; i++) h = (h * 31 + seed.charCodeAt(i)) >>> 0;
  return AVATAR_GRADIENTS[h % AVATAR_GRADIENTS.length];
}

export default function CollabListPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [newTitle, setNewTitle] = useState('');
  const [newDescription, setNewDescription] = useState('');
  const [originRoomId, setOriginRoomId] = useState('');
  const [dialogOpen, setDialogOpen] = useState(false);

  const { data, isLoading } = useQuery({
    queryKey: ['collab-rooms'],
    queryFn: () => api.collab.listRooms(),
    refetchInterval: 15_000,
  });
  // 一覧の未読はサーバー判定に合わせる（別端末で読んだ分もここで消える）
  const syncFromServer = useUnreadStore((s) => s.syncFromServer);
  useEffect(() => {
    if (data) syncFromServer(data.rooms.filter((r) => r.unread).map((r) => r.id));
  }, [data, syncFromServer]);

  // 紐づけ先の候補（本体チャットのプロジェクト一覧）。紐づけるとダン自動対応が有効になる
  const { data: projectsData } = useQuery({
    queryKey: ['collab-link-projects'],
    queryFn: () => api.projects.list(),
    enabled: dialogOpen,
  });
  const linkableProjects = (projectsData?.projects ?? []).filter((p) => p.room_id);

  const createMutation = useMutation({
    mutationFn: (data: { title: string; description?: string; origin_chat_room_id?: string }) =>
      api.collab.createRoom(data),
    onSuccess: (room) => {
      queryClient.invalidateQueries({ queryKey: ['collab-rooms'] });
      setDialogOpen(false);
      setNewTitle('');
      setNewDescription('');
      setOriginRoomId('');
      router.push(`/collab/${room.id}`);
      toast.success('ルーム作成しました');
    },
    onError: () => toast.error('作成に失敗しました'),
  });

  const rooms = data?.rooms ?? [];

  return (
    <>
      <div className="flex-1 px-4 py-6 sm:p-6 max-w-3xl mx-auto w-full">
        <div className="flex items-center justify-between mb-5">
          <div>
            <h1 className="text-2xl font-bold tracking-tight">コミュニケーション</h1>
            <p className="text-muted-foreground text-sm mt-1">
              外部の相手との窓口。招待リンクを送るだけで相手はログイン不要で参加できます
            </p>
          </div>
          <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
            <DialogTrigger asChild>
              <Button className="shrink-0">
                <Plus className="h-4 w-4 mr-1.5" />
                新しいルーム
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>コラボルーム作成</DialogTitle>
              </DialogHeader>
              <div className="space-y-4 mt-2">
                <div>
                  <label className="text-sm font-medium">タイトル</label>
                  <Input
                    placeholder="例: バードSTC HPレビュー"
                    value={newTitle}
                    onChange={(e) => setNewTitle(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && newTitle.trim()) {
                        createMutation.mutate({ title: newTitle.trim(), description: newDescription.trim() || undefined, origin_chat_room_id: originRoomId || undefined });
                      }
                    }}
                  />
                </div>
                <div>
                  <label className="text-sm font-medium">説明 (任意)</label>
                  <Input
                    placeholder="例: トップページのデザイン確認"
                    value={newDescription}
                    onChange={(e) => setNewDescription(e.target.value)}
                  />
                </div>
                <div>
                  <label className="text-sm font-medium">ダンの担当チャット (任意)</label>
                  <select
                    value={originRoomId}
                    onChange={(e) => setOriginRoomId(e.target.value)}
                    className="mt-1 w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
                  >
                    <option value="">紐づけない（ただの共有チャット）</option>
                    {linkableProjects.map((p) => (
                      <option key={p.id} value={p.room_id as string}>{p.title}</option>
                    ))}
                  </select>
                  <p className="mt-1 text-xs text-muted-foreground">
                    紐づけると、相手の発言にダンが自動で対応します（作業・返信案の用意）
                  </p>
                </div>
                <Button
                  className="w-full"
                  onClick={() => createMutation.mutate({ title: newTitle.trim(), description: newDescription.trim() || undefined, origin_chat_room_id: originRoomId || undefined })}
                  disabled={!newTitle.trim() || createMutation.isPending}
                >
                  作成
                </Button>
              </div>
            </DialogContent>
          </Dialog>
        </div>

        {isLoading ? (
          <div className="rounded-2xl border bg-card overflow-hidden">
            {[0, 1, 2].map((i) => (
              <div key={i} className="flex items-center gap-3 px-4 py-4 animate-pulse">
                <div className="h-12 w-12 rounded-full bg-muted shrink-0" />
                <div className="flex-1 space-y-2">
                  <div className="h-3.5 w-1/3 rounded bg-muted" />
                  <div className="h-3 w-2/3 rounded bg-muted/70" />
                </div>
              </div>
            ))}
          </div>
        ) : rooms.length === 0 ? (
          <div className="rounded-2xl border border-dashed bg-card/50 flex flex-col items-center justify-center py-16 px-6 text-center">
            <div className="h-14 w-14 rounded-2xl bg-primary/10 flex items-center justify-center mb-4">
              <MessagesSquare className="h-7 w-7 text-primary" />
            </div>
            <p className="font-medium mb-1">まだ窓口がありません</p>
            <p className="text-sm text-muted-foreground mb-5 max-w-sm">
              ルームを作って招待リンクを相手に送るだけ。相手はログイン不要で、スマホならアプリのように使えます
            </p>
            <Button onClick={() => setDialogOpen(true)}>
              <Plus className="h-4 w-4 mr-1.5" />
              最初のルームを作成
            </Button>
          </div>
        ) : (
          <div className="rounded-2xl border bg-card overflow-hidden divide-y divide-border/60">
            {rooms.map((room) => (
              <RoomRow
                key={room.id}
                room={room}
                onClick={() => router.push(`/collab/${room.id}`)}
                onDelete={() => {
                  if (confirm(`「${room.title}」を削除しますか？メッセージも全て削除されます。`)) {
                    api.collab.deleteRoom(room.id).then(() => {
                      queryClient.invalidateQueries({ queryKey: ['collab-rooms'] });
                      toast.success('ルームを削除しました');
                    }).catch(() => toast.error('削除に失敗しました'));
                  }
                }}
              />
            ))}
          </div>
        )}
      </div>
    </>
  );
}

function RoomRow({ room, onClick, onDelete }: { room: CollabRoomResponse; onClick: () => void; onDelete: () => void }) {
  const isUnread = useUnreadStore((s) => s.unreadRooms.has(room.id));
  const markRead = useUnreadStore((s) => s.markRead);

  const handleClick = () => {
    markRead(room.id);
    onClick();
  };

  const time = formatListTime(room.last_message_at || room.updated_at);

  return (
    <div
      role="button"
      tabIndex={0}
      className="w-full flex items-center gap-3.5 px-4 py-3.5 text-left cursor-pointer hover:bg-accent/40 active:bg-accent/60 transition-colors group"
      onClick={handleClick}
      onKeyDown={(e) => { if (e.key === 'Enter') handleClick(); }}
    >
      {/* アバター（タイトル頭文字 + ID由来の固定グラデーション） */}
      <div className="relative shrink-0">
        <div className={`h-12 w-12 rounded-full bg-gradient-to-br ${avatarGradient(room.id)} flex items-center justify-center shadow-sm`}>
          <User className="h-6 w-6 text-white/90" />
        </div>
        {(isUnread || (room.unread_count ?? 0) > 0) && (
          <span className="absolute -top-1 -right-1 min-w-[18px] h-[18px] px-1 rounded-full bg-primary text-primary-foreground text-[10px] font-bold leading-[18px] text-center ring-2 ring-card tabular-nums">
            {(room.unread_count ?? 0) > 99 ? '99+' : (room.unread_count ?? 0) > 0 ? room.unread_count : ''}
          </span>
        )}
      </div>

      <div className="flex-1 min-w-0">
        <div className="flex items-baseline justify-between gap-2">
          <div className="flex items-center gap-1.5 min-w-0">
            <span className={`truncate text-[15px] ${isUnread ? 'font-bold' : 'font-semibold'}`}>
              {room.title}
            </span>
            {room.status === 'archived' && (
              <Archive className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
            )}
          </div>
          <span className={`text-xs shrink-0 tabular-nums ${isUnread ? 'text-primary font-semibold' : 'text-muted-foreground'}`}>
            {time}
          </span>
        </div>
        <div className="flex items-center justify-between gap-2 mt-0.5">
          <p className={`text-sm truncate ${isUnread ? 'text-foreground' : 'text-muted-foreground'}`}>
            {room.last_message || (
              <span className="italic text-muted-foreground/70">まだメッセージはありません</span>
            )}
          </p>
          <span className="flex items-center gap-2 shrink-0">
            {room.guest_count > 0 && (
              <span className="flex items-center gap-1 text-xs text-muted-foreground bg-muted/70 rounded-full px-2 py-0.5">
                <Users className="h-3 w-3" />
                {room.guest_count}
              </span>
            )}
            <button
              onClick={(e) => { e.stopPropagation(); onDelete(); }}
              className="p-1.5 rounded-md text-muted-foreground/60 opacity-0 group-hover:opacity-100 focus:opacity-100 hover:bg-destructive/10 hover:text-destructive transition-all"
              aria-label="ルームを削除"
            >
              <Trash2 className="h-4 w-4" />
            </button>
          </span>
        </div>
      </div>
    </div>
  );
}
