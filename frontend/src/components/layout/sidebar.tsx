'use client';

import { useState, useEffect } from 'react';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import { motion, AnimatePresence } from 'framer-motion';
import {
  MessageSquare,
  Users,
  Settings,
  LogOut,
  Plus,
  Search,
  ChevronLeft,
  ChevronRight,
  Loader2,
  MessageCircle,
} from 'lucide-react';
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
import { api, SessionResponse } from '@/lib/api-client';

interface SidebarProps {
  className?: string;
}

const navItems = [
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

export function Sidebar({ className }: SidebarProps) {
  const pathname = usePathname();
  const router = useRouter();
  const queryClient = useQueryClient();
  const { user, logout, isLoggingOut } = useAuth();
  const [isCollapsed, setIsCollapsed] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [hasMounted, setHasMounted] = useState(false);

  // Wait for client-side mount to avoid hydration mismatch
  useEffect(() => {
    setHasMounted(true);
  }, []);

  // Check if token exists in localStorage (only after mount)
  const hasToken = hasMounted && !!localStorage.getItem('done-token');

  // Fetch sessions
  const { data: sessionsData, isLoading: isLoadingSessions } = useQuery({
    queryKey: ['dan-sessions'],
    queryFn: api.dan.getSessions,
    enabled: hasToken,
    staleTime: 60 * 1000, // 1 minute - cache longer
  });

  // Filter sessions by search query
  const filteredSessions = sessionsData?.sessions?.filter((session) =>
    session.title.toLowerCase().includes(searchQuery.toLowerCase())
  ) ?? [];

  // Create new session
  const createSessionMutation = useMutation({
    mutationFn: api.dan.createSession,
    onSuccess: (newSession) => {
      // Invalidate queries to refresh the session list
      queryClient.invalidateQueries({ queryKey: ['dan-sessions'] });
      queryClient.invalidateQueries({ queryKey: ['dan-messages'] });
      queryClient.invalidateQueries({ queryKey: ['dan-room'] });
      // Navigate to chat page
      router.push('/chat');
      toast.success('新しい会話を開始しました');
    },
    onError: () => {
      toast.error('新しい会話の開始に失敗しました');
    },
  });

  // Activate session
  const activateSessionMutation = useMutation({
    mutationFn: (sessionId: string) => api.dan.activateSession(sessionId),
    onSuccess: () => {
      // Refresh messages for the new active session
      queryClient.invalidateQueries({ queryKey: ['dan-sessions'] });
      queryClient.invalidateQueries({ queryKey: ['dan-messages'] });
      queryClient.invalidateQueries({ queryKey: ['dan-room'] });
      router.push('/chat');
    },
    onError: () => {
      toast.error('セッションの切り替えに失敗しました');
    },
  });

  const handleNewConversation = () => {
    createSessionMutation.mutate();
  };

  const handleSessionClick = (session: SessionResponse) => {
    // If already the current session, just navigate to chat
    if (session.id === sessionsData?.current_session_id) {
      router.push('/chat');
      return;
    }
    // Otherwise, activate the session
    activateSessionMutation.mutate(session.id);
  };

  const handleLogout = async () => {
    try {
      await logout();
      router.push('/login');
    } catch {
      toast.error('ログアウトに失敗しました');
    }
  };

  // Format relative time
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
          'relative flex flex-col h-screen bg-sidebar border-r border-sidebar-border',
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

        {/* New Chat Button */}
        <div className="p-3">
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
        </div>

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
        <ScrollArea className="flex-1 px-3 py-2">
          {/* Dan section header */}
          {!isCollapsed && (
            <div className="flex items-center gap-2 px-2 py-1.5 text-xs text-muted-foreground font-medium">
              <MessageSquare className="h-3 w-3" />
              <span>ダンとの会話</span>
            </div>
          )}

          {/* Sessions list */}
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
                const isActive = session.id === sessionsData?.current_session_id;
                const isActivating = activateSessionMutation.isPending && 
                  activateSessionMutation.variables === session.id;

                return (
                  <Tooltip key={session.id}>
                    <TooltipTrigger asChild>
                      <motion.button
                        whileHover={{ scale: 1.01 }}
                        whileTap={{ scale: 0.99 }}
                        onClick={() => handleSessionClick(session)}
                        disabled={isActivating}
                        className={cn(
                          'w-full flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors text-left',
                          isActive
                            ? 'bg-sidebar-accent text-sidebar-accent-foreground'
                            : 'text-sidebar-foreground/70 hover:bg-sidebar-accent/50 hover:text-sidebar-foreground',
                          isCollapsed && 'justify-center px-0'
                        )}
                      >
                        {isActivating ? (
                          <Loader2 className="h-4 w-4 shrink-0 animate-spin" />
                        ) : (
                          <MessageCircle className="h-4 w-4 shrink-0" />
                        )}
                        {!isCollapsed && (
                          <div className="flex-1 min-w-0">
                            <p className="truncate font-medium">{session.title}</p>
                            <p className="text-xs text-muted-foreground truncate">
                              {formatRelativeTime(session.last_message_at)}
                            </p>
                          </div>
                        )}
                      </motion.button>
                    </TooltipTrigger>
                    {isCollapsed && (
                      <TooltipContent side="right">
                        <p className="font-medium">{session.title}</p>
                        <p className="text-xs text-muted-foreground">
                          {formatRelativeTime(session.last_message_at)}
                        </p>
                      </TooltipContent>
                    )}
                  </Tooltip>
                );
              })
            )}
          </nav>

          <Separator className="my-3 bg-sidebar-border" />

          {/* Other navigation items */}
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
      </motion.aside>
    </TooltipProvider>
  );
}
