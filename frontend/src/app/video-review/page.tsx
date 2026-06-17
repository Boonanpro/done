'use client';

import { Suspense } from 'react';
import { useSearchParams } from 'next/navigation';

import { VideoReviewEditor } from '@/components/video-review/video-review-editor';

function VideoReviewPageInner() {
  const params = useSearchParams();
  const path = params.get('path') || '';
  const url = params.get('url') || '';
  return <VideoReviewEditor initialPath={path} initialUrl={url} />;
}

export default function VideoReviewPage() {
  return (
    <Suspense fallback={<div className="p-6 text-sm text-muted-foreground">Loading editor...</div>}>
      <VideoReviewPageInner />
    </Suspense>
  );
}
