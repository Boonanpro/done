'use client';

import { useEffect, useState } from 'react';
import { isDanPreview } from '@/lib/dan-preview';

export type SetupGateStatus = 'loading' | 'needs-setup' | 'ready';

/**
 * ログイン / 初期設定ゲートの共通フック。
 *
 * ログインや初回登録が必須なページ（成果物）は、このフックでゲートを判定する。
 * こうしておくと **ライブプレビュー（チャット右ペイン）では自動でゲートがバイパス**され、
 * 管理者として全画面を閲覧・編集できる。各成果物でプレビュー判定を再実装する必要はない。
 *
 * 挙動:
 *  - `isDanPreview()` が true（プレビュー）→ `check` を呼ばずに即 `'ready'`。`isPreview` も true。
 *  - それ以外 → `check()` の結果で `'ready'`（設定済み）/ `'needs-setup'`（要設定）。
 *  - 解決するまでは `'loading'`。
 *
 * 使い方:
 * ```tsx
 * const gate = useSetupGate(async () => {
 *   const r = await fetch('/api/.../status?...');
 *   return r.ok && (await r.json()).has_credentials;
 * });
 * if (gate.status === 'loading')     return <Spinner />;
 * if (gate.status === 'needs-setup') return <SetupScreen onDone={gate.markReady} />;
 * return <MainApp />;
 * ```
 *
 * 注意: 認証境界ではない。プレビューでゲートを飛ばしても保存済み認証情報が無ければ
 * 実処理（自動投稿など）は動かないため、バイパスは「閲覧/編集の解放」に留まる。
 *
 * @param check 設定が完了済みかを返す非同期関数。マウント時に1回だけ実行される。
 */
export function useSetupGate(check: () => Promise<boolean>): {
  status: SetupGateStatus;
  isPreview: boolean;
  markReady: () => void;
  markNeedsSetup: () => void;
} {
  const [status, setStatus] = useState<SetupGateStatus>('loading');
  const [isPreview, setIsPreview] = useState(false);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    // プレビューはゲートを飛ばす（check は呼ばない）
    if (isDanPreview()) {
      setIsPreview(true);
      setStatus('ready');
      return;
    }
    let alive = true;
    check()
      .then((ok) => {
        if (alive) setStatus(ok ? 'ready' : 'needs-setup');
      })
      .catch(() => {
        if (alive) setStatus('needs-setup');
      });
    return () => {
      alive = false;
    };
    // check は呼び出し側で安定化していなくても、マウント時1回のみ実行する設計
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return {
    status,
    isPreview,
    markReady: () => setStatus('ready'),
    markNeedsSetup: () => setStatus('needs-setup'),
  };
}
