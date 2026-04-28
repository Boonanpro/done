'use client';

import { useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';

import { MainLayout } from '@/components/layout/main-layout';
import { useProjectStore } from '@/stores/project-store';
import { usePreviewStore } from '@/stores/preview-store';
import { OWNER_USER_ID } from '@/lib/api-client';

/**
 * /chat/[projectId] - プロジェクト個別ページ
 * URLからプロジェクトIDを取得してstoreにセット
 */
export default function ChatProjectPage() {
  const router = useRouter();
  const params = useParams();
  const projectId = params.projectId as string;
  const selectProject = useProjectStore((s) => s.selectProject);
  const [checked, setChecked] = useState(false);
  const [hasToken, setHasToken] = useState(true);

  // 認証チェック
  useEffect(() => {
    const token = localStorage.getItem('done-token');
    setHasToken(!!token);
    setChecked(true);
    if (!token) {
      // 幽霊プレビュー防止
      try { usePreviewStore.getState().closePreview(); } catch {}
      router.push('/login');
      return;
    }
    try {
      const payload = JSON.parse(atob(token.split('.')[1]));
      if (payload.sub !== OWNER_USER_ID) {
        router.replace('/collab');
        return;
      }
    } catch {
      // Invalid token
    }
  }, [router]);

  // URLのprojectIdをstoreに同期
  useEffect(() => {
    if (projectId) {
      selectProject(projectId);
    }
  }, [projectId, selectProject]);

  if (!checked || !hasToken) return null;

  return <MainLayout />;
}
