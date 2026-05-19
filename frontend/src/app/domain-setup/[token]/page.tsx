'use client';

/**
 * クライアント向け・独自ドメイン取得の案内ページ (公開・認証なし)。
 *
 * オーナーが発行した /domain-setup/<token> をクライアントに渡す。
 * クライアントは金額を見てカード決済するだけ。決済完了後、運営者の
 * インフラが自動でドメイン取得〜公開まで行う。技術操作は一切不要。
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { useParams } from 'next/navigation';
import { AlertTriangle, CheckCircle2, ExternalLink, Globe, Loader2 } from 'lucide-react';

interface DomainSetup {
  success: boolean;
  artifact_label?: string | null;
  domain?: string | null;
  status?: string | null; // pending / registering / live / failed
  price?: string | null; // USD
  production_url?: string | null;
  detail?: string | null;
  error?: string | null;
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <main className="fixed inset-0 overflow-y-auto bg-slate-50">
      <div className="flex min-h-full items-center justify-center p-6">
        <div className="w-full max-w-md rounded-2xl border border-slate-200 bg-white p-8 shadow-sm">
          {children}
        </div>
      </div>
    </main>
  );
}

export default function DomainSetupPage() {
  const params = useParams<{ token: string }>();
  const token = params?.token;

  const [data, setData] = useState<DomainSetup | null>(null);
  const [loading, setLoading] = useState(true);
  const [paying, setPaying] = useState(false);
  const [payError, setPayError] = useState('');
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchState = useCallback(async (): Promise<DomainSetup | null> => {
    if (!token) return null;
    try {
      const res = await fetch(`/api/v1/publish/domain-setup/${token}`);
      return (await res.json()) as DomainSetup;
    } catch {
      return null;
    }
  }, [token]);

  // 初回ロード（決済から戻ってきた場合は確認APIを叩く）
  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    (async () => {
      const sessionId = new URLSearchParams(window.location.search).get('session_id');
      let state = await fetchState();
      if (sessionId && state?.success && state.status === 'pending') {
        try {
          const res = await fetch(`/api/v1/publish/domain-setup/${token}/confirm`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ session_id: sessionId }),
          });
          state = (await res.json()) as DomainSetup;
        } catch {
          /* 確認失敗時は通常表示にフォールバック */
        }
      }
      if (!cancelled) {
        setData(state);
        setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [token, fetchState]);

  // 取得処理中はポーリングして完了を待つ
  useEffect(() => {
    if (data?.status === 'registering' && !pollRef.current) {
      pollRef.current = setInterval(async () => {
        const next = await fetchState();
        if (next) setData(next);
      }, 5000);
    } else if (data?.status !== 'registering' && pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    return () => {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [data?.status, fetchState]);

  const pay = async () => {
    if (!token) return;
    setPaying(true);
    setPayError('');
    try {
      const res = await fetch(`/api/v1/publish/domain-setup/${token}/checkout`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ return_origin: window.location.origin }),
      });
      const json = await res.json();
      if (json.success && json.checkout_url) {
        window.location.href = json.checkout_url;
        return;
      }
      setPayError(json.error || '決済ページを開けませんでした');
    } catch {
      setPayError('決済ページを開けませんでした');
    }
    setPaying(false);
  };

  if (loading) {
    return (
      <Shell>
        <div className="flex justify-center py-6">
          <Loader2 className="h-7 w-7 animate-spin text-slate-400" />
        </div>
      </Shell>
    );
  }

  if (!data || !data.success) {
    return (
      <Shell>
        <div className="text-center">
          <AlertTriangle className="mx-auto h-10 w-10 text-amber-500" />
          <h1 className="mt-3 text-lg font-bold text-slate-900">案内ページを表示できません</h1>
          <p className="mt-2 text-sm text-slate-600">
            {data?.error || 'リンクが正しいか、発行元にご確認ください。'}
          </p>
        </div>
      </Shell>
    );
  }

  const label = data.artifact_label || '成果物';
  const domain = data.domain || '';

  // 公開完了
  if (data.status === 'live') {
    return (
      <Shell>
        <div className="text-center">
          <CheckCircle2 className="mx-auto h-12 w-12 text-emerald-500" />
          <h1 className="mt-3 text-xl font-bold text-slate-900">公開が完了しました</h1>
          <p className="mt-2 text-sm text-slate-600">
            {domain} でサイトをご覧いただけます。
          </p>
          {data.production_url && (
            <a
              href={data.production_url}
              target="_blank"
              rel="noreferrer"
              className="mt-5 inline-flex items-center gap-2 rounded-lg bg-slate-900 px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-slate-700"
            >
              <Globe className="h-4 w-4" />
              {data.production_url.replace(/^https?:\/\//, '')}
              <ExternalLink className="h-3.5 w-3.5" />
            </a>
          )}
        </div>
      </Shell>
    );
  }

  // 取得・公開処理中
  if (data.status === 'registering') {
    return (
      <Shell>
        <div className="text-center">
          <Loader2 className="mx-auto h-10 w-10 animate-spin text-slate-500" />
          <h1 className="mt-3 text-lg font-bold text-slate-900">公開の準備をしています</h1>
          <p className="mt-2 text-sm text-slate-600">
            ドメインを取得してサイトを公開しています。1〜3分ほどお待ちください。
            この画面は開いたままで構いません。
          </p>
        </div>
      </Shell>
    );
  }

  // 失敗
  if (data.status === 'failed') {
    return (
      <Shell>
        <div className="text-center">
          <AlertTriangle className="mx-auto h-10 w-10 text-amber-500" />
          <h1 className="mt-3 text-lg font-bold text-slate-900">うまくいきませんでした</h1>
          <p className="mt-2 text-sm text-slate-600">
            {data.detail || '時間をおいて再度お試しいただくか、発行元にご連絡ください。'}
          </p>
        </div>
      </Shell>
    );
  }

  // pending — 決済画面
  return (
    <Shell>
      <div className="flex items-center gap-2 text-sm text-slate-500">
        <Globe className="h-4 w-4" /> 独自ドメインで公開
      </div>
      <h1 className="mt-2 text-lg font-bold text-slate-900">
        「{label}」を独自ドメインで公開します
      </h1>

      <div className="mt-5 rounded-lg bg-slate-100 px-4 py-3">
        <div className="text-xs text-slate-500">取得するドメイン</div>
        <div className="mt-0.5 break-all font-mono text-base font-semibold text-slate-900">
          {domain}
        </div>
      </div>

      <div className="mt-3 flex items-center justify-between rounded-lg border border-slate-200 px-4 py-3">
        <span className="text-sm text-slate-600">ドメイン取得・公開（1年分）</span>
        <span className="text-lg font-bold text-slate-900">
          {data.price ? `$${data.price}` : '—'}
        </span>
      </div>

      {payError && (
        <p className="mt-3 rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-700">{payError}</p>
      )}

      <button
        type="button"
        onClick={pay}
        disabled={paying || !data.price}
        className="mt-5 flex w-full items-center justify-center gap-2 rounded-lg bg-slate-900 px-5 py-3 text-sm font-semibold text-white transition hover:bg-slate-700 disabled:opacity-50"
      >
        {paying ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
        カードで決済して取得する
      </button>
      <p className="mt-3 text-center text-xs text-slate-400">
        決済後、ドメインの取得・公開はすべて自動で行われます。設定作業はありません。
      </p>
    </Shell>
  );
}
