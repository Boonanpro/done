import { NextRequest, NextResponse } from 'next/server';

function backendUrl(): string {
  return process.env.BACKEND_URL || 'http://127.0.0.1:8000';
}

function supabaseConfig() {
  const url = process.env.SUPABASE_URL || process.env.NEXT_PUBLIC_SUPABASE_URL;
  const key =
    process.env.SUPABASE_SERVICE_ROLE_KEY ||
    process.env.SUPABASE_SERVICE_KEY ||
    process.env.SUPABASE_KEY ||
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  return { url, key };
}

export async function GET(request: NextRequest) {
  const slug = request.nextUrl.searchParams.get('slug')?.trim();
  if (!slug) {
    return NextResponse.json({ detail: 'slug is required' }, { status: 400 });
  }

  try {
    const endpoint = new URL('/api/v1/inspector-overrides/public', backendUrl());
    endpoint.searchParams.set('slug', slug);
    const res = await fetch(endpoint, { cache: 'no-store' });
    const body = await res.text();
    return new NextResponse(body, {
      status: res.status,
      headers: {
        'Content-Type': res.headers.get('Content-Type') || 'application/json',
        'Cache-Control': 'no-store',
      },
    });
  } catch {
    // Fall through to the direct Supabase read for deployments that do not
    // have a reachable backend proxy configured.
  }

  const { url, key } = supabaseConfig();
  if (!url || !key) {
    return NextResponse.json({ detail: 'Supabase is not configured' }, { status: 500 });
  }

  const endpoint = new URL('/rest/v1/artifact_edit_releases', url);
  endpoint.searchParams.set('artifact_slug', `eq.${slug}`);
  endpoint.searchParams.set('select', 'overrides');
  endpoint.searchParams.set('order', 'revision.desc');
  endpoint.searchParams.set('limit', '1');

  const res = await fetch(endpoint, {
    headers: {
      apikey: key,
      Authorization: `Bearer ${key}`,
    },
    cache: 'no-store',
  });

  if (!res.ok) {
    return NextResponse.json({ detail: 'Failed to load public overrides' }, { status: res.status });
  }

  const releases = await res.json() as Array<{ overrides?: Record<string, { styles?: Record<string, string>; attrs?: Record<string, unknown> }> }>;
  const overrides = releases[0]?.overrides || {};
  const rows = Object.entries(overrides).map(([element_key, value]) => ({
    element_key,
    styles: value?.styles || {},
    attrs: value?.attrs || {},
  }));
  return NextResponse.json(rows, {
    headers: {
      'Cache-Control': 'no-store',
    },
  });
}
