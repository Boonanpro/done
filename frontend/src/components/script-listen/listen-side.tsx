'use client';

// 台本を聞く画面の横の2つ（2026-11-20 本人）:
// - ListenChat: 右の「ダンと台本」。コメントとは別の、常にいる会話（「台本エディターにもチャットいる。コメント機能だけじゃなくて
//   常駐のチャットみたいなやつ」）。台本1本に1部屋（app/services/script_rooms.py）。ふだんのチャット欄と同じ部品で、文字・音声・
//   画像の貼り付けができる。ダンには本人のカーソルの文・選んだ文字が「ここ」として届く。
// - ListenThumb: 上のサムネを押すと、動画エディターと同じサムネの編集（部品・ペンで書き込んでダンに直させる・仕上げ）がその場で
//   開く（「ダンと一緒にサムネ編集して仕上げたりしたい」）。閉じると、直した形が Google ドキュメントの絵にも入る
//   （app/services/script_listen_thumbs.py）。

import { useEffect, useState, type ReactNode } from 'react';
import { Loader2 } from 'lucide-react';
import { toast } from 'sonner';

import { ProjectChatPanel } from '@/components/layout/project-chat-panel';
import { ThumbnailEditor } from '@/components/thumbnail/thumbnail-editor';
import { useRoomFeed } from '@/hooks/useRoomFeed';
import { errorText, listenApi } from '@/lib/script-listen-api';

// サムネの編集と会話の欄は、ログインの印を付けずに自分の API を呼ぶ（クッキーだけ）。クッキーが切れていても動くよう、
// この画面と同じ端末に残したログインの印を付ける（制作の窓 editor-dan-chat.tsx と同じ）。
function useBearerFetch() {
  useEffect(() => {
    const w = window as unknown as { __danListenFetch?: boolean };
    if (w.__danListenFetch) return;
    w.__danListenFetch = true;
    const original = window.fetch.bind(window);
    window.fetch = (input: RequestInfo | URL, init?: RequestInit) => {
      try {
        const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
        const token = localStorage.getItem('done-token');
        if (token && typeof input === 'string' && (url.startsWith('/api/') || url.startsWith(window.location.origin + '/api/'))) {
          const headers = new Headers(init?.headers || undefined);
          if (!headers.has('Authorization')) headers.set('Authorization', `Bearer ${token}`);
          return original(input, { ...init, headers });
        }
      } catch { /* そのまま */ }
      return original(input, init);
    };
  }, []);
}

const roomCache = new Map<string, string>();

export function ListenChat({ docId, lead }: { docId: string; lead?: ReactNode }) {
  useBearerFetch();
  useRoomFeed(true);   // ダンの返事と作業中の表示をすぐ届ける
  const [projectId, setProjectId] = useState<string | null>(roomCache.get(docId) || null);
  const [failed, setFailed] = useState('');
  useEffect(() => {
    if (roomCache.get(docId)) return;
    let live = true;
    listenApi.room(docId)
      .then(r => { roomCache.set(docId, r.project_id); if (live) setProjectId(r.project_id); })
      .catch(e => { if (live) setFailed(errorText(e)); });
    return () => { live = false; };
  }, [docId]);
  return (
    <div data-testid="script-chat" className="flex h-full min-h-0 flex-col bg-background">
      {projectId ? (
        <ProjectChatPanel key={projectId} projectId={projectId} editorChat editorHeaderLead={lead}
          emptyHint="この台本のことを、ここに書くか上の「話す」で話してください。カーソルのある文や選んだ文字は、ダンにも見えています。" />
      ) : (
        <div className="flex h-full items-center justify-center px-4 text-center text-sm text-muted-foreground">
          {failed ? `ダンとの会話を開けませんでした（${failed}）` : (<><Loader2 className="mr-2 h-4 w-4 animate-spin" />ダンを呼んでいます…</>)}
        </div>
      )}
    </div>
  );
}

export type ThumbTarget = { order: number; object: string | null };

export function ListenThumb({ docId, target, title, compact, phoneChat, onClose }: {
  docId: string;
  target: ThumbTarget;
  title: string;
  compact: boolean;
  phoneChat?: ((lead: ReactNode) => ReactNode) | null;
  onClose: (changed: boolean) => void;
}) {
  useBearerFetch();
  const [work, setWork] = useState<{ room_id: string; content_id: string } | null>(null);
  const [failed, setFailed] = useState('');
  useEffect(() => {
    let live = true;
    listenApi.thumbOpen(docId, target.object, target.order)
      .then(w => { if (live) setWork(w); })
      .catch(e => { if (live) setFailed(errorText(e)); });
    return () => { live = false; };
  }, [docId, target.object, target.order]);

  const close = () => {
    if (!work) { onClose(false); return; }
    onClose(true);
    // 直した形をドキュメントの絵に（変わっていなければ何もしない）。書き出しに数秒かかるので待たずに閉じる
    listenApi.thumbSync(docId, work.content_id)
      .then(r => { if (r.changed) toast.success('ドキュメントのサムネも差し替えました'); })
      .catch(e => toast.error(`ドキュメントのサムネを差し替えられませんでした（${errorText(e)}）`));
  };

  if (!work) {
    return (
      <div className="flex h-full items-center justify-center bg-background text-sm text-muted-foreground">
        {failed
          ? <div className="space-y-3 text-center"><div>サムネを開けませんでした（{failed}）</div>
              <button type="button" onClick={() => onClose(false)} className="rounded-md border border-border px-3 py-1.5">台本に戻る</button></div>
          : <><Loader2 className="mr-2 h-4 w-4 animate-spin" />サムネを開いています…</>}
      </div>
    );
  }
  return (
    <ThumbnailEditor
      key={work.content_id}
      roomId={work.room_id}
      contentId={work.content_id}
      title={title}
      compact={compact}
      phoneChat={phoneChat}
      backLabel="台本に戻る"
      onBack={close}
    />
  );
}
