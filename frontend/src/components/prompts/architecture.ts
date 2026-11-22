// ダンの中の構成図（指示文の画面の上の図。2026-11-17 本人「技術的に正しい配置の、上から下に降りていく階層図に、何の場所か分かるイラスト」）。
// 箱と矢印はコードで確かめた呼び出し順だけ。直したら下の「根拠」のファイルも読み直すこと。
//   画面→入口: frontend/src/lib/backend-url.ts（~/.dan/generations/enabled がある時は 9100/8100）、next.config.ts の rewrites
//   入口: scripts/run_gateway.py（9100・8100、app.core.gateway）→ 会話の本体 app.core.main（9000）／道具のサーバー app.sandbox.main（8000）
//   チャットのダン: chat_routes.process_message_cli → cli_runner.build_cmd（claude -p）。決まりは cli_runner._build_system_prompt
//     （USER.md・SOUL.md・RULES.md は bootstrap_context、Done の部屋だけ command_center.room_instructions）
//   通話: voicelog_routes /live/session → voice_live.session_config（GPT-Live の決まり = voice_plain）→ voice_sideband.attach が
//     調べもの係・振り分け・画面係を開く。GPT-Live が任せると（session.delegation.created）voice_router.answer → route（Jev）→ run
//   振り分けの行き先: lookup → voice_lookup（deepseek-flash）、show → voice_stage（gpt-5.4-mini）、迷う・連絡・文書 → luna
//     （voice_responses、gpt-6-luna）、作る・直す → start_chat_dan → command_center.execute(engine='make')
//   作業: command_job_runner.run が make/parallel → parallel_job_runner（Claude Code、部屋の会話を引き継ぐ）、api → api_job_runner
//     （deepseek-flash。判断役の replay_operation など）、それ以外 → Codex（gpt-6-astra）
//   エディター: ダンと制作 = production_asset_routes → timeline_agent → editor_runtime（チャットのダンと同じ決まり＋制作の決まり）。
//     「話す」= editor_assistant_routes /live/session（editor_live、GPT-Live）と /reason（editor_reasoning、gpt-6-astra）
export interface ArchNode {
  id: string;
  name: string;
  model: string;          // 中で動く物（モデル・プログラム）
  line: string;           // 何をする所か（1文）
  icon: string;           // public/prompts/arch/<icon>.webp
  x: number; y: number; w: number;   // 図の中の位置（左上・幅。単位は図の幅 W に対して）
  prompts?: string[];     // この箱が読む指示文（app/prompts/catalog.json の id。skill/* は手順書）
  skills?: boolean;       // 手順書（.claude/skills）もここで読む
  same?: string;          // 自分の文は無く、この箱と同じ決まりを読む
  group?: 'work';
}

export interface ArchEdge {
  from: string; to: string;
  a?: 't' | 'b' | 'l' | 'r'; b?: 't' | 'b' | 'l' | 'r';
  label?: string; dashed?: boolean;
  ax?: number;            // 出る位置（箱の左からの単位）。省くと真ん中
  bx?: number;            // 着く位置（箱の左からの単位）。省くと真ん中
  bend?: number;          // 曲がりの強さ
  at?: number;            // 線の上の札の位置（0=出る所、1=着く所。省くと0.5）
}

export const W = 1000;
export const H = 1040;
export const BOX_H = 78;

export const NODES: ArchNode[] = [
  { id: 'owner', name: 'みきさん', model: 'スマホ・PCのチャット・エディター', icon: 'owner', x: 360, y: 8, w: 280,
    line: '話しかける・頼む・直す。チャットと通話とエディターの画面から。' },
  { id: 'next', name: '画面のサーバー', model: 'Next.js（dan.paina.info）', icon: 'next', x: 360, y: 118, w: 280,
    line: '画面を出し、チャットや通話の要求を入口へ渡す。' },
  { id: 'gateway', name: '入口', model: 'プログラム（9100・8100）', icon: 'gateway', x: 360, y: 228, w: 280,
    line: '要求を、今動いている版の会話の本体・道具のサーバーへ渡す。ダンを入れ替えても会話を切らないための所。' },
  { id: 'core', name: '会話の本体', model: 'プログラム（9000）', icon: 'core', x: 20, y: 346, w: 240,
    line: 'チャットの1通ごとにチャットのダンを起こし、作業の部屋の仕事を回す。' },
  { id: 'sandbox', name: '道具と通話のサーバー', model: 'プログラム（8000）', icon: 'sandbox', x: 380, y: 346, w: 500,
    line: '通話を作って横で聞き、振り分け・調べもの係・画面係を動かす。エディターの裏もここ。' },
  { id: 'chat', name: 'チャットのダン', model: 'Claude Code', icon: 'chat', x: 20, y: 470, w: 240,
    prompts: ['workspace/user', 'workspace/soul', 'workspace/rules', 'code/command-center'], skills: true,
    line: 'チャットで話し、道具を使って作業する。モデルは部屋ごとに決まる。USER・SOUL・RULES は毎回読む。Done の部屋だけ部屋の役目の文も読む。' },
  { id: 'voice', name: '通話のダン', model: 'GPT-Live（OpenAI）', icon: 'voice', x: 300, y: 470, w: 240,
    prompts: ['call/persona', 'call/policies', 'call/editor-place', 'call/router-job-started'],
    line: '声で受け答えする。自分で答えられない頼みは、裏に任せる。' },
  { id: 'editor', name: 'エディターのダンと制作', model: 'Claude Code', icon: 'editor', x: 740, y: 470, w: 240, same: 'chat', skills: true, prompts: ['work/editor-handoff'],
    line: 'エディターで動画を作る・直す。チャットのダンと同じ決まりに、制作の決まり（プログラムの中）を足して読む。' },
  { id: 'router', name: '振り分け', model: 'Jev', icon: 'router', x: 300, y: 594, w: 240,
    prompts: ['call/router-routes', 'call/router-ask', 'call/router-work', 'call/router-reply', 'call/router-calendar', 'call/router-promise-words', 'call/editor-place'],
    line: '通話のダンが任せた頼みを、どこへ回すか一瞬で選ぶ。' },
  { id: 'editorTalk', name: 'エディターの「話す」', model: 'GPT-Live ＋ GPT-6 Astra', icon: 'editorTalk', x: 740, y: 594, w: 240,
    prompts: ['code/editor-live', 'code/editor-reasoning', 'code/editor-conversation'],
    line: 'エディターで指した所を、声で直す。' },
  { id: 'lookup', name: '調べもの係', model: 'DeepSeek', icon: 'lookup', x: 440, y: 744, w: 160,
    prompts: ['call/lookup-instructions'],
    line: '通話を止めずに、裏で調べる・記憶やメールを読む。' },
  { id: 'stage', name: '画面係', model: 'GPT-5.4 mini', icon: 'stage', x: 615, y: 744, w: 170,
    prompts: ['call-code/stage-instructions', 'call-code/stage-flow-message', 'call-code/stage-flow-doc', 'call-code/stage-flow-assist', 'call-code/stage-flow-media'],
    line: '通話中に見せる画面（写真・地図・下書き）を描く。' },
  { id: 'backend', name: '判断役', model: 'GPT-6 Luna', icon: 'backend', x: 800, y: 744, w: 180,
    prompts: ['call/backend-instructions', 'call/backend-plain-rules', 'call/backend-background-rules', 'call/luna-rules', 'call-code/backend-tools', 'call-code/backend-background-lines', 'call/editor-place'],
    line: '迷う頼み・連絡・文書を、道具を使って判断し、下書きを書く（OpenAI のモデル）。' },
  { id: 'parallel', name: '並行作業', model: 'Claude Code', icon: 'parallel', x: 355, y: 916, w: 290, group: 'work',
    prompts: ['work/parallel-job-rules', 'work/confirmation-rule', 'call/call-job-note', 'call/editor-call-note', 'work/editor-handoff', 'call/voice-task', 'call/make-origin-note'], same: 'chat',
    line: '頼んだ部屋の会話を引き継いだ別のダンが、時間のかかる制作・調べものをする。起こすのはチャットのダン（並行作業の道具）と、振り分け（作る・直す）。' },
  { id: 'codex', name: '別の部屋への頼み', model: 'Codex（GPT-6 Astra）', icon: 'codex', x: 30, y: 916, w: 290, group: 'work',
    prompts: ['work/codex-job-rules', 'work/confirmation-rule', 'work/relay-header'],
    line: 'チャットのダンが別の部屋に頼んだ作業。結果はその部屋に「〇〇からの報告」で届く。' },
  { id: 'api', name: '手順の再生', model: 'DeepSeek', icon: 'api', x: 680, y: 916, w: 290, group: 'work',
    prompts: ['work/api-job-instructions', 'work/confirmation-rule', 'work/relay-header'],
    line: '判断役が起こす、一度やった手順の再生などの短い手続き。' },
];

// 作業の部屋の枠（中の3つを囲む）
export const WORK_FRAME = { x: 14, y: 880, w: 972, h: 126, name: '作業の部屋',
  line: '終わると、通話中ならその通話で声で、そうでなければ頼んだ部屋のチャットへ報告する。' };

export const EDGES: ArchEdge[] = [
  { from: 'owner', to: 'next' },
  { from: 'next', to: 'gateway' },
  { from: 'gateway', to: 'core', label: 'チャット', ax: 70 },
  { from: 'gateway', to: 'sandbox', label: '通話・エディター・道具', ax: 220 },
  { from: 'core', to: 'chat', label: '1通ごとに起こす' },
  { from: 'owner', to: 'voice', a: 'l', b: 'l', dashed: true, label: '声はOpenAIへ直接', bend: 70 },
  { from: 'sandbox', to: 'voice', label: '通話を作り、横で聞く', ax: 90 },
  { from: 'sandbox', to: 'editor', ax: 440 },
  { from: 'sandbox', to: 'editorTalk', a: 'r', b: 'r', bend: 40 },
  { from: 'voice', to: 'router', label: '任せる' },
  { from: 'router', to: 'lookup', label: '調べる' },
  { from: 'router', to: 'stage', label: '見せる' },
  { from: 'router', to: 'backend', label: '迷う・連絡・文書' },
  { from: 'router', to: 'parallel', label: '作る・直す', ax: 40, bx: 90, bend: 110, at: 0.62 },
  { from: 'chat', to: 'parallel', label: '並行作業', ax: 200, bx: 40, at: 0.55 },
  { from: 'chat', to: 'codex', label: '別の部屋へ頼む', ax: 120, bx: 110, at: 0.6 },
  { from: 'backend', to: 'api', label: '手順の再生', ax: 90, bx: 210 },
];
