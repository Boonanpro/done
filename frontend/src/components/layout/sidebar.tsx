'use client';

import { useState, useSyncExternalStore } from 'react';
import Link from 'next/link';
import { usePathname, useRouter, useParams } from 'next/navigation';
import { motion, AnimatePresence } from 'framer-motion';
import { MessageSquare, Users, Settings, LogOut, Plus, Search, ChevronLeft, ChevronRight, ChevronDown, Loader2, MessageCircle, X, Briefcase, FileEdit, Clapperboard } from 'lucide-react';
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
import { api, SessionResponse, ApiError } from '@/lib/api-client';
import { useSessionStateStore } from '@/stores/session-state-store';

// Hook to safely check localStorage after hydration
function useHasToken() {
  return useSyncExternalStore(
    () => () => {},
    () => !!localStorage.getItem('done-token'),
    () => false
  );
}

interface SidebarProps {
  className?: string;
}

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

const businessItems = [
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

export function Sidebar({ className }: SidebarProps) {
  const pathname = usePathname();
  const router = useRouter();
  const params = useParams();
  const queryClient = useQueryClient();
  const { user, logout, isLoggingOut } = useAuth();
  const [isCollapsed, setIsCollapsed] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [isBusinessOpen, setIsBusinessOpen] = useState(false);
  const hasToken = useHasToken();

  // URLから現在のセッションIDを取得（唯一の真実源）
  const currentSessionId = params.sessionId as string | undefined;

  // セッション状態ストア
  const setActiveSessionId = useSessionStateStore((state) => state.setActiveSessionId);
  const sessionStates = useSessionStateStore((state) => state.sessions);
  const markAsRead = useSessionStateStore((state) => state.markAsRead);

  // Fetch sessions
  const { data: sessionsData, isLoading: isLoadingSessions } = useQuery({
    queryKey: ['dan-sessions'],
    queryFn: api.dan.getSessions,
    enabled: hasToken,
    staleTime: 60 * 1000,
  });

  // Filter sessions by search query
  const filteredSessions = sessionsData?.sessions?.filter((session) =>
    session.title.toLowerCase().includes(searchQuery.toLowerCase())
  ) ?? [];

  // Create new session
  const createSessionMutation = useMutation({
    mutationFn: api.dan.createSession,
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['dan-sessions'] });
      if (data?.id) {
        // 新しいセッションに直接遷移
        router.push(`/chat/${data.id}`);
        toast.success('新しい会話を開始しました');
      }
    },
    onError: () => {
      toast.error('新しい会話の開始に失敗しました');
    },
  });

  // Delete session
  const deleteSessionMutation = useMutation({
    mutationFn: (sessionId: string) => api.dan.deleteSession(sessionId),
    onSuccess: (data, deletedSessionId) => {
      const wasActive = deletedSessionId === currentSessionId;
      const newActiveId = data.new_active_session_id;

      // Remove from cache
      queryClient.setQueryData(['dan-sessions'], (old: typeof sessionsData) => ({
        sessions: old?.sessions?.filter((s) => s.id !== deletedSessionId) || [],
        current_session_id: newActiveId || old?.current_session_id,
      }));

      // If the deleted session was active, navigate to new session
      if (wasActive && newActiveId) {
        router.push(`/chat/${newActiveId}`);
      }

      toast.success('会話を削除しました');
    },
    onError: (err) => {
      if (err instanceof ApiError && err.status === 400) {
        toast.error('会話の削除に失敗しました');
      } else {
        toast.error('会話の削除に失敗しました');
      }
    },
  });

  const handleNewConversation = () => {
    createSessionMutation.mutate();
  };

  // セッションクリック時はURLで遷移するだけ
  const handleSessionClick = (session: SessionResponse) => {
    if (session.id === currentSessionId) {
      return; // 既に同じセッション
    }
    // セッション状態を更新して既読にする
    setActiveSessionId(session.id);
    markAsRead(session.id);
    // URLで遷移
    router.push(`/chat/${session.id}`);
  };

  const handleDeleteSession = (e: React.MouseEvent, sessionId: string) => {
    e.stopPropagation();
    deleteSessionMutation.mutate(sessionId);
  };

  const handleLogout = async () => {
    try {
      await logout();
      router.push('/login');
    } catch {
      toast.error('ログアウトに失敗しました');
    }
  };

  const formatRelativeTime = (dateString: string | undefined) => {
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
      <motion.aside
        initial={false}
        animate={{ width: isCollapsed ? 64 : 280 }}
        transition={{ duration: 0.2, ease: 'easeInOut' }}
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
            onClick={() => setIsCollapsed(!isCollapsed)}
          >
            {isCollapsed ? (
              <ChevronRight className="h-4 w-4" />
            ) : (
              <ChevronLeft className="h-4 w-4" />
            )}
          </Button>
        </div>

        {/*
          New Chat Button - 単一セッションモードでは非表示
          将来マルチセッションに戻す場合はコメント解除
        */}
        {/* <div className="p-3">
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="outline"
                className={cn(
                  'w-full justify-start gap-2 bg-sidebar-accent/50 border-sidebar-border hover:bg-sidebar-accent',
                  isCollapsed && 'justify-center px-0'
                )}
                onClick={handleNewConversation}
                disabled={createSessionMutation.isPending}
              >
                {createSessionMutation.isPending ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Plus className="h-4 w-4" />
                )}
                {!isCollapsed && <span>新しい会話</span>}
              </Button>
            </TooltipTrigger>
            {isCollapsed && <TooltipContent side="right">新しい会話</TooltipContent>}
          </Tooltip>
        </div> */}

        {/* Search */}
        <AnimatePresence>
          {!isCollapsed && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: 'auto' }}
              exit={{ opacity: 0, height: 0 }}
              className="px-3 pb-3"
            >
              <div className="relative">
                <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                <Input
                  placeholder="チャットを検索..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="pl-8 h-9 bg-sidebar-accent/30 border-sidebar-border text-sm"
                />
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        <Separator className="bg-sidebar-border" />

        {/* Chat Sessions */}
        <ScrollArea className="flex-1 min-h-0 px-3 py-2">
          {!isCollapsed && (
            <div className="flex items-center gap-2 px-2 py-1.5 text-xs text-muted-foreground font-medium">
              <MessageSquare className="h-3 w-3" />
              <span>ダンとの会話</span>
            </div>
          )}

          <nav className="space-y-1">
            {isLoadingSessions ? (
              <div className="flex items-center justify-center py-4">
                <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
              </div>
            ) : filteredSessions.length === 0 ? (
              !isCollapsed && (
                <p className="text-xs text-muted-foreground text-center py-4">
                  会話履歴がありません
                </p>
              )
            ) : (
              filteredSessions.map((session) => {
                // URLのsessionIdと比較してアクティブ判定
                const isActive = session.id === currentSessionId;
                const isDeleting = deleteSessionMutation.isPending &&
                  deleteSessionMutation.variables === session.id;
                const unreadCount = sessionStates.get(session.id)?.unreadCount || 0;
                const hasUnread = unreadCount > 0;

                return (
                  <Tooltip key={session.id}>
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
                        onClick={() => !isDeleting && handleSessionClick(session)}
                      >
                        <div className="relative shrink-0">
                          <MessageCircle className="h-4 w-4" />
                          {hasUnread && !isActive && (
                            <span className="absolute -top-0.5 -right-0.5 h-2 w-2 rounded-full bg-white border border-sidebar-border" />
                          )}
                        </div>
                        {!isCollapsed && (
                          <>
                            <div className="flex-1 min-w-0">
                              <p className={cn("truncate", hasUnread && !isActive && "font-semibold")}>{session.title}</p>
                              <p className="text-xs text-muted-foreground truncate">
                                {formatRelativeTime(session.last_message_at)}
                              </p>
                            </div>
                            <button
                              onClick={(e) => handleDeleteSession(e, session.id)}
                              disabled={isDeleting}
                              className="opacity-0 group-hover:opacity-100 p-1 rounded hover:bg-destructive/20 hover:text-destructive transition-all"
                              title="会話を削除"
                            >
                              {isDeleting ? (
                                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                              ) : (
                                <X className="h-3.5 w-3.5" />
                              )}
                            </button>
                          </>
                        )}
                      </motion.div>
                    </TooltipTrigger>
                    {isCollapsed && (
                      <TooltipContent side="right">
                        <p className="font-medium">{session.title}</p>
                        <p className="text-xs text-muted-foreground">
                          {formatRelativeTime(session.last_message_at)}
                        </p>
                        {hasUnread && <p className="text-xs text-primary">新着メッセージあり</p>}
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

            {/* ビジネス */}
            <Tooltip>
              <TooltipTrigger asChild>
                <motion.div
                  whileHover={{ scale: 1.02 }}
                  whileTap={{ scale: 0.98 }}
                  className={cn(
                    'flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors cursor-pointer',
                    (isBusinessOpen || pathname.startsWith('/notes'))
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
                          <Link href={item.href}>
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
                          </Link>
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
      </motion.aside>
    </TooltipProvider>
  );
}
