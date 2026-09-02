/**
 * /scratch/realtime-voice 実験専用の ephemeral トークン発行ルート。
 *
 * ダンコアの /api/v1/realtime/session（gpt-realtime-2 固定・delegate ツール）とは
 * 独立に、モデル / reasoning effort / ツール車線 / プリアンブル方式を
 * リクエストごとに変えられるようにした実験用ミント。
 *
 * ローカル開発専用（production ビルドでは 403）。OPENAI_API_KEY は
 * 環境変数 → リポジトリ直下 D:/done/.env の順で探し、ブラウザへは出さない。
 */
import { readFileSync, readdirSync, statSync } from 'fs';
import path from 'path';
import { NextResponse } from 'next/server';

import { buildSessionConfig, normalizeConfig } from '../../session-config';

/**
 * 直前セッションの経緯をログから要約して返す（セッション継続性）。
 * 音声セッションの会話記憶は切断で消えるため、「続きをやって」を成立させるには
 * 接続時に前回の文脈を instructions へ注入する必要がある（2026-08-21、切断3回で実証）。
 */
function loadPreviousSessionBrief(): { text: string; lines: number } {
  try {
    const dir = path.resolve(process.cwd(), '..', 'logs', 'realtime-voice');
    const files = readdirSync(dir)
      .filter((f) => f.endsWith('.jsonl'))
      .map((f) => ({ f, t: statSync(path.join(dir, f)).mtimeMs }))
      .sort((a, b) => b.t - a.t)
      .slice(0, 3);
    for (const { f } of files) {
      const raw = readFileSync(path.join(dir, f), 'utf-8').trim().split('\n');
      // 開きたてのセッション（自分自身）の数行だけのファイルはスキップして1つ前を使う
      if (raw.length < 8) continue;
      // ⚠ 対話の生引用は入れない。過去の発言を注入すると、モデルが今の会話と混同して
      // 「前回の未解決依頼」に答え始める（2026-08-23 実害: 挨拶に対して前回の
      // 「これ直して」への応答を繰り返した）。事実サマリーのみ渡す。
      const toolCounts: Record<string, number> = {};
      let draftSaves = 0;
      let sourceEdits = 0;
      for (const line of raw) {
        try {
          const e = JSON.parse(line) as { tag?: string; text?: string };
          const t = String(e.text || '');
          if (e.tag === '🔧') {
            const m = t.match(/^([a-z_]+)\(/);
            if (m) toolCounts[m[1]] = (toolCounts[m[1]] || 0) + 1;
          } else if (e.tag === '💾') {
            if (t.startsWith('draft保存')) draftSaves += 1;
            if (t.startsWith('ソース編集') || t.startsWith('ソース書換')) sourceEdits += 1;
          }
        } catch {
          /* noop */
        }
      }
      const toolSummary = Object.entries(toolCounts)
        .map(([k, v]) => `${k}×${v}`)
        .join('、');
      if (!toolSummary && !draftSaves && !sourceEdits) continue;
      const summaryLines = [
        '',
        '',
        '【参考メモ: 前回セッションの作業記録。これは過去の記録であり、今の会話ではない】',
        `- 実行した操作: ${toolSummary || 'なし'}`,
        `- 保存: draft ${draftSaves}件 / ソース編集 ${sourceEdits}件`,
        '新しい会話は挨拶から普通に始めてよい。ユーザーが「続き」を求めたときだけ、',
        'この記録を参考にしつつ、必ず get_page_state / look_at_page で現状を自分で確認してから再開する。',
      ];
      return { lines: summaryLines.length, text: summaryLines.join('\n') };
    }
  } catch {
    /* noop */
  }
  return { text: '', lines: 0 };
}

const CLIENT_SECRETS_ENDPOINT = 'https://api.openai.com/v1/realtime/client_secrets';

function loadApiKey(): string {
  if (process.env.OPENAI_API_KEY) return process.env.OPENAI_API_KEY;
  try {
    // frontend/ の親 = リポジトリ直下の .env（バックエンドと共用）から読む
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

export async function POST(req: Request) {
  if (process.env.NODE_ENV === 'production') {
    return NextResponse.json({ error: 'ローカル開発専用の実験エンドポイントです' }, { status: 403 });
  }

  const apiKey = loadApiKey();
  if (!apiKey) {
    return NextResponse.json(
      { error: 'OPENAI_API_KEY が見つかりません（環境変数か D:/done/.env を確認）' },
      { status: 503 },
    );
  }

  const cfg = normalizeConfig(await req.json().catch(() => ({})));
  const session = buildSessionConfig(cfg);
  // 本物のLP編集セッションには直前セッションの経緯を引き継ぐ（「続きをやって」を成立させる）
  let continuityLines = 0;
  if (cfg.surface === 'lp') {
    const brief = loadPreviousSessionBrief();
    if (brief.text) {
      session.instructions = `${String(session.instructions ?? '')}${brief.text}`;
      continuityLines = brief.lines;
    }
  }

  const resp = await fetch(CLIENT_SECRETS_ENDPOINT, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${apiKey}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ session }),
  });

  if (!resp.ok) {
    const detail = (await resp.text()).slice(0, 800);
    return NextResponse.json(
      { error: `OpenAI client_secrets 失敗 (HTTP ${resp.status}): ${detail}`, config: cfg },
      { status: 502 },
    );
  }

  const body = await resp.json();
  return NextResponse.json({
    value: body.value ?? '',
    expires_at: body.expires_at ?? null,
    config: cfg,
    // 直前セッションの経緯を何行引き継いだか（0なら引き継ぎなし）
    continuity: continuityLines,
  });
}
