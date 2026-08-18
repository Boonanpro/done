/**
 * SSE Streaming Proxy Route Handler
 *
 * Next.js の rewrites プロキシは SSE レスポンスをバッファリングしてしまうため、
 * このエンドポイントだけ Route Handler で明示的にストリーミング転送する。
 *
 * backendResponse.body (ReadableStream) をそのまま new Response() に渡すことで、
 * バッファリングなしにクライアントへストリーミングされる。
 */

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';
// Vercel の関数実行上限。未設定だと既定値（短い）で長いターンのストリームが
// HTTP 200 のまま途中でブツ切りされ、クライアント側は done を受け取れない
// （モバイルの Send 固着の主因だった）。
export const maxDuration = 300;

export async function POST(request: Request) {
  const body = await request.text();

  // チャットはダンコア(port 9000)へ。CORE_BACKEND_URL で上書き可（本番tunnel等）。
  const coreUrl = process.env.CORE_BACKEND_URL || 'http://127.0.0.1:9000';
  // バックエンドの認証は Cookie(done_access_token) を Bearer より優先して見る。
  // rewrites 経由の他の /api/v1/chat/* は Cookie がそのまま届くのに、この
  // Route Handler だけ落とすと「受信は通るのに送信だけ 401」という非対称が
  // 生まれる（モバイルの "Could not connect to DAN" の真因）。必ず転送する。
  const headers: Record<string, string> = {
    'Content-Type': request.headers.get('Content-Type') || 'application/json',
  };
  const authorization = request.headers.get('Authorization');
  if (authorization) headers['Authorization'] = authorization;
  const cookie = request.headers.get('Cookie');
  if (cookie) headers['Cookie'] = cookie;
  const backendResponse = await fetch(
    `${coreUrl}/api/v1/chat/dan/messages/stream`,
    {
      method: 'POST',
      headers,
      body,
    },
  );

  if (!backendResponse.ok) {
    return new Response(backendResponse.body, {
      status: backendResponse.status,
      headers: { 'Content-Type': 'application/json' },
    });
  }

  // ReadableStream をそのまま転送（バッファリングしない）
  return new Response(backendResponse.body, {
    status: 200,
    headers: {
      'Content-Type': 'text/event-stream; charset=utf-8',
      'Cache-Control': 'no-cache, no-transform',
      'Connection': 'keep-alive',
      'X-Accel-Buffering': 'no',
      'Content-Encoding': 'none',
    },
  });
}
