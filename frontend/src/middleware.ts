/**
 * Next.js Middleware - Route protection
 * 
 * NOTE: Authentication is handled client-side via localStorage.
 * This middleware only handles basic routing, not auth checks.
 */

import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const host = request.headers.get('host') || '';

  // 吉川特装HP専用ドメイン: ルートを /artifacts/kittoku に rewrite してダン本体に到達させない
  if (host === 'kittoku.vercel.app' || host === 'kittoku-tokuso.vercel.app') {
    if (pathname === '/') {
      const url = request.nextUrl.clone();
      url.pathname = '/artifacts/kittoku';
      return NextResponse.rewrite(url);
    }
    return NextResponse.next();
  }

  // それ以外のドメイン (ダン本体): root を /login にリダイレクト
  if (pathname === '/') {
    return NextResponse.redirect(new URL('/login', request.url));
  }

  return NextResponse.next();
}

export const config = {
  matcher: [
    /*
     * Match only the root path
     */
    '/',
  ],
};

