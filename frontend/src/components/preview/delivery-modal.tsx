'use client';

import { useMemo, useState } from 'react';
import { toast } from 'sonner';
import { CheckCircle2, ClipboardList, Copy, ExternalLink } from 'lucide-react';

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

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  artifact: ArtifactRecord;
  publicUrl: string;
  onUpdated?: (artifact: ArtifactRecord) => void;
}

function artifactLabel(type: string) {
  if (type === 'dashboard') return 'ダッシュボード';
  if (type === 'tool') return 'ツール';
  return '成果物';
}

function deliveryCopy(type: string) {
  if (type === 'dashboard') {
    return {
      title: 'このダッシュボードは、納品URLで確認してもらえます。',
      body: 'まずはこのURLを渡して、表示内容と閲覧範囲を確認してもらう段階です。社外秘データを扱う場合は、次の段階でログイン付きにします。',
      mode: 'internal_only',
      requiresAuth: true,
    };
  }
  return {
    title: 'このツールは、納品URLで使ってもらえます。',
    body: 'まずはこのURLを渡せば、相手はブラウザで開いて動きを確認できます。本格運用する場合は、次の段階で専用URLやログイン付きにします。',
    mode: 'private_link',
    requiresAuth: false,
  };
}

async function copyText(text: string) {
  await navigator.clipboard.writeText(text);
}

export function DeliveryModal({ open, onOpenChange, artifact, publicUrl, onUpdated }: Props) {
  const [notes, setNotes] = useState(artifact.handoff_notes || '');
  const [saving, setSaving] = useState(false);
  const copy = useMemo(() => deliveryCopy(artifact.artifact_type), [artifact.artifact_type]);
  const sharePath = artifactSharePath(artifact.share_url || artifact.preview_url || artifact.slug);

  const save = async () => {
    setSaving(true);
    try {
      const res = await fetch(`/api/v1/chat-artifact/${artifact.id}`, {
        method: 'PATCH',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          delivery_status: 'ready',
          delivery_mode: copy.mode,
          target_audience: artifact.artifact_type === 'dashboard' ? 'internal' : 'client',
          requires_auth: copy.requiresAuth,
          payment_responsibility: 'client_pays',
          handoff_notes: notes,
          delivery_checklist: {
            delivery_url: publicUrl,
            share_path: sharePath,
            next_step:
              artifact.artifact_type === 'dashboard'
                ? '閲覧者とログイン要否を決める'
                : '相手にURLを渡して動作確認してもらう',
          },
        }),
      });
      if (!res.ok) throw new Error(await res.text());
      const updated = (await res.json()) as ArtifactRecord;
      await copyText(publicUrl);
      onUpdated?.(updated);
      toast.success('納品URLをコピーしました');
      onOpenChange(false);
    } catch (error) {
      toast.error('納品URLの準備に失敗しました', { description: String(error).slice(0, 160) });
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <ClipboardList className="h-4 w-4 text-primary" /> 納品URL
          </DialogTitle>
          <DialogDescription>
            {artifactLabel(artifact.artifact_type)}を相手に渡すためのURLです。
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="rounded-lg border bg-muted/30 p-4">
            <div className="text-lg font-semibold">{copy.title}</div>
            <p className="mt-2 text-sm leading-6 text-muted-foreground">{copy.body}</p>
          </div>

          <div className="rounded-lg border p-4">
            <div className="mb-2 flex items-center gap-2 text-sm font-medium">
              <ExternalLink className="h-4 w-4" /> 納品URL
            </div>
            <div className="break-all rounded-md bg-muted px-3 py-2 font-mono text-xs">
              {publicUrl}
            </div>
            <Button
              variant="secondary"
              size="sm"
              className="mt-3"
              onClick={() => copyText(publicUrl).then(() => toast.success('URLをコピーしました'))}
            >
              <Copy className="mr-1 h-3.5 w-3.5" /> URLをコピー
            </Button>
          </div>

          <div className="space-y-2 rounded-lg border p-4">
            <div className="flex items-center gap-2 text-sm">
              <CheckCircle2 className="h-4 w-4 text-emerald-500" />
              このURLを渡せば、相手は成果物を確認できます。
            </div>
            <div className="flex items-center gap-2 text-sm">
              <CheckCircle2 className="h-4 w-4 text-emerald-500" />
              本格運用する時は、あとで専用URLやログイン付きにできます。
            </div>
          </div>

          <Textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="必要ならメモを書いてください。例: 先方の担当者、確認期限、注意点など"
          />
        </div>

        <DialogFooter>
          <Button variant="secondary" onClick={() => onOpenChange(false)}>
            閉じる
          </Button>
          <Button onClick={save} disabled={saving}>
            {saving ? '準備中...' : '納品URLをコピーして完了'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
