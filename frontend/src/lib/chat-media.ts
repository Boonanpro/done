/**
 * チャットの吹き出しの添付（画像・動画・ファイル）の読み取りと、画像・動画を読む時の決まり（ブラウザの画面）。
 * project-chat-panel の吹き出しと作業の途中の文章、本文の Markdown の画像、media-grid、media-viewer が使う。
 *
 * 読み取り（parseMediaContent）:
 * - 添付の印 [添付画像: …]・[添付動画: 名前 (URL)]・[添付ファイル: 名前 (URL)] を抜き出す。一番外側のコードブロック
 *   （部品の ```openui-lang も、ほかの言語も）の中は読まない（plain.ts splitTopFences）。部品の名前や画像の値に書いた
 *   印を、部品を読む前に抜き出して部品の外へ画像として出していた（2026-10-17、確かめる役の VERIFY8 新P1-1）。
 * - 画像・動画の URL は、部品の縮小画像と同じ許可の境界（plain.ts safeImageUrl）を通った物だけ: ダンのファイル
 *   （/api/v1/files/<名前>）と https:// の外の物。通らない印は読みに行かず、文字のまま残す。
 * - 画面で再生する動画はダンのファイルだけ（<video> には Referer を止める属性が無い）。外の動画はファイルのリンクにする。
 *
 * 読む時の決まり（imageRequest）: 外の画像は Cookie を送らない要求（crossOrigin=anonymous）で、Referer も送らない。
 * CORS に応じない外の画像は読めないので、使う側が枠ごと消す（壊れた画像の印を出さない）。画面の道（ダンのファイル）は
 * 今までどおり同じサイトの要求（ログインの Cookie つき）。
 *
 * 依存は plain.ts だけ（拡張子つきで読み込む: node:test からも Next からも同じ形で読める）。
 */
import { safeImageUrl, splitTopFences } from './chat-shapes/plain.ts';

export type ParsedMedia = { images: string[]; videos: string[]; files: { name: string; url: string }[]; text: string };

/** この画面のホスト（例 dan.paina.info）。サーバーで描く時は null */
export function pageHost(): string | null {
  return typeof window !== 'undefined' ? window.location.host : null;
}

/** この画面のオリジンの道（/ で始まり、// や /\ ではない）か。それ以外（https://… など）は外の物として読む */
export function isPagePath(url: string): boolean {
  return /^\/(?![/\\])/.test(url);
}

/** 画像を読む <img> に足す属性。外の画像は Cookie を送らない・Referer なし。画面の道には何も足さない（今までどおり） */
export function imageRequest(url: string): { crossOrigin?: 'anonymous'; referrerPolicy?: 'no-referrer' } {
  return isPagePath(url) ? {} : { crossOrigin: 'anonymous', referrerPolicy: 'no-referrer' };
}

/** 画面で再生してよい動画か: 画面の道（ダンのファイル）だけ。外の動画を <video> で読むと Referer が付く */
export function playableVideo(url: string): boolean {
  return isPagePath(url);
}

const FILE_PATH = /\/api\/v1\/files\/[^?#\s)]+/;
const LOCAL_FILE = /^https?:\/\/(?:localhost|127\.0\.0\.1)(?::\d+)?(?=\/api\/v1\/files\/)/i;

/**
 * 本文の Markdown の画像・リンクの URL を、画面で読む URL にする（通らなければ null）。この PC の中だけで通じる住所の
 * ダンのファイル（http://localhost:8000/api/v1/files/…）は道に直す（app/services/message_media.py の portable と同じ）。
 */
export function chatImageUrl(raw: unknown, host: string | null = pageHost()): string | null {
  if (typeof raw !== 'string') return null;
  return safeImageUrl(raw.trim().replace(LOCAL_FILE, ''), host);
}

/**
 * [添付画像: …] の中身 → 画面で読む URL（通らなければ null）。中の書き方の揺れ（「名前 (URL)」・URL・道・C:\…\x.png・x.png）は
 * 今までどおり読む: http(s) の URL の中にダンのファイルの道があればその道、ファイル名だけなら /api/v1/files/<名前>。
 */
function attachedImageUrl(raw: string, host: string | null): string | null {
  const urlMatch = raw.match(/https?:\/\/\S+|\/api\/\S+/);
  // 末尾の記号（`)` `,` `.` `;` `"` `'`）を剥がす
  const token = (urlMatch ? urlMatch[0] : raw.trim().split(/\s+/).pop() || '').trim().replace(/[)\],.;"'`]+$/, '');
  if (/^https?:\/\//.test(token)) return safeImageUrl(token.match(FILE_PATH)?.[0] ?? token, host);
  if (token.startsWith('/api/')) return safeImageUrl(token, host);
  const filename = token.replace(/\\/g, '/').split('/').pop();
  return filename ? safeImageUrl(`/api/v1/files/${filename}`, host) : null;
}

/** [添付動画: 名前 (URL)] などの URL → ダンのファイルの道か外の https の URL（通らなければ null） */
function attachedFileUrl(raw: string, host: string | null): string | null {
  const t = raw.trim();
  return safeImageUrl(/^https?:\/\//i.test(t) ? (t.match(FILE_PATH)?.[0] ?? t) : t, host);
}

const VIDEO_NAME = /\.(mp4|avi|mov|mkv|webm)$/i;

/**
 * 吹き出しの文章から添付を抜き出し、残りの文章と分ける。host はこの画面のホスト（safeImageUrl へ。試験では渡す）。
 * システムが本人の発言に付ける包み（ダンへの文脈・動画の分析結果）は今までどおり文章全体から外す。
 */
export function parseMediaContent(content: string, host: string | null = pageHost()): ParsedMedia {
  const images: string[] = [];
  const videos: string[] = [];
  const files: { name: string; url: string }[] = [];
  const video = (whole: string, name: string, url: string) => {
    const u = attachedFileUrl(url, host);
    if (!u) return whole;
    if (playableVideo(u)) videos.push(u);
    else files.push({ name, url: u });
    return '';
  };
  const read = (s: string) => s
    .replace(/\[添付画像: ([^\]]+)\]/g, (whole, raw: string) => {
      const u = attachedImageUrl(raw, host);
      if (!u) return whole;
      images.push(u);
      return '';
    })
    .replace(/\[添付動画: (.+?) \((.+?)\)\](?:\s*※分析に失敗しました)?/g, video)
    .replace(/\[添付ファイル: (.+?) \((.+?)\)\]/g, (whole, name: string, url: string) => {
      const u = VIDEO_NAME.test(name) ? attachedFileUrl(url, host) : null;
      if (u && playableVideo(u)) videos.push(u);
      else files.push({ name, url });
      return '';
    });
  const unwrapped = content
    .replace(/<dan-context>[\s\S]*?<\/dan-context>/g, '')
    .replace(/\[動画分析結果\(Gemini\):\n[\s\S]*?\n\]/g, '');
  const text = splitTopFences(unwrapped).map((p) => (p.code ? p.text : read(p.text))).join('').trim();
  return { images, videos, files, text };
}

// 文章の中の、ファイル・画像・動画の印（parseMediaContent と本文の Markdown が表示に変えるもの）
const MEDIA_TAG = /!\[[^\]]*\]\([^)]+\)|\[添付(?:画像|動画|ファイル): [^\]]+\]/g;

/** 文章の中の添付の印と Markdown の画像を、順に返す。一番外側のコードブロック（部品を含む）の中は見ない */
export function mediaTags(text: string): string[] {
  return splitTopFences(text).flatMap((p) => (p.code ? [] : p.text.match(MEDIA_TAG) || []));
}
