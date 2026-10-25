'use client';

/**
 * The stage of a call: the caption 「今の話: …」 and the scene the server draws while Dan talks (app/services/voice_stage.py).
 *
 * The scene is an answer-shapes program (the same ```openui-lang parts as the chat: Flow, Stat, Compare, Chart…), drawn with
 * ShapeBlock. It arrives by long poll (GET /api/v1/voicelog/stage/<room>?after=<version>): the server answers the moment a
 * newer version exists, when the call ends, or after ~25 s. A scene that fails the parts' validation is not shown; the
 * previous one stays (checkCompleteShape). Each new scene slides in; the caption changes in place.
 *
 * Used by the PC voice panel (voice-session.tsx) and, as its own page, by the phone app's WebView (app/voice-stage/page.tsx).
 */
import { useEffect, useRef, useState } from 'react';

import { ShapeBlock, checkCompleteShape } from '@/components/chat/chat-shapes';

export type StageState = { version: number; caption: string; program: string; at: string | null; active: boolean; scenes?: number; session_id?: string };

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

/** The caption and the scene. Draws nothing until a scene exists (the orb alone is the call's face until then). */
export function VoiceStage({ roomId, active, className = '', onShown }: { roomId: string; active: boolean; className?: string; onShown?: (shown: boolean) => void }) {
  // The last scene that drew: a new program the checker refuses (an unknown icon, a bad argument) keeps it on the stage
  // instead of blanking the call's screen (2026-10-25). A new call (session) starts empty.
  const [lastGood, setLastGood] = useState<{ program: string; version: number; session: string } | null>(null);
  const state = useVoiceStage(roomId, active, (s) => {
    const p = s.program?.trim() || '';
    const check = p ? checkCompleteShape(p) : null;
    if (check?.ok) setLastGood({ program: p, version: s.version || 0, session: s.session_id || '' });
    else if (check && !check.ok) console.warn('[voice-stage] scene not drawable, keeping the last one:', check.reason);
  });
  const program = state?.program?.trim() || '';
  const ok = program ? checkCompleteShape(program) : null;
  const session = state?.session_id || '';
  const scene = ok?.ok && state ? { program, version: state.version || 0 } : (lastGood && lastGood.session === session ? lastGood : null);
  const drawable = !!scene;
  const shown = !!state?.active && (drawable || !!state?.caption);
  const onShownRef = useRef(onShown);
  useEffect(() => { onShownRef.current = onShown; }, [onShown]);
  useEffect(() => { onShownRef.current?.(shown && drawable); }, [shown, drawable]);
  if (!shown) return null;
  return (
    <div className={`flex flex-col gap-2 ${className}`} data-voice-stage={state?.version}>
      {state?.caption ? (
        <div className="flex items-center gap-2 text-xs text-muted-foreground" data-stage-caption>
          <span className="inline-block h-1.5 w-1.5 rounded-full bg-primary" aria-hidden />
          <span className="truncate">今の話: {state.caption}</span>
        </div>
      ) : null}
      {drawable ? (
        <div key={scene.version} className="animate-in fade-in slide-in-from-bottom-2 duration-300 fill-mode-both" data-stage-scene>
          <ShapeBlock code={scene.program} complete live messageId={null} part="stage" renderFallback={() => null} />
        </div>
      ) : null}
    </div>
  );
}
