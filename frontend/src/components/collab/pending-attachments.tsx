'use client';

import { useEffect, useMemo } from 'react';
import { X, FileText, Play } from 'lucide-react';

/**
 * 送信前の添付一覧（入力欄の上）。添付しただけでは送らず、送信ボタンで本文と一緒に1メッセージになる。
 * 画像・動画はサムネ、その他はファイル名チップ。×で外せる。
 */
export function PendingAttachments({ files, onRemove }: { files: File[]; onRemove: (index: number) => void }) {
  const previews = useMemo(
    () => files.map((f) => ({ file: f, url: (f.type.startsWith('image/') || f.type.startsWith('video/')) ? URL.createObjectURL(f) : null })),
    [files],
  );
  useEffect(() => () => { previews.forEach((p) => { if (p.url) URL.revokeObjectURL(p.url); }); }, [previews]);
  if (files.length === 0) return null;
  return (
    <div className="flex gap-2 overflow-x-auto px-1 pb-2">
      {previews.map((p, i) => (
        <div key={`${p.file.name}-${i}`} className="relative shrink-0 animate-in fade-in zoom-in-95 duration-200">
          {p.url && p.file.type.startsWith('image/') ? (
            <img src={p.url} alt={p.file.name} className="h-16 w-16 rounded-lg object-cover border border-border" />
          ) : p.url ? (
            <div className="relative h-16 w-16 rounded-lg overflow-hidden border border-border bg-black">
              <video src={p.url} muted playsInline className="h-full w-full object-cover" />
              <span className="absolute inset-0 flex items-center justify-center"><Play className="h-5 w-5 text-white fill-white" /></span>
            </div>
          ) : (
            <div className="flex h-16 max-w-[160px] items-center gap-1.5 rounded-lg border border-border bg-muted/60 px-2 text-xs">
              <FileText className="h-4 w-4 shrink-0 text-primary" />
              <span className="truncate">{p.file.name}</span>
            </div>
          )}
          <button
            type="button"
            onClick={() => onRemove(i)}
            className="absolute -top-1.5 -right-1.5 rounded-full bg-foreground text-background p-0.5 shadow"
            aria-label="添付を外す"
          >
            <X className="h-3 w-3" />
          </button>
        </div>
      ))}
    </div>
  );
}

export type UploadedFile = { id: string; name: string; url: string; type: string; size: number };

/** コラボルームへ順にアップロードして files[] を返す（オーナー=Bearer、ゲスト=X-Guest-Token） */
export async function uploadCollabFiles(
  roomId: string,
  files: File[],
  auth: { token?: string | null; guestToken?: string | null },
): Promise<UploadedFile[]> {
  const out: UploadedFile[] = [];
  for (const file of files) {
    const formData = new FormData();
    formData.append('file', file);
    const headers: Record<string, string> = {};
    if (auth.guestToken) headers['X-Guest-Token'] = auth.guestToken;
    else if (auth.token) headers.Authorization = `Bearer ${auth.token}`;
    const res = await fetch(`/api/v1/collab/rooms/${roomId}/files`, { method: 'POST', headers, body: formData });
    if (!res.ok) {
      const bodyText = await res.text().catch(() => '');
      throw new Error(`HTTP ${res.status}${bodyText ? ' | ' + bodyText.slice(0, 200) : ''} (${file.name})`);
    }
    const d = await res.json();
    out.push({ id: d.id, name: d.file_name, url: d.file_path, type: d.file_type || file.type, size: d.file_size });
  }
  return out;
}
