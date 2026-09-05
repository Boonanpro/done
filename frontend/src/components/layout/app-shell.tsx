'use client';

import { useEffect } from 'react';
import { usePathname, useRouter } from 'next/navigation';

import { MainLayout } from '@/components/layout/main-layout';
import { OWNER_USER_ID } from '@/lib/api-client';
import { guestHomeUrl } from '@/lib/guest-home';
import { usePreviewStore } from '@/stores/preview-store';
import { useProjectStore } from '@/stores/project-store';
import { useRoomFeed } from '@/hooks/useRoomFeed';

/**
 * ダッシュボード全体（/chat, /collab, /friends, /notes, /settings, /today）の外枠。
 *
 * ルートの layout から一度だけマウントされ、以後どのページへ移っても
 * サイドバー・ロゴ・通知パネルは同じインスタンスのまま残る。
 * 以前は /chat だけが layout に外枠を持ち、他ページは各 page.tsx が自前で
 * <MainLayout> を描いていたため、タブを移るたびに外枠ごと作り直され
 * （ロゴの登場アニメーションが再生され）画面全体がガタついていた。
 *
 * ここで決めるのは「外枠を出すか」「通知パネルを出すか」「ハンバーガーを隠すか」
 * だけ。中身（children）は各ページが描く。/chat 配下は MainLayout が
 * selectedProjectId に基づいて ProjectChatPanel を自前で出すので children を渡さない。
 */
const SHELL_PREFIXES = ['/chat', '/collab', '/friends', '/notes', '/settings', '/today'];

function shellFor(pathname: string) {
  // /collab/join/<token> は外部の相手（ゲスト）の窓口。オーナーの外枠にも認証ゲートにも
  // 入れてはいけない（入れるとゲストが毎回ログイン画面に飛ばされる。2026-09-05 実発生）
  if (pathname.startsWith('/collab/join/')) {
    return { inShell: false, isChat: false, isCollabRoom: false };
  }
  const inShell = SHELL_PREFIXES.some((p) => pathname === p || pathname.startsWith(p + '/'));
  const isChat = pathname === '/chat' || pathname.startsWith('/chat/');
  const isCollabRoom = /^\/collab\/[^/]+/.test(pathname);
  return { inShell, isChat, isCollabRoom };
}

// PWA の precache を一度だけ捨てる（デプロイ直後に古い chunk を掴み続ける事故の予防）。
// 以前は /chat の layout がマウントされるたびに全消去していたが、ページ遷移のたびに
// 走ると再取得が発生して重い。プロセスにつき1回で目的は満たせる。
let cachesCleared = false;

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname() || '';
  const router = useRouter();
  const selectProject = useProjectStore((s) => s.selectProject);
  const { inShell, isChat, isCollabRoom } = shellFor(pathname);
  // 押し込み同期: 外枠が生きている間、全部屋の新着を手元の写しへ流し込む
  useRoomFeed(inShell);

  // URL → ストアの同期（/chat/<projectId>）。サイドバーの部屋切替は RSC 往復を避けて
  // history.pushState で URL だけ書き換えるため、usePathname で戻る/進むも含めて拾う。
  useEffect(() => {
    if (!isChat) return;
    const m = pathname.match(/^\/chat\/([^/]+)/);
    const id = m ? decodeURIComponent(m[1]) : null;
    if (useProjectStore.getState().selectedProjectId !== id) selectProject(id);
  }, [pathname, isChat, selectProject]);

  // 認証ゲート。外枠は先に描き、未ログインならその場で /login へ送る
  // （以前は判定が済むまで null を返していたので、遷移のたびに空白フレームが出ていた）。
  useEffect(() => {
    if (!inShell) return;
    const token = localStorage.getItem('done-token');
    if (!token) {
      // ゲスト（外部窓口の相手）がオーナー用URLに来た場合は、ログインではなく自分の窓口へ
      const roomMatch = pathname.match(/^\/collab\/([^/]+)/);
      const guestHome = guestHomeUrl(roomMatch ? roomMatch[1] : null);
      if (guestHome) {
        router.replace(guestHome);
        return;
      }
      import('@/lib/api-client').then((m) => m.recordLogoutReason('app-shell-no-token')).catch(() => {});
      try { usePreviewStore.getState().closePreview(); } catch {}
      router.push('/login');
      return;
    }
    if (!isChat) return;
    try {
      const payload = JSON.parse(atob(token.split('.')[1]));
      if (payload.sub !== OWNER_USER_ID) router.replace('/collab');
    } catch {
      // 壊れたトークンは API 側の 401 → ログアウト処理に任せる
    }
  }, [inShell, isChat, router]);

  useEffect(() => {
    if (!inShell || cachesCleared || typeof window === 'undefined' || !('caches' in window)) return;
    cachesCleared = true;
    caches.keys().then((keys) => { keys.forEach((key) => { caches.delete(key); }); }).catch(() => {});
  }, [inShell]);

  if (!inShell) return <>{children}</>;

  return (
    <>
      {/* /chat の page.tsx は null を返す。外枠は同じインスタンスのまま中身だけ差し替わる */}
      {isChat ? children : null}
      <MainLayout showNotifications={isChat} hideHamburger={isCollabRoom}>
        {isChat ? undefined : children}
      </MainLayout>
    </>
  );
}
