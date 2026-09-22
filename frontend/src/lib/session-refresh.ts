// Share refresh attempts across simultaneous API requests in one browser tab.
let pending: Promise<string> | null = null;

export class SessionRefreshError extends Error {
  constructor(public status: number) { super(`Session refresh failed (${status})`); }
}

export function refreshSession(save: (token: string) => void): Promise<string> {
  if (!pending) {
    pending = (async () => {
      const response = await fetch('/api/v1/chat/refresh', {
        method: 'POST', credentials: 'include',
        signal: AbortSignal.timeout(15000),
      });
      if (!response.ok) throw new SessionRefreshError(response.status);
      const data = await response.json();
      if (typeof data.access_token !== 'string' || !data.access_token) {
        throw new Error('Missing access token');
      }
      save(data.access_token);
      return data.access_token;
    })().finally(() => { pending = null; });
  }
  return pending;
}
