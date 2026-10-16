// 今動いているダッシュボードのビルド名。開いたままのタブが、自分を描いたビルドと比べて
// 入れ替わりに気づくのに使う（components/layout/new-build-notice.tsx）。
export const dynamic = 'force-dynamic';

export function GET() {
  return Response.json(
    // 起動時の値を読む（NEXT_PUBLIC_* はビルドに焼き込まれてしまうので使わない）。
    { build: process.env['NEXT_DIST_DIR'] || '' },
    { headers: { 'Cache-Control': 'no-store' } },
  );
}
