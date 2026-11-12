// 「制作」ボタン: 押した瞬間に別の窓を開き、まず「ダン 制作」の起動画面を出してから、同じ窓でエディターを読み込む
// （2026-11-11 本人「押した瞬間に何かが立ち上がってほしい。DaVinci Resolve の起動画面のように」）。
// 起動画面は空の窓に直接書くので、通信を待たずに出る。続けて読み込むエディターの画面は、自分の画面が描けるまで
// この起動画面を残す（ブラウザは新しいページが描けるまで前の画面を出したまま）。エディター側の待ち画面も同じ見た目。

export const EDITOR_SPLASH_BG = '#0b0d12';

export function editorSplashHtml(): string {
  return `<!doctype html><html lang="ja"><head><meta charset="utf-8"><title>ダン 制作</title>
<style>
html,body{margin:0;height:100%;background:${EDITOR_SPLASH_BG};color:#e8eaf0;font-family:-apple-system,"Hiragino Sans","Yu Gothic UI","Meiryo",sans-serif}
.w{height:100%;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:18px}
.t{font-size:34px;font-weight:700;letter-spacing:.06em}.t span{color:#7aa2ff}
.s{font-size:13px;color:#8a90a0}
.bar{width:220px;height:3px;border-radius:2px;background:#1d2230;overflow:hidden}
.bar i{display:block;width:40%;height:100%;background:#7aa2ff;border-radius:2px;animation:m 1.1s ease-in-out infinite}
@keyframes m{0%{transform:translateX(-100%)}100%{transform:translateX(250%)}}
</style></head><body><div class="w"><div class="t">ダン <span>制作</span></div><div class="bar"><i></i></div><div class="s">エディターを開いています…</div></div></body></html>`;
}

/**
 * チャットの本文のリンクが制作エディターの作品を指すか（/production-workspace?room_id=…&content_id=…、
 * 住所つきの https://dan.paina.info/production-workspace?… も）。指していれば部屋と作品、それ以外は null。
 * チャットはこのリンクを、押すとエディターの窓でその作品のタイムラインを開くサムネにする
 * （2026-11-12 本人「書き出して動画をそのまま貼るんじゃなくて、タイムラインへのリンク、タップしたら開くサムネ」）。
 */
export function editorWorkLink(href: unknown): { roomId: string; contentId: string | null } | null {
  if (typeof href !== 'string') return null;
  const m = /^(?:https:\/\/dan\.paina\.info|https?:\/\/(?:localhost|127\.0\.0\.1)(?::\d+)?)?\/production-workspace\/?\?([^#\s]*)$/i.exec(href.trim());
  if (!m) return null;
  const q = new URLSearchParams(m[1]);
  const roomId = q.get('room_id') || '';
  if (!/^[0-9a-f-]{8,}$/i.test(roomId)) return null;
  const contentId = q.get('content_id');
  return { roomId, contentId: contentId && /^[0-9a-f-]{8,}$/i.test(contentId) ? contentId : null };
}

/** エディターの窓を開く。contentId を渡すとその作品のタイムラインを開く（同じ部屋の窓が別の作品やライブラリなら、その窓で開き直す） */
export function openEditorWindow(roomId: string, contentId?: string | null): void {
  const url = `/production-workspace?room_id=${encodeURIComponent(roomId)}${contentId ? `&content_id=${encodeURIComponent(contentId)}` : ''}`;
  const name = `dan-editor-${roomId.slice(0, 8)}`;
  const w = Math.max(1100, window.screen.availWidth || 1440);
  const h = Math.max(700, window.screen.availHeight || 900);
  // 既に同じ部屋のエディターの窓があれば、読み直さずに前に出すだけ（作業中の画面を消さない）
  const win = window.open('', name, `popup=yes,width=${w},height=${h},left=0,top=0`);
  if (!win) {
    window.location.href = url;   // 窓を開けない環境（ポップアップの禁止）では、この画面で開く
    return;
  }
  let alreadyOpen = false;
  try {
    alreadyOpen = win.location.pathname === '/production-workspace'
      && (!contentId || new URLSearchParams(win.location.search).get('content_id') === contentId);
  } catch {
    alreadyOpen = false;
  }
  if (!alreadyOpen) {
    if (win.location.href === 'about:blank') {
      win.document.open();
      win.document.write(editorSplashHtml());
      win.document.close();
    }
    win.location.replace(url);
  }
  win.focus();
}
