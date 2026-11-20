'use client';

// 上の段の「共有」: 相手に送るリンクをコピーする（11/20 本人「URL共有できるコピーボタン」「これまで通り相手が編集したり
// コメントしたりできるドキュメントで」）。リンクはお客さん用の写し（リンクを知る人は誰でも編集・コメントできる）で、
// 作業用の台本（本人のコメントと提案が入っている）は渡さない。初めて押した時に写しができる（app/services/script_share.py）。

import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Check, Copy, Link2, Loader2 } from 'lucide-react';

import { errorText, listenApi, type ShareState } from '@/lib/script-listen-api';

function when(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  return `${d.getMonth() + 1}/${d.getDate()} ${d.getHours()}:${String(d.getMinutes()).padStart(2, '0')}`;
}

async function copyText(text: string): Promise<boolean> {
  try { await navigator.clipboard.writeText(text); return true; } catch { /* 下の方法へ */ }
  try {
    const area = document.createElement('textarea');
    area.value = text; area.setAttribute('readonly', ''); area.style.position = 'fixed'; area.style.opacity = '0';
    document.body.appendChild(area); area.select();
    const ok = document.execCommand('copy');
    area.remove();
    return ok;
  } catch { return false; }
}

export function ListenShare({ docId }: { docId: string }) {
  const [info, setInfo] = useState<ShareState | null>(null);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState<'' | 'make'>('');
  const [copied, setCopied] = useState(false);
  const [failed, setFailed] = useState('');
  const box = useRef<HTMLDivElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  // 上の段は横に流れて切れるので、欄は画面の上に重ねて出す（ボタンの真下、画面の端からはみ出さない所）
  const [place, setPlace] = useState<{ top: number; right: number } | null>(null);

  useEffect(() => {
    let live = true;
    listenApi.shareState(docId).then(s => { if (live) setInfo(s); }).catch(() => { /* 押した時に作る */ });
    return () => { live = false; };
  }, [docId]);

  useEffect(() => {
    if (!open) return;
    const away = (e: PointerEvent) => {
      const t = e.target as Node;
      if (box.current?.contains(t) || panel.current?.contains(t)) return;
      setOpen(false);
    };
    document.addEventListener('pointerdown', away);
    return () => document.removeEventListener('pointerdown', away);
  }, [open]);

  const copy = async (url: string) => { const ok = await copyText(url); setCopied(ok); return ok; };

  const press = async () => {
    if (open) { setOpen(false); return; }
    const r = box.current?.getBoundingClientRect();
    if (r) setPlace({ top: r.bottom + 4, right: Math.max(8, window.innerWidth - r.right) });
    setOpen(true); setFailed(''); setCopied(false);
    if (info?.url) {
      await copy(info.url);
      listenApi.shareState(docId).then(setInfo).catch(() => { /* 前の状態のまま */ });   // 開いている間に台本が進んだか
      return;
    }
    setBusy('make');
    try {
      const s = await listenApi.share(docId);
      setInfo(s);
      if (s.url) await copy(s.url);
    } catch (e) { setFailed(errorText(e)); }
    finally { setBusy(''); }
  };


  return (
    <div ref={box} className="relative shrink-0">
      <button
        type="button"
        data-testid="share-copy"
        title="相手に送るリンクをコピーします（相手が編集・コメントできるドキュメント）"
        onMouseDown={e => e.preventDefault()}
        onClick={() => void press()}
        className="flex items-center gap-1 rounded-md border border-stone-300 bg-white px-2 py-1 text-[12px] text-stone-700"
      >
        <Link2 className="h-3.5 w-3.5" /><span className="hidden sm:inline">共有</span>
      </button>
      {open && place && createPortal(
        <div data-testid="share-panel" ref={panel} style={{ top: place.top, right: place.right }}
          className="fixed z-[200] w-[19rem] max-w-[calc(100vw-1rem)] rounded-lg border border-stone-200 bg-white p-3 text-[13px] text-stone-800 shadow-lg">
          {busy === 'make' ? (
            <div className="flex items-center gap-2 text-stone-600"><Loader2 className="h-4 w-4 animate-spin" />相手に送るドキュメントを作っています…</div>
          ) : info?.url ? (
            <div className="space-y-2">
              <div className="flex items-center gap-1.5 font-medium">
                {copied ? <><Check className="h-4 w-4 text-emerald-600" />リンクをコピーしました</> : 'リンク'}
              </div>
              <div className="flex items-center gap-1">
                <input readOnly value={info.url} onFocus={e => e.currentTarget.select()}
                  className="min-w-0 flex-1 rounded border border-stone-300 bg-stone-50 px-1.5 py-1 text-[12px] text-stone-600" />
                <button type="button" onClick={() => void copy(info.url!)}
                  className="flex shrink-0 items-center gap-1 rounded border border-stone-300 px-2 py-1 text-[12px]">
                  <Copy className="h-3.5 w-3.5" />コピー
                </button>
              </div>
              <div className="text-[12px] text-stone-500">リンクを知っている人は、誰でも編集・コメントできます。ダンのコメントと提案は入っていません。</div>
              <div data-testid="share-follow" className="rounded-md bg-stone-50 p-2 text-[12px] text-stone-600">
                {info.error ? (
                  <span className="text-red-700">相手のドキュメントに写せませんでした。少ししてからもう一度写します。</span>
                ) : (
                  <>台本を直すと、数秒で相手のドキュメントも同じに書き換わります。承認していない提案は写りません。
                    {info.synced_at && <span className="text-stone-400">（最後に写した時刻 {when(info.synced_at)}）</span>}</>
                )}
                {!!info.from_client && (
                  <div className="mt-1 text-amber-800">相手が直した所が{info.from_client}か所あります。台本に「相手の直し」の提案として入っています。決めるまで、そこは相手の文のままにしています。</div>
                )}
              </div>
            </div>
          ) : null}
          {failed && <div className="mt-2 text-[12px] text-red-600">{failed}</div>}
        </div>,
        document.body,
      )}
    </div>
  );
}
