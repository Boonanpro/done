import type { NextConfig } from 'next';
import withPWA from 'next-pwa';

import { CUSTOM_DOMAIN_REWRITES } from './src/lib/custom-domain-rewrites.generated';

// 静的アセットのキャッシュバスト用バージョン文字列を build-time に決定する。
// Vercel では VERCEL_GIT_COMMIT_SHA が自動付与される。ローカル dev ではタイムスタンプ。
// 各 page で `process.env.NEXT_PUBLIC_ASSET_VERSION` を参照して使う。
const ASSET_VERSION =
  (process.env.VERCEL_GIT_COMMIT_SHA?.slice(0, 8) ||
    process.env.NEXT_PUBLIC_ASSET_VERSION ||
    `dev`) + `-${Date.now()}`;

const nextConfig: NextConfig = {
  reactStrictMode: true,
  compress: false, // SSE ストリーミングのバッファリング防止
  devIndicators: false,
  turbopack: {},
  experimental: {
    // middleware(proxy) があると Next がリクエストボディをバッファし、
    // デフォルト10MBで打ち切る（超過分は欠落→バックエンドへのproxyが
    // socket hang up で 500 になる）。チャット添付はバックエンド側が
    // 500MB 上限なので、proxy層がボトルネックにならない値にする。
    proxyClientMaxBodySize: '550mb',
  },
  env: {
    NEXT_PUBLIC_ASSET_VERSION: ASSET_VERSION,
  },
  images: {
    dangerouslyAllowSVG: true,
    localPatterns: [
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
    return [
      {
        source: '/:path((?!_next/static|_next/image|api/|ws/).*)',
        headers: [
          { key: 'Cache-Control', value: 'no-cache, must-revalidate' },
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
    const backendUrl = process.env.BACKEND_URL || 'http://127.0.0.1:8000';
    // ダンコア(チャット・認証・ボイス) の URL。dev はデフォルトで 9000、
    // 本番は CORE_BACKEND_URL を別途設定する想定。未設定なら BACKEND_URL に
    // フォールバック（旧アーキの単一プロセスでも動くように）。
    const coreBackendUrl =
      process.env.CORE_BACKEND_URL || 'http://127.0.0.1:9000';
    return [
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
      // 接続済み独自ドメインの host条件付き rewrite（DB由来で自動生成）。
      // 配列末尾＝filesystem ルートと先行 rewrite の後に評価されるので、クリーンパス
      // (/business 等)だけを成果物配下に振り向ける（/robots.txt /sitemap.xml /_next
      // /api /artifacts は先に解決され影響しない）。
      ...CUSTOM_DOMAIN_REWRITES,
    ];
  },
};

const withPwa = withPWA({
  dest: 'public',
  register: true,
  skipWaiting: true,
  disable: process.env.NODE_ENV === 'development',
});

export default withPwa(nextConfig);
