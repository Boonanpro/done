'use client';

import { useState, useSyncExternalStore } from 'react';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { motion, AnimatePresence } from 'framer-motion';
import { MessageSquare, Users, Settings, LogOut, Search, ChevronLeft, ChevronRight, Loader2, FolderKanban } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
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
    title: '友達',
    href: '/friends',
    icon: Users,
    description: '友達とのチャット',
  },
  {
    title: '設定',
    href: '/settings',
    icon: Settings,
    description: 'アカウント設定',
  },
];

interface ProjectListPanelProps {
  className?: string;
  isCollapsed: boolean;
  onToggleCollapse: () => void;
}

export function ProjectListPanel({ className, isCollapsed, onToggleCollapse }: ProjectListPanelProps) {
  const pathname = usePathname();
  const router = useRouter();
  const { user, logout, isLoggingOut } = useAuth();
  const [searchQuery, setSearchQuery] = useState('');
  const hasToken = useHasToken();

  const selectedProjectId = useProjectStore((s) => s.selectedProjectId);
  const selectProject = useProjectStore((s) => s.selectProject);

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
          'relative flex flex-col h-full overflow-hidden bg-sidebar border-r border-sidebar-border',
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

          <Button
            variant="ghost"
            size="icon"
            className="ml-auto h-8 w-8 text-sidebar-foreground hover:bg-sidebar-accent"
            onClick={onToggleCollapse}
          >
            {isCollapsed ? (
              <ChevronRight className="h-4 w-4" />
            ) : (
              <ChevronLeft className="h-4 w-4" />
            )}
          </Button>
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
            <div className="flex items-center gap-2 px-2 py-1.5 text-xs text-muted-foreground font-medium">
              <FolderKanban className="h-3 w-3" />
              <span>プロジェクト</span>
            </div>
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
                        whileHover={{ scale: 1.01 }}
                        whileTap={{ scale: 0.99 }}
                        className={cn(
                          'group w-full flex items-center gap-2 px-3 py-2 rounded-lg text-sm transition-colors text-left cursor-pointer',
                          isActive
                            ? 'bg-sidebar-accent text-sidebar-accent-foreground'
                            : 'text-sidebar-foreground/70 hover:bg-sidebar-accent/50 hover:text-sidebar-foreground',
                          isCollapsed && 'justify-center px-0'
                        )}
                        onClick={() => handleProjectClick(project)}
                      >
                        <div className="relative shrink-0">
                          <FolderKanban className="h-4 w-4" />
                          <span className={cn('absolute -bottom-0.5 -right-0.5 h-2 w-2 rounded-full', statusColor)} />
                        </div>
                        {!isCollapsed && (
                          <div className="flex-1 min-w-0">
                            <p className="truncate">{project.title}</p>
                            <p className="text-xs text-muted-foreground truncate">
                              {STATUS_LABELS[project.status]} · {formatRelativeTime(project.updated_at || project.created_at)}
                            </p>
                          </div>
                        )}
                      </motion.div>
                    </TooltipTrigger>
                    {isCollapsed && (
                      <TooltipContent side="right">
                        <p className="font-medium">{project.title}</p>
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
            {navItems.map((item) => {
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
