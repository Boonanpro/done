/**
 * /scratch/realtime-voice 実験用の画像生成ルート（GPT Image 2 直叩き）。
 *
 * scripts/gpt_image.py と同じ API（/v1/images/generations, model=gpt-image-2,
 * quality=low 既定 ≒ $0.02/枚）を Next サーバー側から呼び、生成画像を
 * frontend/public/scratch/realtime-voice-gen/ に保存して公開URLを返す。
 * ローカル開発専用（production ビルドでは 403）。
 */
import { mkdirSync, readFileSync, writeFileSync } from 'fs';
import path from 'path';
import { NextResponse } from 'next/server';

function loadApiKey(): string {
  if (process.env.OPENAI_API_KEY) return process.env.OPENAI_API_KEY;
  try {
    const envPath = path.resolve(process.cwd(), '..', '.env');
    const line = readFileSync(envPath, 'utf-8')
      .split(/\r?\n/)
      .find((l) => l.startsWith('OPENAI_API_KEY='));
    if (line) return line.slice('OPENAI_API_KEY='.length).trim().replace(/^"|"$/g, '');
  } catch {
    /* fall through */
  }
  return '';
}

/** gpt-image-2 のサイズ制約: 両辺16の倍数 / 最長辺3840以下 / 比3:1以内 / 総画素655,360以上 */
function validateSize(size: string): string | null {
  const m = size.match(/^(\d+)x(\d+)$/);
  if (!m) return null;
  const w = parseInt(m[1], 10);
  const h = parseInt(m[2], 10);
  if (w % 16 || h % 16) return null;
  if (Math.max(w, h) > 3840) return null;
  if (Math.max(w, h) / Math.min(w, h) > 3) return null;
  if (w * h < 655_360 || w * h > 8_294_400) return null;
  return `${w}x${h}`;
}

export async function POST(req: Request) {
  if (process.env.NODE_ENV === 'production') {
    return NextResponse.json({ error: 'ローカル開発専用です' }, { status: 403 });
  }
  const apiKey = loadApiKey();
  if (!apiKey) {
    return NextResponse.json({ error: 'OPENAI_API_KEY が見つかりません' }, { status: 503 });
  }

  const body = (await req.json().catch(() => ({}))) as { prompt?: string; size?: string };
  const prompt = (body.prompt || '').trim();
  if (!prompt) return NextResponse.json({ error: 'prompt が空です' }, { status: 400 });
  const size = validateSize(body.size || '') || '1520x800';

  const started = Date.now();
  const resp = await fetch('https://api.openai.com/v1/images/generations', {
    method: 'POST',
    headers: { Authorization: `Bearer ${apiKey}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ model: 'gpt-image-2', prompt, size, quality: 'low' }),
  });
  if (!resp.ok) {
    const detail = (await resp.text()).slice(0, 500);
    return NextResponse.json(
      { error: `画像生成に失敗 (HTTP ${resp.status}): ${detail}` },
      { status: 502 },
    );
  }
  const data = await resp.json();
  const b64 = data?.data?.[0]?.b64_json;
  if (!b64) return NextResponse.json({ error: '画像データが空でした' }, { status: 502 });

  const dir = path.resolve(process.cwd(), 'public', 'scratch', 'realtime-voice-gen');
  mkdirSync(dir, { recursive: true });
  const name = `gen-${Date.now()}.png`;
  writeFileSync(path.join(dir, name), Buffer.from(b64, 'base64'));

  return NextResponse.json({
    url: `/scratch/realtime-voice-gen/${name}`,
    size,
    seconds: Math.round((Date.now() - started) / 100) / 10,
  });
}
