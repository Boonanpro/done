import { NextRequest } from 'next/server';

function titleFromSlug(slug: string): string {
  return decodeURIComponent(slug)
    .split('-')
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}

export async function GET(
  _request: NextRequest,
  { params }: { params: Promise<{ slug: string }> },
) {
  const { slug } = await params;
  const title = titleFromSlug(slug) || 'Artifact';
  const manifest = {
    name: title,
    short_name: title.slice(0, 12),
    description: `${title} public preview`,
    start_url: `/preview/${slug}`,
    scope: `/preview/${slug}`,
    display: 'standalone',
    background_color: '#ffffff',
    theme_color: '#111827',
    lang: 'ja-JP',
    icons: [
      {
        src: `/artifacts/${slug}/icon-192.png`,
        sizes: '192x192',
        type: 'image/png',
        purpose: 'any maskable',
      },
      {
        src: `/artifacts/${slug}/icon-512.png`,
        sizes: '512x512',
        type: 'image/png',
        purpose: 'any maskable',
      },
    ],
  };

  return new Response(JSON.stringify(manifest, null, 2), {
    headers: {
      'Content-Type': 'application/manifest+json',
      'Cache-Control': 'public, max-age=3600',
    },
  });
}
