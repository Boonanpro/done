'use client';

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';
import { toast } from 'sonner';
import { Plus, Users, MessageSquare, Clock, Archive, Copy, Link2, Trash2 } from 'lucide-react';
import { api, type CollabRoomResponse } from '@/lib/api-client';
import { useUnreadStore } from '@/stores/unread-store';
import { MainLayout } from '@/components/layout/main-layout';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog';

function formatRelativeTime(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime();
  const minutes = Math.floor(diff / 60000);
  if (minutes < 1) return 'たった今';
  if (minutes < 60) return `${minutes}分前`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}時間前`;
  const days = Math.floor(hours / 24);
  return `${days}日前`;
}

export default function CollabListPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [newTitle, setNewTitle] = useState('');
  const [newDescription, setNewDescription] = useState('');
  const [dialogOpen, setDialogOpen] = useState(false);

  const { data, isLoading } = useQuery({
    queryKey: ['collab-rooms'],
    queryFn: () => api.collab.listRooms(),
  });

  const createMutation = useMutation({
    mutationFn: (data: { title: string; description?: string }) =>
      api.collab.createRoom(data),
    onSuccess: (room) => {
      queryClient.invalidateQueries({ queryKey: ['collab-rooms'] });
      setDialogOpen(false);
      setNewTitle('');
      setNewDescription('');
      router.push(`/collab/${room.id}`);
      toast.success('ルーム作成しました');
    },
    onError: () => toast.error('作成に失敗しました'),
  });

  const rooms = data?.rooms ?? [];

  return (
    <MainLayout showNotifications={false}>
    <div className="flex-1 p-6 max-w-4xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold">コミュニケーション</h1>
          <p className="text-muted-foreground text-sm mt-1">
            友人やクライアントとコラボレーション
          </p>
        </div>
        <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
          <DialogTrigger asChild>
            <Button>
              <Plus className="h-4 w-4 mr-2" />
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
                      createMutation.mutate({ title: newTitle.trim(), description: newDescription.trim() || undefined });
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
              <Button
                className="w-full"
                onClick={() => createMutation.mutate({ title: newTitle.trim(), description: newDescription.trim() || undefined })}
                disabled={!newTitle.trim() || createMutation.isPending}
              >
                作成
              </Button>
            </div>
          </DialogContent>
        </Dialog>
      </div>

      {isLoading ? (
        <div className="text-center py-12 text-muted-foreground">読み込み中...</div>
      ) : rooms.length === 0 ? (
        <Card className="border-dashed">
          <CardContent className="flex flex-col items-center justify-center py-12">
            <Users className="h-12 w-12 text-muted-foreground mb-4" />
            <p className="text-muted-foreground mb-2">まだルームがありません</p>
            <p className="text-sm text-muted-foreground mb-4">
              コラボルームを作成して、招待リンクをLINEで共有しましょう
            </p>
            <Button onClick={() => setDialogOpen(true)}>
              <Plus className="h-4 w-4 mr-2" />
              最初のルームを作成
            </Button>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-3">
          {rooms.map((room) => (
            <RoomCard
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
    </MainLayout>
  );
}

function RoomCard({ room, onClick, onDelete }: { room: CollabRoomResponse; onClick: () => void; onDelete: () => void }) {
  const isUnread = useUnreadStore((s) => s.unreadRooms.has(room.id));
  const markRead = useUnreadStore((s) => s.markRead);

  const handleClick = () => {
    markRead(room.id);
    onClick();
  };

  return (
    <Card
      className={`cursor-pointer hover:bg-accent/50 transition-colors ${isUnread ? 'border-primary/50 bg-primary/5' : ''}`}
      onClick={handleClick}
    >
      <CardContent className="flex items-center gap-4 py-4">
        <div className={`h-10 w-10 rounded-full flex items-center justify-center shrink-0 ${isUnread ? 'bg-primary/20' : 'bg-primary/10'}`}>
          <MessageSquare className={`h-5 w-5 ${isUnread ? 'text-primary' : 'text-primary'}`} />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <h3 className={`truncate ${isUnread ? 'font-bold' : 'font-medium'}`}>{room.title}</h3>
            {isUnread && (
              <span className="h-2.5 w-2.5 rounded-full bg-primary shrink-0" />
            )}
            {room.status === 'archived' && (
              <Archive className="h-3.5 w-3.5 text-muted-foreground" />
            )}
          </div>
          {room.last_message && (
            <p className={`text-sm truncate ${isUnread ? 'text-foreground font-medium' : 'text-muted-foreground'}`}>{room.last_message}</p>
          )}
          {room.description && !room.last_message && (
            <p className="text-sm text-muted-foreground truncate">{room.description}</p>
          )}
        </div>
        <div className="flex items-center gap-3 text-sm text-muted-foreground shrink-0">
          <div className="flex items-center gap-1">
            <Users className="h-3.5 w-3.5" />
            <span>{room.guest_count}</span>
          </div>
          <span>{formatRelativeTime(room.updated_at)}</span>
          <button
            onClick={(e) => { e.stopPropagation(); onDelete(); }}
            className="p-1 rounded hover:bg-destructive/10 hover:text-destructive transition-colors"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
      </CardContent>
    </Card>
  );
}
