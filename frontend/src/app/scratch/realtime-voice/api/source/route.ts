/**
 * 音声エージェント用のソースコード読み書きルート。
 *
 * 方針転換（2026-08-20 ユーザー指示）: 「まず音声エージェント自身で全部できるかを試す。
 * 委譲はセカンドオプション」。構造変更も自分でできるよう、対象成果物の
 * ソースディレクトリ（frontend/src/app/artifacts/<slug>/）に限定して
 * list / read / edit / write を許可する。dev サーバーの HMR により、
 * 編集は1〜2秒で iframe の表示に反映される。
 *
 * ローカル開発専用（production では 403）。パスは成果物ディレクトリ内に厳格に制限。
 */
import { mkdirSync, readdirSync, readFileSync, statSync, writeFileSync } from 'fs';
import path from 'path';
import { NextResponse } from 'next/server';

const ALLOWED_EXT = new Set(['.tsx', '.ts', '.css', '.md', '.json', '.txt', '.tmp']);

function artifactRoot(slug: string): string | null {
  if (!/^[a-z0-9][a-z0-9-]*$/i.test(slug)) return null;
  return path.resolve(process.cwd(), 'src', 'app', 'artifacts', slug);
}

function resolveFile(root: string, file: string): string | null {
  if (!file || file.includes('..') || path.isAbsolute(file)) return null;
  if (!ALLOWED_EXT.has(path.extname(file).toLowerCase())) return null;
  const full = path.resolve(root, file);
  if (!full.startsWith(root + path.sep) && full !== root) return null;
  return full;
}

export async function POST(req: Request) {
  if (process.env.NODE_ENV === 'production') {
    return NextResponse.json({ error: 'ローカル開発専用です' }, { status: 403 });
  }
  const body = (await req.json().catch(() => ({}))) as {
    action?: string;
    slug?: string;
    file?: string;
    old_string?: string;
    new_string?: string;
    content?: string;
  };
  const root = artifactRoot(String(body.slug || ''));
  if (!root) return NextResponse.json({ error: 'slug が不正です' }, { status: 400 });

  if (body.action === 'list') {
    const files: Array<{ file: string; bytes: number }> = [];
    const walk = (dir: string, rel: string) => {
      let entries: string[] = [];
      try {
        entries = readdirSync(dir);
      } catch {
        return;
      }
      for (const e of entries) {
        const full = path.join(dir, e);
        const r = rel ? `${rel}/${e}` : e;
        const st = statSync(full);
        if (st.isDirectory()) walk(full, r);
        else files.push({ file: r, bytes: st.size });
      }
    };
    walk(root, '');
    return NextResponse.json({ files: files.slice(0, 100) });
  }

  const full = resolveFile(root, String(body.file || ''));
  if (!full) return NextResponse.json({ error: 'file パスが不正です（成果物ディレクトリ内のみ可）' }, { status: 400 });

  if (body.action === 'read') {
    try {
      const content = readFileSync(full, 'utf-8');
      return NextResponse.json({
        file: body.file,
        bytes: content.length,
        content: content.slice(0, 120_000),
        truncated: content.length > 120_000,
      });
    } catch {
      return NextResponse.json({ error: 'ファイルが読めません（存在しない可能性）' }, { status: 404 });
    }
  }

  if (body.action === 'edit') {
    const oldStr = String(body.old_string ?? '');
    const newStr = String(body.new_string ?? '');
    if (!oldStr) return NextResponse.json({ error: 'old_string が空です' }, { status: 400 });
    let content: string;
    try {
      content = readFileSync(full, 'utf-8');
    } catch {
      return NextResponse.json({ error: 'ファイルが読めません' }, { status: 404 });
    }
    const count = content.split(oldStr).length - 1;
    if (count === 0) {
      return NextResponse.json({ error: 'old_string がファイル内に見つかりません（完全一致が必要）' }, { status: 409 });
    }
    if (count > 1) {
      return NextResponse.json(
        { error: `old_string が ${count} 箇所にマッチします。前後を含めて一意にしてください` },
        { status: 409 },
      );
    }
    writeFileSync(full, content.replace(oldStr, newStr), 'utf-8');
    return NextResponse.json({ ok: true, file: body.file, note: 'HMRで1〜2秒後に画面へ反映されます' });
  }

  if (body.action === 'write') {
    const content = String(body.content ?? '');
    if (!content) return NextResponse.json({ error: 'content が空です' }, { status: 400 });
    if (content.length > 400_000) return NextResponse.json({ error: 'content が大きすぎます' }, { status: 413 });
    mkdirSync(path.dirname(full), { recursive: true });
    writeFileSync(full, content, 'utf-8');
    return NextResponse.json({ ok: true, file: body.file, bytes: content.length, note: 'HMRで1〜2秒後に画面へ反映されます' });
  }

  return NextResponse.json({ error: `未知の action: ${body.action}` }, { status: 400 });
}
