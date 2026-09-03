'use client';

/**
 * ポルノブロッカー — 端末の見張り台
 *
 * 【この画面が要る理由】
 * 遮断の精度をいくら上げても、遮断そのものが止まっていれば意味が無い。
 * そして守りを外した本人は、外れたことを運営に言わない。
 *
 * Android の作り上「絶対に破れない」は作れないので、
 * 「破ったら必ず分かる」でふさぐ。ここはそれを見る場所。
 *
 * 【並べ方】
 * 名前順でも時刻順でもなく、**手を打つべきものを先頭**に出す。
 * 運営が見たいのは「今どれが危ないか」だけなので、並べ替えは持たせない。
 */
import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Loader2,
  Pencil,
  ShieldOff,
  WifiOff,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useAuthStore } from '@/stores/auth-store';

const API_BASE = '/api/v1/pornblocker';

type Device = {
  device_id: string;
  label: string | null;
  contact: string | null;
  first_seen_at: string | null;
  last_seen_at: string | null;
  protected: boolean;
  guard: boolean;
  overlay: boolean;
  vpn: boolean;
  admin: boolean;
  notifications: boolean;
  locked: boolean;
  safe_mode: boolean;
  app_version: string | null;
  model: string | null;
  android: string | null;
  silent: boolean;
  minutes_since_seen: number | null;
  needs_attention: boolean;
};

type DeviceEvent = {
  id: number;
  device_id: string;
  received_at: string | null;
  protected: boolean;
  guard: boolean;
  overlay: boolean;
  vpn: boolean;
  admin: boolean;
  locked: boolean;
  safe_mode: boolean;
};

function authHeaders(): Record<string, string> {
  const token = useAuthStore.getState().token;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { headers: authHeaders() });
  if (!res.ok) throw new Error(`取得に失敗しました (${res.status})`);
  return res.json();
}

/** 「12分前」「3日前」。秒まで出しても運営の判断は変わらないので丸める。 */
function sinceLabel(minutes: number | null): string {
  if (minutes === null) return '一度も連絡なし';
  if (minutes < 1) return 'たった今';
  if (minutes < 60) return `${minutes}分前`;
  const h = Math.floor(minutes / 60);
  if (h < 24) return `${h}時間前`;
  return `${Math.floor(h / 24)}日前`;
}

/** 欠けているものだけを日本語で並べる。専門用語は出さない。 */
function problems(d: Device): string[] {
  const out: string[] = [];
  if (d.silent) out.push('連絡が途絶えています');
  if (d.safe_mode) out.push('セーフモードで起動しています');
  if (!d.guard) out.push('画面の見張りが止まっています');
  if (!d.overlay) out.push('画面に重ねる許可がありません');
  if (!d.vpn) out.push('サイトの遮断が止まっています');
  if (d.locked && !d.admin) out.push('アプリを消せる状態です');
  if (!d.notifications) out.push('通知が切られています');
  return out;
}

export default function PornblockerGuardBeaconPage() {
  const queryClient = useQueryClient();
  const [openId, setOpenId] = useState<string | null>(null);
  const [editId, setEditId] = useState<string | null>(null);
  const [labelDraft, setLabelDraft] = useState('');
  const [contactDraft, setContactDraft] = useState('');

  const { data: devices, isLoading, error } = useQuery({
    queryKey: ['pornblocker-devices'],
    queryFn: () => getJson<Device[]>('/devices'),
    // 守りが外れたことを、画面を開いたまま気付けるようにする。
    refetchInterval: 60_000,
  });

  const { data: events } = useQuery({
    queryKey: ['pornblocker-events', openId],
    queryFn: () => getJson<DeviceEvent[]>(`/devices/${openId}/events?limit=50`),
    enabled: !!openId,
  });

  const saveLabel = useMutation({
    mutationFn: async (vars: { id: string; label: string; contact: string }) => {
      const res = await fetch(`${API_BASE}/devices/${vars.id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', ...authHeaders() },
        body: JSON.stringify({ label: vars.label, contact: vars.contact }),
      });
      if (!res.ok) throw new Error('保存に失敗しました');
      return res.json();
    },
    onSuccess: () => {
      setEditId(null);
      queryClient.invalidateQueries({ queryKey: ['pornblocker-devices'] });
    },
  });

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-6 text-destructive">
        端末の一覧を取れませんでした。ログインし直してください。
      </div>
    );
  }

  const list = devices ?? [];
  const attention = list.filter((d) => d.needs_attention);

  return (
    <div className="space-y-6 p-6">
      <div>
        <h1 className="text-2xl font-bold text-foreground">端末の見張り台</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          守りが止まった端末を見つける場所です。1分ごとに自動で読み直します。
        </p>
      </div>

      {/* 一番上に、手を打つべき台数だけを出す。詳細は下で見ればいい。 */}
      <div
        className={`rounded-lg border p-4 ${
          attention.length > 0
            ? 'border-destructive/40 bg-destructive/10'
            : 'border-emerald-500/30 bg-emerald-500/10'
        }`}
      >
        {attention.length > 0 ? (
          <div className="flex items-start gap-3">
            <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-destructive" />
            <div>
              <p className="font-semibold text-foreground">
                {attention.length}台で守りが止まっています
              </p>
              <p className="mt-1 text-sm text-muted-foreground">
                この間、その端末ではポルノが素通りしている可能性があります。
              </p>
            </div>
          </div>
        ) : (
          <div className="flex items-center gap-3">
            <CheckCircle2 className="h-5 w-5 text-emerald-600" />
            <p className="font-semibold text-foreground">
              {list.length}台すべて守られています
            </p>
          </div>
        )}
      </div>

      {list.length === 0 && (
        <p className="text-muted-foreground">
          まだ1台も連絡してきていません。端末に送り先を設定すると、ここに並びます。
        </p>
      )}

      <div className="space-y-3">
        {list.map((d) => {
          const issues = problems(d);
          const isOpen = openId === d.device_id;
          return (
            <div
              key={d.device_id}
              className={`rounded-lg border p-4 ${
                d.needs_attention
                  ? 'border-destructive/40 bg-destructive/5'
                  : 'border-border bg-card'
              }`}
            >
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    {d.needs_attention ? (
                      d.silent ? (
                        <WifiOff className="h-4 w-4 shrink-0 text-destructive" />
                      ) : (
                        <ShieldOff className="h-4 w-4 shrink-0 text-destructive" />
                      )
                    ) : (
                      <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-600" />
                    )}
                    <span className="font-semibold text-foreground">
                      {d.label || '（名前なし）'}
                    </span>
                    {d.locked && (
                      <span className="rounded bg-muted px-2 py-0.5 text-xs text-muted-foreground">
                        保護ロック中
                      </span>
                    )}
                  </div>
                  <p className="mt-1 text-xs text-muted-foreground">
                    最後の連絡 {sinceLabel(d.minutes_since_seen)}
                    {d.model ? ` ・ ${d.model}` : ''}
                    {d.android ? ` ・ Android ${d.android}` : ''}
                    {d.app_version ? ` ・ v${d.app_version}` : ''}
                  </p>
                  {d.contact && (
                    <p className="mt-0.5 text-xs text-muted-foreground">
                      連絡先 {d.contact}
                    </p>
                  )}
                </div>

                <div className="flex items-center gap-2">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => {
                      setEditId(d.device_id);
                      setLabelDraft(d.label ?? '');
                      setContactDraft(d.contact ?? '');
                    }}
                  >
                    <Pencil className="mr-1 h-3.5 w-3.5" />
                    名前
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setOpenId(isOpen ? null : d.device_id)}
                  >
                    履歴
                    {isOpen ? (
                      <ChevronUp className="ml-1 h-3.5 w-3.5" />
                    ) : (
                      <ChevronDown className="ml-1 h-3.5 w-3.5" />
                    )}
                  </Button>
                </div>
              </div>

              {issues.length > 0 && (
                <ul className="mt-3 space-y-1">
                  {issues.map((t) => (
                    <li key={t} className="text-sm text-destructive">
                      ・{t}
                    </li>
                  ))}
                </ul>
              )}

              {editId === d.device_id && (
                <div className="mt-3 flex flex-wrap items-center gap-2 rounded-md border border-border bg-background p-3">
                  <Input
                    placeholder="呼び名（契約者の名前など）"
                    value={labelDraft}
                    onChange={(e) => setLabelDraft(e.target.value)}
                    className="max-w-56"
                  />
                  <Input
                    placeholder="連絡先（メール・電話）"
                    value={contactDraft}
                    onChange={(e) => setContactDraft(e.target.value)}
                    className="max-w-64"
                  />
                  <Button
                    size="sm"
                    disabled={saveLabel.isPending}
                    onClick={() =>
                      saveLabel.mutate({
                        id: d.device_id,
                        label: labelDraft,
                        contact: contactDraft,
                      })
                    }
                  >
                    保存
                  </Button>
                  <Button variant="ghost" size="sm" onClick={() => setEditId(null)}>
                    やめる
                  </Button>
                </div>
              )}

              {isOpen && (
                <div className="mt-3 rounded-md border border-border bg-background p-3">
                  <p className="mb-2 text-xs text-muted-foreground">
                    いつ外れて、いつ戻ったか（新しい順）
                  </p>
                  {!events && (
                    <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
                  )}
                  {events?.length === 0 && (
                    <p className="text-sm text-muted-foreground">履歴がありません。</p>
                  )}
                  <ul className="space-y-1">
                    {events?.map((e) => (
                      <li key={e.id} className="flex items-center gap-2 text-sm">
                        <span className="text-muted-foreground">
                          {e.received_at
                            ? new Date(e.received_at).toLocaleString('ja-JP')
                            : '-'}
                        </span>
                        <span
                          className={
                            e.protected ? 'text-emerald-600' : 'text-destructive'
                          }
                        >
                          {e.protected ? '守られていた' : '守りが欠けていた'}
                        </span>
                        {!e.guard && (
                          <span className="text-xs text-muted-foreground">見張り停止</span>
                        )}
                        {!e.vpn && (
                          <span className="text-xs text-muted-foreground">遮断停止</span>
                        )}
                        {e.safe_mode && (
                          <span className="text-xs text-muted-foreground">
                            セーフモード
                          </span>
                        )}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
