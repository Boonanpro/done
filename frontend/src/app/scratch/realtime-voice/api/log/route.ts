/**
 * /scratch/realtime-voice 系ページのログ永続化（開発CLIが後から読めるように）。
 *
 * ページの実行ログ（音声の文字起こし・ツール実行・保存結果）はブラウザ内で揮発するため、
 * ここに逐次 POST して D:/done/logs/realtime-voice/<セッションID>.jsonl に追記する。
 * logs/ は gitignore 済み。ローカル開発専用（production では 403）。
 */
import { appendFileSync, mkdirSync } from 'fs';
import path from 'path';
import { NextResponse } from 'next/server';

export async function POST(req: Request) {
  if (process.env.NODE_ENV === 'production') {
    return NextResponse.json({ error: 'ローカル開発専用です' }, { status: 403 });
  }
  const body = (await req.json().catch(() => null)) as {
    session_id?: string;
    entries?: Array<{ time?: string; tag?: string; text?: string }>;
    /** 成果物スナップショット: 編集後ページの完全HTML。実行ログと別ファイルに保存する。 */
    snapshot_html?: string;
    snapshot_label?: string;
  } | null;
  const sessionId = (body?.session_id || '').replace(/[^a-zA-Z0-9_-]/g, '').slice(0, 64);
  if (!sessionId) {
    return NextResponse.json({ error: 'session_id が必要です' }, { status: 400 });
  }
  const dir = path.resolve(process.cwd(), '..', 'logs', 'realtime-voice');
  mkdirSync(dir, { recursive: true });

  if (typeof body?.snapshot_html === 'string' && body.snapshot_html.length > 0) {
    const label = (body.snapshot_label || 'snap').replace(/[^a-zA-Z0-9_-]/g, '').slice(0, 40);
    const stamp = new Date().toISOString().slice(11, 19).replace(/:/g, '');
    const file = `${sessionId}-${stamp}-${label}.html`;
    // 2MB キャップ（巨大ページの暴発防止）
    appendFileSync(path.join(dir, file), body.snapshot_html.slice(0, 2_000_000), 'utf-8');
    return NextResponse.json({ ok: true, snapshot: file });
  }

  const entries = Array.isArray(body?.entries) ? body!.entries!.slice(0, 200) : [];
  if (entries.length === 0) {
    return NextResponse.json({ error: 'entries か snapshot_html が必要です' }, { status: 400 });
  }
  const lines = entries
    .map((e) =>
      JSON.stringify({
        time: String(e.time ?? '').slice(0, 32),
        tag: String(e.tag ?? '').slice(0, 8),
        text: String(e.text ?? '').slice(0, 2000),
      }),
    )
    .join('\n');
  appendFileSync(path.join(dir, `${sessionId}.jsonl`), lines + '\n', 'utf-8');
  return NextResponse.json({ ok: true, saved: entries.length });
}
