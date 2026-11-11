'use client';

import { Suspense } from 'react';
import { useSearchParams } from 'next/navigation';

import { EditorSplash, ProductionStudio } from '@/components/production/editor-dan-chat';

function ProductionWorkspaceInner() {
  const params = useSearchParams();
  const roomId = params.get('room_id') || '';

  if (!roomId) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background p-6 text-sm text-muted-foreground">
        room_id が必要です。
      </div>
    );
  }

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
