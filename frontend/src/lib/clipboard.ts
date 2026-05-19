/**
 * クリップボードコピー（セキュアでない環境フォールバック付き）。
 *
 * navigator.clipboard は HTTPS または localhost でしか使えない。
 * Tailscale IP 等の HTTP アクセスでは undefined になりクラッシュするため、
 * その場合は execCommand('copy') にフォールバックする。
 *
 * 例外は投げず、成否を boolean で返す。
 */
export async function copyToClipboard(text: string): Promise<boolean> {
  try {
    if (
      typeof navigator !== 'undefined' &&
      navigator.clipboard &&
      typeof window !== 'undefined' &&
      window.isSecureContext
    ) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    /* フォールバックへ */
  }

  try {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.top = '0';
    ta.style.left = '0';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.focus();
    ta.select();
    const ok = document.execCommand('copy');
    document.body.removeChild(ta);
    return ok;
  } catch {
    return false;
  }
}
