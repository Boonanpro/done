// next.config.ts の resolveAlias が、開発サーバーでは current.gen.ts、それ以外では stub.ts に向ける。
declare module 'dan-live-version' {
  export const LIVE_VERSION: string;
}
