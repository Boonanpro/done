// 保存済みパスワードを本人の画面にだけ出す（/vault）。毎回パスキーで本人確認する。
// 裏側は app/api/secret_vault_routes.py（Dan Core。/api/v1/credentials/* は Core へ中継される）。
import { ApiError } from './api-client';
import { refreshSession } from './session-refresh';
import { useAuthStore } from '@/stores/auth-store';

const TOKEN_KEY = 'done-token';

export interface VaultStatus {
  passkeys: { credential_id: string; label: string; rp_id: string; created_at: string; last_used_at: string | null }[];
  enroll_open_until: string | null;
  services: { service: string; updated_at: string | null }[];
  recent: { at: string; event: string; service?: string; device?: string; label?: string; by?: string }[];
}

export interface VaultRegisterOptions {
  challenge: string;
  rp: { id: string; name: string };
  user: { id: string; name: string; displayName: string };
  excludeCredentials: string[];
}

export interface VaultAssertOptions {
  challenge: string;
  rpId: string;
  allowCredentials: string[];
}

export interface VaultRevealed {
  service: string;
  login_id: string;
  password: string;
  login_url: string;
}

async function call<T>(path: string, body?: Record<string, unknown>): Promise<T> {
  const send = (token: string | null) =>
    fetch(`/api/v1/credentials/vault${path}`, {
      method: body === undefined ? 'GET' : 'POST',
      headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: body === undefined ? undefined : JSON.stringify(body),
      credentials: 'include',
    });
  let response = await send(localStorage.getItem(TOKEN_KEY));
  if (response.status === 401) {
    const renewed = await refreshSession(value => {
      localStorage.setItem(TOKEN_KEY, value);
      useAuthStore.getState().setToken(value);
    });
    response = await send(renewed);
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new ApiError(response.status, response.statusText, data);
  return data as T;
}

export const vaultApi = {
  status: () => call<VaultStatus>('/status'),
  registerOptions: () => call<VaultRegisterOptions>('/register/options', {}),
  registerFinish: (body: Record<string, unknown>) => call<{ ok: boolean; label: string }>('/register/finish', body),
  assertOptions: (purpose: 'reveal' | 'enroll' | 'delete', target = '') =>
    call<VaultAssertOptions>('/assert/options', { purpose, target }),
  reveal: (body: Record<string, unknown>) => call<VaultRevealed>('/reveal', body),
  openEnroll: (body: Record<string, unknown>) => call<{ ok: boolean; enroll_open_until: string }>('/enroll', body),
  deletePasskey: (body: Record<string, unknown>) => call<{ ok: boolean }>('/passkeys/delete', body),
};
