'use client';

import { useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';
import { ArrowLeft, ArrowRight, CheckCircle2, ClipboardList, Copy, ShieldCheck } from 'lucide-react';

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import type { ArtifactRecord } from '@/stores/preview-store';
import { artifactSharePath } from '@/lib/artifact-paths';

type DeliveryMode = 'preview' | 'private_link' | 'public_tool' | 'client_domain' | 'internal_only';
type TargetAudience = 'internal' | 'client' | 'public';
type PaymentResponsibility =
  | 'owner_pays'
  | 'client_pays'
  | 'client_invited_to_pay'
  | 'bring_existing_domain'
  | 'manual_invoice';
type DeliveryStatus = 'preview' | 'review' | 'ready' | 'delivered';

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  artifact: ArtifactRecord;
  publicUrl: string;
  onUpdated?: (artifact: ArtifactRecord) => void;
}

type Plan = {
  mode: DeliveryMode;
  audience: TargetAudience;
  requiresAuth: boolean;
  payment: PaymentResponsibility;
  summary: string;
  reason: string;
};

const PAYMENT_LABEL: Record<PaymentResponsibility, string> = {
  owner_pays: '自分が払う',
  client_pays: 'クライアントが払う',
  client_invited_to_pay: 'クライアントに支払いリンクを送る',
  bring_existing_domain: 'クライアントの既存ドメインを使う',
  manual_invoice: '請求書や振込であとから処理する',
};

function recommendedPlan(type: string): Plan {
  if (type === 'website') {
    return {
      mode: 'client_domain',
      audience: 'public',
      requiresAuth: false,
      payment: 'client_pays',
      summary: '独自ドメインで公開する',
      reason: 'HPやLPは、お客さんや検索から見られる前提なので、専用のURLにするのがおすすめです。',
    };
  }
  if (type === 'dashboard') {
    return {
      mode: 'internal_only',
      audience: 'internal',
      requiresAuth: true,
      payment: 'owner_pays',
      summary: '限られた人だけが見られるようにする',
      reason: 'ダッシュボードは業務データを含みやすいので、誰でも開けるURLにしない方が安全です。',
    };
  }
  return {
    mode: 'private_link',
    audience: 'client',
    requiresAuth: false,
    payment: 'client_pays',
    summary: 'URLを知っている人だけが使える形で渡す',
    reason: '業務ツールは、まず限定URLで試してもらい、必要になったらログインや専用URLに進むのが安全です。',
  };
}

function checklistFor(type: string, plan: Plan) {
  const items = [
    '仮公開URLで開けることを確認する',
    'スマホとPCで主要画面を確認する',
    '見せてはいけない情報が入っていないか確認する',
  ];
  if (plan.requiresAuth || plan.mode === 'internal_only') items.push('誰が見られるべきかを決める');
  if (plan.mode === 'client_domain') items.push('使うドメイン名と支払い方法を決める');
  if (type === 'website') items.push('検索対策、SNS表示、問い合わせ導線を確認する');
  if (type === 'dashboard') items.push('表示データと閲覧者を確認する');
  if (type === 'tool') items.push('入力した内容をあとから見返す必要があるか決める');
  return items;
}

function artifactKindLabel(type: string) {
  if (type === 'website') return 'HP/LP';
  if (type === 'dashboard') return 'ダッシュボード';
  if (type === 'tool') return 'ツール';
  return '成果物';
}

function copyText(text: string) {
  return navigator.clipboard.writeText(text);
}

function Choice({
  active,
  title,
  description,
  onClick,
}: {
  active: boolean;
  title: string;
  description: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`w-full rounded-lg border p-3 text-left transition-colors ${
        active ? 'border-primary bg-primary/10' : 'border-border hover:bg-muted'
      }`}
    >
      <div className="font-medium">{title}</div>
      <div className="mt-1 text-sm text-muted-foreground">{description}</div>
    </button>
  );
}

export function DeliveryModal({ open, onOpenChange, artifact, publicUrl, onUpdated }: Props) {
  const basePlan = useMemo(() => recommendedPlan(artifact.artifact_type), [artifact.artifact_type]);
  const [step, setStep] = useState(0);
  const [plan, setPlan] = useState<Plan>(basePlan);
  const [notes, setNotes] = useState(artifact.handoff_notes || '');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
    const recommended = recommendedPlan(artifact.artifact_type);
    setStep(0);
    setPlan({
      ...recommended,
      mode: (artifact.delivery_mode as DeliveryMode | null) || recommended.mode,
      audience: (artifact.target_audience as TargetAudience | null) || recommended.audience,
      requiresAuth: artifact.requires_auth ?? recommended.requiresAuth,
      payment: (artifact.payment_responsibility as PaymentResponsibility | null) || recommended.payment,
    });
    setNotes(artifact.handoff_notes || '');
  }, [artifact, open]);

  const checklist = useMemo(() => checklistFor(artifact.artifact_type, plan), [artifact.artifact_type, plan]);
  const sharePath = artifactSharePath(artifact.share_url || artifact.preview_url || artifact.slug);
  const status: DeliveryStatus = plan.mode === 'preview' ? 'review' : 'ready';
  const totalSteps = 4;

  const save = async () => {
    setSaving(true);
    try {
      const res = await fetch(`/api/v1/chat-artifact/${artifact.id}`, {
        method: 'PATCH',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          delivery_status: status,
          delivery_mode: plan.mode,
          target_audience: plan.audience,
          requires_auth: plan.requiresAuth,
          payment_responsibility: plan.payment,
          handoff_notes: notes,
          delivery_checklist: {
            recommendation: plan.summary,
            recommendation_reason: plan.reason,
            items: checklist.map((label) => ({ label, done: false })),
            share_path: sharePath,
          },
        }),
      });
      if (!res.ok) throw new Error(await res.text());
      const updated = (await res.json()) as ArtifactRecord;
      onUpdated?.(updated);
      toast.success('納品準備を保存しました');
      onOpenChange(false);
    } catch (error) {
      toast.error('納品準備の保存に失敗しました', { description: String(error).slice(0, 160) });
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <ClipboardList className="h-4 w-4 text-primary" /> 納品準備
          </DialogTitle>
          <DialogDescription>
            難しい設定名ではなく、DANのおすすめを確認しながら進めます。
          </DialogDescription>
        </DialogHeader>

        <div className="mb-1 flex items-center gap-2">
          {Array.from({ length: totalSteps }).map((_, index) => (
            <div
              key={index}
              className={`h-1.5 flex-1 rounded-full ${index <= step ? 'bg-primary' : 'bg-muted'}`}
            />
          ))}
        </div>

        {step === 0 && (
          <div className="space-y-4">
            <div className="rounded-lg border bg-muted/30 p-4">
              <div className="text-sm text-muted-foreground">DANの判定</div>
              <div className="mt-1 text-lg font-semibold">
                これは「{artifactKindLabel(artifact.artifact_type)}」として扱います
              </div>
              <div className="mt-3 text-sm text-muted-foreground">{plan.reason}</div>
            </div>
            <div className="space-y-2">
              <Choice
                active={plan.mode === basePlan.mode && plan.requiresAuth === basePlan.requiresAuth}
                title={`おすすめで進める: ${basePlan.summary}`}
                description="迷ったらこれで大丈夫です。あとから変更できます。"
                onClick={() => setPlan(basePlan)}
              />
              <Choice
                active={plan.mode === 'preview'}
                title="まだ確認だけしたい"
                description="第三者に渡す前の、仮確認URLとして扱います。"
                onClick={() => setPlan({ ...plan, mode: 'preview', audience: 'internal', requiresAuth: false })}
              />
            </div>
          </div>
        )}

        {step === 1 && (
          <div className="space-y-4">
            <div>
              <div className="text-lg font-semibold">このURLを知っている人なら、誰でも使えて大丈夫ですか？</div>
              <div className="mt-1 text-sm text-muted-foreground">
                わからなければ「おすすめで」を選んでください。
              </div>
            </div>
            <div className="space-y-2">
              <Choice
                active={!plan.requiresAuth && plan.mode !== 'internal_only'}
                title="大丈夫"
                description="URLを知っている人は開けます。確認共有や簡単な納品向きです。"
                onClick={() => setPlan({ ...plan, requiresAuth: false, mode: plan.mode === 'internal_only' ? 'private_link' : plan.mode })}
              />
              <Choice
                active={plan.requiresAuth}
                title="限られた人だけにしたい"
                description="ログインや権限管理を前提にします。業務データがある場合はこちらです。"
                onClick={() => setPlan({ ...plan, requiresAuth: true, mode: 'internal_only', audience: 'internal' })}
              />
              <Choice
                active={plan.requiresAuth === basePlan.requiresAuth && plan.mode === basePlan.mode}
                title="おすすめで"
                description={basePlan.reason}
                onClick={() => setPlan(basePlan)}
              />
            </div>
          </div>
        )}

        {step === 2 && (
          <div className="space-y-4">
            <div>
              <div className="text-lg font-semibold">お金がかかる場合、誰が払う想定ですか？</div>
              <div className="mt-1 text-sm text-muted-foreground">
                たとえば独自ドメイン代や本番公開費用です。まだなら「あとで決める」で大丈夫です。
              </div>
            </div>
            <div className="space-y-2">
              {(Object.keys(PAYMENT_LABEL) as PaymentResponsibility[]).map((key) => (
                <Choice
                  key={key}
                  active={plan.payment === key}
                  title={PAYMENT_LABEL[key]}
                  description={key === 'client_invited_to_pay' ? '今後、決済リンクを送る導線に接続します。' : 'この前提で納品メモに残します。'}
                  onClick={() => setPlan({ ...plan, payment: key })}
                />
              ))}
            </div>
          </div>
        )}

        {step === 3 && (
          <div className="space-y-4">
            <div className="rounded-lg border bg-muted/30 p-4">
              <div className="flex items-center gap-2 text-sm font-medium">
                <ShieldCheck className="h-4 w-4" /> 今回のおすすめ
              </div>
              <div className="mt-2 text-lg font-semibold">{plan.summary}</div>
              <div className="mt-2 break-all font-mono text-xs text-muted-foreground">{publicUrl}</div>
              <Button
                variant="secondary"
                size="sm"
                className="mt-3"
                onClick={() => copyText(publicUrl).then(() => toast.success('URLをコピーしました'))}
              >
                <Copy className="mr-1 h-3.5 w-3.5" /> URLをコピー
              </Button>
            </div>

            <div className="space-y-1">
              {checklist.map((item) => (
                <div key={item} className="flex items-center gap-2 text-sm text-muted-foreground">
                  <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" /> {item}
                </div>
              ))}
            </div>

            <Textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="必要ならメモを書いてください。例: 先方の担当者、確認期限、注意点など"
            />
          </div>
        )}

        <DialogFooter className="gap-2">
          <Button variant="secondary" onClick={() => (step === 0 ? onOpenChange(false) : setStep((s) => s - 1))}>
            {step === 0 ? '閉じる' : (
              <>
                <ArrowLeft className="mr-1 h-3.5 w-3.5" /> 戻る
              </>
            )}
          </Button>
          {step < totalSteps - 1 ? (
            <Button onClick={() => setStep((s) => s + 1)}>
              次へ <ArrowRight className="ml-1 h-3.5 w-3.5" />
            </Button>
          ) : (
            <Button onClick={save} disabled={saving}>
              {saving ? '保存中...' : 'この内容で保存'}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
