'use client';

import { useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';
import { CheckCircle2, ClipboardList, ExternalLink, ShieldCheck } from 'lucide-react';

import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import type { ArtifactRecord } from '@/stores/preview-store';
import { artifactSharePath } from '@/lib/artifact-paths';

type DeliveryMode = 'preview' | 'private_link' | 'public_tool' | 'client_domain' | 'internal_only';
type TargetAudience = 'internal' | 'client' | 'public';
type PaymentResponsibility = 'owner_pays' | 'client_pays' | 'client_invited_to_pay' | 'bring_existing_domain' | 'manual_invoice';
type DeliveryStatus = 'preview' | 'review' | 'ready' | 'delivered';

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  artifact: ArtifactRecord;
  publicUrl: string;
  onUpdated?: (artifact: ArtifactRecord) => void;
}

const MODE_LABEL: Record<DeliveryMode, string> = {
  preview: '確認共有',
  private_link: '限定URLで共有',
  public_tool: '公開ツールとして提供',
  client_domain: '専用/独自ドメインで提供',
  internal_only: '社内限定',
};

const AUDIENCE_LABEL: Record<TargetAudience, string> = {
  internal: '自分/社内',
  client: 'クライアント',
  public: '一般公開',
};

const PAYMENT_LABEL: Record<PaymentResponsibility, string> = {
  owner_pays: '自分が支払う',
  client_pays: 'クライアントが支払う',
  client_invited_to_pay: 'クライアントに決済リンクを送る',
  bring_existing_domain: '既存ドメインを使う',
  manual_invoice: '請求書/振込で別処理',
};

function defaultMode(type: string): DeliveryMode {
  if (type === 'dashboard') return 'internal_only';
  if (type === 'website') return 'client_domain';
  return 'private_link';
}

function checklistFor(type: string, mode: DeliveryMode, requiresAuth: boolean) {
  const items = [
    '仮公開URLで表示確認する',
    'スマホ/PCで主要画面を確認する',
    '第三者に渡してよい情報だけが入っているか確認する',
  ];
  if (requiresAuth || mode === 'internal_only') items.push('ログイン/権限の設計を確認する');
  if (mode === 'client_domain') items.push('ドメイン名と支払い者を決める');
  if (type === 'website') items.push('SEO、OGP、問い合わせ導線を確認する');
  if (type === 'dashboard') items.push('表示データと閲覧者範囲を確認する');
  if (type === 'tool') items.push('入力データの保存有無と運用責任者を確認する');
  return items;
}

async function copyText(text: string) {
  await navigator.clipboard.writeText(text);
}

export function DeliveryModal({ open, onOpenChange, artifact, publicUrl, onUpdated }: Props) {
  const initialMode = (artifact.delivery_mode as DeliveryMode | null) || defaultMode(artifact.artifact_type);
  const [mode, setMode] = useState<DeliveryMode>(initialMode);
  const [audience, setAudience] = useState<TargetAudience>((artifact.target_audience as TargetAudience | null) || 'client');
  const [requiresAuth, setRequiresAuth] = useState(Boolean(artifact.requires_auth));
  const [payment, setPayment] = useState<PaymentResponsibility>((artifact.payment_responsibility as PaymentResponsibility | null) || 'owner_pays');
  const [notes, setNotes] = useState(artifact.handoff_notes || '');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
    setMode((artifact.delivery_mode as DeliveryMode | null) || defaultMode(artifact.artifact_type));
    setAudience((artifact.target_audience as TargetAudience | null) || 'client');
    setRequiresAuth(Boolean(artifact.requires_auth));
    setPayment((artifact.payment_responsibility as PaymentResponsibility | null) || 'owner_pays');
    setNotes(artifact.handoff_notes || '');
  }, [artifact, open]);

  const checklist = useMemo(
    () => checklistFor(artifact.artifact_type, mode, requiresAuth),
    [artifact.artifact_type, mode, requiresAuth],
  );

  const status: DeliveryStatus = mode === 'preview' ? 'review' : 'ready';
  const sharePath = artifactSharePath(artifact.share_url || artifact.preview_url || artifact.slug);

  const save = async () => {
    setSaving(true);
    try {
      const res = await fetch(`/api/v1/chat-artifact/${artifact.id}`, {
        method: 'PATCH',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          delivery_status: status,
          delivery_mode: mode,
          target_audience: audience,
          requires_auth: requiresAuth,
          payment_responsibility: payment,
          handoff_notes: notes,
          delivery_checklist: {
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
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <ClipboardList className="h-4 w-4 text-primary" /> 納品準備
          </DialogTitle>
          <DialogDescription>
            成果物を誰に、どのURLで、どの範囲まで提供するかを決めます。
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-4 md:grid-cols-2">
          <div className="space-y-3">
            <div className="space-y-2">
              <Label>提供方法</Label>
              <div className="grid gap-2">
                {(Object.keys(MODE_LABEL) as DeliveryMode[]).map((key) => (
                  <button
                    key={key}
                    type="button"
                    onClick={() => setMode(key)}
                    className={`rounded-md border px-3 py-2 text-left text-sm ${mode === key ? 'border-primary bg-primary/10' : 'border-border hover:bg-muted'}`}
                  >
                    {MODE_LABEL[key]}
                  </button>
                ))}
              </div>
            </div>
            <div className="space-y-2">
              <Label>利用者</Label>
              <select className="w-full rounded-md border bg-background px-3 py-2 text-sm" value={audience} onChange={(e) => setAudience(e.target.value as TargetAudience)}>
                {(Object.keys(AUDIENCE_LABEL) as TargetAudience[]).map((key) => (
                  <option key={key} value={key}>{AUDIENCE_LABEL[key]}</option>
                ))}
              </select>
            </div>
            <label className="flex items-center gap-2 rounded-md border p-3 text-sm">
              <input type="checkbox" checked={requiresAuth} onChange={(e) => setRequiresAuth(e.target.checked)} />
              ログイン/権限管理が必要
            </label>
          </div>

          <div className="space-y-3">
            <div className="rounded-md border bg-muted/30 p-3">
              <div className="mb-2 flex items-center gap-2 text-sm font-medium">
                <ExternalLink className="h-4 w-4" /> 仮公開URL
              </div>
              <div className="break-all font-mono text-xs text-muted-foreground">{publicUrl}</div>
              <Button variant="secondary" size="sm" className="mt-3" onClick={() => copyText(publicUrl).then(() => toast.success('URLをコピーしました'))}>
                URLをコピー
              </Button>
            </div>
            <div className="space-y-2">
              <Label>支払い者</Label>
              <select className="w-full rounded-md border bg-background px-3 py-2 text-sm" value={payment} onChange={(e) => setPayment(e.target.value as PaymentResponsibility)}>
                {(Object.keys(PAYMENT_LABEL) as PaymentResponsibility[]).map((key) => (
                  <option key={key} value={key}>{PAYMENT_LABEL[key]}</option>
                ))}
              </select>
            </div>
            <div className="space-y-2">
              <Label>引き渡しメモ</Label>
              <Textarea value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="クライアント名、運用者、注意点など" />
            </div>
          </div>
        </div>

        <div className="rounded-md border p-3">
          <div className="mb-2 flex items-center gap-2 text-sm font-medium">
            <ShieldCheck className="h-4 w-4" /> 確認項目
          </div>
          <div className="space-y-1">
            {checklist.map((item) => (
              <div key={item} className="flex items-center gap-2 text-sm text-muted-foreground">
                <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" /> {item}
              </div>
            ))}
          </div>
        </div>

        <DialogFooter>
          <Button variant="secondary" onClick={() => onOpenChange(false)}>閉じる</Button>
          <Button onClick={save} disabled={saving}>{saving ? '保存中...' : '保存する'}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
