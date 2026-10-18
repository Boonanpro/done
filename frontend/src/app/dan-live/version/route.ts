// 今のファイルの版（lib/live-version/server.ts）。成果物タブの画面が、自分の部品の版と
// 比べるのに使う。画面からは /_live/live-version で届く（next.config.ts の書き換え）。
import { readLiveVersion } from '@/lib/live-version/server';

export const dynamic = 'force-dynamic';

export function GET() {
  return Response.json({ version: readLiveVersion() }, { headers: { 'Cache-Control': 'no-store' } });
}
