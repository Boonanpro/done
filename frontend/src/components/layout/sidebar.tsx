'use client';

import { useState, useRef, useEffect, useSyncExternalStore } from 'react';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { motion, AnimatePresence } from 'framer-motion';
import { MessageSquare, Users, Settings, LogOut, Search, ChevronLeft, ChevronRight, ChevronDown, Loader2, FolderKanban, FileEdit, Plus, Pencil, Clapperboard, LayoutDashboard, Notebook, Zap, Pin, PinOff, Trash2, MoreVertical } from 'lucide-react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';

import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Separator } from '@/components/ui/separator';
import { Avatar, AvatarFallback, AvatarImage } from '@/components/ui/avatar';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { useAuth } from '@/hooks/use-auth';
import { api, OWNER_USER_ID, type ProjectResponse } from '@/lib/api-client';
import { useUnreadStore } from '@/stores/unread-store';
import { useProjectStore } from '@/stores/project-store';
import { usePreviewStore } from '@/stores/preview-store';
import { useIsMobile } from '@/hooks/useIsMobile';
import { NotificationPanel } from '@/components/notification/notification-panel';

function useHasToken() {
  return useSyncExternalStore(
    () => () => {},
    () => !!localStorage.getItem('done-token'),
    () => false
  );
}


const navItems = [
  {
    title: 'チャット',
    href: '/chat',
    icon: MessageSquare,
    description: 'ダンとの会話',
  },
  {
    title: 'コミュニケーション',
    href: '/collab',
    icon: Users,
    description: 'コラボルーム・外部連携',
  },
  {
    title: 'ダン用Notion',
    href: '/dan-notion',
    icon: Notebook,
    description: '情報管理 + 自律エージェント',
  },
  {
    title: '設定',
    href: '/settings',
    icon: Settings,
    description: 'アカウント設定',
  },
];

interface SidebarProps {
  className?: string;
  isCollapsed: boolean;
  onToggleCollapse: () => void;
  showNotifications?: boolean;
}

export function Sidebar({
  className,
  isCollapsed,
  onToggleCollapse,
  showNotifications = false,
}: SidebarProps) {
  const pathname = usePathname();
  const router = useRouter();
  const { user, logout, isLoggingOut } = useAuth();
  const [searchQuery, setSearchQuery] = useState('');
  const [showAllProjects, setShowAllProjects] = useState(false);
  // 新チャットで使う Claude モデル（既定: opus）。Fable トライアル用トグル。
  const [selectedModel, setSelectedModel] = useState<'opus' | 'fable'>('opus');
  const PROJECT_DISPLAY_LIMIT = 5;
  const [editingProjectId, setEditingProjectId] = useState<string | null>(null);
  const [editingTitle, setEditingTitle] = useState('');
  const editInputRef = useRef<HTMLInputElement>(null);
  const hasToken = useHasToken();
  const isMobile = useIsMobile();
  const queryClient = useQueryClient();

  const selectedProjectId = useProjectStore((s) => s.selectedProjectId);
  const selectProject = useProjectStore((s) => s.selectProject);
  const isOwner = user?.id === OWNER_USER_ID;
  const unreadCount = useUnreadStore((s) => s.unreadRooms.size);

  const createProjectMutation = useMutation({
    mutationFn: (payload: { title: string; description?: string; model?: string }) => api.projects.create(payload),
    onSuccess: (project) => {
      queryClient.invalidateQueries({ queryKey: ['projects'] });
      selectProject(project.id);
      router.push(`/chat/${project.id}`);
    },
    onError: () => {
      toast.error('プロジェクト作成に失敗しました');
    },
  });

  const renameMutation = useMutation({
    mutationFn: ({ id, title }: { id: string; title: string }) => api.projects.update(id, { title }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['projects'] });
      setEditingProjectId(null);
    },
    onError: () => {
      toast.error('タイトルの更新に失敗しました');
      setEditingProjectId(null);
    },
  });

  const iconMutation = useMutation({
    mutationFn: ({ id, icon }: { id: string; icon: string }) => api.projects.update(id, { icon }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['projects'] });
      setEmojiPickerProjectId(null);
    },
  });

  const pinMutation = useMutation({
    mutationFn: ({ id, pinned }: { id: string; pinned: boolean }) =>
      api.projects.update(id, { pinned }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['projects'] });
    },
    onError: () => {
      toast.error('ピン留めの更新に失敗しました');
    },
  });

  const deleteProjectMutation = useMutation({
    mutationFn: (id: string) => api.projects.delete(id),
    onSuccess: (_, deletedId) => {
      queryClient.invalidateQueries({ queryKey: ['projects'] });
      // 削除したチャットを開いていたら閉じる
      if (selectedProjectId === deletedId) {
        selectProject(null);
        router.push('/chat');
      }
      toast.success('チャットを削除しました');
    },
    onError: () => {
      toast.error('チャットの削除に失敗しました');
    },
  });

  const [emojiPickerProjectId, setEmojiPickerProjectId] = useState<string | null>(null);
  const emojiPickerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!emojiPickerProjectId) return;
    const handler = (e: MouseEvent) => {
      if (emojiPickerRef.current && !emojiPickerRef.current.contains(e.target as Node)) {
        setEmojiPickerProjectId(null);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [emojiPickerProjectId]);

  const EMOJI_OPTIONS = [
    '📁', '📂', '📊', '📈', '💼', '🏗️', '🌐', '🎯', '🚀', '💡',
    '📝', '📋', '🔧', '⚙️', '🎨', '🏠', '🏢', '🛒', '📱', '💻',
    '⚾', '🎵', '📷', '🎬', '📚', '✈️', '🍽️', '🏥', '🎓', '🔬',
    '💰', '📮', '🗂️', '🔑', '🛠️', '🎪', '🌟', '🎁', '🤖', '🧩',
  ];

  const handleStartEdit = (e: React.MouseEvent, project: ProjectResponse) => {
    e.stopPropagation();
    setEditingProjectId(project.id);
    setEditingTitle(project.title);
    setTimeout(() => editInputRef.current?.select(), 0);
  };

  const handleConfirmEdit = (project: ProjectResponse) => {
    const trimmed = editingTitle.trim();
    if (trimmed && trimmed !== project.title) {
      renameMutation.mutate({ id: project.id, title: trimmed });
    } else {
      setEditingProjectId(null);
    }
  };

  const { data: projectsData, isLoading: isLoadingProjects } = useQuery({
    queryKey: ['projects'],
    queryFn: () => api.projects.list(),
    // localStorage gate を撤廃。Cookie 認証でも projects を取得できるようにする。
    // 未認証なら api-client の request() が 401 → /login で処理する。
    enabled: true,
    staleTime: 5 * 1000,
    refetchInterval: 10 * 1000,
  });

  // 「作業中」のチャットは開かれる前に中身を先読みしておく。開いた瞬間に
  // キャッシュから完成形（メッセージ＋run状態＋作業イベント）を一発描画
  // するため。prefetchQuery は staleTime 内なら何もしないので、10秒ごとの
  // 一覧ポーリングで無駄な再取得は走らない。メッセージだけはキャッシュが
  // 既にある場合スキップ必須: チャットパネルはSSE直挿入行をキャッシュ上で
  // 一方通行マージしており、素のスナップショットで上書きすると最新回答が
  // 数秒消える既知バグが再発する。
  useEffect(() => {
    const activeProjects = (projectsData?.projects ?? []).filter((p) => p.has_active_run).slice(0, 5);
    for (const p of activeProjects) {
      queryClient.prefetchQuery({
        queryKey: ['current-run', p.id],
        queryFn: () => api.projects.currentRun(p.id),
        staleTime: 5 * 1000,
      });
      queryClient.prefetchQuery({
        queryKey: ['execution-events', p.id],
        queryFn: () => api.projects.executionEvents.list(p.id, 500),
        staleTime: 15 * 1000,
      });
      const roomId = p.room_id;
      if (roomId && !queryClient.getQueryData(['project-messages', roomId])) {
        queryClient.prefetchQuery({
          queryKey: ['project-messages', roomId],
          queryFn: () => api.rooms.getMessages(roomId, { limit: 50 }),
          staleTime: 15 * 1000,
        });
      }
    }
  }, [projectsData, queryClient]);

  const filteredProjects = projectsData?.projects?.filter((p) =>
    p.title.toLowerCase().includes(searchQuery.toLowerCase())
  ) ?? [];
  const handleProjectClick = (project: ProjectResponse) => {
    if (project.id === selectedProjectId) {
      selectProject(null);
      router.push('/chat');
    } else {
      selectProject(project.id);
      router.push(`/chat/${project.id}`);
      if (isMobile) {
        onToggleCollapse();
      }
    }
  };

  const handleInstantCreate = () => {
    if (!createProjectMutation.isPending) {
      createProjectMutation.mutate({ title: '新しいプロジェクト', model: selectedModel });
    }
  };

  const handleLogout = async () => {
    try {
      await logout();
      // 幽霊プレビュー防止: ログアウト時に preview state を完全リセット
      usePreviewStore.getState().closePreview();
      router.push('/login');
    } catch {
      toast.error('ログアウトに失敗しました');
    }
  };

  const formatRelativeTime = (dateString: string | null | undefined) => {
    if (!dateString) return '';
    const date = new Date(dateString);
    const now = new Date();
    const diff = now.getTime() - date.getTime();
    const minutes = Math.floor(diff / (1000 * 60));
    const hours = Math.floor(diff / (1000 * 60 * 60));
    const days = Math.floor(diff / (1000 * 60 * 60 * 24));

    if (minutes < 1) return '今';
    if (minutes < 60) return `${minutes}分前`;
    if (hours < 24) return `${hours}時間前`;
    if (days < 7) return `${days}日前`;
    return date.toLocaleDateString('ja-JP', { month: 'short', day: 'numeric' });
  };

  return (
    <TooltipProvider delayDuration={0}>
      <div
        className={cn(
          'relative flex flex-col h-full w-full overflow-hidden bg-sidebar border-r border-sidebar-border',
          className
        )}
      >
        {/* Header */}
        <div className="flex items-center h-14 px-3 border-b border-sidebar-border">
          <AnimatePresence mode="wait">
            {!isCollapsed && (
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                className="flex items-center gap-2"
              >
                <div className="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center">
                  <span className="text-lg font-bold text-primary">D</span>
                </div>
                <span className="font-semibold text-sidebar-foreground">Done</span>
              </motion.div>
            )}
          </AnimatePresence>

          <div className={cn("flex items-center gap-1", isCollapsed ? "mx-auto" : "ml-auto")}>
            <Button
              variant="ghost"
              size="icon"
              className="h-8 w-8 text-sidebar-foreground hover:bg-sidebar-accent"
              onClick={onToggleCollapse}
            >
              {isCollapsed ? (
                <ChevronRight className="h-4 w-4" />
              ) : (
                <ChevronLeft className="h-4 w-4" />
              )}
            </Button>
          </div>
        </div>

        {/* Search */}
        <AnimatePresence>
          {!isCollapsed && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              exit={{ opacity: 0, height: 0 }}
              className="px-3 py-3"
            >
              <div className="relative">
                <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                <Input
                  placeholder="プロジェクトを検索..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="pl-8 h-9 bg-sidebar-accent/30 border-sidebar-border text-sm"
                />
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        <Separator className="bg-sidebar-border" />

        {/* Project List */}
        <ScrollArea className="flex-1 min-h-0 px-3 py-2">
          {isOwner && !isCollapsed && (
            <>
              <div className="flex items-center justify-between gap-2 px-2 py-1.5 text-xs text-muted-foreground font-medium">
                <div className="flex items-center gap-2">
                  <FolderKanban className="h-3 w-3" />
                  <span>プロジェクト</span>
                </div>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="h-6 w-6 text-muted-foreground hover:text-sidebar-foreground"
                  onClick={handleInstantCreate}
                  disabled={createProjectMutation.isPending}
                >
                  {createProjectMutation.isPending ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Plus className="h-3.5 w-3.5" />
                  )}
                </Button>
              </div>
              {/* 新チャットのモデル選択（Fable トライアル用）。+ を押すと選択中のモデルで作成される */}
              <div className="flex items-center gap-1 px-2 pb-1.5">
                <span className="text-[10px] text-muted-foreground mr-1">新規:</span>
                <div className="inline-flex rounded-md border border-sidebar-border overflow-hidden">
                  {(['opus', 'fable'] as const).map((m) => (
                    <button
                      key={m}
                      type="button"
                      onClick={() => setSelectedModel(m)}
                      className={`px-2 py-0.5 text-[10px] font-medium transition-colors ${
                        selectedModel === m
                          ? 'bg-sidebar-accent text-sidebar-foreground'
                          : 'text-muted-foreground hover:text-sidebar-foreground'
                      }`}
                      title={m === 'opus' ? 'Opus（標準・速い）' : 'Fable（高性能・やや遅い／トライアル中）'}
                    >
                      {m === 'opus' ? 'Opus' : 'Fable'}
                    </button>
                  ))}
                </div>
              </div>
            </>
          )}

          <nav className="space-y-1">
            {!isOwner ? null : isLoadingProjects ? (
              <div className="flex items-center justify-center py-4">
                <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
              </div>
            ) : filteredProjects.length === 0 ? (
              !isCollapsed && (
                <p className="text-xs text-muted-foreground text-center py-4">
                  プロジェクトはありません
                </p>
              )
            ) : (
              <>
              {(searchQuery ? filteredProjects : (showAllProjects ? filteredProjects : filteredProjects.slice(0, PROJECT_DISPLAY_LIMIT))).map((project) => {
                const isActive = project.id === selectedProjectId;

                return (
                  <Tooltip key={project.id}>
                    <TooltipTrigger asChild>
                      <motion.div
                        whileHover={{ scale: 1 }}
                        whileTap={{ scale: 1 }}
                        className={cn(
                          'group w-full flex items-center gap-2 px-3 py-2 rounded-lg text-sm transition-colors text-left cursor-pointer',
                          isActive
                            ? 'bg-sidebar-accent text-sidebar-accent-foreground'
                            : 'text-sidebar-foreground/70 hover:bg-sidebar-accent/50 hover:text-sidebar-foreground',
                          isCollapsed && 'justify-center px-0'
                        )}
                        onClick={() => editingProjectId !== project.id && handleProjectClick(project)}
                      >
                        <div className="relative shrink-0">
                          <button
                            className="text-base leading-none hover:scale-110 transition-transform"
                            onClick={(e) => {
                              e.stopPropagation();
                              setEmojiPickerProjectId(emojiPickerProjectId === project.id ? null : project.id);
                            }}
                            title="アイコンを変更"
                          >
                            {project.icon || '📁'}
                          </button>
                          {project.has_active_run && (
                            <span
                              className="absolute -top-0.5 -right-1 flex h-2.5 w-2.5 pointer-events-none"
                              title="ダンが作業中"
                            >
                              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
                              <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-emerald-500" />
                            </span>
                          )}
                          {emojiPickerProjectId === project.id && (
                            <div
                              ref={emojiPickerRef}
                              className="absolute top-7 left-0 z-50 bg-popover border border-border rounded-lg shadow-lg p-2 w-[220px]"
                              onClick={(e) => e.stopPropagation()}
                            >
                              <div className="grid grid-cols-8 gap-1">
                                {EMOJI_OPTIONS.map((emoji) => (
                                  <button
                                    key={emoji}
                                    className="h-7 w-7 flex items-center justify-center rounded hover:bg-accent text-base"
                                    onClick={() => iconMutation.mutate({ id: project.id, icon: emoji })}
                                  >
                                    {emoji}
                                  </button>
                                ))}
                              </div>
                            </div>
                          )}
                        </div>
                        {!isCollapsed && (
                          <div className="flex-1 min-w-0 flex items-center gap-1">
                            {editingProjectId === project.id ? (
                              <input
                                ref={editInputRef}
                                className="flex-1 min-w-0 bg-transparent border-b border-primary text-sm outline-none py-0.5"
                                value={editingTitle}
                                onClick={(e) => e.stopPropagation()}
                                onChange={(e) => setEditingTitle(e.target.value)}
                                onKeyDown={(e) => {
                                  if (e.key === 'Enter') { e.preventDefault(); handleConfirmEdit(project); }
                                  if (e.key === 'Escape') setEditingProjectId(null);
                                }}
                                onBlur={() => handleConfirmEdit(project)}
                                autoFocus
                              />
                            ) : (
                              <>
                                <div className="flex-1 min-w-0">
                                  <div className="flex items-center gap-1.5">
                                    {project.pinned_at && (
                                      <Pin className="h-3 w-3 shrink-0 text-muted-foreground/70 fill-current" />
                                    )}
                                    <p className="truncate">{project.title}</p>
                                  </div>
                                  <p className="text-xs text-muted-foreground truncate">
                                    {project.has_active_run ? (
                                      <span className="animate-pulse font-medium text-emerald-500">ダンが作業中…</span>
                                    ) : (
                                      formatRelativeTime(project.last_message_at || project.updated_at || project.created_at)
                                    )}
                                  </p>
                                </div>
                                {(project.unread_count || 0) > 0 && (
                                  <span className="shrink-0 min-w-5 h-5 px-1.5 rounded-full bg-red-500 text-[10px] font-bold leading-5 text-white text-center">
                                    {project.unread_count > 99 ? '99+' : project.unread_count}
                                  </span>
                                )}
                                <DropdownMenu>
                                  <DropdownMenuTrigger asChild>
                                    <button
                                      className="shrink-0 p-1 rounded transition-opacity opacity-0 group-hover:opacity-100 hover:bg-accent/50"
                                      onClick={(e) => e.stopPropagation()}
                                      title="メニュー"
                                    >
                                      <MoreVertical className="h-3.5 w-3.5 text-muted-foreground" />
                                    </button>
                                  </DropdownMenuTrigger>
                                  <DropdownMenuContent
                                    align="end"
                                    onClick={(e) => e.stopPropagation()}
                                  >
                                    <DropdownMenuItem
                                      onClick={() =>
                                        pinMutation.mutate({ id: project.id, pinned: !project.pinned_at })
                                      }
                                    >
                                      {project.pinned_at ? (
                                        <>
                                          <PinOff className="h-4 w-4 mr-2" />
                                          ピン留めを外す
                                        </>
                                      ) : (
                                        <>
                                          <Pin className="h-4 w-4 mr-2" />
                                          ピン留めして上部に固定
                                        </>
                                      )}
                                    </DropdownMenuItem>
                                    <DropdownMenuItem onClick={(e) => handleStartEdit(e as unknown as React.MouseEvent, project)}>
                                      <Pencil className="h-4 w-4 mr-2" />
                                      名前を変更
                                    </DropdownMenuItem>
                                    <DropdownMenuSeparator />
                                    <DropdownMenuItem
                                      className="text-red-500 focus:text-red-500"
                                      onClick={() => {
                                        if (window.confirm(`「${project.title}」を削除しますか？この操作は取り消せません。`)) {
                                          deleteProjectMutation.mutate(project.id);
                                        }
                                      }}
                                    >
                                      <Trash2 className="h-4 w-4 mr-2" />
                                      削除
                                    </DropdownMenuItem>
                                  </DropdownMenuContent>
                                </DropdownMenu>
                              </>
                            )}
                          </div>
                        )}
                      </motion.div>
                    </TooltipTrigger>
                    {isCollapsed && (
                      <TooltipContent side="right">
                        <p className="font-medium">{project.icon || '📁'} {project.title}</p>
                      </TooltipContent>
                    )}
                  </Tooltip>
                );
              })}
              {!isCollapsed && !searchQuery && filteredProjects.length > PROJECT_DISPLAY_LIMIT && (
                <button
                  className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-muted-foreground hover:text-sidebar-foreground transition-colors"
                  onClick={() => setShowAllProjects(!showAllProjects)}
                >
                  <ChevronDown className={cn('h-3 w-3 transition-transform', showAllProjects && 'rotate-180')} />
                  <span>{showAllProjects ? '折りたたむ' : `他${filteredProjects.length - PROJECT_DISPLAY_LIMIT}件を表示`}</span>
                </button>
              )}
              </>
            )}
          </nav>

          <Separator className="my-3 bg-sidebar-border" />

          <nav className="space-y-1">
            {/* チャット (owner only) */}
            {isOwner && navItems.filter(item => item.href === '/chat').map((item) => {
              const isActive = pathname.startsWith(item.href);
              const Icon = item.icon;
              return (
                <Tooltip key={item.href}>
                  <TooltipTrigger asChild>
                    <Link
                      href={item.href}
                      onClick={() => { if (isMobile) selectProject(null); }}
                    >
                      <motion.div
                        whileHover={{ scale: 1.02 }}
                        whileTap={{ scale: 0.98 }}
                        className={cn(
                          'flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors',
                          isActive
                            ? 'bg-sidebar-accent text-sidebar-accent-foreground'
                            : 'text-sidebar-foreground/70 hover:bg-sidebar-accent/50 hover:text-sidebar-foreground',
                          isCollapsed && 'justify-center px-0'
                        )}
                      >
                        <div className="relative shrink-0">
                          <Icon className="h-4 w-4" />
                        </div>
                        {!isCollapsed && (
                          <span className="flex min-w-0 flex-1 items-center justify-between gap-2">
                            <span className="truncate">{item.title}</span>
                          </span>
                        )}
                      </motion.div>
                    </Link>
                  </TooltipTrigger>
                  {isCollapsed && (
                    <TooltipContent side="right">
                      <p className="font-medium">{item.title}</p>
                      <p className="text-xs text-muted-foreground">{item.description}</p>
                    </TooltipContent>
                  )}
                </Tooltip>
              );
            })}

            {/* コミュニケーション・連絡先・ダン用Notion・設定 */}
            {navItems.filter(item => item.href !== '/chat').map((item) => {
              const isActive = pathname.startsWith(item.href);
              const Icon = item.icon;
              const showBadge = item.href === '/collab' && unreadCount > 0;
              const openInNewTab = item.href === '/dan-notion';
              const LinkWrapper = openInNewTab
                ? ({ children }: { children: React.ReactNode }) => (
                    <a href={item.href} target="_blank" rel="noopener noreferrer">
                      {children}
                    </a>
                  )
                : ({ children }: { children: React.ReactNode }) => (
                    <Link href={item.href}>{children}</Link>
                  );
              return (
                <Tooltip key={item.href}>
                  <TooltipTrigger asChild>
                    <LinkWrapper>
                      <motion.div
                        whileHover={{ scale: 1.02 }}
                        whileTap={{ scale: 0.98 }}
                        className={cn(
                          'flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors',
                          isActive
                            ? 'bg-sidebar-accent text-sidebar-accent-foreground'
                            : 'text-sidebar-foreground/70 hover:bg-sidebar-accent/50 hover:text-sidebar-foreground',
                          isCollapsed && 'justify-center px-0'
                        )}
                      >
                        <div className="relative shrink-0">
                          <Icon className="h-4 w-4" />
                          {showBadge && (
                            <span className="absolute -top-1.5 -right-1.5 h-4 min-w-4 flex items-center justify-center rounded-full bg-destructive text-destructive-foreground text-[10px] font-bold px-1">
                              {unreadCount}
                            </span>
                          )}
                        </div>
                        {!isCollapsed && <span className="flex-1">{item.title}</span>}
                        {!isCollapsed && showBadge && (
                          <span className="h-5 min-w-5 flex items-center justify-center rounded-full bg-destructive text-destructive-foreground text-[10px] font-bold px-1.5">
                            {unreadCount}
                          </span>
                        )}
                      </motion.div>
                    </LinkWrapper>
                  </TooltipTrigger>
                  {isCollapsed && (
                    <TooltipContent side="right">
                      <p className="font-medium">{item.title}</p>
                      <p className="text-xs text-muted-foreground">{item.description}</p>
                    </TooltipContent>
                  )}
                </Tooltip>
              );
            })}
          </nav>
        </ScrollArea>

        {/* Notifications (mobile only, inline in sidebar) */}
        {showNotifications && !isCollapsed && (
          <div className="px-3 py-2">
            <NotificationPanel inline />
          </div>
        )}

        <Separator className="bg-sidebar-border" />

        {/* User Section */}
        <div className="p-3">
          <div
            className={cn(
              'flex items-center gap-3 p-2 rounded-lg hover:bg-sidebar-accent/50 transition-colors',
              isCollapsed && 'justify-center'
            )}
          >
            <Avatar className="h-8 w-8">
              <AvatarImage src={user?.avatar_url || undefined} />
              <AvatarFallback className="bg-primary/10 text-primary text-sm">
                {user?.display_name?.charAt(0) || 'U'}
              </AvatarFallback>
            </Avatar>

            {!isCollapsed && (
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-sidebar-foreground truncate">
                  {user?.display_name || 'ユーザー'}
                </p>
                <p className="text-xs text-muted-foreground truncate">{user?.email}</p>
              </div>
            )}

            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-8 w-8 text-sidebar-foreground/70 hover:text-sidebar-foreground hover:bg-sidebar-accent"
                  onClick={handleLogout}
                  disabled={isLoggingOut}
                >
                  {isLoggingOut ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <LogOut className="h-4 w-4" />
                  )}
                </Button>
              </TooltipTrigger>
              <TooltipContent side="right">ログアウト</TooltipContent>
            </Tooltip>
          </div>
        </div>
      </div>
    </TooltipProvider>
  );
}
