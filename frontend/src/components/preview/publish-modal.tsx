'use client';

import { useMemo, useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { toast } from 'sonner';
import {
  AlertCircle,
  CheckCircle2,
  Circle,
  Copy,
  Globe,
  Loader2,
  Send,
  Sparkles,
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
import { Badge } from '@/components/ui/badge';
import type { ArtifactRecord } from '@/stores/preview-store';

type Stage = 'input' | 'confirm' | 'publishing' | 'done' | 'guide';
type Payer = 'owner_pays' | 'client_owns';

interface DomainCheckCandidate {
  name: string;
  registrable: boolean;
  tier?: string | null;
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
  artifact_id: string;
  domain: string;
  deploy_url: string | null;
  steps: PublishStepDTO[];
  error: string | null;
  pricing?: { currency: string; registration_cost: string; renewal_cost: string } | null;
}

interface DomainSetupResponse {
  success: boolean;
  token?: string | null;
  setup_path?: string | null;
  domain?: string | null;
  status?: string | null;
  error?: string | null;
}

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  artifact: ArtifactRecord;
  onPublished?: () => void;
}

const STEP_LABEL: Record<string, string> = {
  check_availability: 'ドメイン確認',
  register_domain: 'ドメイン購入',
  wait_registration_complete: '購入完了待ち',
  attach_to_vercel: 'サイトに接続',
  configure_dns: 'URLの向き先設定',
  verify_dns_propagation: '反映確認',
  generate_seo_assets: '検索向けファイル作成',
  submit_to_search_console: '検索エンジンに登録',
  update_artifact_db: 'DANに保存',
};

function money(value?: string | number | null) {
  const n = Number(value ?? 0);
  return Number.isFinite(n) ? n.toFixed(2) : '0.00';
}

function shareOrigin() {
  const configured = process.env.NEXT_PUBLIC_SHARE_ORIGIN?.trim();
  if (configured) return configured.replace(/\/$/, '');
  if (typeof window !== 'undefined') return window.location.origin;
  return '';
}

function StepIcon({ status }: { status: PublishStepDTO['status'] }) {
  if (status === 'completed') return <CheckCircle2 className="h-4 w-4 text-emerald-500" />;
  if (status === 'failed') return <XCircle className="h-4 w-4 text-red-500" />;
  if (status === 'skipped') return <Circle className="h-4 w-4 text-muted-foreground/40" />;
  if (status === 'running') return <Loader2 className="h-4 w-4 animate-spin text-primary" />;
  return <Circle className="h-4 w-4 text-muted-foreground" />;
}

export function PublishModal({ open, onOpenChange, artifact, onPublished }: Props) {
  const [stage, setStage] = useState<Stage>('input');
  const [domain, setDomain] = useState(artifact.custom_domain || `${artifact.slug}.com`);
  const [years, setYears] = useState(1);
  const [vercelProject, setVercelProject] = useState('frontend');
  const [payer, setPayer] = useState<Payer>('owner_pays');
  const [check, setCheck] = useState<DomainCheckResponse | null>(null);
  const [result, setResult] = useState<PublishResponse | null>(null);
  const [guide, setGuide] = useState<DomainSetupResponse | null>(null);

  const clientUrl = useMemo(
    () => (guide?.setup_path ? `${shareOrigin()}${guide.setup_path}` : ''),
    [guide],
  );

  const reset = () => {
    setStage('input');
    setCheck(null);
    setResult(null);
    setGuide(null);
  };

  const handleClose = (next: boolean) => {
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
      if (data.exact?.registrable) setStage('confirm');
    },
    onError: (err) => {
      toast.error('ドメイン確認に失敗しました', { description: String(err).slice(0, 160) });
    },
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
          vercel_project: vercelProject,
          artifact_dir: `frontend/src/app/artifacts/${artifact.slug}`,
          write_seo_files: true,
          years,
          auto_renew: true,
          dry_run: false,
          payment_responsibility: 'owner_pays',
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
        toast.success('公開しました', { description: data.deploy_url || data.domain });
        onPublished?.();
      } else {
        toast.error('公開できませんでした', { description: data.error?.slice(0, 160) });
      }
    },
    onError: (err) => {
      setResult({
        success: false,
        artifact_id: artifact.id,
        domain,
        deploy_url: null,
        steps: [],
        error: String(err),
      });
      setStage('done');
      toast.error('公開リクエストに失敗しました', { description: String(err).slice(0, 160) });
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
          vercel_project: vercelProject,
        }),
      });
      if (!res.ok) throw new Error(await res.text());
      return res.json() as Promise<DomainSetupResponse>;
    },
    onSuccess: (data) => {
      if (!data.success) {
        toast.error('案内URLの発行に失敗しました', { description: data.error?.slice(0, 160) });
        return;
      }
      setGuide(data);
      setStage('guide');
      onPublished?.();
    },
    onError: (err) => {
      toast.error('案内URLの発行に失敗しました', { description: String(err).slice(0, 160) });
    },
  });

  const total = Number(check?.exact?.pricing?.registration_cost ?? 0) * years;

  const copyClientUrl = () => {
    if (!clientUrl) return;
    navigator.clipboard
      .writeText(clientUrl)
      .then(() => toast.success('案内URLをコピーしました'))
      .catch(() => toast.error('コピーできませんでした'));
  };

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-primary" /> 公開
          </DialogTitle>
          <DialogDescription>
            専用ドメインを取り、検索に出せる形へ進めます。ドメイン代を誰が持つかで進め方が変わります。
          </DialogDescription>
        </DialogHeader>

        {stage === 'input' && (
          <div className="space-y-4">
            <div className="space-y-2">
              <Label>誰がドメインを用意しますか？</Label>
              <div className="grid grid-cols-2 gap-2">
                <button
                  type="button"
                  onClick={() => {
                    setPayer('owner_pays');
                    setCheck(null);
                  }}
                  className={`rounded-md border p-3 text-left text-sm transition ${
                    payer === 'owner_pays' ? 'border-primary bg-primary/10' : 'hover:bg-muted'
                  }`}
                >
                  <UserRound className="mb-2 h-4 w-4" />
                  <div className="font-medium">自分で取得</div>
                  <div className="mt-1 text-xs text-muted-foreground">
                    その場で取得して公開まで進めます。
                  </div>
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setPayer('client_owns');
                    setCheck(null);
                  }}
                  className={`rounded-md border p-3 text-left text-sm transition ${
                    payer === 'client_owns' ? 'border-primary bg-primary/10' : 'hover:bg-muted'
                  }`}
                >
                  <Send className="mb-2 h-4 w-4" />
                  <div className="font-medium">クライアントが用意</div>
                  <div className="mt-1 text-xs text-muted-foreground">
                    案内URLを発行して相手に送ります。
                  </div>
                </button>
              </div>
              {payer === 'client_owns' && (
                <div className="flex gap-2 rounded-md border border-blue-500/30 bg-blue-500/10 p-3 text-xs text-blue-800">
                  <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                  <div>
                    案内URLを発行すると、相手はそのページだけで取得・設定・公開まで進められます。
                    ドメインは相手の名義・支払いになり、相手の資産として残ります。
                  </div>
                </div>
              )}
            </div>

            <div className="space-y-2">
              <Label htmlFor="domain">
                {payer === 'client_owns' ? '相手に取得してもらうURL' : '取りたいURL'}
              </Label>
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
              <p className="text-xs text-muted-foreground">
                例: salon-styleup.com。
                {payer === 'client_owns'
                  ? ' このドメイン名を相手に取得してもらいます。'
                  : ' 空いていれば、このURLで公開できます。'}
              </p>
            </div>

            <div className="space-y-2">
              <Label htmlFor="vercelProject">公開先</Label>
              <Input
                id="vercelProject"
                value={vercelProject}
                onChange={(e) => setVercelProject(e.target.value)}
              />
            </div>

            {check?.exact && !check.exact.registrable && (
              <div className="flex items-start gap-2 rounded-md border border-amber-500/30 bg-amber-500/10 p-3 text-sm">
                <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-amber-500" />
                <div>
                  <div>{check.exact.name} は空いていません。</div>
                  {check.suggestions.length > 0 && (
                    <div className="mt-2 space-y-1">
                      <div className="text-xs text-muted-foreground">代わりの候補</div>
                      {check.suggestions.slice(0, 5).map((s) => (
                        <button
                          key={s.name}
                          onClick={() => {
                            setDomain(s.name);
                            setCheck(null);
                          }}
                          className="block w-full rounded px-2 py-1 text-left text-xs hover:bg-background"
                        >
                          <span className="font-mono">{s.name}</span>
                          {s.pricing && (
                            <span className="ml-2 text-muted-foreground">
                              ${s.pricing.registration_cost}/年
                            </span>
                          )}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        )}

        {stage === 'confirm' && check?.exact && (
          <div className="space-y-4">
            <div className="rounded-md border bg-card p-4">
              <div className="flex items-center justify-between gap-3">
                <div className="flex min-w-0 items-center gap-2">
                  <Globe className="h-4 w-4 shrink-0 text-primary" />
                  <span className="truncate font-mono text-base">{check.exact.name}</span>
                </div>
                <Badge variant="secondary">取得できます</Badge>
              </div>
              {check.exact.pricing && (
                <div className="mt-3 grid grid-cols-2 gap-2 text-sm">
                  <div className="text-muted-foreground">初年度</div>
                  <div className="text-right font-medium">
                    ${money(check.exact.pricing.registration_cost)} / 年
                  </div>
                  <div className="text-muted-foreground">翌年以降</div>
                  <div className="text-right font-medium">
                    ${money(check.exact.pricing.renewal_cost)} / 年
                  </div>
                </div>
              )}
            </div>

            <div className="space-y-2">
              <Label htmlFor="years">何年分買いますか？</Label>
              <Input
                id="years"
                type="number"
                min={1}
                max={10}
                value={years}
                onChange={(e) => setYears(Math.max(1, Math.min(10, Number(e.target.value) || 1)))}
              />
              <p className="text-xs text-muted-foreground">合計 ${money(total)}</p>
            </div>

            <div className="rounded-md border border-amber-500/30 bg-amber-500/10 p-3 text-xs text-amber-800">
              「公開する」を押すと、登録済みのCloudflare支払い方法で実際に購入します。
            </div>
          </div>
        )}

        {stage === 'publishing' && (
          <div className="space-y-2 text-sm">
            <div className="text-xs text-muted-foreground">公開しています...</div>
            {Object.entries(STEP_LABEL).map(([key, label]) => {
              const step = result?.steps.find((s) => s.name === key);
              const status = step?.status ?? 'pending';
              return (
                <div key={key} className="flex items-center gap-3 rounded px-2 py-1.5">
                  <StepIcon status={status} />
                  <span className="flex-1">{label}</span>
                  {step?.duration_ms ? (
                    <span className="text-xs text-muted-foreground">{step.duration_ms}ms</span>
                  ) : null}
                </div>
              );
            })}
            <div className="flex items-center gap-2 rounded-md border bg-muted/30 p-3 text-xs">
              <Loader2 className="h-3 w-3 animate-spin" />
              ドメイン購入とURL反映には数分かかることがあります。
            </div>
          </div>
        )}

        {stage === 'done' && result && (
          <div className="space-y-3">
            {result.success ? (
              <div className="rounded-md border border-emerald-500/30 bg-emerald-500/10 p-4">
                <div className="flex items-center gap-2 text-emerald-700">
                  <CheckCircle2 className="h-5 w-5" />
                  <span className="font-medium">公開しました</span>
                </div>
                {result.deploy_url && (
                  <a
                    href={result.deploy_url}
                    target="_blank"
                    rel="noreferrer"
                    className="mt-2 block break-all text-sm text-primary underline"
                  >
                    {result.deploy_url}
                  </a>
                )}
              </div>
            ) : (
              <div className="rounded-md border border-red-500/30 bg-red-500/10 p-4">
                <div className="flex items-center gap-2 text-red-700">
                  <XCircle className="h-5 w-5" />
                  <span className="font-medium">公開できませんでした</span>
                </div>
                {result.error && (
                  <pre className="mt-2 whitespace-pre-wrap break-all text-xs text-red-900">
                    {result.error}
                  </pre>
                )}
              </div>
            )}
            <div className="space-y-1 text-sm">
              {result.steps.map((s) => (
                <div key={s.name} className="flex items-center gap-3 rounded px-2 py-1.5">
                  <StepIcon status={s.status} />
                  <span className="flex-1">{STEP_LABEL[s.name] ?? s.name}</span>
                  <span className="text-xs text-muted-foreground">{s.detail}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {stage === 'guide' && (
          <div className="space-y-4">
            <div className="rounded-md border border-emerald-500/30 bg-emerald-500/10 p-4">
              <div className="flex items-center gap-2 text-emerald-700">
                <CheckCircle2 className="h-5 w-5" />
                <span className="font-medium">クライアント用の案内URLを発行しました</span>
              </div>
              <p className="mt-2 text-xs text-emerald-900/80">
                このURLを相手に送ってください。相手はこのページだけで、ドメインの取得・設定・公開まで
                自分で進められます。設定が完了すると、サイトは自動で公開されます。
              </p>
            </div>

            <div className="space-y-2">
              <Label>案内URL</Label>
              <div className="break-all rounded-md bg-muted px-3 py-2 font-mono text-xs">
                {clientUrl}
              </div>
              <Button variant="secondary" size="sm" onClick={copyClientUrl}>
                <Copy className="mr-1 h-3.5 w-3.5" /> 案内URLをコピー
              </Button>
            </div>

            <div className="space-y-1.5 rounded-md border bg-muted/30 p-3 text-xs text-muted-foreground">
              <div className="font-medium text-foreground">相手がこのページで行うこと</div>
              <div>1. 案内されたサービスでドメイン（{domain}）を取得</div>
              <div>2. 表示されたDNSレコードを設定</div>
              <div>3.「接続を確認」を押す → 公開完了</div>
            </div>
          </div>
        )}

        <DialogFooter>
          {stage === 'input' && (
            <>
              <Button variant="ghost" onClick={() => handleClose(false)}>
                キャンセル
              </Button>
              {payer === 'owner_pays' ? (
                <Button
                  onClick={() => checkMutation.mutate(domain)}
                  disabled={checkMutation.isPending || !domain.includes('.')}
                >
                  {checkMutation.isPending ? (
                    <Loader2 className="mr-2 h-3 w-3 animate-spin" />
                  ) : null}
                  URLを確認
                </Button>
              ) : (
                <Button
                  onClick={() => guideMutation.mutate()}
                  disabled={guideMutation.isPending || !domain.includes('.')}
                >
                  {guideMutation.isPending ? (
                    <Loader2 className="mr-2 h-3 w-3 animate-spin" />
                  ) : null}
                  案内URLを発行
                </Button>
              )}
            </>
          )}
          {stage === 'confirm' && (
            <>
              <Button variant="ghost" onClick={() => setStage('input')}>
                戻る
              </Button>
              <Button
                onClick={() => publishMutation.mutate()}
                disabled={publishMutation.isPending}
              >
                公開する（${money(total)}）
              </Button>
            </>
          )}
          {stage === 'publishing' && (
            <Button disabled variant="ghost">
              <Loader2 className="mr-2 h-3 w-3 animate-spin" /> 実行中...
            </Button>
          )}
          {(stage === 'done' || stage === 'guide') && (
            <Button onClick={() => handleClose(false)}>閉じる</Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
