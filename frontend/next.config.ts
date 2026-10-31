import path from 'node:path';
import { backendUrl as resolveBackendUrl } from './src/lib/backend-url';

import type { NextConfig } from 'next';

import { CUSTOM_DOMAIN_REWRITES, CUSTOM_DOMAIN_SLUG_MAP } from './src/lib/custom-domain-rewrites.generated';
import { publicArtifactRoutingDomains } from './scripts/artifact-routing-config';
import { startLiveVersionWatcher } from './src/lib/live-version/server';

// 成果物タブ用の開発サーバー（3001）か。ここだけ「今のファイルの版」を作り、画面の部品に
// 焼き込む（'dan-live-version' → current.gen.ts）。画面はその版をサーバーの版と比べて、
// 古い部品・HMR の取りこぼしを自分で直す（src/lib/live-version/）。
const LIVE_DEV = process.env.NODE_ENV === 'development' && process.env.NEXT_ASSET_PREFIX === '/_live';
if (LIVE_DEV) startLiveVersionWatcher(process.cwd());
const LIVE_VERSION_MODULE = LIVE_DEV
  ? './src/lib/live-version/current.gen.ts'
  : './src/lib/live-version/stub.ts';

// 静的アセットのキャッシュバスト用バージョン文字列を build-time に決定する。
// Vercel では VERCEL_GIT_COMMIT_SHA が自動付与される。ローカル dev ではタイムスタンプ。
// 各 page で `process.env.NEXT_PUBLIC_ASSET_VERSION` を参照して使う。
const ASSET_VERSION =
  (process.env.VERCEL_GIT_COMMIT_SHA?.slice(0, 8) ||
    process.env.NEXT_PUBLIC_ASSET_VERSION ||
    `dev`) + `-${Date.now()}`;

const nextConfig: NextConfig = {
  // 本番ビルド(ダッシュボード, 3000)と開発サーバー(成果物プレビュー, 3001)を同じ
  // リポジトリで同時に動かすため、出力先を分ける。既定 .next は dev 用。
  distDir: process.env.NEXT_DIST_DIR || '.next',
  // 開発サーバー（3001・成果物のファイルそのまま）は部品を /_live/_next に出す。
  // 本番ビルド（3000）が /preview と /_live をそこへ中継するので、両者の /_next が混ざらない。
  assetPrefix: process.env.NEXT_ASSET_PREFIX || undefined,
  typescript: { tsconfigPath: process.env.NEXT_TSCONFIG || 'tsconfig.json' },
  reactStrictMode: true,
  // 成果物の editorial（/api/voice-note/editorial・artifacts/<slug>/editorial）は process.cwd() で python ワーカーを spawn する
  // ローカル専用ルート。Next のファイルトレースが process.cwd() を見て frontend/ を
  // まるごと同梱し、関数が 1.16GB になって Vercel のビルドが落ちるため除外する。
  outputFileTracingExcludes: {
    '/api/*/editorial': ['**/*'],
    '/artifacts/*/editorial': ['**/*'],
  },
  compress: false, // SSE ストリーミングのバッファリング防止
  devIndicators: false,
  turbopack: {
    resolveAlias: { 'dan-live-version': LIVE_VERSION_MODULE },
  },
  webpack: (config) => {
    config.resolve.alias = {
      ...config.resolve.alias,
      'dan-live-version': path.resolve(process.cwd(), LIVE_VERSION_MODULE),
    };
    return config;
  },
  experimental: {
    // middleware(proxy) があると Next がリクエストボディをバッファし、
    // デフォルト10MBで打ち切る（超過分は欠落→バックエンドへのproxyが
    // socket hang up で 500 になる）。チャット添付はバックエンド側が
    // 500MB 上限なので、proxy層がボトルネックにならない値にする。
    proxyClientMaxBodySize: '550mb',
  },
  env: {
    NEXT_PUBLIC_ASSET_VERSION: ASSET_VERSION,
    NEXT_PUBLIC_ARTIFACT_ROUTING_DOMAINS: JSON.stringify(publicArtifactRoutingDomains(CUSTOM_DOMAIN_SLUG_MAP, process.env)),
  },
  images: {
    dangerouslyAllowSVG: true,
    localPatterns: process.env.ARTIFACT_ONLY_SLUG && process.env.ARTIFACT_ONLY_SLUG !== 'kittoku' ? [] : [
      {
        pathname: '/kikkawa/**',
      },
    ],
    contentSecurityPolicy:
      "default-src 'self'; script-src 'none'; sandbox;",
  },
  async headers() {
    // ダンが生成するサイトやツール、そのアセット（画像/動画等）すべてを
    // 「常に最新」で返すための設定。
    //
    // 仕組み:
    //   no-cache, must-revalidate
    //     → ブラウザは保存はするが、毎リクエスト If-None-Match で origin に確認する。
    //       変わってなければ 304 を返すので帯域コストは小さい。
    //       ファイル差し替え後は次のリクエストで即座に新バイトに切り替わる。
    //
    // 除外:
    //   /_next/static, /_next/image, /api/, /ws/ は別ルールで動いているので触らない。
    //   (_next/* は Next.js がコンテンツハッシュ付きURLで配信し immutable キャッシュ前提)
    //
    // この設定を入れると、Inspector で画像を差し替え → リロード → 即時反映される。
    // ASSET_VERSION の dev 起動時刻固定問題（dev サーバー再起動まで古い画像が残る）も解消する。
    //
    // /_live/*（成果物タブが映す開発サーバーの部品）だけは no-store にする。
    // 部品のファイル名は直しても変わらないのに、Cloudflare が no-cache を
    // max-age=14400 に書き換えるので、開いていたブラウザが最大4時間古い部品を使い続けた
    // （2026-10-18 実測）。no-store は書き換えられない。
    return [
      {
        source: '/:path((?!_next/static|_next/image|_live/|api/|ws/).*)',
        headers: [
          { key: 'Cache-Control', value: 'no-cache, must-revalidate' },
        ],
      },
      {
        source: '/_live/:path*',
        headers: [
          { key: 'Cache-Control', value: 'no-store, must-revalidate' },
        ],
      },
    ];
  },
  async rewrites() {
    // 本番 (Vercel 等) は自宅 PC を指せないので Cloudflare tunnel 等の
    // 公開 URL へ proxy する。BACKEND_URL 環境変数で指定、なければ localhost。
    // Vercel ダッシュボード: Settings → Environment Variables で
    //   BACKEND_URL=https://xxx.trycloudflare.com
    // を設定する。tunnel URL が変わったら env 値を更新して再デプロイ。
    const backendUrl = resolveBackendUrl('sandbox');
    // ダンコア(チャット・認証・ボイス) の URL。dev はデフォルトで 9000、
    // 本番は CORE_BACKEND_URL を別途設定する想定。未設定なら BACKEND_URL に
    // フォールバック（旧アーキの単一プロセスでも動くように）。
    const coreBackendUrl =
      resolveBackendUrl('core');
    return [
      // 成果物タブの画面が版を比べる・知らせる先（src/lib/live-version/guard.ts）。
      // 画面からは /_live/* で来るので、ダッシュボード（3000）がこの開発サーバーへ中継する。
      ...(LIVE_DEV
        ? [
            { source: '/_live/live-version', destination: '/dan-live/version' },
            { source: '/_live/live-view', destination: '/dan-live/view' },
          ]
        : []),
      {
        source: '/preview/:path*',
        destination: '/artifacts/:path*',
      },
      // ダンコア向け: 具体的な path を先に評価させる
      {
        source: '/api/v1/chat/:path*',
        destination: `${coreBackendUrl}/api/v1/chat/:path*`,
      },
      {
        source: '/api/v1/voice/:path*',
        destination: `${coreBackendUrl}/api/v1/voice/:path*`,
      },
      {
        source: '/api/v1/credentials/:path*',
        destination: `${coreBackendUrl}/api/v1/credentials/:path*`,
      },
      {
        source: '/api/v1/credentials',
        destination: `${coreBackendUrl}/api/v1/credentials`,
      },
      {
        source: '/api/v1/public-chat/:path*',
        destination: `${coreBackendUrl}/api/v1/public-chat/:path*`,
      },
      // ダンコア管理API (内部用だが念のため)
      {
        source: '/api/v1/sandbox/:path*',
        destination: `${coreBackendUrl}/api/v1/sandbox/:path*`,
      },
      // Realtime 音声レイヤー (gpt-realtime-2 ephemeral トークン発行)
      {
        source: '/api/v1/realtime/:path*',
        destination: `${coreBackendUrl}/api/v1/realtime/:path*`,
      },
      // 「今日やったこと」台帳はダンコア (ポーラーと同居)
      {
        source: '/api/v1/achievements',
        destination: `${coreBackendUrl}/api/v1/achievements`,
      },
      {
        source: '/api/v1/achievements/:path*',
        destination: `${coreBackendUrl}/api/v1/achievements/:path*`,
      },
      // ダン開発の物語 (静的HTMLをダンコア経由で配信)
      {
        source: '/api/v1/story',
        destination: `${coreBackendUrl}/api/v1/story`,
      },
      {
        source: '/api/v1/story/:path*',
        destination: `${coreBackendUrl}/api/v1/story/:path*`,
      },
      // 成果物アプリを外から開く入口（例: スマホアプリが叩く /api/x-operation/open）。
      // 処理は成果物自身の artifacts/<slug>/open/route.ts にあり、ダン本体には置かない。
      {
        source: '/api/:slug((?!v1$)[a-z0-9-]+)/open',
        destination: '/artifacts/:slug/open',
      },
      // 上記以外の /api/* は業務系サンドボックスへ
      {
        source: '/api/:path*',
        destination: `${backendUrl}/api/:path*`,
      },
      // ボイス系 WebSocket はダンコアへ
      {
        source: '/ws/voice',
        destination: `${coreBackendUrl}/ws/voice`,
      },
      {
        source: '/ws/voice/:path*',
        destination: `${coreBackendUrl}/ws/voice/:path*`,
      },
      {
        source: '/ws/gemini-voice',
        destination: `${coreBackendUrl}/ws/gemini-voice`,
      },
      {
        source: '/ws/gemini-voice/:path*',
        destination: `${coreBackendUrl}/ws/gemini-voice/:path*`,
      },
      // Realtime delegate ブリッジ WebSocket (gpt-realtime-2 → 実行エンジン)
      {
        source: '/ws/realtime-delegate',
        destination: `${coreBackendUrl}/ws/realtime-delegate`,
      },
      // 上記以外の WebSocket は業務系サンドボックスへ
      {
        source: '/ws/:path*',
        destination: `${backendUrl}/ws/:path*`,
      },
      // 吉川特装HP専用ドメイン: ルート(/)だけ /artifacts/kittoku にマップする。
      // 内部リンクは /artifacts/kittoku/... 形式なのでそのまま動く。
      {
        source: '/',
        has: [{ type: 'host', value: 'kittoku.vercel.app' }],
        destination: '/artifacts/kittoku',
      },
      {
        source: '/v2',
        has: [{ type: 'host', value: 'kittoku.vercel.app' }],
        destination: '/artifacts/kittoku/v2',
      },
      {
        source: '/:path(services|company|careers|contact)',
        has: [{ type: 'host', value: 'kittoku.vercel.app' }],
        destination: '/artifacts/kittoku/:path',
      },
      {
        source: '/',
        has: [{ type: 'host', value: 'yoshikawa-tokuso.vercel.app' }],
        destination: '/artifacts/kittoku',
      },
      {
        source: '/:path(v2|services|company|careers|contact)',
        has: [{ type: 'host', value: 'yoshikawa-tokuso.vercel.app' }],
        destination: '/artifacts/kittoku/:path',
      },
      // 吉川特装HP: /kikkawa-tokuso 短縮パスは /artifacts/kittoku にエイリアス
      {
        source: '/kikkawa-tokuso',
        destination: '/artifacts/kittoku',
      },
      {
        source: '/kikkawa-tokuso/:path*',
        destination: '/artifacts/kittoku/:path*',
      },
      // 専用配信プロジェクト（1 プロジェクト = 1 成果物）の子ページ。
      //
      // middleware は `/` だけを成果物直下へ rewrite し、サブパスは
      // 「filesystem 側に任せる」として素通ししている。ところが専用
      // プロジェクトには /download や /legal という実ルートが無い（実体は
      // /artifacts/<slug>/download）ので、ここが無いと**トップだけ開いて
      // 子ページが全部 404** になる。独自ドメインを繋いだ成果物は
      // CUSTOM_DOMAIN_REWRITES が同じ役目を果たすが、専用URLのままの
      // 成果物には対応するものが無かった。
      //
      // rewrites() の配列は afterFiles として評価されるため、/_next・/api・
      // /artifacts・public 配下の実ファイルはここへ来る前に解決される。
      ...(process.env.ARTIFACT_ONLY_SLUG?.trim()
        ? [
            {
              source: '/:path+',
              destination: `/artifacts/${process.env.ARTIFACT_ONLY_SLUG.trim()}/:path+`,
            },
          ]
        : []),
      // 接続済み独自ドメインの host条件付き rewrite（DB由来で自動生成）。
      // 配列末尾＝filesystem ルートと先行 rewrite の後に評価されるので、クリーンパス
      // (/business 等)だけを成果物配下に振り向ける（/robots.txt /sitemap.xml /_next
      // /api /artifacts は先に解決され影響しない）。
      ...CUSTOM_DOMAIN_REWRITES,
    ];
  },
};

export default nextConfig;
