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
          if ((data.version || 0) > after || after === 0) {
            after = data.version || 0;
            setState(data);
            onStateRef.current?.(data);
          }
          if (!data.active) await new Promise((r) => setTimeout(r, 1500));   // no call yet (or it ended): look again, slowly
        } catch (error) {
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
  const state = useVoiceStage(roomId, active);
  const program = state?.program?.trim() || '';
  const ok = program ? checkCompleteShape(program) : null;
  // The last scene that drew: a new program the checker refuses (an unknown icon, a bad argument) keeps it on the stage
  // instead of blanking the call's screen (2026-10-25). A new call (session) starts empty.
  const lastGood = useRef<{ program: string; version: number; session: string } | null>(null);
  const session = state?.session_id || '';
  if (ok?.ok && state) lastGood.current = { program, version: state.version || 0, session };
  else if (ok && !ok.ok && program) console.warn('[voice-stage] scene not drawable, keeping the last one:', ok.reason);
  const scene = ok?.ok && state ? { program, version: state.version || 0 } : (lastGood.current && lastGood.current.session === session ? lastGood.current : null);
  const drawable = !!scene;
  const shown = !!state?.active && (drawable || !!state?.caption);
  const onShownRef = useRef(onShown);
  onShownRef.current = onShown;
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
