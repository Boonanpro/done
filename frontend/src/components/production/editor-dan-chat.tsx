'use client';

// エディターの中の「ダンと制作」（2026-11-11 本人「映像を作るときはここでチャットするんだよ、という画面が欲しい」）。
// ライブラリでは本体の部屋のライブラリの部屋、作品を開くとその作品の部屋で、ふだんのチャット欄と同じ部品で話す
// （文字・音声・画像や動画の貼り付け）。部屋は本体のチャットと分かれ、ダンは本体の部屋の話と記憶を読める
// （app/services/editor_rooms.py）。

import { useEffect, useState } from 'react';
import { ChevronRight, Loader2, MessageSquare } from 'lucide-react';

import { ProjectChatPanel } from '@/components/layout/project-chat-panel';
import { ProductionWorkspace } from '@/components/production/production-workspace';
import { useRoomFeed } from '@/hooks/useRoomFeed';
import { EDITOR_SPLASH_BG } from '@/lib/open-editor-window';

const roomCache = new Map<string, string>();   // `${roomId}:${contentId}` → 制作の部屋の project id

// 制作の窓のライブラリとエディターは、ログインのクッキー（短い寿命）だけで API を呼んでいて、クッキーが切れると
// 「Not authenticated」で何も出なくなっていた。この窓（この部品を読むのは制作の窓だけ）では、ダン本体の画面と同じ
// 端末に残したログインの印を、印を付けていない自分の API の呼び出しに付ける。
if (typeof window !== 'undefined' && !(window as unknown as { __danEditorFetch?: boolean }).__danEditorFetch) {
  (window as unknown as { __danEditorFetch?: boolean }).__danEditorFetch = true;
  const original = window.fetch.bind(window);
  window.fetch = (input: RequestInfo | URL, init?: RequestInit) => {
    try {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
      const sameOriginApi = url.startsWith('/api/') || url.startsWith(window.location.origin + '/api/');
      const token = localStorage.getItem('done-token');
      if (sameOriginApi && token && typeof input === 'string') {
        const headers = new Headers(init?.headers || undefined);
        if (!headers.has('Authorization')) headers.set('Authorization', `Bearer ${token}`);
        return original(input, { ...init, headers });
      }
    } catch {
      /* 付けられない時はそのまま */
    }
    return original(input, init);
  };
}

function authHeaders(): Record<string, string> {
  const token = typeof window !== 'undefined' ? localStorage.getItem('done-token') || '' : '';
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export function EditorSplash() {
  return (
    <div className="flex h-screen flex-col items-center justify-center gap-[18px]" style={{ background: EDITOR_SPLASH_BG, color: '#e8eaf0' }}>
      <div className="text-[34px] font-bold tracking-[.06em]">ダン <span style={{ color: '#7aa2ff' }}>制作</span></div>
      <div className="h-[3px] w-[220px] overflow-hidden rounded-sm" style={{ background: '#1d2230' }}>
        <i className="block h-full w-2/5 animate-[editor-splash_1.1s_ease-in-out_infinite] rounded-sm" style={{ background: '#7aa2ff' }} />
      </div>
      <div className="text-[13px]" style={{ color: '#8a90a0' }}>エディターを開いています…</div>
      <style>{'@keyframes editor-splash{0%{transform:translateX(-100%)}100%{transform:translateX(250%)}}'}</style>
    </div>
  );
}

function EditorDanChat({ roomId, contentId }: { roomId: string; contentId: string | null }) {
  const key = `${roomId}:${contentId || ''}`;
  const [projectId, setProjectId] = useState<string | null>(roomCache.get(key) || null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const cached = roomCache.get(key);
    if (cached) {
      setProjectId(cached);
      return;
    }
    setProjectId(null);
    setFailed(false);
    let cancelled = false;
    fetch('/api/v1/production-assets/editor-room', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify({ room_id: roomId, content_id: contentId }),
    })
      .then(async (res) => {
        if (!res.ok) throw new Error(await res.text());
        const j = (await res.json()) as { project_id?: string };
        if (!j.project_id) throw new Error('no project');
        roomCache.set(key, j.project_id);
        if (!cancelled) setProjectId(j.project_id);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [key, roomId, contentId]);

  if (!projectId) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        {failed ? 'ダンとの会話を開けませんでした。窓を開き直してください。' : (<><Loader2 className="mr-2 h-4 w-4 animate-spin" />ダンを呼んでいます…</>)}
      </div>
    );
  }
  return <ProjectChatPanel key={projectId} projectId={projectId} editorChat />;
}

const OPEN_KEY = 'dan-editor-chat-open';
const WIDTH = 420;

/** 制作の窓の中身: 左にライブラリか作品のタイムライン、右に「ダンと制作」。 */
export function ProductionStudio({ roomId }: { roomId: string }) {
  useRoomFeed(true);   // ダンの返事と作業中の表示をすぐ届ける（ダン本体の画面と同じ受け口）
  const [contentId, setContentId] = useState<string | null>(() =>
    typeof window === 'undefined' ? null : new URLSearchParams(window.location.search).get('content_id'));
  const [open, setOpen] = useState(true);
  useEffect(() => {
    if (localStorage.getItem(OPEN_KEY) === '0') setOpen(false);
    document.title = 'ダン 制作';
  }, []);
  const toggle = (v: boolean) => {
    setOpen(v);
    try { localStorage.setItem(OPEN_KEY, v ? '1' : '0'); } catch {}
  };

  return (
    <div className="flex h-screen min-h-0 w-full overflow-hidden bg-background">
      <div className="min-h-0 min-w-0 flex-1">
        <ProductionWorkspace roomId={roomId} onContentChange={setContentId} />
      </div>
      {open ? (
        <aside className="relative flex h-full shrink-0 flex-col border-l border-border" style={{ width: WIDTH }} aria-label="ダンと制作">
          <button
            type="button"
            onClick={() => toggle(false)}
            className="absolute -left-3 top-1/2 z-20 flex h-12 w-3 items-center justify-center rounded-l border border-r-0 border-border bg-background text-muted-foreground hover:text-foreground"
            title="ダンと制作を閉じる"
          >
            <ChevronRight className="h-3 w-3" />
          </button>
          <div className="min-h-0 flex-1">
            <EditorDanChat roomId={roomId} contentId={contentId} />
          </div>
        </aside>
      ) : (
        <button
          type="button"
          onClick={() => toggle(true)}
          className="flex h-full w-9 shrink-0 flex-col items-center gap-2 border-l border-border bg-muted/30 pt-4 text-xs font-medium text-foreground hover:bg-muted"
          title="ダンと制作を開く"
        >
          <MessageSquare className="h-4 w-4 text-primary" />
          <span style={{ writingMode: 'vertical-rl' }}>ダンと制作</span>
        </button>
      )}
    </div>
  );
}
