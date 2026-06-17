'use client';

import { Suspense } from 'react';
import { useSearchParams } from 'next/navigation';

import { ProductionWorkspace } from '@/components/production/production-workspace';

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
    <div className="h-screen">
      <ProductionWorkspace roomId={roomId} />
    </div>
  );
}

export default function ProductionWorkspacePage() {
  return (
    <Suspense fallback={<div className="p-6 text-sm text-muted-foreground">Loading workspace...</div>}>
      <ProductionWorkspaceInner />
    </Suspense>
  );
}
