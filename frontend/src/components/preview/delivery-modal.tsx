'use client';

import { useState } from 'react';
import { toast } from 'sonner';
import { ClipboardList, Copy } from 'lucide-react';

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { copyToClipboard } from '@/lib/clipboard';
import type { ArtifactRecord } from '@/stores/preview-store';
import { artifactSharePath } from '@/lib/artifact-paths';

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  artifact: ArtifactRecord;
  publicUrl: string;
  onUpdated?: (artifact: ArtifactRecord) => void;
  onRequestDomain?: () => void;
}

function artifactLabel(type: string) {
  if (type === 'dashboard') return 'ダッシュボード';
  if (type === 'tool') return 'ツール';
  return '成果物';
}

export function DeliveryModal({
  open,
  onOpenChange,
  artifact,
  publicUrl,
  onUpdated,
  onRequestDomain,
}: Props) {
  const [saving, setSaving] = useState(false);
  const sharePath = artifactSharePath(
    artifact.share_url || artifact.preview_url || artifact.slug,
  );
  const deliveryUrl = artifact.production_url || publicUrl;
  const hasDedicatedUrl = Boolean(artifact.production_url);

  const save = async () => {
    setSaving(true);
    try {
      // 専用URL未発行なら発行する
      let finalUrl = deliveryUrl;
      if (!hasDedicatedUrl) {
        const res = await fetch('/api/v1/publish/delivery-url', {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            artifact_id: artifact.id,
            slug: artifact.slug,
            vercel_project: 'frontend',
          }),
        });
        if (!res.ok) throw new Error(await res.text());
        const data = await res.json();
        if (!data.success) throw new Error(data.error || 'URL発行に失敗しました');
        finalUrl = data.url || deliveryUrl;
      }

      const patch = await fetch(`/api/v1/chat-artifact/${artifact.id}`, {
        method: 'PATCH',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          delivery_status: 'ready',
          delivery_mode: 'dedicated_url',
          target_audience: artifact.artifact_type === 'dashboard' ? 'internal' : 'client',
          requires_auth: artifact.artifact_type === 'dashboard',
          production_url: finalUrl,
          delivery_checklist: { delivery_url: finalUrl, share_path: sharePath },
        }),
      });
      if (!patch.ok) throw new Error(await patch.text());
      onUpdated?.((await patch.json()) as ArtifactRecord);

      // コピー失敗（HTTP環境等）でも納品準備自体は成功扱いにする
      const copied = await copyToClipboard(finalUrl);
      toast.success(copied ? '納品URLをコピーしました' : '納品URLを準備しました');
      onOpenChange(false);
    } catch (error) {
      toast.error('納品URLの準備に失敗しました', {
        description: String(error).slice(0, 160),
      });
    } finally {
      setSaving(false);
    }
  };

  const copyUrl = async () => {
    const ok = await copyToClipboard(deliveryUrl);
    if (ok) toast.success('コピーしました');
    else toast.error('コピーできませんでした');
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <ClipboardList className="h-4 w-4 text-primary" /> 納品URL
          </DialogTitle>
          <DialogDescription>
            {artifactLabel(artifact.artifact_type)}を相手に渡すためのURLです。
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          <div className="break-all rounded-md bg-muted px-3 py-2 font-mono text-xs">
            {deliveryUrl}
          </div>
          <Button variant="secondary" size="sm" onClick={copyUrl}>
            <Copy className="mr-1 h-3.5 w-3.5" /> URLをコピー
          </Button>
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            閉じる
          </Button>
          {onRequestDomain && (
            <Button
              variant="secondary"
              onClick={() => {
                onOpenChange(false);
                onRequestDomain();
              }}
            >
              独自ドメインを取る
            </Button>
          )}
          <Button onClick={save} disabled={saving}>
            {saving ? '発行中...' : hasDedicatedUrl ? 'コピーして完了' : '専用URLを発行'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
