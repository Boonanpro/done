declare module 'next-pwa' {
  import type { NextConfig } from 'next';

  interface PWAConfig {
    dest?: string;
    register?: boolean;
    skipWaiting?: boolean;
    disable?: boolean;
    runtimeCaching?: import('workbox-build').RuntimeCaching[];
  }

  export default function withPWA(config: PWAConfig): (nextConfig: NextConfig) => NextConfig;
}

declare module 'next-pwa/cache' {
  const caching: import('workbox-build').RuntimeCaching[];
  export default caching;
}
