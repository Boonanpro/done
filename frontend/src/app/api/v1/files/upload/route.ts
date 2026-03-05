import { NextRequest, NextResponse } from 'next/server';

export const runtime = 'nodejs';
export const maxDuration = 60;

const BACKEND = 'http://127.0.0.1:8000';

export async function POST(request: NextRequest) {
  const body = await request.arrayBuffer();

  const resp = await fetch(`${BACKEND}/api/v1/files/upload`, {
    method: 'POST',
    headers: {
      'content-type': request.headers.get('content-type') || 'application/octet-stream',
      ...(request.headers.get('authorization')
        ? { authorization: request.headers.get('authorization')! }
        : {}),
      ...(request.headers.get('cookie')
        ? { cookie: request.headers.get('cookie')! }
        : {}),
    },
    body,
  });

  const data = await resp.json();
  return NextResponse.json(data, { status: resp.status });
}
