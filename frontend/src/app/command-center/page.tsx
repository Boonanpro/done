'use client';

import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api-client';
import { ProjectChatPanel } from '@/components/layout/project-chat-panel';

export default function CommandCenterPage() {
  const projects = useQuery({ queryKey: ['projects'], queryFn: () => api.projects.list() });
  const hub = projects.data?.projects.find(p => p.metadata?.role === 'command_center');
  const device = useQuery({ queryKey: ['command-center-device'], queryFn: api.commandCenter.device, refetchInterval: 5000 });
  return <div className="flex h-full min-h-0 flex-col bg-background">
    <header className="shrink-0 border-b border-border/60 bg-muted/20 px-5 pb-5 pt-16 md:px-8 md:pt-6">
      <h1 className="text-3xl font-semibold tracking-tight">Done</h1>
      <p className="mt-2 text-sm text-muted-foreground">プロジェクトの確認も、ちょっとした頼みごとも。</p>
      <p className="mt-3 text-xs text-muted-foreground" role="status">Atom · {device.isLoading ? '接続を確認中' : !device.data?.connected ? '未接続' : device.data.room_id !== hub?.room_id ? '別の部屋に接続中' : !device.data.requested ? 'ヘイダンの呼びかけ待ち' : device.data.state === 'connected' ? '会話中' : '接続しています'}</p>
    </header>
    <section aria-label="Doneとの会話" className="min-h-0 min-w-0 flex-1">
      {hub ? <ProjectChatPanel projectId={hub.id} commandCenter /> : <p className="p-8 text-sm text-muted-foreground">{projects.isError ? 'Doneを取得できませんでした。ページを再読み込みしてください。' : projects.isLoading ? '読み込み中…' : 'Doneがまだ設定されていません。'}</p>}
    </section>
  </div>;
}
