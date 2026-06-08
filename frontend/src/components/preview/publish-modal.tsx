'use client';

import { useRef, useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { toast } from 'sonner';
import {
  AlertCircle,
  CheckCircle2,
  Circle,
  Copy,
  Loader2,
  Send,
  UserRound,
  XCircle,
} from 'lucide-react';

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import type { ArtifactRecord } from '@/stores/preview-store';

// 公開先の Vercel プロジェクト。内部固定値（UI には出さない）。
const VERCEL_PROJECT = 'frontend';

type Stage = 'domain' | 'payer' | 'confirm' | 'publishing' | 'done' | 'guide';

interface DomainCheckCandidate {
  name: string;
  registrable: boolean;
  pricing?: { currency: string; registration_cost: string; renewal_cost: string } | null;
}
interface DomainCheckResponse {
  exact: DomainCheckCandidate | null;
  suggestions: DomainCheckCandidate[];
}
interface PublishStepDTO {
  name: string;
  status: 'pending' | 'running' | 'completed' | 'failed' | 'skipped';
  detail: string;
  duration_ms: number;
}
interface PublishResponse {
  success: boolean;
  domain: string;
  deploy_url: string | null;
  steps: PublishStepDTO[];
  error: string | null;
}
interface DomainSetupResponse {
  success: boolean;
  setup_path?: string | null;
  error?: string | null;
}

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  artifact: ArtifactRecord;
  onPublished?: () => void;
}

const STAGE_TITLE: Record<Stage, string> = {
  domain: '公開するURLを決める',
  payer: 'ドメイン代の支払いは誰？',
  confirm: '内容の確認',
  publishing: '公開しています',
  done: '公開結果',
  guide: '相手に送るURL',
};

const STEP_LABEL: Record<string, string> = {
  check_availability: 'ドメイン確認',
  register_domain: 'ドメイン購入',
  wait_registration_complete: '購入完了待ち',
  attach_to_vercel: 'サイトに接続',
  configure_dns: 'URL設定',
  verify_dns_propagation: '反映確認',
  generate_seo_assets: '検索向けファイル作成',
  submit_to_search_console: '検索エンジンに登録',
  update_artifact_db: '保存',
};

function money(v?: string | number | null) {
  const n = Number(v ?? 0);
  return Number.isFinite(n) ? n.toFixed(2) : '0.00';
}

function StepIcon({ status }: { status: PublishStepDTO['status'] }) {
  if (status === 'completed') return <CheckCircle2 className="h-4 w-4 text-emerald-500" />;
  if (status === 'failed') return <XCircle className="h-4 w-4 text-red-500" />;
  if (status === 'skipped') return <Circle className="h-4 w-4 text-muted-foreground/40" />;
  if (status === 'running') return <Loader2 className="h-4 w-4 animate-spin text-primary" />;
  return <Circle className="h-4 w-4 text-muted-foreground" />;
}

export function PublishModal({ open, onOpenChange, artifact, onPublished }: Props) {
  const [stage, setStage] = useState<Stage>('domain');
  const [domain, setDomain] = useState(artifact.custom_domain || `${artifact.slug}.com`);
  const [years, setYears] = useState(1);
  const [check, setCheck] = useState<DomainCheckResponse | null>(null);
  const [result, setResult] = useState<PublishResponse | null>(null);
  const [clientUrl, setClientUrl] = useState('');
  const urlInputRef = useRef<HTMLInputElement>(null);

  const reset = () => {
    setStage('domain');
    setCheck(null);
    setResult(null);
    setClientUrl('');
  };
  const close = (next: boolean) => {
    if (!next) reset();
    onOpenChange(next);
  };

  const checkMutation = useMutation({
    mutationFn: async (q: string) => {
      const res = await fetch('/api/v1/publish/check', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: q, include_suggestions: true }),
      });
      if (!res.ok) throw new Error(await res.text());
      return res.json() as Promise<DomainCheckResponse>;
    },
    onSuccess: (data) => {
      setCheck(data);
      if (data.exact?.registrable) setStage('payer');
    },
    onError: (e) => toast.error('確認に失敗しました', { description: String(e).slice(0, 140) }),
  });

  const publishMutation = useMutation({
    mutationFn: async () => {
      const res = await fetch('/api/v1/publish/run', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          artifact_id: artifact.id,
          domain,
          vercel_project: VERCEL_PROJECT,
          artifact_dir: `frontend/src/app/artifacts/${artifact.slug}`,
          write_seo_files: true,
          years,
          auto_renew: true,
          dry_run: false,
        }),
      });
      if (!res.ok) throw new Error(await res.text());
      return res.json() as Promise<PublishResponse>;
    },
    onMutate: () => setStage('publishing'),
    onSuccess: (data) => {
      setResult(data);
      setStage('done');
      if (data.success) {
        toast.success('公開しました');
        onPublished?.();
      }
    },
    onError: (e) => {
      setResult({ success: false, domain, deploy_url: null, steps: [], error: String(e) });
      setStage('done');
    },
  });

  const guideMutation = useMutation({
    mutationFn: async () => {
      const res = await fetch('/api/v1/publish/domain-setup', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          artifact_id: artifact.id,
          domain,
          vercel_project: VERCEL_PROJECT,
        }),
      });
      if (!res.ok) throw new Error(await res.text());
      return res.json() as Promise<DomainSetupResponse>;
    },
    onSuccess: (data) => {
      if (!data.success || !data.setup_path) {
        toast.error('発行に失敗しました', { description: data.error?.slice(0, 140) });
        return;
      }
      const origin = typeof window !== 'undefined' ? window.location.origin : '';
      setClientUrl(`${origin}${data.setup_path}`);
      setStage('guide');
      onPublished?.();
    },
    onError: (e) => toast.error('発行に失敗しました', { description: String(e).slice(0, 140) }),
  });

  const exact = check?.exact;
  const total = Number(exact?.pricing?.registration_cost ?? 0) * years;

  const copyClientUrl = async () => {
    let ok = false;
    // HTTPS/localhost なら Clipboard API
    try {
      if (typeof navigator !== 'undefined' && navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(clientUrl);
        ok = true;
      }
    } catch {
      /* フォールバックへ */
    }
    // 非セキュア環境(IP/HTTP)はダイアログ内の入力欄を選択して execCommand
    if (!ok && urlInputRef.current) {
      const el = urlInputRef.current;
      el.focus();
      el.select();
      el.setSelectionRange(0, clientUrl.length);
      try {
        ok = document.execCommand('copy');
      } catch {
        ok = false;
      }
    }
    if (ok) toast.success('コピーしました');
    else toast.error('コピーできませんでした');
  };

  return (
    <Dialog open={open} onOpenChange={close}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{STAGE_TITLE[stage]}</DialogTitle>
          <DialogDescription className="sr-only">成果物を独自ドメインで公開します。</DialogDescription>
        </DialogHeader>

        {/* ステップ1: URL入力 */}
        {stage === 'domain' && (
          <div className="space-y-3">
            <div className="space-y-2">
              <Label htmlFor="domain">公開したいURL</Label>
              <Input
                id="domain"
                value={domain}
                onChange={(e) => {
                  setDomain(e.target.value.trim());
                  setCheck(null);
                }}
                placeholder="example.com"
                autoComplete="off"
              />
            </div>
            {exact && !exact.registrable && (
              <div className="space-y-2 rounded-md border border-amber-500/30 bg-amber-500/10 p-3 text-sm">
                <div className="flex items-center gap-2 text-amber-700">
                  <AlertCircle className="h-4 w-4" /> {exact.name} は使えません
                </div>
                {check!.suggestions.slice(0, 5).map((s) => (
                  <button
                    key={s.name}
                    onClick={() => {
                      setDomain(s.name);
                      setCheck(null);
                    }}
                    className="block w-full rounded px-2 py-1 text-left font-mono text-xs hover:bg-background"
                  >
                    {s.name}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}

        {/* ステップ2: 支払う人を選ぶ */}
        {stage === 'payer' && (
          <div className="space-y-2">
            <button
              type="button"
              onClick={() => setStage('confirm')}
              className="flex w-full items-start gap-3 rounded-md border p-3 text-left transition hover:bg-muted"
            >
              <UserRound className="mt-0.5 h-5 w-5 shrink-0" />
              <span>
                <span className="block font-medium">あなた</span>
                <span className="block text-xs text-muted-foreground">今すぐ取得して公開します</span>
              </span>
            </button>
            <button
              type="button"
              onClick={() => guideMutation.mutate()}
              disabled={guideMutation.isPending}
              className="flex w-full items-start gap-3 rounded-md border p-3 text-left transition hover:bg-muted disabled:opacity-60"
            >
              {guideMutation.isPending ? (
                <Loader2 className="mt-0.5 h-5 w-5 shrink-0 animate-spin" />
              ) : (
                <Send className="mt-0.5 h-5 w-5 shrink-0" />
              )}
              <span>
                <span className="block font-medium">あなた以外</span>
                <span className="block text-xs text-muted-foreground">相手に送るURLを発行します</span>
              </span>
            </button>
          </div>
        )}

        {/* ステップ3a: 購入確認（自分で払う） */}
        {stage === 'confirm' && exact && (
          <div className="space-y-3">
            <div className="rounded-md border bg-card p-3">
              <div className="font-mono text-base">{exact.name}</div>
              {exact.pricing && (
                <div className="mt-2 grid grid-cols-2 gap-1 text-sm">
                  <span className="text-muted-foreground">初年度</span>
                  <span className="text-right">${money(exact.pricing.registration_cost)} / 年</span>
                  <span className="text-muted-foreground">翌年以降</span>
                  <span className="text-right">${money(exact.pricing.renewal_cost)} / 年</span>
                </div>
              )}
            </div>
            <div className="space-y-2">
              <Label htmlFor="years">取得年数</Label>
              <Input
                id="years"
                type="number"
                min={1}
                max={10}
                value={years}
                onChange={(e) => setYears(Math.max(1, Math.min(10, Number(e.target.value) || 1)))}
              />
            </div>
          </div>
        )}

        {/* ステップ3a': 公開処理中 */}
        {stage === 'publishing' && (
          <div className="space-y-1.5 text-sm">
            {Object.entries(STEP_LABEL).map(([key, label]) => {
              const step = result?.steps.find((s) => s.name === key);
              return (
                <div key={key} className="flex items-center gap-3 px-1 py-1">
                  <StepIcon status={step?.status ?? 'pending'} />
                  <span>{label}</span>
                </div>
              );
            })}
          </div>
        )}

        {/* 公開結果 */}
        {stage === 'done' && result && (
          <div className="space-y-3">
            {result.success ? (
              <div className="rounded-md border border-emerald-500/30 bg-emerald-500/10 p-3">
                <div className="flex items-center gap-2 font-medium text-emerald-700">
                  <CheckCircle2 className="h-5 w-5" /> 公開しました
                </div>
                {result.deploy_url && (
                  <a
                    href={result.deploy_url}
                    target="_blank"
                    rel="noreferrer"
                    className="mt-1 block break-all text-sm text-primary underline"
                  >
                    {result.deploy_url}
                  </a>
                )}
              </div>
            ) : (
              <div className="rounded-md border border-red-500/30 bg-red-500/10 p-3">
                <div className="flex items-center gap-2 font-medium text-red-700">
                  <XCircle className="h-5 w-5" /> 公開できませんでした
                </div>
                {result.error && (
                  <pre className="mt-1 whitespace-pre-wrap break-all text-xs text-red-900">
                    {result.error}
                  </pre>
                )}
              </div>
            )}
          </div>
        )}

        {/* ステップ3b: 相手に送るURL */}
        {stage === 'guide' && (
          <div className="space-y-3">
            <p className="text-sm text-muted-foreground">このURLを相手に送ってください。</p>
            <Input
              ref={urlInputRef}
              readOnly
              value={clientUrl}
              onFocus={(e) => e.currentTarget.select()}
              className="font-mono text-xs"
            />
            <Button variant="secondary" size="sm" onClick={copyClientUrl}>
              <Copy className="mr-1 h-3.5 w-3.5" /> コピー
            </Button>
          </div>
        )}

        <DialogFooter>
          {stage === 'domain' && (
            <>
              <Button variant="ghost" onClick={() => close(false)}>
                キャンセル
              </Button>
              <Button
                onClick={() => checkMutation.mutate(domain)}
                disabled={checkMutation.isPending || !domain.includes('.')}
              >
                {checkMutation.isPending && <Loader2 className="mr-2 h-3 w-3 animate-spin" />}
                確認
              </Button>
            </>
          )}
          {stage === 'payer' && (
            <Button variant="ghost" onClick={() => setStage('domain')}>
              戻る
            </Button>
          )}
          {stage === 'confirm' && (
            <>
              <Button variant="ghost" onClick={() => setStage('payer')}>
                戻る
              </Button>
              <Button onClick={() => publishMutation.mutate()} disabled={publishMutation.isPending}>
                公開する（${money(total)}）
              </Button>
            </>
          )}
          {stage === 'publishing' && (
            <Button disabled variant="ghost">
              <Loader2 className="mr-2 h-3 w-3 animate-spin" /> 実行中
            </Button>
          )}
          {stage === 'guide' && (
            <Button variant="ghost" onClick={() => setStage('payer')}>
              戻る
            </Button>
          )}
          {(stage === 'done' || stage === 'guide') && (
            <Button onClick={() => close(false)}>閉じる</Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
