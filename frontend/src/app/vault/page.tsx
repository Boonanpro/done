'use client';

// 保存済みパスワードを本人の画面にだけ全文で出す。
// ダン（AI）は全文を受け取らない。毎回パスキー（PC は Windows の PIN、スマホは指紋・顔認証）で本人確認する。
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Copy, Eye, KeyRound, Loader2, Plus, Search, ShieldCheck, Trash2 } from 'lucide-react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { ApiError } from '@/lib/api-client';
import { vaultApi, type VaultAssertOptions, type VaultRevealed } from '@/lib/vault-api';
import { cn } from '@/lib/utils';

const SHOW_SECONDS = 30;

function toBuf(b64u: string): ArrayBuffer {
  const b64 = b64u.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - (b64u.length % 4)) % 4);
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i += 1) out[i] = bin.charCodeAt(i);
  return out.buffer;
}

function toB64u(buf: ArrayBuffer): string {
  const bytes = new Uint8Array(buf);
  let bin = '';
  for (let i = 0; i < bytes.length; i += 1) bin += String.fromCharCode(bytes[i]);
  return btoa(bin).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function errorText(err: unknown): string {
  if (err instanceof ApiError) {
    const detail = (err.data as { detail?: unknown } | null)?.detail;
    if (typeof detail === 'string') return detail;
  }
  if (err instanceof DOMException && (err.name === 'NotAllowedError' || err.name === 'AbortError')) {
    return '本人確認を取り消しました。';
  }
  if (err instanceof DOMException && err.name === 'InvalidStateError') {
    return 'この端末はもう登録されています。';
  }
  return err instanceof Error ? err.message : '失敗しました。';
}

async function passkeyAssertion(options: VaultAssertOptions) {
  const cred = (await navigator.credentials.get({
    publicKey: {
      challenge: toBuf(options.challenge),
      rpId: options.rpId,
      allowCredentials: options.allowCredentials.map(id => ({ type: 'public-key' as const, id: toBuf(id) })),
      userVerification: 'required',
      timeout: 120000,
    },
  })) as PublicKeyCredential | null;
  if (!cred) throw new Error('本人確認ができませんでした。');
  const res = cred.response as AuthenticatorAssertionResponse;
  return {
    challenge: options.challenge,
    credential_id: toB64u(cred.rawId),
    client_data_json: toB64u(res.clientDataJSON),
    authenticator_data: toB64u(res.authenticatorData),
    signature: toB64u(res.signature),
  };
}

function guessDeviceLabel(): string {
  if (typeof navigator === 'undefined') return '';
  const ua = navigator.userAgent;
  if (/Android/i.test(ua)) return 'スマホ（Android）';
  if (/iPhone|iPad/i.test(ua)) return 'スマホ（iPhone）';
  if (/Windows/i.test(ua)) return 'PC（Windows）';
  if (/Mac/i.test(ua)) return 'Mac';
  return '';
}

function charKind(ch: string): { label: string; className: string } {
  if (/[0-9]/.test(ch)) return { label: '数字', className: 'text-sky-700 bg-sky-50 border-sky-200' };
  if (/[A-Z]/.test(ch)) return { label: '大文字', className: 'text-rose-700 bg-rose-50 border-rose-200' };
  if (/[a-z]/.test(ch)) return { label: '小文字', className: 'text-emerald-700 bg-emerald-50 border-emerald-200' };
  if (ch === ' ') return { label: '空白', className: 'text-amber-700 bg-amber-50 border-amber-200' };
  return { label: '記号', className: 'text-violet-700 bg-violet-50 border-violet-200' };
}

const EVENT_TEXT: Record<string, string> = {
  reveal: '表示',
  register: '端末を登録',
  delete: '端末を外した',
  enroll_open: '登録受付を開けた',
  reset: '端末を全部外した',
};


export default function VaultPage() {
  const queryClient = useQueryClient();
  const [query, setQuery] = useState('');
  const [focusService, setFocusService] = useState('');
  const [busy, setBusy] = useState('');
  const [revealed, setRevealed] = useState<VaultRevealed | null>(null);
  const [remaining, setRemaining] = useState(0);
  const [label, setLabel] = useState('');
  const [supported, setSupported] = useState(true);
  const [rpId, setRpId] = useState('');

  const status = useQuery({ queryKey: ['vault-status'], queryFn: vaultApi.status });

  useEffect(() => {
    const service = new URLSearchParams(window.location.search).get('service') || '';
    setFocusService(service);
    setLabel(guessDeviceLabel());
    setRpId(window.location.hostname);
    setSupported(typeof window.PublicKeyCredential !== 'undefined' && window.isSecureContext);
  }, []);

  useEffect(() => {
    if (!revealed) return undefined;
    setRemaining(SHOW_SECONDS);
    const timer = window.setInterval(() => {
      setRemaining(prev => {
        if (prev <= 1) {
          window.clearInterval(timer);
          setRevealed(null);
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
    return () => window.clearInterval(timer);
  }, [revealed]);

  const passkeys = status.data?.passkeys ?? [];
  const hereKeys = passkeys.filter(p => p.rp_id === rpId);
  const enrollOpen = Boolean(status.data?.enroll_open_until);

  const services = useMemo(() => {
    const all = status.data?.services ?? [];
    const q = query.trim().toLowerCase();
    const filtered = q ? all.filter(s => s.service.toLowerCase().includes(q)) : all;
    if (!focusService) return filtered;
    const first = filtered.filter(s => s.service === focusService);
    return [...first, ...filtered.filter(s => s.service !== focusService)];
  }, [status.data, query, focusService]);

  const refresh = useCallback(() => queryClient.invalidateQueries({ queryKey: ['vault-status'] }), [queryClient]);

  const run = useCallback(
    async (key: string, fn: () => Promise<void>) => {
      setBusy(key);
      try {
        await fn();
      } catch (err) {
        toast.error(errorText(err));
      } finally {
        setBusy('');
        refresh();
      }
    },
    [refresh]
  );

  const reveal = (service: string) =>
    run(`reveal:${service}`, async () => {
      const options = await vaultApi.assertOptions('reveal', service);
      const assertion = await passkeyAssertion(options);
      setRevealed(await vaultApi.reveal({ ...assertion, service }));
    });

  const register = () =>
    run('register', async () => {
      const options = await vaultApi.registerOptions();
      const cred = (await navigator.credentials.create({
        publicKey: {
          challenge: toBuf(options.challenge),
          rp: options.rp,
          user: { id: toBuf(options.user.id), name: options.user.name, displayName: options.user.displayName },
          pubKeyCredParams: [
            { type: 'public-key', alg: -7 },
            { type: 'public-key', alg: -257 },
            { type: 'public-key', alg: -8 },
          ],
          authenticatorSelection: { authenticatorAttachment: 'platform', userVerification: 'required', residentKey: 'preferred' },
          excludeCredentials: options.excludeCredentials.map(id => ({ type: 'public-key' as const, id: toBuf(id) })),
          attestation: 'none',
          timeout: 120000,
        },
      })) as PublicKeyCredential | null;
      if (!cred) throw new Error('登録できませんでした。');
      const res = cred.response as AuthenticatorAttestationResponse;
      const publicKey = res.getPublicKey();
      if (!publicKey) throw new Error('このブラウザでは登録できません。Chrome か Safari の新しい版で開いてください。');
      const done = await vaultApi.registerFinish({
        challenge: options.challenge,
        credential_id: toB64u(cred.rawId),
        client_data_json: toB64u(res.clientDataJSON),
        authenticator_data: toB64u(res.getAuthenticatorData()),
        public_key: toB64u(publicKey),
        alg: res.getPublicKeyAlgorithm(),
        label,
      });
      toast.success(`「${done.label}」を登録しました`);
    });

  const openEnroll = () =>
    run('enroll', async () => {
      const options = await vaultApi.assertOptions('enroll');
      await vaultApi.openEnroll(await passkeyAssertion(options));
      toast.success('10分間、別の端末を登録できます。登録したい端末でこの画面を開いてください。');
    });

  const removeKey = (credentialId: string, keyLabel: string) => {
    if (!window.confirm(`「${keyLabel}」を外しますか？`)) return;
    run(`delete:${credentialId}`, async () => {
      const options = await vaultApi.assertOptions('delete', credentialId);
      await vaultApi.deletePasskey({ ...(await passkeyAssertion(options)), target: credentialId });
      toast.success(`「${keyLabel}」を外しました`);
    });
  };

  const copy = async (text: string, what: string) => {
    await navigator.clipboard.writeText(text);
    toast.success(`${what}をコピーしました`);
  };

  if (status.isLoading) {
    return (
      <div className="flex h-full items-center justify-center text-muted-foreground">
        <Loader2 className="mr-2 h-5 w-5 animate-spin" /> 読み込み中
      </div>
    );
  }
  if (status.isError) {
    return <div className="p-6 text-sm text-destructive">{errorText(status.error)}</div>;
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-2xl space-y-6 p-4 pb-24 md:p-8" data-testid="vault-page">
        <header className="space-y-1">
          <h1 className="flex items-center gap-2 text-xl font-semibold">
            <KeyRound className="h-5 w-5" /> パスワード
          </h1>
          <p className="text-sm text-muted-foreground">
            ダンが保管しているパスワードを、この画面にだけ表示します。表示するたびに、PCでは Windows の PIN、スマホでは指紋か顔認証で確かめます。
          </p>
        </header>

        {!supported && (
          <div className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
            このブラウザでは本人確認ができません。Chrome か Safari で https://dan.paina.info/vault を開いてください。
          </div>
        )}

        {revealed && (
          <section className="space-y-3 rounded-xl border-2 border-primary/40 bg-primary/5 p-4" data-testid="vault-revealed">
            <div className="flex items-center justify-between">
              <h2 className="font-semibold">{revealed.service}</h2>
              <span className="text-xs text-muted-foreground">あと {remaining} 秒で消えます</span>
            </div>
            {revealed.login_id && (
              <div className="flex items-center gap-2">
                <span className="w-24 shrink-0 text-xs text-muted-foreground">ログインID</span>
                <code className="min-w-0 flex-1 break-all font-mono text-sm">{revealed.login_id}</code>
                <Button size="sm" variant="ghost" onClick={() => copy(revealed.login_id, 'ログインID')}>
                  <Copy className="h-4 w-4" />
                </Button>
              </div>
            )}
            <div className="flex items-center gap-2">
              <span className="w-24 shrink-0 text-xs text-muted-foreground">パスワード</span>
              <code className="min-w-0 flex-1 break-all font-mono text-lg tracking-wider" data-testid="vault-password">
                {revealed.password || '（保存されていません）'}
              </code>
              {revealed.password && (
                <Button size="sm" onClick={() => copy(revealed.password, 'パスワード')}>
                  <Copy className="mr-1 h-4 w-4" /> コピー
                </Button>
              )}
            </div>
            {revealed.password && (
              <div>
                <p className="mb-1 text-xs text-muted-foreground">1文字ずつ（手で入れる時の確認用）</p>
                <div className="flex flex-wrap gap-1">
                  {Array.from(revealed.password).map((ch, i) => {
                    const kind = charKind(ch);
                    return (
                      <div key={i} className={cn('flex w-11 flex-col items-center rounded border py-1', kind.className)}>
                        <span className="font-mono text-lg leading-tight">{ch === ' ' ? '␣' : ch}</span>
                        <span className="text-[10px] leading-tight">{kind.label}</span>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}
            {revealed.login_url && (
              <p className="break-all text-xs text-muted-foreground">ログイン先: {revealed.login_url}</p>
            )}
            <Button variant="outline" size="sm" onClick={() => setRevealed(null)}>
              今すぐ消す
            </Button>
          </section>
        )}

        {hereKeys.length === 0 ? (
          <section className="space-y-3 rounded-xl border p-4">
            <h2 className="flex items-center gap-2 font-semibold">
              <ShieldCheck className="h-4 w-4" /> この端末を登録する
            </h2>
            {enrollOpen ? (
              <>
                <p className="text-sm text-muted-foreground">
                  登録を受け付けています（{new Date(status.data!.enroll_open_until!).toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit' })} まで）。
                  ボタンを押すと、PCでは Windows の PIN、スマホでは指紋か顔認証を求められます。
                </p>
                <div className="flex gap-2">
                  <Input value={label} onChange={e => setLabel(e.target.value)} placeholder="端末の名前（例: PC）" className="max-w-xs" />
                  <Button onClick={register} disabled={busy === 'register' || !supported} data-testid="vault-register">
                    {busy === 'register' ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <Plus className="mr-1 h-4 w-4" />}
                    この端末を登録
                  </Button>
                </div>
              </>
            ) : passkeys.length > 0 ? (
              <p className="text-sm text-muted-foreground">
                登録済みの端末でこの画面を開き、「端末を追加」を押してください。10分間、この端末を登録できるようになります。
              </p>
            ) : (
              <p className="text-sm text-muted-foreground">
                まだ1台も登録されていません。ダンに「パスワード表示の端末を登録したい」と言うと、PCで10分間だけ登録を受け付けます。
              </p>
            )}
          </section>
        ) : (
          <section className="space-y-3">
            <div className="relative">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input value={query} onChange={e => setQuery(e.target.value)} placeholder="サービス名で探す" className="pl-9" />
            </div>
            <ul className="divide-y rounded-xl border" data-testid="vault-services">
              {services.map(s => (
                <li
                  key={s.service}
                  className={cn('flex items-center gap-3 px-4 py-2', s.service === focusService && 'bg-primary/5')}
                >
                  <span className="min-w-0 flex-1 truncate text-sm">{s.service}</span>
                  <Button
                    size="sm"
                    variant={s.service === focusService ? 'default' : 'outline'}
                    onClick={() => reveal(s.service)}
                    disabled={busy !== ''}
                    data-testid={`vault-reveal-${s.service}`}
                  >
                    {busy === `reveal:${s.service}` ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <Eye className="mr-1 h-4 w-4" />}
                    表示
                  </Button>
                </li>
              ))}
              {services.length === 0 && <li className="px-4 py-6 text-center text-sm text-muted-foreground">見つかりません</li>}
            </ul>
          </section>
        )}

        <section className="space-y-2">
          <div className="flex items-center justify-between">
            <h2 className="font-semibold">登録済みの端末</h2>
            {hereKeys.length > 0 && (
              <Button size="sm" variant="outline" onClick={openEnroll} disabled={busy !== ''}>
                <Plus className="mr-1 h-4 w-4" /> 端末を追加
              </Button>
            )}
          </div>
          {passkeys.length === 0 ? (
            <p className="text-sm text-muted-foreground">まだありません。</p>
          ) : (
            <ul className="divide-y rounded-xl border">
              {passkeys.map(p => (
                <li key={p.credential_id} className="flex items-center gap-3 px-4 py-2 text-sm">
                  <div className="min-w-0 flex-1">
                    <div className="truncate">{p.label}</div>
                    <div className="text-xs text-muted-foreground">
                      {p.rp_id} ・ 登録 {new Date(p.created_at).toLocaleDateString('ja-JP')}
                      {p.last_used_at && ` ・ 最後に使用 ${new Date(p.last_used_at).toLocaleString('ja-JP')}`}
                    </div>
                  </div>
                  {hereKeys.length > 0 && (
                    <Button size="sm" variant="ghost" onClick={() => removeKey(p.credential_id, p.label)} disabled={busy !== ''}>
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>

        {(status.data?.recent?.length ?? 0) > 0 && (
          <section className="space-y-2">
            <h2 className="font-semibold">最近の記録</h2>
            <ul className="space-y-1 text-xs text-muted-foreground">
              {status.data!.recent.map((e, i) => (
                <li key={i}>
                  {new Date(e.at).toLocaleString('ja-JP')} ・ {EVENT_TEXT[e.event] ?? e.event}
                  {e.service && ` ・ ${e.service}`}
                  {(e.device || e.label) && ` ・ ${e.device || e.label}`}
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>
    </div>
  );
}
