import type { NextConfig } from 'next';
import withPWA from 'next-pwa';

const nextConfig: NextConfig = {
  reactStrictMode: true,
  compress: false, // SSE ストリーミングのバッファリング防止
  devIndicators: false,
  turbopack: {},
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
    return [
      {
        source: '/api/:path*',
        destination: `${backendUrl}/api/:path*`,
      },
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
