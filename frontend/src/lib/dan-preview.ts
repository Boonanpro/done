/**
 * ダンのライブプレビュー（チャット右側ペイン）で成果物が描画されているかを判定する。
 *
 * 成果物がこれを見て true の時は、ログイン/初期設定などの「初回ゲート」をスキップし、
 * 管理者として全画面を自由に閲覧・編集できるようにする（プレビュー専用バイパス）。
 *
 * 判定は2系統（どちらかが真ならプレビュー扱い）:
 *  1. iframe 内で動いているか — プレビューペインは必ず iframe 経由で成果物を読み込む
 *  2. URL に ?dan_preview=1 が付いているか — preview-pane.tsx が iframe src に付与する明示信号
 *
 * 公開ページ（実ユーザー）はトップウィンドウで開かれ、このクエリも付かないので
 * false になり、通常どおり初回ゲートが表示される。
 *
 * 注意: これは認証境界ではない。ゲートを跨いでも保存済み認証情報が無ければ実処理
 * （例: サロンボードへの自動投稿）は動かないため、バイパス＝閲覧/編集の解放に留まる。
 */
export const DAN_PREVIEW_PARAM = 'dan_preview';

export function isDanPreview(): boolean {
  if (typeof window === 'undefined') return false;

  let inIframe = false;
  try {
    inIframe = window.top !== window.self;
  } catch {
    // クロスオリジン埋め込みで window.top にアクセスすると例外 → iframe 内とみなす
    inIframe = true;
  }

  let flagged = false;
  try {
    flagged = new URLSearchParams(window.location.search).has(DAN_PREVIEW_PARAM);
  } catch {
    flagged = false;
  }

  return inIframe || flagged;
}
