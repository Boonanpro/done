'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { ArrowLeft, Home, Users, FolderKanban, Building2, Handshake, MessageSquare } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Separator } from '@/components/ui/separator';
import { Button } from '@/components/ui/button';

const b2bNavItems = [
  { href: '/dashboard/ai-b2b-sales', label: 'ホーム', icon: Home },
  { href: '/dashboard/ai-b2b-sales/companies', label: '企業リスト', icon: Building2 },
  { href: '/dashboard/ai-b2b-sales/deals', label: '商談管理', icon: Handshake },
];

const dxNavItems = [
  { href: '/dashboard/dx', label: 'ホーム', icon: Home },
  { href: '/dashboard/dx/clients', label: 'クライアント', icon: Users },
  { href: '/dashboard/dx/projects', label: 'プロジェクト', icon: FolderKanban },
];


export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const pathname = usePathname();

  const isDx = pathname.startsWith('/dashboard/dx');
  const isB2b = pathname.startsWith('/dashboard/ai-b2b-sales');
  const isHub = pathname === '/dashboard';

  const navItems = isDx ? dxNavItems : isB2b ? b2bNavItems : [];
  const title = isDx ? 'DX事業' : isB2b ? 'AI B2B営業' : 'Dashboard';

  return (
    <div className="flex h-screen bg-background text-foreground">
      {!isHub && (
        <aside className="hidden md:flex md:w-60 flex-col border-r border-border bg-background">
          <div className="h-14 flex items-center px-5 border-b border-border">
            <Link href="/dashboard" className="text-lg font-semibold tracking-tight text-foreground">
              {title}
            </Link>
          </div>

          <nav className="flex-1 py-4 px-3 space-y-1">
            {navItems.map((item) => {
              const isActive = pathname === item.href;
              const Icon = item.icon;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={cn(
                    'flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors',
                    isActive
                      ? 'bg-secondary text-foreground'
                      : 'text-muted-foreground hover:text-foreground hover:bg-secondary/60'
                  )}
                >
                  <Icon className="h-4 w-4" />
                  {item.label}
                </Link>
              );
            })}
          </nav>

          <Separator />
          <div className="p-3 space-y-1">
            <Button variant="ghost" size="sm" className="w-full justify-start gap-2 text-muted-foreground" asChild>
              <Link href="/dashboard">
                <ArrowLeft className="h-4 w-4" />
                ダッシュボード一覧
              </Link>
            </Button>
            <Button variant="ghost" size="sm" className="w-full justify-start gap-2 text-muted-foreground" asChild>
              <Link href="/chat">
                <MessageSquare className="h-4 w-4" />
                チャットに戻る
              </Link>
            </Button>
          </div>
        </aside>
      )}

      <div className="flex flex-col flex-1 min-w-0">
        {!isHub && (
          <header className="md:hidden h-14 flex items-center justify-between px-4 border-b border-border">
            <Link href="/dashboard" className="text-lg font-semibold text-foreground">
              {title}
            </Link>
            <nav className="flex items-center gap-3">
              {navItems.map((item) => (
                <Link
                  key={item.href}
                  href={item.href}
                  className={cn(
                    'text-xs transition-colors',
                    pathname === item.href ? 'text-foreground' : 'text-muted-foreground hover:text-foreground'
                  )}
                >
                  {item.label}
                </Link>
              ))}
            </nav>
          </header>
        )}

        <main className="flex-1 overflow-y-auto p-6 lg:p-8">
          {children}
        </main>
      </div>
    </div>
  );
}
