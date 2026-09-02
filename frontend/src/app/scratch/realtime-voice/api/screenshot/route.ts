/**
 * 認証付きフルページスクリーンショット ルート（look_at_page の裏側）。
 *
 * 同ディレクトリの fullpage.py（Playwright）を起動し、対象ページの
 * スクロール全域を JPEG で撮って data URL として返す。
 * ブラウザから渡された done-token をクッキーとして注入するので、
 * draft override が適用された「ユーザーが見ているのと同じ状態」が写る。
 * ローカル開発専用（production では 403）。
 */
import { execFile } from 'child_process';
import { mkdirSync, readFileSync, rmSync } from 'fs';
import path from 'path';
import { NextResponse } from 'next/server';

function runPython(args: string[], timeoutMs: number): Promise<void> {
  return new Promise((resolve, reject) => {
    execFile('python', args, { timeout: timeoutMs }, (err) => {
      if (err) reject(err);
      else resolve();
    });
  });
}

export async function POST(req: Request) {
  if (process.env.NODE_ENV === 'production') {
    return NextResponse.json({ error: 'ローカル開発専用です' }, { status: 403 });
  }
  const body = (await req.json().catch(() => ({}))) as {
    path?: string;
    token?: string;
    /** 指定時はこの data-edit-id の要素だけを原寸で撮る（look_at_section）。 */
    element_id?: string;
  };
  const target = String(body.path || '');
  if (!/^\/(artifacts|preview|scratch|demo)\/[a-zA-Z0-9_/-]*$/.test(target)) {
    return NextResponse.json({ error: 'path が不正です' }, { status: 400 });
  }
  const elementId = String(body.element_id || '');
  if (elementId && !/^[a-zA-Z0-9_-]+$/.test(elementId)) {
    return NextResponse.json({ error: 'element_id が不正です' }, { status: 400 });
  }

  const script = path.resolve(
    process.cwd(),
    'src',
    'app',
    'scratch',
    'realtime-voice',
    'api',
    'screenshot',
    'fullpage.py',
  );
  const outDir = path.resolve(process.cwd(), '..', 'logs', 'realtime-voice', 'shots');
  mkdirSync(outDir, { recursive: true });
  const outFile = path.join(outDir, `shot-${Date.now()}.jpg`);

  try {
    const args = [script, '--url', `http://localhost:3000${target}`, '--out', outFile];
    const token = String(body.token || '');
    if (token) args.push('--token', token);
    if (elementId) args.push('--selector', `[data-edit-id="${elementId}"]`);
    // 汎用の目: 全域撮影は文字が読める解像度のタイル群で返す（縮小1枚では知能が気付けない）
    const useTiles = !elementId;
    if (useTiles) args.push('--tiles', '8');
    await runPython(args, 60_000);
    if (useTiles) {
      const tiles: string[] = [];
      for (let i = 1; i <= 8; i += 1) {
        const tilePath = `${outFile}.tile${String(i).padStart(2, '0')}.jpg`;
        try {
          const buf = readFileSync(tilePath);
          tiles.push(`data:image/jpeg;base64,${buf.toString('base64')}`);
        } catch {
          break;
        }
      }
      if (!tiles.length) throw new Error('タイルが生成されませんでした');
      return NextResponse.json({
        tiles,
        count: tiles.length,
        bytes: tiles.reduce((a, t) => a + t.length, 0),
        file: path.basename(outFile),
      });
    }
    const buf = readFileSync(outFile);
    // 撮影ファイルはログ置き場に残す（開発CLIが後から成果物確認に使える）
    return NextResponse.json({
      image: `data:image/jpeg;base64,${buf.toString('base64')}`,
      bytes: buf.length,
      file: path.basename(outFile),
    });
  } catch (e) {
    try {
      rmSync(outFile, { force: true });
    } catch {
      /* noop */
    }
    return NextResponse.json(
      { error: `スクリーンショットに失敗: ${String(e).slice(0, 200)}` },
      { status: 502 },
    );
  }
}
