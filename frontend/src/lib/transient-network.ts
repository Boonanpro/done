/**
 * 通信が一時的に切れただけかどうか（ブラウザごとの文言で見分ける）。
 *
 * ダンへの送信の返事は1本の通信で流れてくる。途中で画面のサーバーや本体が再起動すると切れるが、
 * ダンの作業はサーバーで続き、返事は新着の線で届く。切れただけならエラーとして見せず、作業中の表示を
 * 保ったまま取り直す（api-client の sendMessageStream → onInterrupted）。
 *
 * 2026-10-14: Chrome は流れている途中の切断を "network error"（空白あり）と言う。一覧に Firefox の
 * "NetworkError" しか無く、画面右下に「network error」が出て、作業中の表示も消えていた。
 */
export function isTransientNetworkError(message?: string): boolean {
  if (!message) return false;
  const m = message.toLowerCase();
  return (
    m.includes('network error') ||              // Chrome: 返事の途中で切れた
    m.includes('networkerror') ||               // Firefox
    m.includes('failed to fetch') ||            // Chrome: つながる前に切れた
    m.includes('network request failed') ||
    m.includes('load failed') ||                // iOS Safari
    m.includes('the operation was aborted') ||  // Chrome Android
    m.includes('connection was lost') ||        // Safari generic
    m.includes('network connection') ||         // Android WebView
    m.includes('aborted')                       // fetch abort by OS
  );
}
