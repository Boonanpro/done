/**
 * /chat 配下の layout。外枠（サイドバー + メインペイン）はルートの AppShell が
 * 全ダッシュボード共通で一度だけマウントするので、ここは素通しでよい。
 * URL→ストア同期・認証ゲートも AppShell に移した。
 */
export default function ChatLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
