'use client';

import { Suspense, useEffect, useState } from 'react';
import { useSearchParams } from 'next/navigation';

import { EditorSplash, ProductionStudio } from '@/components/production/editor-dan-chat';

import { appIntentUrl } from './open-in-app';

function ProductionWorkspaceInner() {
  const params = useSearchParams();
  const roomId = params.get('room_id') || '';
  // Android の Chrome なら、ダンのアプリの中（帯の無い全画面）で開き直す。移る間はエディターを読み込まない。
  const [toApp, setToApp] = useState<string | null | undefined>(undefined);
  useEffect(() => {
    const target = appIntentUrl(window.location.href);
    setToApp(target);
    if (target) window.location.replace(target);
  }, []);

  if (!roomId) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background p-6 text-sm text-muted-foreground">
        room_id が必要です。
      </div>
    );
  }

  if (toApp === undefined || toApp) return <EditorSplash />;

  return (
    <ProductionStudio roomId={roomId} />
  );
}

export default function ProductionWorkspacePage() {
  return (
    <Suspense fallback={<EditorSplash />}>
      <ProductionWorkspaceInner />
    </Suspense>
  );
}
