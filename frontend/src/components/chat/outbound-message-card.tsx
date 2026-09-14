'use client';

/**
 * 送信案カード — ダンが compose_message で用意した外部宛メッセージ（メール/DM等）。
 *
 * チャット履歴の `[送信案: <proposal_id>]` メッセージがこのカードとして描画される。
 * - 本文/件名/宛先はその場で編集でき、オートセーブで DB に保存される（DB が唯一の正）。
 *   だから「編集だけしてダンに送らせる」場合も、ダンが送るのは編集後の版になる。
 * - 送信ボタンはサーバーがそのまま送る（ダンは起動しない）。結果は部屋の履歴に
 *   「📤 送信済み」として残り、次のターンでダンの記憶に合流する。
 * - 送らずに放置・破棄・コピーして別で送る、全部OK。
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Check, Copy, Loader2, Mail, MessageCircle, Send, Trash2, RefreshCw, FileText } from 'lucide-react';
import { toast } from 'sonner';
import { api, type ProposalResponse } from '@/lib/api-client';
import { MediaGrid, collabMediaItems } from '@/components/chat/media-grid';

const CHANNEL_LABEL: Record<string, string> = {
  email: 'メール',
  instagram_dm: 'Instagram DM',
  line: 'LINE',
  sms: 'SMS',
  web_form: 'Webフォーム',
  chatwork: 'Chatwork',
  slack: 'Slack',
  x_dm: 'X DM',
  collab: 'コラボチャット',
  other: 'メッセージ',
};
const channelLabel = (c: string) => CHANNEL_LABEL[c] || c;

// サーバーから直接送れるチャネル。それ以外はダンが browser で送る（カードは承認用）。
const SERVER_SENDABLE = new Set(['email', 'instagram_dm', 'instagram_comment', 'collab']);

type ActionData = {
  channel?: string;
  to?: string;
  to_name?: string | null;
  subject?: string | null;
  intent?: string | null;
  from_name?: string | null;
  original_body?: string;
  reply_to?: { message_id?: string; subject?: string; thread_id?: string; post_url?: string; comment_id?: string; account?: string } | null;
  from_account?: string | null;
  target?: { url?: string; note?: string } | null;
  user_edited?: boolean;
  sent_by?: 'user' | 'dan' | null;
  sent_at?: string | null;
  sent_manually?: boolean;
  discarded_by?: string;
  // collab: 添付（propose 時点で窓口の保存先に写してある）／名義／版
  attachments?: { name: string; url: string; type?: string; size?: number }[] | null;
  sender?: 'dan' | 'owner' | null;
  revision?: number;
  dan_updated_at?: string | null;
  // ユーザー編集中にダンが用意した新版（採用するまで本文は据え置き）
  pending_update?: { body: string; intent?: string | null; at: string } | null;
};

function fmtTime(iso?: string | null): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

export function OutboundMessageCard({ proposalId, foldCollab = false }: { proposalId: string; foldCollab?: boolean }) {
  const queryClient = useQueryClient();
  const queryKey = ['outbound-proposal', proposalId];
  const { data: proposal, isLoading, isError } = useQuery({
    queryKey,
    queryFn: () => api.proposals.get(proposalId),
    staleTime: 15_000,
  });

  const ad = (proposal?.action_data || {}) as ActionData;
  const channel = ad.channel || 'other';
  const pending = proposal?.status === 'pending';
  const sendable = SERVER_SENDABLE.has(channel);
  const isReply = !!(ad.reply_to && Object.values(ad.reply_to).some(Boolean));
  // 件名欄はメールの新規送信だけ。返信は Re: 自動、DM/フォームは件名そのものが無い。
  const showSubject = channel === 'email' && !isReply;

  // ローカル編集状態（サーバー値と同期）
  const [body, setBody] = useState('');
  const [subject, setSubject] = useState('');
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState<number | null>(null);
  // collab カードを本体チャット側では薄い1行に折り畳む（対応の主戦場はコラボ窓口画面）
  const [expanded, setExpanded] = useState(false);
  // 送信/破棄の退場アニメーション（ボタン→送信→カード消滅の繋がり感）
  const [exiting, setExiting] = useState(false);
  const [gone, setGone] = useState(false);
  const [updateDismissed, setUpdateDismissed] = useState<string | null>(null);
  // カード上でダンに直接聞く／指示する（相手には見えない）。返事は窓口の非公開バブル、
  // 直した結果は同じカードに反映される（1窓口=1下書き）
  const [askText, setAskText] = useState('');
  const askMutation = useMutation({
    mutationFn: async () => {
      const roomId = (ad.reply_to as { collab_room_id?: string } | null)?.collab_room_id;
      if (!roomId) throw new Error('窓口が特定できません');
      const text = askText.trim();
      if (!text) return null;
      return api.collab.sendMessage(roomId, text, undefined, { visibility: 'owner_only', about_proposal: proposalId });
    },
    onSuccess: () => {
      setAskText('');
      toast.success('ダンに送りました。返事は窓口の非公開バブルに出ます');
      queryClient.invalidateQueries({ queryKey: ['collab-messages'] });
    },
    onError: (e: Error) => toast.error(`送れませんでした: ${e.message}`),
  });
  const lastServer = useRef<{ body: string; subject: string } | null>(null);

  // 名義の切替（collab のみ）。押した瞬間に保存する
  const senderMutation = useMutation({
    mutationFn: (sender: 'dan' | 'owner') => api.proposals.updateDraft(proposalId, { sender }),
    onSuccess: (updated: ProposalResponse) => queryClient.setQueryData(queryKey, updated),
    onError: (e: Error) => toast.error(`名義の変更に失敗: ${e.message}`),
  });
  // ダンの新版を採用（ユーザー編集を置き換える）
  const applyUpdateMutation = useMutation({
    mutationFn: () => api.proposals.updateDraft(proposalId, { apply_update: true }),
    onSuccess: (updated: ProposalResponse) => {
      queryClient.setQueryData(queryKey, updated);
      lastServer.current = null;   // 次の同期で本文をサーバー値に置き換える
      setDirty(false);
      toast.success('ダンの新しい版を反映しました');
    },
    onError: (e: Error) => toast.error(`反映に失敗: ${e.message}`),
  });

  useEffect(() => {
    if (!proposal) return;
    const sv = { body: proposal.content || '', subject: ad.subject || '' };
    const prev = lastServer.current;
    // サーバー側が変わった時だけ（初回 or 他所で更新）ローカルを上書き。編集中は守る。
    if (!prev || (!dirty && (prev.body !== sv.body || prev.subject !== sv.subject))) {
      setBody(sv.body);
      setSubject(sv.subject);
    }
    lastServer.current = sv;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [proposal?.content, ad.subject, proposal?.status]);

  // オートセーブ（入力停止 700ms 後）
  useEffect(() => {
    if (!dirty || !pending) return;
    const t = setTimeout(async () => {
      try {
        setSaving(true);
        const updated = await api.proposals.updateDraft(proposalId, {
          body,
          ...(showSubject ? { subject } : {}),
        });
        queryClient.setQueryData(queryKey, updated);
        lastServer.current = { body, subject };
        setDirty(false);
        setSavedAt(Date.now());
      } catch (e) {
        toast.error(`保存に失敗: ${e instanceof Error ? e.message : String(e)}`);
      } finally {
        setSaving(false);
      }
    }, 700);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [body, subject, dirty, pending]);

  const flush = useCallback(async () => {
    if (!dirty) return;
    const updated = await api.proposals.updateDraft(proposalId, {
      body,
      ...(showSubject ? { subject } : {}),
    });
    queryClient.setQueryData(queryKey, updated);
    lastServer.current = { body, subject };
    setDirty(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dirty, body, subject, proposalId, showSubject]);

  const sendMutation = useMutation({
    mutationFn: async () => {
      await flush();
      return api.proposals.sendDraft(proposalId);
    },
    onSuccess: (updated: ProposalResponse) => {
      queryClient.setQueryData(queryKey, updated);
      toast.success('送信しました');
      // 退場アニメーション → 消えたタイミングで一覧を更新（ラグの正体だった10秒待ちを排除）
      setExiting(true);
      setTimeout(() => {
        setGone(true);
        queryClient.invalidateQueries({ queryKey: ['collab-outbound'] });
      }, 380);
    },
    onError: (e: Error) => toast.error(`送信に失敗: ${e.message}`),
  });

  const discardMutation = useMutation({
    mutationFn: () => api.proposals.discardDraft(proposalId),
    onSuccess: (updated: ProposalResponse) => {
      queryClient.setQueryData(queryKey, updated);
      setExiting(true);
      setTimeout(() => {
        setGone(true);
        queryClient.invalidateQueries({ queryKey: ['collab-outbound'] });
      }, 380);
    },
    onError: (e: Error) => toast.error(`破棄に失敗: ${e.message}`),
  });

  const copyBody = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(body);
      toast.success('本文をコピーしました');
    } catch {
      toast.error('コピーできませんでした');
    }
  }, [body]);

  if (isLoading) {
    return (
      <div className="my-1 flex items-center gap-2 rounded-xl border border-border bg-card px-3 py-2 text-xs text-muted-foreground">
        <Loader2 className="h-3 w-3 animate-spin" /> 送信案を読み込み中…
      </div>
    );
  }
  if (isError || !proposal) {
    return (
      <div className="my-1 rounded-xl border border-border bg-card px-3 py-2 text-xs text-muted-foreground">
        送信案が見つかりません（{proposalId.slice(0, 8)}）
      </div>
    );
  }

  if (foldCollab && channel === 'collab' && !expanded) {
    const statusLabel =
      proposal?.status === 'pending' ? '未送信・コミュニケーションタブで確認できます'
      : proposal?.status === 'sent' ? '送信済み'
      : proposal?.status === 'sending' ? '送信中'
      : proposal?.status === 'rejected' ? '破棄'
      : '';
    return (
      <div className="my-1 max-w-[640px] rounded-lg border border-dashed border-border bg-muted/30 px-3 py-1.5 text-xs text-muted-foreground">
        <button type="button" className="text-left w-full" onClick={() => setExpanded(true)}>
          📨 窓口への返信案{statusLabel ? `（${statusLabel}）` : ''}: {ad.to_name || ad.to || ''}
          {ad.intent ? ` — ${ad.intent}` : ''}
          <span className="ml-1 opacity-70">▼ 開く</span>
        </button>
      </div>
    );
  }

  const Icon = channel === 'email' ? Mail : MessageCircle;
  const label = channelLabel(channel);
  const senderOwner = ad.sender === 'owner';
  const { media: attMedia, others: attOthers } = collabMediaItems({ files: ad.attachments || [] });
  const pendingUpdate = ad.pending_update && ad.pending_update.at !== updateDismissed ? ad.pending_update : null;
  const status = proposal.status as string;
  const sent = status === 'sent';
  const sending = status === 'sending'; // ダンが手動送信のためロック中（編集・送信不可）
  const discarded = status === 'rejected';
  const busy = sendMutation.isPending || discardMutation.isPending;

  if (gone) return null;

  return (
    <div
      className={`my-1 w-full max-w-[640px] overflow-hidden rounded-xl border bg-card shadow-sm transition-all duration-300 ease-out motion-reduce:transition-none ${
        exiting
          ? 'opacity-0 scale-95 -translate-y-2'
          : sendMutation.isPending
            ? 'border-primary ring-2 ring-primary/40'
            : ''
      } ${
        sent ? 'border-emerald-500/40' : sending ? 'border-amber-500/40' : discarded ? 'border-border opacity-60' : 'border-primary/40'
      }`}
    >
      {/* ヘッダ */}
      <div className="flex items-center gap-2 border-b border-border bg-muted/40 px-3 py-2">
        <Icon className="h-4 w-4 shrink-0 text-primary" />
        <div className="min-w-0 flex-1">
          <div className="truncate text-xs font-medium text-foreground">
            {channelLabel(channel)}
            {isReply ? '（返信）' : ''}
            {ad.intent ? <span className="text-muted-foreground"> — {ad.intent}</span> : null}
          </div>
          <div className="truncate text-[11px] text-muted-foreground">
            宛先: {ad.to_name ? `${ad.to_name} ` : ''}
            <span className="font-mono">{ad.to}</span>
            {ad.from_name ? ` ／ 差出人: ${ad.from_name}` : ''}
            {ad.from_account ? ` ／ 送信元: @${ad.from_account}` : ''}
          </div>
          {isReply && (ad.reply_to?.subject || ad.reply_to?.thread_id || ad.reply_to?.post_url) && (
            <div className="truncate text-[11px] text-muted-foreground">
              返信先:{' '}
              {ad.reply_to?.subject
                || (ad.reply_to?.post_url
                  ? <a href={ad.reply_to.post_url} target="_blank" rel="noopener noreferrer" className="underline">投稿{ad.reply_to.comment_id ? 'のコメント' : ''}</a>
                  : `DMスレッド ${ad.reply_to?.thread_id}`)}
            </div>
          )}
          {ad.target?.url && (
            <div className="truncate text-[11px] text-muted-foreground">
              送信先:{' '}
              <a href={ad.target.url} target="_blank" rel="noopener noreferrer" className="underline">
                {ad.target.url}
              </a>
              {ad.target.note ? ` — ${ad.target.note}` : ''}
            </div>
          )}
        </div>
        <div className="shrink-0 text-[11px]">
          {sent && (
            <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/15 px-2 py-0.5 text-emerald-600 dark:text-emerald-400">
              <Check className="h-3 w-3" />
              送信済み {fmtTime(ad.sent_at)}
              {ad.sent_by === 'user' ? '（あなたが送信）' : '（ダンが送信）'}
              {channel === 'collab' ? `・名義: ${senderOwner ? 'あなた' : 'ダン'}` : ''}
              {ad.user_edited ? '・修正あり' : ''}
            </span>
          )}
          {sending && (
            <span className="inline-flex items-center gap-1 rounded-full bg-amber-500/15 px-2 py-0.5 text-amber-600 dark:text-amber-400">
              <Loader2 className="h-3 w-3 animate-spin" />
              送信中（ダンが送信しています）
            </span>
          )}
          {discarded && <span className="rounded-full bg-muted px-2 py-0.5 text-muted-foreground">破棄</span>}
          {pending && (
            <span className="text-muted-foreground">
              {(ad.revision || 1) > 1 && ad.dan_updated_at ? `更新 ${fmtTime(ad.dan_updated_at)}・` : ''}
              {saving ? '保存中…' : dirty ? '未保存' : savedAt ? '保存済み' : ad.user_edited ? '編集済み' : '下書き'}
            </span>
          )}
          {foldCollab && channel === 'collab' && (
            <button
              type="button"
              onClick={() => setExpanded(false)}
              className="ml-2 text-muted-foreground hover:text-foreground"
              title="1行表示に戻す"
            >
              ▲ たたむ
            </button>
          )}
        </div>
      </div>

      {/* 本文 */}
      <div className="flex flex-col gap-2 px-3 py-2">
        {pending && pendingUpdate && (
          <div className="flex flex-wrap items-center gap-2 rounded-md border border-primary/40 bg-primary/5 px-2.5 py-1.5 text-xs">
            <RefreshCw className="h-3.5 w-3.5 shrink-0 text-primary" />
            <span className="min-w-0 flex-1">
              ダンが新しい版を用意しました（{fmtTime(pendingUpdate.at)}）。あなたが直している本文はそのままです。
            </span>
            <button
              type="button"
              disabled={applyUpdateMutation.isPending}
              onClick={() => applyUpdateMutation.mutate()}
              className="rounded-md bg-primary px-2 py-1 text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
            >
              新しい版にする
            </button>
            <button
              type="button"
              onClick={() => setUpdateDismissed(pendingUpdate.at)}
              className="rounded-md border border-border px-2 py-1 hover:bg-muted"
            >
              このまま
            </button>
          </div>
        )}
        {channel === 'collab' && pending && (
          <div className="flex items-center gap-2 text-xs">
            <span className="text-muted-foreground">名義:</span>
            <div className="inline-flex overflow-hidden rounded-md border border-border">
              {(['dan', 'owner'] as const).map((s) => (
                <button
                  key={s}
                  type="button"
                  disabled={senderMutation.isPending}
                  onClick={() => { if ((ad.sender || 'dan') !== s) senderMutation.mutate(s); }}
                  className={`px-2.5 py-1 transition-colors ${
                    (ad.sender || 'dan') === s ? 'bg-primary text-primary-foreground' : 'bg-background hover:bg-muted'
                  }`}
                >
                  {s === 'dan' ? 'ダン' : 'あなた'}
                </button>
              ))}
            </div>
            <span className="text-muted-foreground">
              {senderOwner ? '相手にはあなた本人の発言として届きます' : '相手にはダンの発言として届きます'}
            </span>
          </div>
        )}
        {(attMedia.length > 0 || attOthers.length > 0) && (
          <div className="flex flex-col gap-1">
            <span className="text-[11px] text-muted-foreground">添付（一緒に届きます）</span>
            {attMedia.length > 0 && <MediaGrid items={attMedia} />}
            {attOthers.map((f) => (
              <a key={f.url} href={f.url} target="_blank" rel="noopener noreferrer"
                 className="inline-flex w-fit items-center gap-1.5 rounded-md border border-border bg-muted/40 px-2 py-1 text-xs hover:bg-muted">
                <FileText className="h-3.5 w-3.5 text-primary" /> {f.name}
              </a>
            ))}
          </div>
        )}
        {showSubject && (
          pending ? (
            <input
              value={subject}
              onChange={(e) => { setSubject(e.target.value); setDirty(true); }}
              className="w-full rounded-md border border-border bg-input px-2 py-1 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
              placeholder="件名"
            />
          ) : (
            <div className="text-sm font-medium">{ad.subject}</div>
          )
        )}
        {pending ? (
          <textarea
            value={body}
            onChange={(e) => { setBody(e.target.value); setDirty(true); }}
            rows={Math.min(18, Math.max(5, body.split('\n').length + 1))}
            className="w-full resize-y rounded-md border border-border bg-input px-2 py-1.5 text-sm leading-relaxed focus:outline-none focus:ring-1 focus:ring-ring"
          />
        ) : (
          <pre className="whitespace-pre-wrap break-words font-sans text-sm leading-relaxed text-foreground">{proposal.content}</pre>
        )}
      </div>

      {/* 操作 */}
      {pending && (
        <div className="flex flex-wrap items-center gap-2 border-t border-border px-3 py-2">
          {sendable ? (
            <button
              type="button"
              disabled={busy}
              onClick={() => sendMutation.mutate()}
              className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
            >
              {sendMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
              送信
            </button>
          ) : (
            <span className="text-xs text-muted-foreground">
              {label} はここから直接送れません。チャットで「送って」と言えばダンが送ります。
            </span>
          )}
          <button
            type="button"
            onClick={copyBody}
            className="inline-flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-sm hover:bg-muted"
          >
            <Copy className="h-4 w-4" /> コピー
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => discardMutation.mutate()}
            className="ml-auto inline-flex items-center gap-1.5 rounded-md px-2 py-1.5 text-sm text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-50"
            title="この送信案を破棄"
          >
            <Trash2 className="h-4 w-4" /> 破棄
          </button>
        </div>
      )}
      {pending && channel === 'collab' && (
        <div className="flex items-center gap-2 border-t border-border bg-violet-500/5 px-3 py-2">
          <input
            value={askText}
            onChange={(e) => setAskText(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.nativeEvent.isComposing && askText.trim()) askMutation.mutate(); }}
            placeholder="ダンへ（相手には見えません）: 例「これ何？今やって」"
            className="flex-1 rounded-md border border-violet-500/30 bg-background px-2 py-1 text-sm focus:outline-none focus:ring-1 focus:ring-violet-500/50"
          />
          <button
            type="button"
            disabled={!askText.trim() || askMutation.isPending}
            onClick={() => askMutation.mutate()}
            className="inline-flex items-center gap-1 rounded-md bg-violet-600 px-2.5 py-1 text-sm text-white hover:bg-violet-700 disabled:opacity-50"
          >
            {askMutation.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Send className="h-3.5 w-3.5" />}
          </button>
        </div>
      )}
    </div>
  );
}

const CARD_RE = /^\s*\[送信案: ([0-9a-fA-F-]{36})\]\s*$/;

/** チャット履歴のメッセージが送信案カードなら proposal_id を返す。 */
export function parseOutboundCardMarker(content: string | null | undefined): string | null {
  if (!content) return null;
  const m = content.match(CARD_RE);
  return m ? m[1] : null;
}

/** 送信済み/破棄のイベント行（📤 / 🗑）。折り畳み表示にする。 */
export function OutboundEventLine({ content }: { content: string }) {
  const [open, setOpen] = useState(false);
  const [head, ...rest] = content.split('\n');
  const detail = rest.join('\n').trim();
  return (
    <div className="my-1 max-w-[640px] rounded-lg border border-dashed border-border bg-muted/30 px-3 py-1.5 text-xs text-muted-foreground">
      <button type="button" className="text-left" onClick={() => setOpen((v) => !v)}>
        {head}
        {detail ? <span className="ml-1 opacity-70">{open ? '▲' : '▼ 内容'}</span> : null}
      </button>
      {open && detail && (
        <pre className="mt-1 whitespace-pre-wrap break-words font-sans text-foreground/80">{detail}</pre>
      )}
    </div>
  );
}

export function isOutboundEventContent(content: string | null | undefined): boolean {
  return !!content && (content.startsWith('📤 ') || content.startsWith('🗑 '));
}

/** 外部窓口（collab）対応の作業ログ行。「窓口ログ:」（旧「窓口:」）で始まるai発言を折り畳み表示にする。 */
export function isCollabLogContent(content: string | null | undefined): boolean {
  if (!content) return false;
  const head = content.trimStart();
  return head.startsWith('窓口ログ:') || head.startsWith('窓口:');
}
