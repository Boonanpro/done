'use client';

import { useEffect } from 'react';
import { useParams } from 'next/navigation';

import { useProjectStore } from '@/stores/project-store';

/**
 * /chat/[projectId] - プロジェクト個別ページ
 *
 * レイアウト（MainLayout）と認証チェックは app/chat/layout.tsx が担当。
 * このページは URL の projectId を store に同期するだけ。
 * 実際の表示は MainLayout が `selectedProjectId` を見てレンダリングする。
 */
export default function ChatProjectPage() {
  const params = useParams();
  const projectId = params.projectId as string;
  const selectProject = useProjectStore((s) => s.selectProject);

  useEffect(() => {
    if (projectId) {
      selectProject(projectId);
    }
  }, [projectId, selectProject]);

  return null;
}
