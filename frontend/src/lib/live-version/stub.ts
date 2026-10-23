// 本番ビルドと Vercel の専用サイトで読まれる版（空なら画面の版の比較をしない）。
// 開発サーバー（3001）では next.config.ts が 'dan-live-version' を current.gen.ts に向ける。
export const LIVE_VERSION = '';
