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
//   エディター: ダンと制作 = 作品ごとの隠れた部屋のふつうのチャット（editor-dan-chat.tsx → ProjectChatPanel、editor_rooms）。
//     cli_runner が attach_timeline_tools で timeline の道具を足す。editor_runtime（制作の決まり・Codex）は「ダンに指示」クリップの実行
//     （production-workspace の requestDanEdit → dan_revise → timeline_agent）だけ。Windows 版の画面の「話す」=
//     editor_assistant_routes /live/session（editor_live）と /reason（editor_reasoning）。Mac の画面版の「話す」はふつうの通話。
//   動画を作る・直す時の枝（VIDEO_*）の根拠は、各箱の programs と facts に書いた。
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
  programs?: { path: string; what: string }[];   // この箱で動くプログラム（読むだけ。押しても開かない）
  facts?: string[];       // コードで確かめた、この箱の動き方（無い物・条件も書く）
  video?: boolean;        // 下の枝「動画を作る・直す時」へ降りる札を付ける
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
export const H = 1320;
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
  { id: 'chat', name: 'チャットのダン', model: 'Claude Code', icon: 'chat', x: 20, y: 470, w: 240, video: true,
    prompts: ['workspace/user', 'workspace/soul', 'workspace/rules', 'code/command-center'], skills: true,
    line: 'チャットで話し、道具を使って作業する。モデルは部屋ごとに決まる。USER・SOUL・RULES は毎回読む。Done の部屋だけ部屋の役目の文も読む。' },
  { id: 'voice', name: '通話のダン', model: 'GPT-Live（OpenAI）', icon: 'voice', x: 300, y: 470, w: 240,
    prompts: ['call/persona', 'call/policies', 'call/editor-place', 'call/router-job-started'],
    line: '声で受け答えする。自分で答えられない頼みは、裏に任せる。' },
  { id: 'editor', name: 'エディターのダンと制作', model: '部屋のモデル（チャットと同じ）', icon: 'editor', x: 740, y: 470, w: 240, same: 'chat', skills: true, video: true, prompts: ['work/editor-handoff'],
    line: '作品ごとの隠れた部屋の、ふつうのチャット。チャットのダンと同じ決まりで動き、その作品のタイムラインの道具が足される。' },
  { id: 'router', name: '振り分け', model: 'Jev', icon: 'router', x: 300, y: 688, w: 240,
    prompts: ['call/router-routes', 'call/router-ask', 'call/router-work', 'call/router-reply', 'call/router-calendar', 'call/router-promise-words', 'call/editor-place'],
    line: '通話のダンが任せた頼みを、どこへ回すか一瞬で選ぶ。' },
  { id: 'editorTalk', name: 'エディターの「話す」', model: 'GPT-Live ＋ GPT-6 Astra', icon: 'editorTalk', x: 740, y: 688, w: 240,
    prompts: ['code/editor-live', 'code/editor-reasoning', 'code/editor-conversation'],
    line: 'Windows 版の画面のエディターで、指した所を声で直す。Mac の画面版エディターの「話す」はふつうの通話で、振り分けから作品の部屋の並行作業へ回る。' },
  { id: 'lookup', name: '調べもの係', model: 'DeepSeek', icon: 'lookup', x: 440, y: 924, w: 160,
    prompts: ['call/lookup-instructions'],
    line: '通話を止めずに、裏で調べる・記憶やメールを読む。' },
  { id: 'stage', name: '画面係', model: 'GPT-5.4 mini', icon: 'stage', x: 615, y: 924, w: 170,
    prompts: ['call-code/stage-instructions', 'call-code/stage-flow-message', 'call-code/stage-flow-doc', 'call-code/stage-flow-assist', 'call-code/stage-flow-media'],
    line: '通話中に見せる画面（写真・地図・下書き）を描く。' },
  { id: 'backend', name: '判断役', model: 'GPT-6 Luna', icon: 'backend', x: 800, y: 924, w: 180,
    prompts: ['call/backend-instructions', 'call/backend-plain-rules', 'call/backend-background-rules', 'call/luna-rules', 'call-code/backend-tools', 'call-code/backend-background-lines', 'call/editor-place'],
    line: '迷う頼み・連絡・文書を、道具を使って判断し、下書きを書く（OpenAI のモデル）。' },
  { id: 'parallel', name: '並行作業', model: '部屋の作業用モデル', icon: 'parallel', x: 355, y: 1096, w: 290, group: 'work', video: true,
    prompts: ['work/parallel-job-rules', 'work/confirmation-rule', 'call/call-job-note', 'call/editor-call-note', 'work/editor-handoff', 'call/voice-task', 'call/make-origin-note'], same: 'chat',
    line: '頼んだ部屋の会話を引き継いだ別のダンが、時間のかかる制作・調べものをする。起こすのはチャットのダン（並行作業の道具）と、振り分け（作る・直す）と、エディターのタイムラインに置いたピン・ペン・枠の指示。' },
  { id: 'codex', name: '別の部屋への頼み', model: 'Codex（GPT-6 Astra）', icon: 'codex', x: 30, y: 1096, w: 290, group: 'work',
    prompts: ['work/codex-job-rules', 'work/confirmation-rule', 'work/relay-header'],
    line: 'チャットのダンが別の部屋に頼んだ作業。結果はその部屋に「〇〇からの報告」で届く。' },
  { id: 'api', name: '手順の再生', model: 'DeepSeek', icon: 'api', x: 680, y: 1096, w: 290, group: 'work',
    prompts: ['work/api-job-instructions', 'work/confirmation-rule', 'work/relay-header'],
    line: '判断役が起こす、一度やった手順の再生などの短い手続き。' },
];

// 作業の部屋の枠（中の3つを囲む）
export const WORK_FRAME = { x: 14, y: 1060, w: 972, h: 216, name: '作業の部屋',
  line: '終わると、通話中ならその通話で声で、そうでなければ頼んだ部屋のチャットへ報告する。' };

export const EDGES: ArchEdge[] = [
  { from: 'owner', to: 'next' },
  { from: 'next', to: 'gateway' },
  { from: 'gateway', to: 'core', label: 'チャット', ax: 70 },
  { from: 'gateway', to: 'sandbox', label: '通話・エディター・道具', ax: 220 },
  { from: 'core', to: 'chat', label: '1通ごとに起こす' },
  { from: 'owner', to: 'voice', a: 'l', b: 'l', dashed: true, label: '声はOpenAIへ直接', bend: 70 },
  { from: 'sandbox', to: 'voice', label: '通話を作り、横で聞く', ax: 90 },
  { from: 'sandbox', to: 'editor', ax: 440, label: '作品・タイムライン', at: 0.7 },
  { from: 'core', to: 'editor', a: 'r', b: 'l', label: '作品の部屋の会話', bend: 60, at: 0.8 },
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

// ---- 動画を作る・直す時（構成図の「チャットのダン」「エディターのダンと制作」「並行作業」から降りる枝）----
// 2026-11-23 本人「動画の作成や編集がチャットのダンや並行作業に届いて、その後にどういうスキルやコンポーネントがあって、それをどう
// 読み込んでいるからこうなっている。だからここを直せばいいんじゃないかってことが分かるページ」。箱と矢印は11/23にコードで確かめた順。
// 仕組みを変えたら、ここの programs・facts も直すこと。
export const VIDEO_W = 1000;
export const VIDEO_H = 1190;

export const VIDEO_NODES: ArchNode[] = [
  { id: 'v-owner', name: 'みきさん', model: 'チャット・エディター・通話', icon: 'owner', x: 360, y: 8, w: 280,
    line: '動画を作って・直して、と頼む。頼む場所で、下の4つのどれに届くかが決まる。' },
  { id: 'v-chat', name: 'チャットのダン', model: '部屋のモデル', icon: 'chat', x: 50, y: 160, w: 215, same: 'chat',
    line: 'ふだんのチャットで頼んだ時。',
    facts: ['作品の名前が話に出た時・その部屋の作品をエディターで開いている時（10分以内）だけ、タイムラインの道具が付く。それ以外の会話では、タイムラインを直接は触れない。'],
    programs: [{ path: 'app/api/chat_routes.py', what: '1通ごとに、話に出た作品を探して（_auto_timeline_refs）チャットのダンを起こす。' }] },
  { id: 'v-editor', name: 'エディターのダンと制作', model: '部屋のモデル', icon: 'editor', x: 285, y: 160, w: 215, same: 'chat',
    line: 'エディターの中の会話で頼んだ時。作品ごとの隠れた部屋で、中身はふつうのチャット。',
    facts: ['この部屋では、開いている作品のタイムラインの道具がいつも付く。', '画面に「タイムラインから送った指示の一覧」と「今のタイムラインの様子」が足される。'],
    programs: [{ path: 'app/services/editor_rooms.py', what: '作品ごとの部屋を作り、元の部屋のモデルを引き継ぐ。' }, { path: 'app/services/editor_instructions.py', what: 'room_work_text でピン・ペンの指示の履歴を会話に足す。' }] },
  { id: 'v-parallel', name: '並行作業', model: '部屋の作業用モデル', icon: 'parallel', x: 520, y: 160, w: 215, same: 'parallel',
    line: 'タイムラインのピン・ペン・枠で指示した時と、通話で「作って・直して」と言った時。作品の部屋の会話を引き継いだ別のダンが動く。',
    facts: ['ピン・ペン・枠は、1つの指示ごとに並行作業が1つ起きる。指示した区間・場所・印を付けたコマの絵が依頼に付く。', '通話からは、振り分けが「作る・直す」と決めた時。エディターから話していれば、その時の再生位置と指した所が付く。', '終わると部屋のダンが起こされ、結果を短く返す（エディターの指示は会話に出さない）。'],
    programs: [{ path: 'app/services/editor_instructions.py', what: 'ピン・ペン・枠の指示を依頼の文にして、並行作業を起こす。' }, { path: 'app/services/voice_router.py', what: '通話の「作る・直す」を、作品の部屋の並行作業にする。' }, { path: 'app/services/parallel_job_runner.py', what: '部屋の会話を引き継いで起こし、タイムラインの道具を付け、終わったら部屋へ返す。' }] },
  { id: 'v-codex', name: '「ダンに指示」の実行', model: 'Codex（GPT-6 Astra）', icon: 'codex', x: 755, y: 160, w: 215,
    line: 'タイムラインに置いた「ダンに指示」のクリップを実行した時だけ。ほかの3つと違い、制作の決まりを足して読む。',
    programs: [{ path: 'frontend/src/components/production/production-workspace.tsx', what: 'requestDanEdit が直しの仕事（dan_revise）を作る。' }, { path: 'app/services/timeline_agent.py', what: '仕事の担当を起こし、選んだクリップ・メモ・作品の流れを依頼に付ける。' }, { path: 'app/services/editor_runtime.py', what: 'チャットのダンと同じ決まりに、右の制作の決まりを足して Codex に渡す。' }] },

  { id: 'v-rules', name: 'チャットのダンと同じ決まり', model: '毎回、決まりの頭に入る', icon: 'v-rules', x: 50, y: 320, w: 685,
    prompts: ['workspace/user', 'workspace/soul', 'workspace/rules', 'work/parallel-job-rules', 'work/confirmation-rule', 'work/editor-handoff'],
    line: 'USER・SOUL・RULES と、並行作業なら並行作業の決まり。動画のためだけの決まりは、ここには無い。',
    facts: ['決まりの中に、手順書（スキル）全部の名前と1行の説明の一覧が入る。動画の手順書の中身は、ここではまだ読まれない。'],
    programs: [{ path: 'app/agent/cli_runner.py', what: '_build_system_prompt が決まりを組み立てる。スキルの一覧もここで入る。' }] },
  { id: 'v-prod', name: '制作の決まり', model: 'プログラムの中（読むだけ）', icon: 'v-rules', x: 755, y: 320, w: 215,
    prompts: ['code/editor-runtime-notes', 'code/editor-production-budget', 'code/editor-production-authority', 'code/editor-execution-contract', 'code/editor-creative-direction', 'code/editor-first-artifact', 'code/editor-film-plan'],
    line: '「ダンに指示」の実行だけが読む7つの文（約5,600字）。チャットのダン・エディターの会話・並行作業は読まない。' },

  { id: 'v-skills', name: '手順書を選んで開く', model: 'ダンが一覧から選ぶ', icon: 'v-skills', x: 50, y: 480, w: 440,
    prompts: ['skill/talking-demo-editing', 'skill/video-draft', 'skill/explainer-video', 'skill/post-production', 'skill/video-direction', 'skill/creative-studio', 'skill/popout', 'skill/studio', 'skill/talk-script', 'skill/media-gen'],
    line: 'ダンが「動画の頼みだ」と判断したら、一覧から合う手順書を選んで check_skill で開く。',
    facts: ['自動で開かれる手順書は無い。開くかどうか・どれを開くかはダンの判断。開かずに作り始めることもできる。', '例外は「/スキル名」と打った時だけで、その時は手順書の本文が頼みに付く。', '話す人の動画は talking-demo-editing。開くと手順書の本文は返るが、案件の決まり（references/）は返らない。'],
    programs: [{ path: 'app/agent/v2/tools.py', what: 'check_skill。.claude/skills の手順書を返す（この画面で直した版があればそちら）。' }] },
  { id: 'v-home', name: 'Claude Code の本体の棚', model: '~/.claude/skills', icon: 'v-skills', x: 520, y: 480, w: 215,
    line: 'HyperFrames（8本）・media-use・motion-graphics・product-launch-video の11本。部屋のモデルが Claude Code の時だけ、Claude Code の Skill の道具で開ける。',
    facts: ['上の一覧には載らず、この画面でも読めない。Codex の部屋では使えない。'] },

  { id: 'v-cases', name: '案件の決まり', model: '手順書が「読め」と書いている', icon: 'v-skills', x: 50, y: 630, w: 440,
    prompts: ['skill/talking-demo-editing/references/suya-youtube', 'skill/talking-demo-editing/references/pornanti-line-gift', 'skill/talking-demo-editing/references/nakamura-line-gift', 'skill/talking-demo-editing/references/new-attack-video', 'skill/talk-script/references/youtube-video', 'skill/talk-script/references/line-gift-video', 'skill/talk-script/references/launch-video'],
    line: 'スヤさん・ポルノアンチ・中村さん・新アタックの好みと、過去の指摘。手順書の「始める前に読む」を見て、ダンが自分で読みに行く。',
    facts: ['読みに行くかどうかもダンの判断。読んだかを確かめるのは、動画を貼る時の関所だけ（手順書の見出しは確かめるが、案件の決まりまでは確かめない）。'] },

  { id: 'v-parts', name: '素材と部品', model: 'その都度ダンが選ぶ', icon: 'v-parts', x: 50, y: 790, w: 290,
    line: 'タイムラインに置く物。撮った映像・制作ライブラリの素材・AIで作る絵と映像・Envato・After Effects・HyperFrames。',
    facts: ['Envato・After Effects・HyperFrames には決まった道具が無い。手順書と記憶を見て、ダンがブラウザやスクリプトでその都度動かす。', '制作の方法の一覧は5つ（production_methods）。部品の棚（71個）・見せ方の型（6個）・参考の棚（37個）は Windows 版の「話す」からしか引けない。', '11/22 に試した「見せ方の棚」（人気動画30場面）は、試しの中だけで本番の作業には入っていない。'],
    programs: [{ path: 'scripts/production_library.py', what: '制作ライブラリの素材と作品を探す・登録する・サムネを作る。' }, { path: 'app/timeline_mcp_server.py', what: 'generate_image・generate_video・import_media で素材をタイムラインへ入れる。' }, { path: 'docs/production-methods.json', what: '制作の方法5つと、確かめ済みかどうか。' }] },
  { id: 'v-timeline', name: 'タイムラインの道具', model: '57個（mcp__timeline__）', icon: 'v-tltools', x: 365, y: 790, w: 290,
    line: 'クリップを置く・切る・動かす・字幕・音・範囲の効果。1手ごとに形を確かめて、みきさんの画面へすぐ出す。',
    facts: ['どの入口でも、同じ道具の箱（timeline_mcp_server.py）を使う。', '道具を使わず、ダンがその場で書いたプログラムで作品を書き換えることもできてしまう（11/22 の棚の試しの②はこれで、手順書の確かめを通らなかった）。'],
    programs: [{ path: 'app/timeline_mcp_server.py', what: '57個の道具の入口。' }, { path: 'app/services/timeline_commands.py', what: 'タイムラインを変える1手ずつの処理。' }, { path: 'app/services/timeline_draft.py', what: '下書きを持ち、1手ごとに画面へ出し、最後に作品へ保存する。' }] },
  { id: 'v-frames', name: 'コマを見る・書き出す', model: 'ダンが時刻を選ぶ', icon: 'v-frames', x: 680, y: 790, w: 290,
    line: '好きな時刻のコマを絵にする・一部だけ書き出す・書き出した動画を Gemini に見せる。',
    facts: ['切れ目と、重ねた絵・字幕の切り替えを全部数えて見るプログラムは無い。どの時刻を見るかはダンが選ぶ（11/22 の②はここで2コマしか見ず、ぶつっと切れたのを見落とした）。'],
    programs: [{ path: 'app/services/sequence_window.py', what: 'タイムラインの好きな時刻のコマ・区間を書き出す。' }, { path: 'app/services/timeline_context.py', what: 'render_frame の道具。Mac では sequence_window を使う。' }, { path: 'app/api/production_asset_routes.py', what: '_render_sequence_job。export_timeline・watch_render の書き出し。' }] },

  { id: 'v-gate', name: '返事の前の関所', model: 'チャットの番の終わりに動く', icon: 'v-gate', x: 50, y: 950, w: 420,
    line: '30秒以上の動画をチャットに貼る番だけ、2つを確かめ、足りなければ返事を止めて差し戻す。',
    facts: ['1. 動画の手順書のどれか1つを、見出しまで全部読んだか。', '2. 前に動画を出してからのみきさんの発言を、指摘として記録したか。', '同じ理由で止めるのは2回まで。エディターの部屋で動画を貼らない番は止めず、裏で指摘を拾う。', '「ダンに指示」の実行（Codex）には、この関所は掛からない。'],
    programs: [{ path: 'scripts/hook_video_feedback_gate.py', what: 'Claude Code の番の終わり（Stop）に動く関所。' }] },
  { id: 'v-show', name: 'みきさんに見せる', model: 'エディター・チャット', icon: 'v-show', x: 500, y: 950, w: 470,
    line: 'タイムラインは直すたびにみきさんのエディターに出る。チャットには、押すとエディターで開くサムネを返す。',
    facts: ['並行作業の結果は、部屋のダンが起こされて短く返す。エディターのピン・ペンの指示の結果は、会話には出さない。'],
    programs: [{ path: 'scripts/production_library.py', what: 'thumb で、作品をエディターで開くサムネを作る。' }] },

  { id: 'v-learn', name: '指摘から手順書を育てる', model: '裏の並行作業（1日3回まで）', icon: 'v-learn', x: 50, y: 1090, w: 600,
    prompts: ['skill/talking-demo-editing/learning', 'skill/talking-demo-editing/sources/generalization-log'],
    line: 'みきさんの指摘を記録すると、裏の作業が案件の決まりを書き足す。2つ以上の案件で同じ失敗が出た時だけ、手順書の本文に上げる。',
    facts: ['記録は ~/.dan/video-learning/ledger.json。書き足した後、前と後を伏せて比べてから本番に入れる。', '案件の決まりだけの直しは references/ と記録だけ触れる。手順書の本文の直しには、別の案件での比べが要る。'],
    programs: [{ path: 'scripts/video_learning.py', what: 'record（指摘を記録）・sweep（会話から指摘を拾う）・complete（作業の終わり）。' }, { path: 'app/services/video_learning.py', what: '記録し、育てる作業を起こす（同時に1つ・1日3回まで）。' }] },
];

export const VIDEO_EDGES: ArchEdge[] = [
  { from: 'v-owner', to: 'v-chat', label: 'チャットで', ax: 30 },
  { from: 'v-owner', to: 'v-editor', label: 'エディターの会話で', ax: 110 },
  { from: 'v-owner', to: 'v-parallel', label: 'ピン・ペン・通話で', ax: 180 },
  { from: 'v-owner', to: 'v-codex', label: '「ダンに指示」を実行', ax: 250 },
  { from: 'v-chat', to: 'v-rules', bx: 107 },
  { from: 'v-editor', to: 'v-rules', bx: 342 },
  { from: 'v-parallel', to: 'v-rules', bx: 577 },
  { from: 'v-codex', to: 'v-prod' },
  { from: 'v-rules', to: 'v-skills', ax: 220, label: 'check_skill で開く' },
  { from: 'v-rules', to: 'v-home', ax: 577, dashed: true, label: 'Claude Code の時だけ' },
  { from: 'v-skills', to: 'v-cases', label: '「始める前に読む」' },
  { from: 'v-cases', to: 'v-timeline', ax: 380, bx: 90, label: '手順どおりに組む' },
  { from: 'v-prod', to: 'v-timeline', ax: 60, bx: 250, label: 'タイムラインの道具で直接', at: 0.4 },
  { from: 'v-parts', to: 'v-timeline', a: 'r', b: 'l' },
  { from: 'v-timeline', to: 'v-frames', a: 'r', b: 'l' },
  { from: 'v-frames', to: 'v-gate', ax: 150, bx: 300, label: 'チャットに動画を貼る時', at: 0.55 },
  { from: 'v-gate', to: 'v-show', a: 'r', b: 'l' },
  { from: 'v-show', to: 'v-learn', ax: 150, bx: 480, label: 'みきさんの指摘' },
  { from: 'v-learn', to: 'v-cases', a: 'l', b: 'l', dashed: true, bend: 34, label: '書き足す', at: 0.5 },
];
