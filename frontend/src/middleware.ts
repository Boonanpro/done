/**
 * Next.js Middleware - Route protection
 *
 * 認証チェックは基本的にクライアント側 (localStorage) だが、
 * 「公開すべきでない /artifacts/* 」への直接アクセスはここで遮断する。
 *
 * - 公開 slug 一覧 (PUBLIC_ARTIFACT_SLUGS): 認証不要
 * - それ以外の /artifacts/* : Cookie の done_access_token を要求
 *   無ければ /login にリダイレクト
 */

import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

const ACCESS_TOKEN_COOKIE = 'done_access_token';

// 公開してよい artifact slug の一覧（クライアント案件など）
// 新しい公開案件を作ったらここに追加する。
const PUBLIC_ARTIFACT_SLUGS = new Set<string>(
  (process.env.NEXT_PUBLIC_ARTIFACT_SLUGS || 'kittoku')
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean),
);

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const host = request.headers.get('host') || '';

  // ----- 吉川特装HP 専用ドメイン: ルートを /artifacts/kittoku に rewrite -----
  if (
    host === 'kittoku.vercel.app' ||
    host === 'kittoku-tokuso.vercel.app' ||
    host === 'yoshikawa-tokuso.vercel.app'
  ) {
    if (pathname === '/') {
      const url = request.nextUrl.clone();
      url.pathname = '/artifacts/kittoku';
      return NextResponse.rewrite(url);
    }
    return NextResponse.next();
  }

  // ----- ダン本体ドメイン: root → /login -----
  if (pathname === '/') {
    return NextResponse.redirect(new URL('/login', request.url));
  }

  // ----- Public preview: /preview/<slug> mirrors /artifacts/<slug> without auth -----
  if (pathname.startsWith('/preview/')) {
    const segments = pathname.split('/').filter(Boolean); // ['preview','slug', ...]
    if (segments.length >= 2) {
      const url = request.nextUrl.clone();
      url.pathname = `/artifacts/${segments.slice(1).join('/')}`;
      return NextResponse.rewrite(url);
    }
  }

  // ----- /artifacts/* の保護 -----
  if (pathname.startsWith('/artifacts/')) {
    // /artifacts/<slug>/<rest...>
    const segments = pathname.split('/').filter(Boolean); // ['artifacts','slug', ...]
    const slug = segments[1];
    if (slug && PUBLIC_ARTIFACT_SLUGS.has(slug)) {
      // 公開 slug は認証不要
      return NextResponse.next();
    }
    // 公開 slug でなければ Cookie 確認
    const token = request.cookies.get(ACCESS_TOKEN_COOKIE)?.value;
    if (!token) {
      // 未認証 → /login へ
      const loginUrl = new URL('/login', request.url);
      loginUrl.searchParams.set('redirect', pathname);
      return NextResponse.redirect(loginUrl);
    }
    return NextResponse.next();
  }

  return NextResponse.next();
}

export const config = {
  matcher: [
    /*
     * Match root and all /artifacts/* paths
     */
    '/',
    '/artifacts/:path*',
    '/preview/:path*',
  ],
};
