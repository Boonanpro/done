'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { cn } from '@/lib/utils';

const b2bNavItems = [
  { href: '/dashboard/ai-b2b-sales', label: 'ホーム' },
  { href: '/dashboard/ai-b2b-sales/companies', label: '企業リスト' },
  { href: '/dashboard/ai-b2b-sales/deals', label: '商談管理' },
];

const dxNavItems = [
  { href: '/dashboard/dx', label: 'ホーム' },
  { href: '/dashboard/dx/clients', label: 'クライアント' },
  { href: '/dashboard/dx/projects', label: 'プロジェクト' },
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
    <div className="flex h-screen bg-neutral-950 text-neutral-100">
      {/* Sidebar */}
      {!isHub && (
        <aside className="hidden md:flex md:w-60 flex-col border-r border-neutral-800 bg-neutral-950">
          <div className="h-14 flex items-center px-5 border-b border-neutral-800">
            <Link href="/dashboard" className="text-lg font-semibold tracking-tight text-white">
              {title}
            </Link>
          </div>

          <nav className="flex-1 py-4 px-3 space-y-1">
            {navItems.map((item) => {
              const isActive = pathname === item.href;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={cn(
                    'flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors',
                    isActive
                      ? 'bg-neutral-800 text-white'
                      : 'text-neutral-400 hover:text-white hover:bg-neutral-800/60'
                  )}
                >
                  {item.label}
                </Link>
              );
            })}
          </nav>

          <div className="p-3 border-t border-neutral-800">
            <Link
              href="/dashboard"
              className="flex items-center gap-2 px-3 py-2 rounded-lg text-sm text-neutral-500 hover:text-white hover:bg-neutral-800/60 transition-colors"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 19l-7-7m0 0l7-7m-7 7h18" />
              </svg>
              ダッシュボード一覧
            </Link>
            <Link
              href="/chat"
              className="flex items-center gap-2 px-3 py-2 rounded-lg text-sm text-neutral-500 hover:text-white hover:bg-neutral-800/60 transition-colors"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
              </svg>
              チャットに戻る
            </Link>
          </div>
        </aside>
      )}

      <div className="flex flex-col flex-1 min-w-0">
        {/* Mobile header */}
        {!isHub && (
          <header className="md:hidden h-14 flex items-center justify-between px-4 border-b border-neutral-800">
            <Link href="/dashboard" className="text-lg font-semibold text-white">
              {title}
            </Link>
            <nav className="flex items-center gap-3">
              {navItems.map((item) => (
                <Link
                  key={item.href}
                  href={item.href}
                  className={cn(
                    'text-xs transition-colors',
                    pathname === item.href ? 'text-white' : 'text-neutral-400 hover:text-white'
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
