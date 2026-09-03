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
    // ?slug=xxx で任意の artifact を編集モードで開けるようにする（既定は test-edit）
    const slugParam =
      new URLSearchParams(window.location.search).get("slug") || "test-edit";
    // テスト目的: store を window に exposed しておくと、E2E から
    // 直接 setLiveText 等を呼んで「ガードが効くか」を検証できる。
    // 本番ページでは exposed しない（test-inspector ハーネス専用）。
    (window as unknown as { usePreviewStore?: typeof usePreviewStore }).usePreviewStore = usePreviewStore;
    const store = usePreviewStore.getState();
    // project_id は保存APIでUUID検証されるため、偽IDではなく空で渡す
    // （空なら保存リクエストから project_id が省かれる）
    store.openArtifact('', {
      id: 'test-artifact-id',
      room_id: 'test-room-id',
      project_id: 'test-project-id',
      message_id: null,
      slug: slugParam,
      kind: 'website',
      artifact_type: 'website',
      label: 'Test Edit',
      preview_url: `/artifacts/${slugParam}`,
      share_url: `/artifacts/${slugParam}`,
      draft_url: `/artifacts/${slugParam}`,
      // ハーネス専用: 未公開slugでも iframe をローカル配信で開けるよう、
      // 配信URLを明示的にこのオリジンの /preview/ に固定する
      delivery_url: `${window.location.origin}/preview/${slugParam}`,
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
      <PreviewPane onAddComment={() => {}} />
    </div>
  );
}
