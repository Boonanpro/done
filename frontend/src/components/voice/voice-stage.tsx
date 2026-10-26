'use client';

/**
 * The stage of a call: the caption 「今の話: …」 and the scene the server draws while Dan talks (app/services/voice_stage.py).
 *
 * A scene is one of three things: an answer-shapes program (the same ```openui-lang parts as the chat: Flow, Stat, Compare,
 * Chart…, drawn with ShapeBlock), a free drawing (SVG/HTML the server cleaned, drawn in a sandboxed frame with no scripts
 * and its own origin) or an image (one of Dan's files or an https URL; a photograph of a real page has its URL too).
 * It arrives by long poll (GET /api/v1/voicelog/stage/<room>?after=<version>): the server answers the moment a newer
 * version exists, when the call ends, or after ~25 s. A program that fails the parts' validation is not shown; the
 * previous scene stays (checkCompleteShape).
 *
 * Only a new scene slides in. A version that changes the caption alone updates the caption in place and leaves the scene
 * untouched (2026-10-26: every caption change remounted the scene and replayed its entrance, 9 times in one call).
 *
 * Used by the PC voice panel (voice-session.tsx) and, as its own page, by the phone app's WebView (app/voice-stage/page.tsx).
 */
import { useEffect, useMemo, useRef, useState } from 'react';

import { ShapeBlock, checkCompleteShape } from '@/components/chat/chat-shapes';

export type StageState = {
  version: number; caption: string; program: string; html?: string; image?: string; page_url?: string;
  at: string | null; active: boolean; scenes?: number; session_id?: string;
};

export function stageHeaders(): Record<string, string> {
  const token = typeof localStorage !== 'undefined' ? localStorage.getItem('done-token') || '' : '';
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/** The room's stage, kept current while `active`. null until the first answer. */
export function useVoiceStage(roomId: string, active: boolean, onState?: (s: StageState) => void): StageState | null {
  const [state, setState] = useState<StageState | null>(null);
  const onStateRef = useRef(onState);
  onStateRef.current = onState;
  useEffect(() => {
    if (!active || !roomId) return;
    let stopped = false;
    let after = 0;
    let session = '';
    const controller = { current: new AbortController() };
    const loop = async () => {
      let failures = 0;
      while (!stopped) {
        try {
          controller.current = new AbortController();
          const response = await fetch(`/api/v1/voicelog/stage/${encodeURIComponent(roomId)}?after=${after}&wait=25`, {
            headers: stageHeaders(), signal: controller.current.signal, cache: 'no-store',
          });
          if (stopped) return;
          if (!response.ok) throw new Error(String(response.status));
          const data = (await response.json()) as StageState;
          failures = 0;
          // a new call (session) is taken even if its version is not above the last one seen (the server counts on
          // across calls since 2026-10-25; this keeps older servers working too)
          if ((data.version || 0) > after || after === 0 || (data.session_id || '') !== session) {
            after = data.version || 0;
            session = data.session_id || '';
            setState(data);
            onStateRef.current?.(data);
          }
          if (!data.active) await new Promise((r) => setTimeout(r, 1500));   // no call yet (or it ended): look again, slowly
        } catch {
          if (stopped) return;
          failures += 1;
          await new Promise((r) => setTimeout(r, Math.min(5000, 500 * failures)));
        }
      }
    };
    void loop();
    return () => { stopped = true; controller.current.abort(); };
  }, [roomId, active]);
  return state;
}

type Scene = { kind: 'program'; program: string } | { kind: 'html'; html: string } | { kind: 'image'; image: string; pageUrl: string };

/** An image the stage may show: one of Dan's files or an https URL (nothing else is a URL the screen should load). */
export function stageImageUrl(v: unknown): string | null {
  if (typeof v !== 'string') return null;
  const s = v.trim();
  if (/^\/api\/v1\/files\/[A-Za-z0-9._-]{1,200}$/.test(s)) return s;
  if (/^https:\/\/[A-Za-z0-9.-]+(:\d+)?\/[^\s"'<>\\]{0,1800}$/.test(s)) return s;
  return null;
}

/** The scene a state describes, or null when it has none the screen can draw. */
export function sceneOf(s: StageState | null): Scene | null {
  if (!s) return null;
  const program = s.program?.trim() || '';
  if (program) return checkCompleteShape(program).ok ? { kind: 'program', program } : null;
  const html = s.html?.trim() || '';
  if (html) return { kind: 'html', html };
  const image = stageImageUrl(s.image);
  if (image) return { kind: 'image', image, pageUrl: s.page_url || '' };
  return null;
}

function sameScene(a: Scene | null, b: Scene | null): boolean {
  if (!a || !b || a.kind !== b.kind) return false;
  if (a.kind === 'program' && b.kind === 'program') return a.program === b.program;
  if (a.kind === 'html' && b.kind === 'html') return a.html === b.html;
  if (a.kind === 'image' && b.kind === 'image') return a.image === b.image;
  return false;
}

/** The document a free drawing is shown in: dark, no margins, the SVG filling the frame. */
export function drawingDocument(html: string): string {
  return `<!doctype html><html><head><meta charset="utf-8"><style>html,body{margin:0;height:100%;background:#0a0a0a;color:#f5f5f5;font-family:system-ui,-apple-system,sans-serif;overflow:hidden}svg{display:block;width:100%;height:100%}img{max-width:100%}</style></head><body>${html}</body></html>`;
}

/** The caption and the scene. Draws nothing until a scene exists (the orb alone is the call's face until then). */
export function VoiceStage({ roomId, active, className = '', onShown }: { roomId: string; active: boolean; className?: string; onShown?: (shown: boolean) => void }) {
  // The scene on the stage and a number that changes only when the scene itself changes: the entrance animation keys
  // on it, so a caption-only version (or the same scene sent again) does not replay it. A program the checker refuses
  // (an unknown icon, a bad argument) keeps the previous scene instead of blanking the call's screen (2026-10-25).
  // A new call (session) starts empty.
  const [shownScene, setShownScene] = useState<{ scene: Scene | null; key: number; session: string }>({ scene: null, key: 0, session: '' });
  const state = useVoiceStage(roomId, active, (s) => {
    const session = s.session_id || '';
    const next = sceneOf(s);
    if (!next && s.program?.trim()) console.warn('[voice-stage] scene not drawable, keeping the last one');
    setShownScene((current) => {
      if (session !== current.session) return { scene: next, key: current.key + 1, session };
      if (next && !sameScene(next, current.scene)) return { scene: next, key: current.key + 1, session };
      return current;
    });
  });
  const { scene, key } = shownScene;
  const drawable = !!scene;
  const shown = !!state?.active && (drawable || !!state?.caption);
  const onShownRef = useRef(onShown);
  useEffect(() => { onShownRef.current = onShown; }, [onShown]);
  useEffect(() => { onShownRef.current?.(shown && drawable); }, [shown, drawable]);
  const drawing = useMemo(() => (scene?.kind === 'html' ? drawingDocument(scene.html) : ''), [scene]);
  if (!shown) return null;
  return (
    <div className={`flex flex-col gap-2 ${className}`} data-voice-stage={state?.version} data-stage-scene-key={key}>
      {state?.caption ? (
        <div className="flex items-center gap-2 text-xs text-muted-foreground" data-stage-caption>
          <span className="inline-block h-1.5 w-1.5 rounded-full bg-primary" aria-hidden />
          <span className="truncate">今の話: {state.caption}</span>
        </div>
      ) : null}
      {scene ? (
        <div key={key} className="animate-in fade-in slide-in-from-bottom-2 duration-300 fill-mode-both" data-stage-scene data-stage-kind={scene.kind}>
          {scene.kind === 'program' ? (
            <ShapeBlock code={scene.program} complete live messageId={null} part="stage" renderFallback={() => null} />
          ) : scene.kind === 'html' ? (
            <iframe
              title="通話の画面の絵"
              sandbox=""
              srcDoc={drawing}
              className="aspect-video w-full rounded-xl border border-border bg-neutral-950"
              referrerPolicy="no-referrer"
            />
          ) : (
            <figure className="m-0 w-full">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={scene.image} alt={state?.caption || 'ページの画面'} className="w-full rounded-xl border border-border bg-neutral-950" />
              {scene.pageUrl ? <figcaption className="mt-1 truncate text-[11px] text-muted-foreground">{scene.pageUrl}</figcaption> : null}
            </figure>
          )}
        </div>
      ) : null}
    </div>
  );
}
