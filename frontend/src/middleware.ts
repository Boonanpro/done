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

  // Redirect root to login (auth check happens client-side)
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

