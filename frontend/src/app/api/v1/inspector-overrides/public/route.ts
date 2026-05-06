import { NextRequest, NextResponse } from 'next/server';

const DEFAULT_PUBLIC_ARTIFACT_SLUGS = 'kittoku';

function publicSlugs(): Set<string> {
  return new Set(
    (process.env.PUBLIC_ARTIFACT_SLUGS || process.env.NEXT_PUBLIC_ARTIFACT_SLUGS || DEFAULT_PUBLIC_ARTIFACT_SLUGS)
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean),
  );
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
  if (!publicSlugs().has(slug)) {
    return NextResponse.json([]);
  }

  const { url, key } = supabaseConfig();
  if (!url || !key) {
    return NextResponse.json({ detail: 'Supabase is not configured' }, { status: 500 });
  }

  const endpoint = new URL('/rest/v1/inspector_overrides', url);
  endpoint.searchParams.set('artifact_slug', `eq.${slug}`);
  endpoint.searchParams.set('select', '*');
  endpoint.searchParams.set('order', 'updated_at.asc');

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

  const rows = await res.json();
  return NextResponse.json(rows, {
    headers: {
      'Cache-Control': 'no-store',
    },
  });
}
