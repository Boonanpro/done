// チャットに貼った画像・動画・音・ファイルを、エディターのタイムラインへ引きずって入れる印（2026-11-26 本人
// 「ドラッグアンドドロップでも入れれるようにして」）。チャットの側が引きずり始めに付け、タイムラインの側が読む。
// 引きずっている間は中身を読めない（HTML5 の決まり）ので、置く所の影を出すために window にも置く。

export const DAN_FILE_DND_TYPE = 'application/x-dan-file';

export type DanDragFile = { url: string; name: string };

declare global {
  interface Window { __danDragFile?: DanDragFile }
}

const VIDEO = /\.(?:mp4|mov|m4v|webm|mkv|avi|mts|m2ts)$/i;
const IMAGE = /\.(?:png|jpe?g|gif|webp|heic|bmp|tiff?)$/i;
const AUDIO = /\.(?:wav|mp3|m4a|aac|flac|ogg|opus|aiff?|caf)$/i;

/** ファイルの名前（か URL）から、タイムラインに置ける種類。置けない物は null。 */
export function mediaKindOfName(name: string, mime = ''): 'video' | 'image' | 'audio' | null {
  const n = String(name || '').split('?')[0];
  if (VIDEO.test(n) || mime.startsWith('video/')) return 'video';
  if (IMAGE.test(n) || mime.startsWith('image/')) return 'image';
  if (AUDIO.test(n) || mime.startsWith('audio/')) return 'audio';
  return null;
}

/** ダンのファイル（/api/v1/files/…）なら、その道。 */
export function danFilePath(url: string): string | null {
  try {
    const u = new URL(url, typeof window !== 'undefined' ? window.location.href : 'http://x');
    return u.pathname.startsWith('/api/v1/files/') ? u.pathname : null;
  } catch {
    return null;
  }
}

/** チャットの添付の引きずり始め。ダンのファイルでなければ何もしない（ふつうのリンクの引きずりのまま）。 */
export function startDanFileDrag(event: { dataTransfer: DataTransfer }, file: DanDragFile): void {
  const path = danFilePath(file.url);
  if (!path) return;
  const payload: DanDragFile = { url: path, name: file.name || decodeURIComponent(path.split('/').pop() || '') };
  event.dataTransfer.setData(DAN_FILE_DND_TYPE, JSON.stringify(payload));
  event.dataTransfer.effectAllowed = 'copy';
  window.__danDragFile = payload;
}

export function endDanFileDrag(): void {
  delete window.__danDragFile;
}
