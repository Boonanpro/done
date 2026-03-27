'use client';

import { useState, useRef, useEffect, useSyncExternalStore } from 'react';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { motion, AnimatePresence } from 'framer-motion';
import { MessageSquare, Users, Settings, LogOut, Search, ChevronLeft, ChevronRight, ChevronDown, Loader2, FolderKanban, Briefcase, FileEdit, Plus, Pencil, Clapperboard, LayoutDashboard } from 'lucide-react';
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
import { useAuth } from '@/hooks/use-auth';
import { api, type ProjectResponse, type ProjectStatusType } from '@/lib/api-client';
import { useProjectStore } from '@/stores/project-store';
import { useIsMobile } from '@/hooks/useIsMobile';
import { NotificationPanel } from '@/components/notification/notification-panel';

function useHasToken() {
  return useSyncExternalStore(
    () => () => {},
    () => !!localStorage.getItem('done-token'),
    () => false
  );
}

const STATUS_COLORS: Record<ProjectStatusType, string> = {
  planning: 'bg-yellow-400',
  proposed: 'bg-blue-400',
  approved: 'bg-green-400',
  in_progress: 'bg-primary',
  completed: 'bg-emerald-500',
  paused: 'bg-gray-400',
  cancelled: 'bg-red-400',
};

const STATUS_LABELS: Record<ProjectStatusType, string> = {
  planning: '計画中',
  proposed: '提案済',
  approved: '承認済',
  in_progress: '進行中',
  completed: '完了',
  paused: '一時停止',
  cancelled: 'キャンセル',
};

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
    title: '設定',
    href: '/settings',
    icon: Settings,
    description: 'アカウント設定',
  },
];

const businessItems = [
  {
    title: 'DX事業',
    href: '/dashboard/dx',
    icon: LayoutDashboard,
    description: 'HP制作・DXツール管理ダッシュボード',
  },
  {
    title: 'note投稿',
    href: '/notes',
    icon: FileEdit,
    description: 'note記事の下書き・投稿管理',
  },
  {
    title: 'Studio',
    href: '/studio',
    icon: Clapperboard,
    description: 'AI Vlog 制作ダッシュボード',
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
  const [isBusinessOpen, setIsBusinessOpen] = useState(false);
  const [editingProjectId, setEditingProjectId] = useState<string | null>(null);
  const [editingTitle, setEditingTitle] = useState('');
  const editInputRef = useRef<HTMLInputElement>(null);
  const hasToken = useHasToken();
  const isMobile = useIsMobile();
  const queryClient = useQueryClient();

  const selectedProjectId = useProjectStore((s) => s.selectedProjectId);
  const selectProject = useProjectStore((s) => s.selectProject);

  const createProjectMutation = useMutation({
    mutationFn: (payload: { title: string; description?: string }) => api.projects.create(payload),
    onSuccess: (project) => {
      queryClient.invalidateQueries({ queryKey: ['projects'] });
      selectProject(project.id);
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
    enabled: hasToken,
    staleTime: 60 * 1000,
  });

  const filteredProjects = projectsData?.projects?.filter((p) =>
    p.title.toLowerCase().includes(searchQuery.toLowerCase())
  ) ?? [];

  const handleProjectClick = (project: ProjectResponse) => {
    if (project.id === selectedProjectId) {
      selectProject(null);
    } else {
      selectProject(project.id);
      // チャットページ以外にいる場合は /chat に遷移
      if (!pathname.startsWith('/chat')) {
        router.push('/chat');
      }
      if (isMobile) {
        onToggleCollapse();
      }
    }
  };

  const handleInstantCreate = () => {
    if (!createProjectMutation.isPending) {
      createProjectMutation.mutate({ title: '新しいプロジェクト' });
    }
  };

  const handleLogout = async () => {
    try {
      await logout();
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
          {!isCollapsed && (
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
            </>
          )}

          <nav className="space-y-1">
            {isLoadingProjects ? (
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
              filteredProjects.map((project) => {
                const isActive = project.id === selectedProjectId;
                const statusColor = STATUS_COLORS[project.status] || 'bg-gray-400';

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
                          <span className={cn('absolute -bottom-0.5 -right-0.5 h-2 w-2 rounded-full', statusColor)} />
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
                                  <p className="truncate">{project.title}</p>
                                  <p className="text-xs text-muted-foreground truncate">
                                    {STATUS_LABELS[project.status]} · {formatRelativeTime(project.updated_at || project.created_at)}
                                  </p>
                                </div>
                                <button
                                  className="shrink-0 p-0.5 rounded transition-opacity opacity-0 group-hover:opacity-100"
                                  onClick={(e) => handleStartEdit(e, project)}
                                  title="タイトルを編集"
                                >
                                  <Pencil className="h-3 w-3 text-muted-foreground" />
                                </button>
                              </>
                            )}
                          </div>
                        )}
                      </motion.div>
                    </TooltipTrigger>
                    {isCollapsed && (
                      <TooltipContent side="right">
                        <p className="font-medium">{project.icon || '📁'} {project.title}</p>
                        <p className="text-xs text-muted-foreground">
                          {STATUS_LABELS[project.status]}
                        </p>
                      </TooltipContent>
                    )}
                  </Tooltip>
                );
              })
            )}
          </nav>

          <Separator className="my-3 bg-sidebar-border" />

          <nav className="space-y-1">
            {/* チャット */}
            {navItems.filter(item => item.href === '/chat').map((item) => {
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
                        <Icon className="h-4 w-4 shrink-0" />
                        {!isCollapsed && <span>{item.title}</span>}
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

            {/* ビジネス */}
            <Tooltip>
              <TooltipTrigger asChild>
                <motion.div
                  whileHover={{ scale: 1.02 }}
                  whileTap={{ scale: 0.98 }}
                  className={cn(
                    'flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors cursor-pointer',
                    (isBusinessOpen || pathname.startsWith('/notes') || pathname.startsWith('/studio') || pathname.startsWith('/dashboard/dx'))
                      ? 'bg-sidebar-accent text-sidebar-accent-foreground'
                      : 'text-sidebar-foreground/70 hover:bg-sidebar-accent/50 hover:text-sidebar-foreground',
                    isCollapsed && 'justify-center px-0'
                  )}
                  onClick={() => setIsBusinessOpen(!isBusinessOpen)}
                >
                  <Briefcase className="h-4 w-4 shrink-0" />
                  {!isCollapsed && (
                    <>
                      <span className="flex-1">ビジネス</span>
                      <ChevronDown className={cn(
                        'h-3.5 w-3.5 transition-transform',
                        isBusinessOpen && 'rotate-180'
                      )} />
                    </>
                  )}
                </motion.div>
              </TooltipTrigger>
              {isCollapsed && (
                <TooltipContent side="right">
                  <p className="font-medium">ビジネス</p>
                  <p className="text-xs text-muted-foreground">ビジネスツール</p>
                </TooltipContent>
              )}
            </Tooltip>

            <AnimatePresence>
              {isBusinessOpen && !isCollapsed && (
                <motion.div
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: 'auto' }}
                  exit={{ opacity: 0, height: 0 }}
                  className="overflow-hidden"
                >
                  {businessItems.map((item) => {
                    const isActive = pathname.startsWith(item.href);
                    const Icon = item.icon;
                    return (
                      <Tooltip key={item.href}>
                        <TooltipTrigger asChild>
                          <a href={item.href} target="_blank" rel="noopener noreferrer">
                            <motion.div
                              whileHover={{ scale: 1.02 }}
                              whileTap={{ scale: 0.98 }}
                              className={cn(
                                'flex items-center gap-3 pl-8 pr-3 py-2 rounded-lg text-sm transition-colors',
                                isActive
                                  ? 'bg-sidebar-accent text-sidebar-accent-foreground'
                                  : 'text-sidebar-foreground/70 hover:bg-sidebar-accent/50 hover:text-sidebar-foreground'
                              )}
                            >
                              <Icon className="h-4 w-4 shrink-0" />
                              <span>{item.title}</span>
                            </motion.div>
                          </a>
                        </TooltipTrigger>
                      </Tooltip>
                    );
                  })}
                </motion.div>
              )}
            </AnimatePresence>

            {/* 友達・設定 */}
            {navItems.filter(item => item.href !== '/chat').map((item) => {
              const isActive = pathname.startsWith(item.href);
              const Icon = item.icon;
              return (
                <Tooltip key={item.href}>
                  <TooltipTrigger asChild>
                    <Link href={item.href}>
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
                        <Icon className="h-4 w-4 shrink-0" />
                        {!isCollapsed && <span>{item.title}</span>}
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
