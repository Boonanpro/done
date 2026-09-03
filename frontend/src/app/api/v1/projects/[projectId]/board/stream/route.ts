/**
 * 部屋ボード SSE ストリーミングプロキシ
 *
 * Next.js の rewrites プロキシは SSE レスポンスをバッファリングしてしまうため、
 * チャットストリーム同様この Route Handler で明示的にストリーミング転送する。
 * ボードAPIはサンドボックス(port 8000)側。
 */

export const dynamic = 'force-dynamic';
export const runtime = 'nodejs';
export const maxDuration = 300;

export async function GET(
  request: Request,
  { params }: { params: Promise<{ projectId: string }> }
) {
  const { projectId } = await params;
  const backendUrl = process.env.BACKEND_URL || 'http://127.0.0.1:8000';

  const headers: Record<string, string> = {};
  const authorization = request.headers.get('Authorization');
  if (authorization) headers['Authorization'] = authorization;
  const cookie = request.headers.get('Cookie');
  if (cookie) headers['Cookie'] = cookie;

  const backendResponse = await fetch(
    `${backendUrl}/api/v1/projects/${projectId}/board/stream`,
    { headers, signal: request.signal }
  );

  if (!backendResponse.ok) {
    return new Response(backendResponse.body, {
      status: backendResponse.status,
      headers: { 'Content-Type': 'application/json' },
    });
  }

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
