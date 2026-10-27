'use client';

/**
 * The call's stage as its own page: /voice-stage?room=<room_id>. The phone app shows this in a WebView above the call's
 * orb (mobile/voice.tsx puts the signed-in token into localStorage before the page loads; the PC panel draws the same
 * component directly). The page tells its host whether a scene is showing (window.ReactNativeWebView.postMessage), so the
 * host can give it room only then, and whether the scene is a page (an artifact's own screen), which the phone gives
 * the whole screen.
 */
import { Suspense, useCallback } from 'react';
import { useSearchParams } from 'next/navigation';

import { VoiceStage } from '@/components/voice/voice-stage';

function Stage() {
  const params = useSearchParams();
  const room = params.get('room') || '';
  const onShown = useCallback((shown: boolean, page: boolean) => {
    const host = (window as Window & { ReactNativeWebView?: { postMessage: (s: string) => void } }).ReactNativeWebView;
    host?.postMessage(JSON.stringify({ type: 'stage', shown, page }));
  }, []);
  if (!room) return null;
  return <VoiceStage roomId={room} active className="w-full" onShown={onShown} fill />;
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
