'use client';

/**
 * The call's stage as its own page: /voice-stage?room=<room_id>. The phone app shows this in a WebView above the call's
 * orb (mobile/voice.tsx puts the signed-in token into localStorage before the page loads; the PC panel draws the same
 * component directly). The page tells its host whether a scene is showing (window.ReactNativeWebView.postMessage), so the
 * host can give it room only then, and whether the scene is a page (an artifact's own screen), which the phone gives
 * the whole screen.
 */
import { Suspense, useCallback, useEffect, useState } from 'react';
import { useSearchParams } from 'next/navigation';

import { CallSketch } from '@/components/voice/call-sketch';
import { VoiceStage } from '@/components/voice/voice-stage';

function Stage() {
  const params = useSearchParams();
  const room = params.get('room') || '';
  const session = params.get('sketchSession');
  const [boardOpen, setBoardOpen] = useState(false);
  const [scene, setScene] = useState({ shown: false, page: false });
  const onShown = useCallback((shown: boolean, page: boolean) => setScene({ shown, page }), []);
  useEffect(() => {
    const host = (window as Window & { ReactNativeWebView?: { postMessage: (s: string) => void } }).ReactNativeWebView;
    host?.postMessage(JSON.stringify({ type: 'stage', shown: boardOpen || scene.shown, page: boardOpen || scene.page }));
  }, [boardOpen, scene]);
  if (!room) return null;
  return <>
    {session && <div className="flex shrink-0 justify-center py-0.5">
      <CallSketch key={session} room={room} session={session} onToggle={setBoardOpen} />
    </div>}
    <VoiceStage roomId={room} active className="w-full" onShown={onShown} fill />
  </>;
}

export default function VoiceStagePage() {
  return (
    <main className="dark flex h-[100dvh] flex-col overflow-y-auto bg-neutral-950 p-1.5 text-foreground">
      <Suspense fallback={null}>
        <Stage />
      </Suspense>
    </main>
  );
}
