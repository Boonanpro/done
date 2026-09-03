import { NextRequest, NextResponse } from 'next/server';

/**
 * 公開した成果物サイトからの問い合わせ／先行登録の受付口。
 *
 * なぜ専用の口が要るか:
 *   成果物は 1サイト＝1つの専用 Vercel プロジェクトで配信される。専用プロジェクトは
 *   バックエンドへの転送設定（BACKEND_URL）を持たないため、成果物のフォームが
 *   相対パスで /api/v1/inquiries に投げると 404 になり、登録が1件も取れない。
 *   ダン本体の公開 origin にあるこの口を経由させれば、接続先を知っているのは
 *   本体だけで済み、バックエンドのURLが変わっても成果物側の再公開は要らない。
 *
 * 別オリジンからの POST になるので CORS を明示する。許可するのは成果物ホストだけ。
 * next.config の rewrites は配列形式（afterFiles）なので、この route.ts が
 * `/api/:path*` → バックエンド の転送より先に解決される。
 */

const ARTIFACT_ORIGIN =
  /^https:\/\/(dan-site-[a-z0-9-]+|[a-z0-9-]+-done|frontend-[a-z0-9-]+)\.vercel\.app$/;

function allowedOrigin(origin: string | null): string | null {
  if (!origin) return null;
  if (ARTIFACT_ORIGIN.test(origin)) return origin;

  // 接続済みの独自ドメイン（middleware と同じ環境変数を使う）。
  const configured =
    process.env.ARTIFACT_CUSTOM_DOMAINS ||
    process.env.NEXT_PUBLIC_ARTIFACT_CUSTOM_DOMAINS ||
    '';
  const domains = configured
    .split(',')
    .map((entry) => entry.split('=')[1]?.trim())
    .filter(Boolean);
  try {
    const host = new URL(origin).hostname;
    if (domains.includes(host)) return origin;
  } catch {
    return null;
  }
  return null;
}

function corsHeaders(origin: string): Record<string, string> {
  return {
    'Access-Control-Allow-Origin': origin,
    'Access-Control-Allow-Methods': 'POST, OPTIONS',
    'Access-Control-Allow-Headers': 'content-type',
    'Access-Control-Max-Age': '86400',
    Vary: 'Origin',
  };
}

export async function OPTIONS(request: NextRequest) {
  const origin = allowedOrigin(request.headers.get('origin'));
  if (!origin) return new NextResponse(null, { status: 403 });
  return new NextResponse(null, { status: 204, headers: corsHeaders(origin) });
}

export async function POST(request: NextRequest) {
  const origin = allowedOrigin(request.headers.get('origin'));
  if (!origin) {
    return NextResponse.json({ detail: 'origin not allowed' }, { status: 403 });
  }

  let payload: unknown;
  try {
    payload = await request.json();
  } catch {
    return NextResponse.json(
      { detail: 'invalid json' },
      { status: 400, headers: corsHeaders(origin) },
    );
  }

  const backendUrl = process.env.BACKEND_URL || 'http://127.0.0.1:8000';
  try {
    const upstream = await fetch(`${backendUrl}/api/v1/inquiries`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const text = await upstream.text();
    return new NextResponse(text, {
      status: upstream.status,
      headers: {
        ...corsHeaders(origin),
        'Content-Type':
          upstream.headers.get('content-type') || 'application/json',
      },
    });
  } catch (error) {
    return NextResponse.json(
      { detail: `upstream unreachable: ${String(error).slice(0, 200)}` },
      { status: 502, headers: corsHeaders(origin) },
    );
  }
}
