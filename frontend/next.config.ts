import type { NextConfig } from 'next';
import withPWA from 'next-pwa';

const nextConfig: NextConfig = {
  reactStrictMode: true,
  compress: false, // SSE ストリーミングのバッファリング防止
  turbopack: {},
  async rewrites() {
    return [
      {
        // API リクエストをバックエンドにプロキシ
        // スマホ HTTPS → Next.js HTTPS → バックエンド HTTP（混合コンテンツ回避）
        source: '/api/:path*',
        destination: 'http://127.0.0.1:8000/api/:path*',
      },
      {
        // WebSocket をバックエンドにプロキシ（同一オリジン化）
        source: '/ws/:path*',
        destination: 'http://127.0.0.1:8000/ws/:path*',
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
