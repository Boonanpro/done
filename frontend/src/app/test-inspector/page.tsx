'use client';

/**
 * Inspector 動作確認用ハーネス。
 * 認証なしで `<PreviewPane />` を直接マウントし、test-edit artifact を編集モードで開く。
 * Playwright スクリプトから自動テストするためのページ。
 */

import { useEffect, useState } from 'react';
import { PreviewPane } from '@/components/preview/preview-pane';
import { usePreviewStore } from '@/stores/preview-store';

export default function TestInspectorHarness() {
  const [ready, setReady] = useState(false);

  useEffect(() => {
    // テスト目的: store を window に exposed しておくと、E2E から
    // 直接 setLiveText 等を呼んで「ガードが効くか」を検証できる。
    // 本番ページでは exposed しない（test-inspector ハーネス専用）。
    (window as unknown as { usePreviewStore?: typeof usePreviewStore }).usePreviewStore = usePreviewStore;
    const store = usePreviewStore.getState();
    store.openArtifact('test-project-id', {
      id: 'test-artifact-id',
      room_id: 'test-room-id',
      project_id: 'test-project-id',
      message_id: null,
      slug: 'test-edit',
      kind: 'website',
      artifact_type: 'website',
      label: 'Test Edit',
      preview_url: '/artifacts/test-edit',
      share_url: '/artifacts/test-edit',
      draft_url: '/artifacts/test-edit',
      created_at: new Date().toISOString(),
    });
    // 編集モードを ON にする
    if (!usePreviewStore.getState().isEditMode) {
      store.toggleEditMode();
    }
    // 手動編集（コメントモードでなく）に切り替え
    store.setInspectorMode('edit');
    setReady(true);
  }, []);

  if (!ready) {
    return <div className="p-4">loading...</div>;
  }

  return (
    <div className="h-screen w-screen">
      <PreviewPane onSubmitComment={() => {}} />
    </div>
  );
}
