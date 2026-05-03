import type { NextConfig } from 'next';
import withPWA from 'next-pwa';

// 静的アセットのキャッシュバスト用バージョン文字列を build-time に決定する。
// Vercel では VERCEL_GIT_COMMIT_SHA が自動付与される。ローカル dev ではタイムスタンプ。
// 各 page で `process.env.NEXT_PUBLIC_ASSET_VERSION` を参照して使う。
const ASSET_VERSION =
  process.env.VERCEL_GIT_COMMIT_SHA?.slice(0, 8) ||
  process.env.NEXT_PUBLIC_ASSET_VERSION ||
  `dev-${Date.now()}`;

const nextConfig: NextConfig = {
  reactStrictMode: true,
  compress: false, // SSE ストリーミングのバッファリング防止
  devIndicators: false,
  turbopack: {},
  env: {
    NEXT_PUBLIC_ASSET_VERSION: ASSET_VERSION,
  },
  images: {
    dangerouslyAllowSVG: true,
    contentSecurityPolicy:
      "default-src 'self'; script-src 'none'; sandbox;",
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
        source: '/',
        has: [{ type: 'host', value: 'kittoku-tokuso.vercel.app' }],
        destination: '/artifacts/kittoku',
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
