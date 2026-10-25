// Exact destinations only: never send the app session to a link's host.
export function isXOperation(url: string): boolean {
  try {
    const u = new URL(url);
    return u.protocol === 'https:' && (
      (u.hostname === 'dan-site-x-operation-3ef49fba.vercel.app' && u.pathname === '/') ||
      (u.hostname === 'dan.paina.info' && /^\/(preview|artifacts)\/x-operation\/?$/.test(u.pathname))
    );
  } catch { return false; }
}

export async function privateArtifactUrl(apiBase: string, token: string): Promise<string> {
  // React Native's AbortSignal polyfill has no static timeout() method.
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 20000);
  try {
  const response = await fetch(apiBase + '/api/x-operation/open', {
    method: 'POST', headers: {Authorization: `Bearer ${token}`}, signal: controller.signal,
  });
  if (!response.ok) throw new Error('運用室に接続できませんでした。アプリからもう一度開いてください。');
  const result = await response.json();
  const url = new URL(result.url);
  if (url.origin !== new URL(apiBase).origin || url.pathname !== '/api/x-operation/open' || !/^#[\w-]{43}$/.test(url.hash)) {
    throw new Error('運用室の接続先を確認できませんでした。');
  }
  return url.toString();
  } finally {
    clearTimeout(timer);
  }
}

// ダンの画面（成果物・パスワードの表示など）をスマホのブラウザで開く時の入口（frontend/src/app/enter/route.ts）。
// ブラウザはアプリのログインを持っていないので、使い捨ての入館証を付けて開き、ブラウザにもログインを入れる
// （10-25 本人「俺にログインさせないで。自動でログインして」）。もらえなかった時は null（元の住所をそのまま開く）。
export async function signedInBrowserUrl(apiBase: string, token: string, refreshToken: string | null, to: string): Promise<string | null> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 15000);
  try {
    const response = await fetch(apiBase + '/enter', {
      method: 'POST', signal: controller.signal,
      headers: {Authorization: `Bearer ${token}`, 'Content-Type': 'application/json'},
      body: JSON.stringify({to, refresh_token: refreshToken || undefined}),
    });
    if (!response.ok) return null;
    const result = await response.json();
    const url = new URL(result.url);
    if (url.origin !== new URL(apiBase).origin || url.pathname !== '/enter' || !/^#[\w-]{43}$/.test(url.hash)) return null;
    return url.toString();
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}
