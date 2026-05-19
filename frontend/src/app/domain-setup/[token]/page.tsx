'use client';

/**
 * クライアント向け・独自ドメイン設定の案内ページ (公開・認証なし)。
 *
 * オーナーが publish-modal から発行した /domain-setup/<token> をクライアントに渡す。
 * クライアントはこのページだけで ①ドメイン確認 ②購入 ③DNS設定 ④接続確認 を進められる。
 * ドメインはクライアント自身が取得・所有するため、オーナーの代理決済は不要。
 */
import { useCallback, useEffect, useState } from 'react';
import { useParams } from 'next/navigation';
import {
  CheckCircle2,
  Copy,
  ExternalLink,
  Globe,
  Loader2,
  AlertTriangle,
} from 'lucide-react';
import { copyToClipboard } from '@/lib/clipboard';

interface DnsRecord {
  type: string;
  name: string;
  value: string;
  purpose: string;
}

interface RegistrarLink {
  label: string;
  url: string;
}

interface DomainSetup {
  success: boolean;
  token?: string | null;
  artifact_label?: string | null;
  domain?: string | null;
  status?: string | null;
  availability?: {
    exact?: { name: string; registrable: boolean } | null;
  } | null;
  registrar_links: RegistrarLink[];
  dns_records: DnsRecord[];
  production_url?: string | null;
  verified: boolean;
  detail?: string | null;
  error?: string | null;
}

function CopyButton({ text, label }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      onClick={async () => {
        const ok = await copyToClipboard(text);
        if (ok) {
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        }
      }}
      className="inline-flex shrink-0 items-center gap-1 rounded-md border border-slate-300 bg-white px-2.5 py-1.5 text-xs font-medium text-slate-600 transition hover:bg-slate-50"
    >
      {copied ? (
        <>
          <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" /> コピー済み
        </>
      ) : (
        <>
          <Copy className="h-3.5 w-3.5" /> {label || 'コピー'}
        </>
      )}
    </button>
  );
}

function StepHeader({ n, title }: { n: number; title: string }) {
  return (
    <div className="flex items-center gap-3">
      <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-slate-900 text-sm font-bold text-white">
        {n}
      </span>
      <h2 className="text-base font-bold text-slate-900">{title}</h2>
    </div>
  );
}

export default function DomainSetupPage() {
  const params = useParams<{ token: string }>();
  const token = params?.token;

  const [data, setData] = useState<DomainSetup | null>(null);
  const [loading, setLoading] = useState(true);
  const [verifying, setVerifying] = useState(false);

  const load = useCallback(async () => {
    if (!token) return;
    try {
      const res = await fetch(`/api/v1/publish/domain-setup/${token}`);
      const json = (await res.json()) as DomainSetup;
      setData(json);
    } catch {
      setData({
        success: false,
        registrar_links: [],
        dns_records: [],
        verified: false,
        error: '読み込みに失敗しました。通信環境を確認してください。',
      });
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    load();
  }, [load]);

  const verify = async () => {
    if (!token) return;
    setVerifying(true);
    try {
      const res = await fetch(`/api/v1/publish/domain-setup/${token}/verify`, {
        method: 'POST',
      });
      const json = (await res.json()) as DomainSetup;
      setData((prev) => ({
        ...(prev as DomainSetup),
        ...json,
        // verify レスポンスにレコード一覧が無い場合は元のものを保持
        registrar_links: json.registrar_links?.length
          ? json.registrar_links
          : prev?.registrar_links || [],
        dns_records: json.dns_records?.length ? json.dns_records : prev?.dns_records || [],
      }));
    } catch {
      setData((prev) =>
        prev ? { ...prev, detail: '接続確認に失敗しました。少し待って再度お試しください。' } : prev,
      );
    } finally {
      setVerifying(false);
    }
  };

  // ---- 読み込み中 ----
  if (loading) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-slate-50">
        <Loader2 className="h-8 w-8 animate-spin text-slate-400" />
      </main>
    );
  }

  // ---- エラー / 見つからない ----
  if (!data || !data.success) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-slate-50 p-6">
        <div className="max-w-md rounded-2xl border border-slate-200 bg-white p-8 text-center shadow-sm">
          <AlertTriangle className="mx-auto h-10 w-10 text-amber-500" />
          <h1 className="mt-4 text-lg font-bold text-slate-900">案内ページを表示できません</h1>
          <p className="mt-2 text-sm text-slate-600">
            {data?.error || 'リンクが正しいか、発行元にご確認ください。'}
          </p>
        </div>
      </main>
    );
  }

  const isLive = data.verified || data.status === 'live';

  // ---- 完了画面 ----
  if (isLive) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-slate-50 p-6">
        <div className="max-w-md rounded-2xl border border-slate-200 bg-white p-8 text-center shadow-sm">
          <CheckCircle2 className="mx-auto h-12 w-12 text-emerald-500" />
          <h1 className="mt-4 text-xl font-bold text-slate-900">公開が完了しました</h1>
          <p className="mt-2 text-sm text-slate-600">
            {data.detail || 'ドメインの接続が完了しました。'}
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
          <p className="mt-4 text-xs text-slate-400">
            検索エンジンへの登録は申請済みです。検索結果に表示されるまで数日かかることがあります。
          </p>
        </div>
      </main>
    );
  }

  const domain = data.domain || '';
  const dnsPending = data.status === 'dns_pending';

  return (
    <main className="fixed inset-0 overflow-y-auto bg-slate-50">
      <div className="mx-auto max-w-2xl space-y-5 px-4 py-10">
        {/* ヘッダー */}
        <header className="rounded-2xl bg-slate-900 p-6 text-white">
          <div className="flex items-center gap-2 text-sm text-slate-300">
            <Globe className="h-4 w-4" /> 独自ドメインの設定
          </div>
          <h1 className="mt-2 text-xl font-bold">
            「{data.artifact_label || '成果物'}」を独自ドメインで公開します
          </h1>
          <p className="mt-2 text-sm leading-6 text-slate-300">
            下の3ステップを上から順に進めてください。ドメインはお客様ご自身の名義で取得・お支払いいただきます。
            ご不明な点は、このページをお送りした担当者までお問い合わせください。
          </p>
        </header>

        {/* ステップ1: ドメイン確認 */}
        <section className="space-y-3 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <StepHeader n={1} title="取得するドメインを確認" />
          <p className="text-sm text-slate-600">このアドレスでサイトを公開します。</p>
          <div className="flex items-center justify-between gap-3 rounded-lg bg-slate-100 px-4 py-3">
            <span className="break-all font-mono text-base font-semibold text-slate-900">
              {domain}
            </span>
            <CopyButton text={domain} label="ドメインをコピー" />
          </div>
          {data.availability?.exact && !data.availability.exact.registrable && (
            <p className="rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-700">
              このドメインは既に取得されている可能性があります。お送りした担当者にご確認ください。
            </p>
          )}
        </section>

        {/* ステップ2: 購入 */}
        <section className="space-y-3 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <StepHeader n={2} title="ドメインを取得する" />
          <p className="text-sm text-slate-600">
            下のいずれかのサービスで、ステップ1のドメイン名を検索して取得（購入）してください。
            お支払いはそのサービスで完結します。年間で千数百円程度が目安です。
          </p>
          <div className="space-y-2">
            {data.registrar_links.map((r) => (
              <a
                key={r.url}
                href={r.url}
                target="_blank"
                rel="noreferrer"
                className="flex items-center justify-between gap-3 rounded-lg border border-slate-200 px-4 py-3 text-sm transition hover:border-slate-400 hover:bg-slate-50"
              >
                <span className="font-medium text-slate-800">{r.label}</span>
                <ExternalLink className="h-4 w-4 shrink-0 text-slate-400" />
              </a>
            ))}
          </div>
        </section>

        {/* ステップ3: DNS設定 */}
        <section className="space-y-3 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <StepHeader n={3} title="ドメインの接続先を設定する" />
          <p className="text-sm text-slate-600">
            取得したサービスの管理画面で「DNS設定」または「ネームサーバー設定」を開き、
            下の表のとおりにレコードを追加してください。
          </p>
          <div className="space-y-3">
            {data.dns_records.map((rec, i) => (
              <div key={i} className="rounded-lg border border-slate-200 p-3">
                <div className="mb-2 text-xs font-medium text-slate-500">{rec.purpose}</div>
                <div className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 text-sm">
                  <span className="text-slate-400">種類</span>
                  <span className="font-mono font-semibold text-slate-900">{rec.type}</span>
                  <span className="text-slate-400">名前 / ホスト</span>
                  <span className="font-mono font-semibold text-slate-900">{rec.name}</span>
                  <span className="text-slate-400">値 / 内容</span>
                  <span className="flex items-center gap-2">
                    <span className="break-all font-mono font-semibold text-slate-900">
                      {rec.value}
                    </span>
                    <CopyButton text={rec.value} />
                  </span>
                </div>
              </div>
            ))}
          </div>
          <p className="rounded-md bg-slate-50 px-3 py-2 text-xs text-slate-500">
            ※「名前 / ホスト」の「@」はドメインそのものを指します。サービスによっては空欄で入力します。
          </p>
        </section>

        {/* ステップ4: 接続確認 */}
        <section className="space-y-3 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <StepHeader n={4} title="接続を確認する" />
          <p className="text-sm text-slate-600">
            ステップ3の設定が終わったら、下のボタンを押してください。
            設定が反映されていれば公開が完了します。
          </p>
          {dnsPending && data.detail && (
            <div className="flex gap-2 rounded-md bg-amber-50 px-3 py-2.5 text-xs text-amber-700">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
              <span>{data.detail}</span>
            </div>
          )}
          <button
            type="button"
            onClick={verify}
            disabled={verifying}
            className="inline-flex items-center gap-2 rounded-lg bg-slate-900 px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-slate-700 disabled:opacity-50"
          >
            {verifying ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" /> 確認しています...
              </>
            ) : (
              '接続を確認'
            )}
          </button>
        </section>

        <p className="pb-4 text-center text-xs text-slate-400">
          取得したドメインはお客様の資産です。契約や更新はお客様のアカウントで管理されます。
        </p>
      </div>
    </main>
  );
}
