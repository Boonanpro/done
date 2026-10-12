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
