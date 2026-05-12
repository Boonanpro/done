'use client';

/**
 * カスタムドメインで artifact を公開するモーダル。
 * 4ステージ: input (ドメイン入力＋空き確認) → confirm (購入確定) → publishing (進捗) → done (結果)
 *
 * Phase 3 backend が提供する以下の API を使う:
 *   POST /api/v1/publish/check   ドメイン空き確認・価格
 *   POST /api/v1/publish/run     8ステップフロー実行
 */
import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { toast } from 'sonner';
import { CheckCircle2, Circle, Loader2, XCircle, AlertCircle, Globe, Sparkles } from 'lucide-react';

import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import type { ArtifactRecord } from '@/stores/preview-store';

type Stage = 'input' | 'confirm' | 'publishing' | 'done';

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

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  artifact: ArtifactRecord;
  onPublished?: () => void;
}

const STEP_LABEL: Record<string, string> = {
  check_availability: 'ドメイン空き確認',
  register_domain: 'ドメイン購入',
  wait_registration_complete: '登録完了待ち',
  attach_to_vercel: 'Vercel プロジェクト紐付け',
  configure_dns: 'DNS レコード設定',
  verify_dns_propagation: 'DNS 反映確認',
  generate_seo_assets: 'SEO アセット生成',
  update_artifact_db: 'DB 更新',
};

function StepIcon({ status }: { status: PublishStepDTO['status'] }) {
  if (status === 'completed') return <CheckCircle2 className="h-4 w-4 text-emerald-500" />;
  if (status === 'failed') return <XCircle className="h-4 w-4 text-red-500" />;
  if (status === 'running') return <Loader2 className="h-4 w-4 animate-spin text-primary" />;
  if (status === 'skipped') return <Circle className="h-4 w-4 text-muted-foreground" />;
  return <Circle className="h-4 w-4 text-muted-foreground" />;
}

export function PublishModal({ open, onOpenChange, artifact, onPublished }: Props) {
  const [stage, setStage] = useState<Stage>('input');
  const [domain, setDomain] = useState(artifact.custom_domain || `${artifact.slug}.com`);
  const [years, setYears] = useState(1);
  const [vercelProject, setVercelProject] = useState(artifact.slug);
  const [check, setCheck] = useState<DomainCheckResponse | null>(null);
  const [result, setResult] = useState<PublishResponse | null>(null);

  const reset = () => {
    setStage('input');
    setCheck(null);
    setResult(null);
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
      toast.error('ドメイン確認に失敗', { description: String(err).slice(0, 160) });
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
        toast.error('公開フローが失敗しました', { description: data.error?.slice(0, 160) });
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
      toast.error('公開リクエスト失敗', { description: String(err).slice(0, 160) });
    },
  });

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-primary" /> カスタムドメインで公開
          </DialogTitle>
          <DialogDescription>
            ドメインを購入して Vercel に紐付け、SEO 設定まで一気に完了します。
          </DialogDescription>
        </DialogHeader>

        {stage === 'input' && (
          <div className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="domain">希望のドメイン</Label>
              <Input
                id="domain"
                value={domain}
                onChange={(e) => setDomain(e.target.value)}
                placeholder="example.com"
                autoComplete="off"
              />
              <p className="text-xs text-muted-foreground">
                .com / .net / .org / .io / .dev など対応。.jp は非対応。
              </p>
            </div>
            <div className="space-y-2">
              <Label htmlFor="vercelProject">Vercel プロジェクト名</Label>
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
                  <div>{check.exact.name} は取得できません。</div>
                  {check.suggestions.length > 0 && (
                    <div className="mt-2 space-y-1">
                      <div className="text-xs text-muted-foreground">候補:</div>
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
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Globe className="h-4 w-4 text-primary" />
                  <span className="font-mono text-base">{check.exact.name}</span>
                </div>
                <Badge variant="secondary">取得可能</Badge>
              </div>
              {check.exact.pricing && (
                <div className="mt-3 grid grid-cols-2 gap-2 text-sm">
                  <div className="text-muted-foreground">登録料</div>
                  <div className="text-right font-medium">
                    ${check.exact.pricing.registration_cost} / 年
                  </div>
                  <div className="text-muted-foreground">更新料</div>
                  <div className="text-right font-medium">
                    ${check.exact.pricing.renewal_cost} / 年
                  </div>
                </div>
              )}
            </div>
            <div className="space-y-2">
              <Label htmlFor="years">登録年数</Label>
              <Input
                id="years"
                type="number"
                min={1}
                max={10}
                value={years}
                onChange={(e) => setYears(Math.max(1, Math.min(10, Number(e.target.value) || 1)))}
              />
              <p className="text-xs text-muted-foreground">
                合計: ${(Number(check.exact.pricing?.registration_cost ?? 0) * years).toFixed(2)}
              </p>
            </div>
            <div className="rounded-md border border-amber-500/30 bg-amber-500/10 p-3 text-xs text-amber-700">
              「公開」を押すと Cloudflare で実際にドメインが購入され、支払い方法に課金されます。
            </div>
          </div>
        )}

        {stage === 'publishing' && (
          <div className="space-y-2 text-sm">
            <div className="text-xs text-muted-foreground">公開フロー実行中...</div>
            {Object.entries(STEP_LABEL).map(([key, label]) => {
              const step = result?.steps.find((s) => s.name === key);
              const status = step?.status ?? (publishMutation.isPending ? 'pending' : 'pending');
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
              ドメイン登録は通常数秒〜2分。DNS反映は最大3分。
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
                  <span className="font-medium">公開フローが失敗しました</span>
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

        <DialogFooter>
          {stage === 'input' && (
            <>
              <Button variant="ghost" onClick={() => handleClose(false)}>
                キャンセル
              </Button>
              <Button
                onClick={() => checkMutation.mutate(domain)}
                disabled={checkMutation.isPending || !domain.includes('.')}
              >
                {checkMutation.isPending ? <Loader2 className="mr-2 h-3 w-3 animate-spin" /> : null}
                空き確認
              </Button>
            </>
          )}
          {stage === 'confirm' && (
            <>
              <Button variant="ghost" onClick={() => setStage('input')}>
                戻る
              </Button>
              <Button onClick={() => publishMutation.mutate()} disabled={publishMutation.isPending}>
                公開（${(Number(check?.exact?.pricing?.registration_cost ?? 0) * years).toFixed(2)} 課金）
              </Button>
            </>
          )}
          {stage === 'publishing' && (
            <Button disabled variant="ghost">
              <Loader2 className="mr-2 h-3 w-3 animate-spin" /> 実行中...
            </Button>
          )}
          {stage === 'done' && (
            <Button onClick={() => handleClose(false)}>閉じる</Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
