'use client';

import { useEffect } from 'react';

import { reportClientCrash } from '@/components/layout/crash-guard';

// 最後の砦。画面の外枠（layout）そのものが落ちた時だけここに来る。ふだんは
// components/layout/crash-guard.tsx が部品の例外を受け止めて組み直す。
export default function GlobalError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => {
    reportClientCrash(error, null, 'global-error');
  }, [error]);

  return (
    <html lang="ja" className="dark">
      <body style={{ margin: 0, background: '#0a0a0a', color: '#fafafa', fontFamily: 'system-ui, sans-serif' }}>
        <div style={{ minHeight: '100dvh', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 16, padding: 24, textAlign: 'center', fontSize: 14 }}>
          <p>画面の表示でエラーが起きました。内容はダンに記録しました。</p>
          <div style={{ display: 'flex', gap: 12 }}>
            <button type="button" onClick={() => reset()} style={{ borderRadius: 9999, border: '1px solid #333', background: 'transparent', color: 'inherit', padding: '8px 16px', cursor: 'pointer' }}>
              もう一度表示する
            </button>
            <button type="button" onClick={() => window.location.reload()} style={{ borderRadius: 9999, border: '1px solid #333', background: 'transparent', color: 'inherit', padding: '8px 16px', cursor: 'pointer' }}>
              読み直す
            </button>
          </div>
        </div>
      </body>
    </html>
  );
}
