// 作業ログ（「N件の作業」）の1行を、人が読める形にする。道具の名前（mcp__dan-tools__browser、Bash など）や
// コマンドの前置き（powershell.exe -Command …）は見せず、何をしたかの種類と短い中身にする（本人、2026-10-03）。
import type { TurnBlock } from './chatTimeline';

export type StepKind = 'command' | 'browser' | 'search' | 'read' | 'edit' | 'desktop' | 'message' | 'image' | 'memory' | 'think' | 'error' | 'other';

export const KIND: Record<StepKind, { label: string; icon: string }> = {
  command: { label: 'コマンド', icon: 'terminal-outline' },
  browser: { label: 'ブラウザ', icon: 'globe-outline' },
  search: { label: '検索', icon: 'search-outline' },
  read: { label: '読む', icon: 'document-text-outline' },
  edit: { label: 'ファイル', icon: 'create-outline' },
  desktop: { label: 'PC操作', icon: 'desktop-outline' },
  message: { label: '送信案', icon: 'paper-plane-outline' },
  image: { label: '画像', icon: 'image-outline' },
  memory: { label: '記録', icon: 'bookmark-outline' },
  think: { label: '考え', icon: 'chatbubble-ellipses-outline' },
  error: { label: '問題', icon: 'alert-circle-outline' },
  other: { label: '道具', icon: 'construct-outline' },
};

const TOOL_KIND: Array<[RegExp, StepKind]> = [
  [/^(Bash|PowerShell)$/, 'command'],
  [/browser|flow$|wait_for$/, 'browser'],
  [/WebSearch|web_search|places|ToolSearch/, 'search'],
  [/^(Read|Grep|Glob)$|WebFetch|read_url|lookup|check_skill|get_location|get_personal_info|get_credentials/, 'read'],
  [/^(Edit|Write|NotebookEdit)$|write_file|edit_file/, 'edit'],
  [/desktop|phone/, 'desktop'],
  [/compose_message|collab_thread|email/, 'message'],
  [/attach_image|image|media/, 'image'],
  [/watch|save_|remember|preference|feed|schedule/, 'memory'],
];

const FRIENDLY: Record<string, string> = {
  attach_image: '画像を添付', compose_message: '送信案を作成', lookup: 'ダンの記録を確認', read_url: 'ページを読む',
  command_center: '別の部屋の作業', get_credentials: 'ログイン情報を取得', save_credentials: 'ログイン情報を保存',
  wait_until: '準備ができるのを待つ', watch: '見張りを設定', wait_for: '表示を待つ', flow: '記憶した手順', desktop: 'PC操作',
  save_totp_secret: '認証アプリの鍵を保存', check_skill: '手順書を確認', WebSearch: 'ウェブ検索', web_search: 'ウェブ検索',
  ToolSearch: '道具を探す', places: '近くの施設を検索', phone: 'スマホ操作', PowerShell: 'コマンド実行',
};

function shortName(name: string) {
  return name.replace(/^mcp__[^_]+(?:-[^_]+)*__/, '');
}

/** The command without the shell's own prefix: `"…\\powershell.exe" -Command 'Get-Content x'` → `Get-Content x`. */
function plainCommand(text: string) {
  return text
    .replace(/^コマンド実行:\s*/, '')
    .replace(/^"?[^"]*powershell(?:\.exe)?"?\s+(?:-NoProfile\s+)?-Command\s+/i, '')
    .replace(/^(["'])([\s\S]*)\1$/, '$2')
    .replace(/^&\s*/, '')
    .trim();
}

export function describe(step: TurnBlock): { kind: StepKind; title: string; detail: string } {
  if (step.type === 'error') return { kind: 'error', title: step.text || 'エラー', detail: '' };
  if (step.type === 'reasoning' || step.type === 'text') return { kind: 'think', title: (step.text || '').trim(), detail: '' };
  const name = shortName(step.name || '');
  const raw = (step.label || '').trim();
  const kind = (TOOL_KIND.find(([re]) => re.test(name || raw)) || [null, 'other'])[1] as StepKind;
  let title = raw && !/^mcp__/.test(raw) && raw !== name ? raw : FRIENDLY[name] || KIND[kind].label;
  let detail = (step.detail || '').trim();
  if (kind === 'command' || /^コマンド実行:/.test(title)) {
    const cmd = plainCommand(detail || title);
    title = 'コマンド実行';
    detail = cmd;
  }
  title = title.replace(/^ブラウザ操作:\s*open_target$/, 'ページを開く').replace(/^WebFetch:\s*/, 'ページを読む: ');
  if (detail === title) detail = '';
  return { kind, title, detail };
}

/** What a group of steps did, for the folded header: kinds with counts, most first. */
export function summarize(steps: TurnBlock[]) {
  const count = new Map<StepKind, number>();
  for (const s of steps) {
    const k = describe(s).kind;
    if (k === 'think') continue;
    count.set(k, (count.get(k) || 0) + 1);
  }
  return [...count.entries()].sort((a, b) => b[1] - a[1]).map(([kind, n]) => ({ kind, n }));
}

export function elapsedLabel(ms: number) {
  const s = Math.max(0, Math.floor(ms / 1000));
  return s < 60 ? `${s}秒` : `${Math.floor(s / 60)}分${String(s % 60).padStart(2, '0')}秒`;
}
