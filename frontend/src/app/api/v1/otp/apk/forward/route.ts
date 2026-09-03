import { NextRequest, NextResponse } from 'next/server';
import { createHash } from 'node:crypto';

// Always-on landing point for SMS OTP forwarded by the Android app.
//
// Why this exists on Vercel instead of proxying to the home PC:
// forwarded OTP codes expire in ~10 minutes and cannot be re-fetched. The
// previous path (phone -> Vercel -> Cloudflare quick tunnel -> home PC:8000)
// silently dropped every code that arrived while the PC's tunnel process was
// down or restarting. Vercel + Supabase are always up, so authenticating the
// device token and writing the OTP straight to Supabase here removes the only
// unreliable hop. The home PC just reads Supabase afterwards.
//
// The parsing below is a faithful mirror of app/services/otp_service.py
// (_extract_otp_from_text / _extract_link_from_text / _guess_service_from_sms /
// save_apk_forwarded_sms). Keep the two in sync when either changes.

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

const OTP_EXPIRY_MINUTES = 10;

// Ordered by priority; first match wins. Mirrors OTP_PATTERNS in otp_schemas.py.
const OTP_PATTERNS: RegExp[] = [
  /(?:認証コード|確認コード|ワンタイムパスワード|OTP|verification code|security code|passcode|セキュリティコード|SafeKey)[：:\s]*[「\[]?(\d{4,8})[」\]]?/i,
  /(?:コード|code)[：:\s]*[「\[]?(\d{4,8})[」\]]?/i,
  /(?:コードは|code is)[：:\s]*[「\[]?(\d{4,8})[」\]]?/i,
  /(?:is|：|:)\s*(\d{6})\b/i,
  /(?<!\d)(\d{6})(?!\d)/,
];

const OTP_LINK_URL_PATTERN = /https?:\/\/[^\s<>"'`）」】\]]+/gi;

const OTP_LINK_TRUSTED_HOSTS = [
  'ig.me',
  'fb.me',
  'm.me',
  'wa.me',
  'l.instagram.com',
  'l.facebook.com',
  'accounts.google.com',
  'appleid.apple.com',
  'id.line.me',
];

const OTP_LINK_CONTEXT_KEYWORDS = [
  'reset', 'verify', 'verification', 'confirm', 'authenticate',
  'sign in', 'log in', 'login', 'one time', 'magic', 'tap to',
  'click the link', 'secure link', 'password',
  'パスワード', '再設定', 'リセット', '認証', '確認', 'ログイン',
  '本人確認', 'ワンタイム', 'タップ',
];

const SERVICE_KEYWORDS: Record<string, string[]> = {
  amazon: ['amazon', 'アマゾン'],
  rakuten: ['楽天', 'rakuten'],
  ex_reservation: ['ex予約', 'smartex', '新幹線', 'jr'],
  google: ['google', 'グーグル'],
  line: ['line', 'ライン'],
  yahoo: ['yahoo', 'ヤフー'],
};

function extractOtpCode(text: string): string | null {
  if (!text) return null;
  for (const pattern of OTP_PATTERNS) {
    const match = pattern.exec(text);
    if (match) {
      const otp = match[1];
      if (/^\d+$/.test(otp) && otp.length >= 4 && otp.length <= 8) {
        return otp;
      }
    }
  }
  return null;
}

function extractLink(text: string): string | null {
  if (!text) return null;
  const urls = text.match(OTP_LINK_URL_PATTERN);
  if (!urls) return null;

  // Treat "sign-in" and "sign in" alike by flattening separators.
  const textLower = text.toLowerCase().replace(/[-_]/g, ' ');
  const hasContext = OTP_LINK_CONTEXT_KEYWORDS.some((k) =>
    textLower.includes(k.toLowerCase()),
  );

  for (let url of urls) {
    // SMS bodies glue trailing punctuation/brackets onto the URL; strip them.
    url = url.replace(/[.,;:!?)\]｝』」）　]+$/, '');
    if (!url) continue;
    const host = url.split('//', 2)[1]?.split('/', 1)[0].split('?', 1)[0].toLowerCase() ?? '';
    const trusted = OTP_LINK_TRUSTED_HOSTS.some(
      (h) => host === h || host.endsWith('.' + h),
    );
    if (trusted || hasContext) {
      return url;
    }
  }
  return null;
}

function guessService(body: string): string | null {
  const bodyLower = body.toLowerCase();
  for (const [service, keywords] of Object.entries(SERVICE_KEYWORDS)) {
    for (const keyword of keywords) {
      if (bodyLower.includes(keyword.toLowerCase())) {
        return service;
      }
    }
  }
  return null;
}

function supabaseConfig() {
  const url = process.env.SUPABASE_URL || process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key =
    process.env.SUPABASE_SERVICE_ROLE_KEY ||
    process.env.SUPABASE_SERVICE_KEY ||
    process.env.SUPABASE_KEY;
  return { url, key };
}

type SupabaseResult = { ok: boolean; status: number; body: unknown };

async function supabaseFetch(
  path: string,
  init: RequestInit,
  url: string,
  key: string,
): Promise<SupabaseResult> {
  const res = await fetch(new URL(path, url), {
    ...init,
    headers: {
      apikey: key,
      Authorization: `Bearer ${key}`,
      'Content-Type': 'application/json',
      ...(init.headers || {}),
    },
    cache: 'no-store',
  });
  let body: unknown = null;
  const text = await res.text();
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = text;
    }
  }
  return { ok: res.ok, status: res.status, body };
}

export async function POST(request: NextRequest) {
  const deviceToken = request.headers.get('x-dan-otp-device-token');
  if (!deviceToken) {
    return NextResponse.json(
      { detail: 'Missing APK OTP device token' },
      { status: 401 },
    );
  }

  const { url, key } = supabaseConfig();
  if (!url || !key) {
    // 500 -> the Android worker retries with backoff, so a transient
    // misconfiguration does not throw the code away.
    return NextResponse.json(
      { detail: 'Supabase is not configured' },
      { status: 500 },
    );
  }

  let payload: { sender?: string; body?: string; message_id?: string };
  try {
    payload = await request.json();
  } catch {
    return NextResponse.json({ detail: 'Invalid JSON body' }, { status: 400 });
  }
  const sender = payload.sender ?? '';
  const body = payload.body ?? '';
  const messageId = payload.message_id ?? null;

  const tokenHash = createHash('sha256').update(deviceToken, 'utf8').digest('hex');

  // Authenticate the device token against apk_otp_devices.
  const deviceLookup = await supabaseFetch(
    `/rest/v1/apk_otp_devices?select=id,user_id&token_hash=eq.${tokenHash}&is_active=eq.true&limit=1`,
    { method: 'GET' },
    url,
    key,
  );
  if (!deviceLookup.ok) {
    return NextResponse.json(
      { detail: 'Device lookup failed' },
      { status: 500 },
    );
  }
  const devices = Array.isArray(deviceLookup.body) ? deviceLookup.body : [];
  if (devices.length === 0) {
    // Revoked or unknown token: 401 tells the worker not to retry.
    return NextResponse.json(
      { detail: 'Invalid or revoked APK OTP device token' },
      { status: 401 },
    );
  }
  const device = devices[0] as { id: string; user_id: string };

  const now = new Date().toISOString();

  // Mark the device as reachable regardless of whether this SMS parses, so the
  // /apk/status heartbeat reflects real delivery.
  await supabaseFetch(
    `/rest/v1/apk_otp_devices?id=eq.${device.id}`,
    {
      method: 'PATCH',
      headers: { Prefer: 'return=minimal' },
      body: JSON.stringify({ last_received_at: now, updated_at: now }),
    },
    url,
    key,
  );

  const otpCode = extractOtpCode(body);
  const linkUrl = otpCode ? null : extractLink(body);

  if (!otpCode && !linkUrl) {
    // Nothing actionable in this SMS. 200 so the worker stops retrying.
    return NextResponse.json({ accepted: true, otp_detected: false });
  }

  const expiresAt = new Date(
    Date.now() + OTP_EXPIRY_MINUTES * 60 * 1000,
  ).toISOString();

  const insert = await supabaseFetch(
    '/rest/v1/otp_extractions',
    {
      method: 'POST',
      headers: { Prefer: 'return=minimal' },
      body: JSON.stringify({
        user_id: device.user_id,
        source: 'sms',
        source_id: messageId,
        service: guessService(body),
        sender,
        otp_code: otpCode,
        link_url: linkUrl,
        expires_at: expiresAt,
      }),
    },
    url,
    key,
  );

  if (!insert.ok) {
    // 500 -> worker retries; the code is not lost to a transient DB error.
    return NextResponse.json(
      { detail: 'Failed to store OTP' },
      { status: 500 },
    );
  }

  return NextResponse.json({ accepted: true, otp_detected: true });
}
