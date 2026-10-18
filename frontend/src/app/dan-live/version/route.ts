// 今のファイルの版（lib/live-version/server.ts）。成果物タブの画面が、自分の部品の版と
// 比べるのに使う。画面からは /_live/live-version で届く（next.config.ts の書き換え）。
// ?slug= を付けると、その成果物の裏側（_server）が今のファイルで動いているかも返す。
import { readBackendStatus, readLiveVersion } from '@/lib/live-version/server';

export const dynamic = 'force-dynamic';

export function GET(request: Request) {
  const slug = new URL(request.url).searchParams.get('slug') || '';
  return Response.json(
    { version: readLiveVersion(), backend: slug ? readBackendStatus(slug) : null },
    { headers: { 'Cache-Control': 'no-store' } },
  );
}
