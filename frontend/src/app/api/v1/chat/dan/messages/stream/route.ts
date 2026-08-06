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
  const backendResponse = await fetch(
    `${coreUrl}/api/v1/chat/dan/messages/stream`,
    {
      method: 'POST',
      headers: {
        'Content-Type': request.headers.get('Content-Type') || 'application/json',
        'Authorization': request.headers.get('Authorization') || '',
      },
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
