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
//   動画を作る・直す時の枝（VIDEO_*）の根拠は facts に書いた（ファイル名は git の履歴の 2026-11-28 より前の programs）。
// 2026-11-28 本人「コードとか実装とかは全部外そう。また後から必要になったタイミングで追加すれば良い」: 箱の中身にファイル名・
//   番号・英語の名前を出さない。裏方の4つ（画面のサーバー・入口・会話の本体・道具と通話のサーバー）は「ダンの本体」1つにまとめた。
export interface ArchNode {
  id: string;
  name: string;
  model: string;          // 中で動く物（モデル・プログラム）
  line: string;           // 何をする所か（1文）
  icon: string;           // public/prompts/arch/<icon>.webp
  height?: number;
  x: number; y: number; w: number;   // 図の中の位置（左上・幅。単位は図の幅 W に対して）
  prompts?: string[];     // この箱が読む指示文（app/prompts/catalog.json の id。skill/* は手順書）
  skills?: boolean;       // 手順書（.claude/skills）もここで読む
  same?: string;          // 自分の文は無く、この箱と同じ決まりを読む
  group?: 'work';
  facts?: string[];       // この箱の動き方（無い物・条件も書く）。みきさんに見える。ファイル名・番号・英語の名前は書かない
  video?: boolean;        // 下の枝「動画を作る・直す時」へ降りる札を付ける
  cutout?: boolean;       // 形どおりに切り抜いた絵（枠も角丸も付けない）
}

export interface ArchEdge {
  from: string; to: string;
  a?: 't' | 'b' | 'l' | 'r'; b?: 't' | 'b' | 'l' | 'r';
  label?: string; dashed?: boolean;
  ax?: number;            // 出る位置（上下の辺なら箱の左から、左右の辺なら箱の上からの単位）。省くと真ん中
  bx?: number;            // 着く位置（同上）。省くと真ん中
  at?: number;            // 線の上の札の位置（0=出る所、1=着く所。省くと0.5）
  via?: [number, number][];   // 通る点（図の単位）。無ければ箱の辺から直角に曲がって結ぶ
}

export const BOX_H = 78;

// 2026-11-28 に「ダンの本体」1つにまとめた裏方の4つの古い id（前に出した直す案・地図を開くリンクが指していても、まとめた箱を開く）
export const NODE_ALIAS: Record<string, string> = { next: 'base', gateway: 'base', core: 'base', sandbox: 'base' };

export const NODES: ArchNode[] = [
  { id: 'owner', name: 'みきさん', model: 'PC・スマホ・エディター・ピンから', icon: 'miki-person', height: 206, x: 0, y: 206, w: 184, cutout: true,
    line: '話しかける・頼む・直す。PC・スマホ・エディター・胸元のピンから。' },
  { id: 'pc', name: 'PC', model: 'ブラウザのダン', icon: 'chat-pc', height: 128, x: 202, y: 24, w: 150,
    line: 'PC のブラウザでダンを開く。入力欄で文字を送るか、横の電話マークで通話する。'},
  { id: 'phone', name: 'スマホ', model: 'ダンのアプリ', icon: 'chat-phone', height: 136, x: 214, y: 168, w: 126,
    line: 'スマホのアプリでダンを開く。文字を送るか、電話マークで通話する。'},
  { id: 'editor-ui', name: 'エディター', model: '作品とタイムライン', icon: 'editor-screen', height: 120, x: 202, y: 322, w: 150,
    line: '作品を開き、横の「ダンと制作」の会話で頼むか、「話す」で声で頼む。PC でもスマホでも同じ画面。' },
  { id: 'pin', name: 'ダンピン', model: '胸元に付ける', icon: 'pin-cut', height: 120, x: 208, y: 462, w: 138, cutout: true,
    line: '胸元のピンを押して話すと、つないだスマホのアプリが通話を始める。ピンには文字の入口は無い。'},
  { id: 'devices', name: 'チャット', model: '文字で頼む', icon: 'chat', x: 420, y: 196, w: 152,
    line: 'PC・スマホ・エディターの会話から、文字で依頼を送り、同じ所で返事を読む。' },
  { id: 'audio', name: '音声', model: '声で頼む', icon: 'voice', x: 420, y: 560, w: 152,
    line: 'PC・スマホの電話マーク、エディターの「話す」、ピンから。マイクの声を通話のダンに送り、声の返事を聞く。' },
  { id: 'reply', name: '届いた返事', model: 'チャット・通話', icon: 'chat', x: 1870, y: 285, w: 230,
    line: '選んだ依頼に対してダンが実際に返した言葉。' },
  { id: 'skills', name: 'スキルの手順書', model: '全文・参考ページ', icon: 'v-skills', x: 1340, y: 1000, w: 235,
    line: 'ダンが仕事に使う手順書を検索し、読んで編集する。' },
  { id: 'base', name: 'ダンの本体', model: '家の Mac mini の中', icon: 'core', x: 760, y: 330, w: 230,
    line: 'みきさんが文字や声で頼んだことを受け取り、チャットのダン・通話のダンへ運ぶ。',
    facts: ['画面を届ける: dan.paina.info を開いた時に、チャット欄やエディターの画面を出し、送った文字を受け取る。ここが止まると画面が開かない（「502」と出るのはここが返事をしない時）。',
      '中継する: 受け取った頼みを、今動いている版のダンへ渡す。ダンを新しい版に入れ替えても、会話が途中で切れないようにするため。',
      'チャットの係: チャットが1通届くたびに、チャットのダンを起こす。チャットの返事が来ない時は、ここが原因のことがある。',
      '通話の係: 通話を始める準備をし、通話を横で聞いて、振り分け・調べもの係・画面係を動かす。通話の頼みが届かない時は、ここが原因のことがある。'] },
  { id: 'chat', name: 'チャットのダン', model: '部屋で選んだモデル', icon: 'chat', x: 1340, y: 24, w: 210, video: true,
    prompts: ['workspace/user', 'workspace/soul', 'workspace/rules', 'code/command-center'], skills: true,
    line: 'チャットで話し、道具を使って作業する。モデルは部屋ごとに決まる。USER・SOUL・RULES は毎回読む。Done の部屋だけ部屋の役目の文も読む。' },
  { id: 'voice', name: '通話のダン', model: 'GPT-Live（OpenAI）', icon: 'voice', x: 1340, y: 560, w: 210,
    prompts: ['call/persona', 'call/policies', 'call/editor-place', 'call/router-job-started'],
    line: '声で受け答えする。自分で答えられない頼みは、裏に任せる。' },
  { id: 'editor', name: 'エディターのダンと制作', model: '部屋のモデル（チャットと同じ）', icon: 'editor', x: 1340, y: 240, w: 210, same: 'chat', skills: true, video: true, prompts: ['work/editor-handoff', 'work/editor-clip-comment'],
    line: '作品ごとの隠れた部屋の、ふつうのチャット。チャットのダンと同じ決まりで動き、その作品のタイムラインの道具が足される。' },
  { id: 'router', name: '振り分け', model: 'Jev', icon: 'router', x: 1620, y: 560, w: 181,
    prompts: ['call/router-model', 'call/router-threshold', 'call/router-look-ask', 'call/router-look', 'call/router-routes', 'call/router-ask', 'call/router-work', 'call/router-reply', 'call/router-calendar', 'call/router-promise-words', 'call/editor-place'],
    line: '通話のダンが任せた頼みを、どこへ回すか一瞬で選ぶ。' },
  { id: 'editorTalk', name: 'エディターの「話す」', model: 'GPT-Live ＋ GPT-6 Astra', icon: 'editorTalk', x: 1080, y: 900, w: 210,
    prompts: ['code/editor-live', 'code/editor-reasoning', 'code/editor-conversation'],
    line: 'Windows 版の画面のエディターで、指した所を声で直す。Mac の画面版エディターの「話す」はふつうの通話で、振り分けから作品の部屋の並行作業へ回る。' },
  { id: 'lookup', name: '調べもの係', model: 'DeepSeek', icon: 'lookup', x: 1870, y: 560, w: 188,
    prompts: ['call/lookup-instructions'],
    line: '通話を止めずに、裏で調べる・記憶やメールを読む。' },
  { id: 'stage', name: '画面係', model: 'GPT-5.4 mini', icon: 'stage', x: 1870, y: 680, w: 188,
    prompts: ['call-code/stage-instructions', 'call-code/stage-flow-message', 'call-code/stage-flow-doc', 'call-code/stage-flow-assist', 'call-code/stage-flow-media'],
    line: '通話中に見せる画面（写真・地図・下書き）を描く。' },
  { id: 'backend', name: '判断役', model: 'GPT-6 Luna', icon: 'backend', x: 1870, y: 800, w: 188,
    prompts: ['call/backend-instructions', 'call/backend-plain-rules', 'call/backend-background-rules', 'call/luna-rules', 'call-code/backend-tools', 'call-code/backend-background-lines', 'call/editor-place'],
    line: '迷う頼み・連絡・文書を、道具を使って判断し、下書きを書く（OpenAI のモデル）。' },
  { id: 'parallel', name: '並行作業', model: '部屋の作業用モデル', icon: 'parallel', x: 2140, y: 210, w: 228, group: 'work', video: true,
    prompts: ['work/parallel-job-rules', 'work/confirmation-rule', 'call/call-job-note', 'call/editor-call-note', 'work/editor-handoff', 'call/voice-task', 'call/make-origin-note'], same: 'chat',
    line: '頼んだ部屋の会話を引き継いだ別のダンが、時間のかかる制作・調べものをする。起こすのはチャットのダン（並行作業の道具）と、振り分け（作る・直す）と、エディターのタイムラインに置いたピン・ペン・枠の指示。' },
  { id: 'codex', name: '別の部屋への頼み', model: 'Codex（GPT-6 Astra）', icon: 'codex', x: 2140, y: 24, w: 228, group: 'work',
    prompts: ['work/codex-job-rules', 'work/confirmation-rule', 'work/relay-header'],
    line: 'チャットのダンが別の部屋に頼んだ作業。結果はその部屋に「〇〇からの報告」で届く。' },
  { id: 'api', name: '手順の再生', model: 'DeepSeek', icon: 'api', x: 2140, y: 800, w: 228, group: 'work',
    prompts: ['work/api-job-instructions', 'work/confirmation-rule', 'work/relay-header'],
    line: '判断役が起こす、一度やった手順の再生などの短い手続き。' },
];

// 作業の部屋の枠（中の3つを囲む）
export const WORK_FRAME = { x: 2110, y: 6, w: 290, h: 896, name: '作業の部屋',
  line: '終わると通話か、頼んだ部屋に結果が届く。' };

// 線は左から右へ。上の段がチャット（文字）、下の段が音声（声）。2026-11-24 本人「PC・スマホ・エディター・ピン → チャットと音声に
// 集約して次に進む。それ以降も無駄なく辻褄が合うように」。線は箱の裏を通さない（via で箱の間を通す）。
export const EDGES: ArchEdge[] = [
  { from: 'owner', to: 'pc' },
  { from: 'owner', to: 'phone' },
  { from: 'owner', to: 'editor-ui' },
  { from: 'owner', to: 'pin' },
  // 入口の端末 → チャット（文字）と音声（声）。ピンは声だけ。
  // 文字の線は x=380、声の線は x=400 の幹にまとめてから、チャット・音声に入る
  { from: 'pc', to: 'devices', ax: 50, via: [[380, 74], [380, 235]] },
  { from: 'phone', to: 'devices', ax: 50, via: [[380, 218], [380, 235]] },
  { from: 'editor-ui', to: 'devices', ax: 40, label: 'ダンと制作', at: 0.3, via: [[380, 362], [380, 235]] },
  { from: 'pc', to: 'audio', ax: 80, via: [[400, 104], [400, 599]] },
  { from: 'phone', to: 'audio', ax: 85, via: [[400, 253], [400, 599]] },
  { from: 'editor-ui', to: 'audio', ax: 75, label: '話す', at: 0.12, via: [[400, 397], [400, 599]] },
  { from: 'pin', to: 'audio', ax: 60, label: 'スマホ経由', at: 0.2, via: [[400, 522], [400, 599]] },
  // どちらもダンの本体へ。チャットはチャットのダンへ、声は通話を開く要求だけがダンの本体を通る。
  { from: 'devices', to: 'base', label: '送る' },
  { from: 'audio', to: 'base', label: '通話を開く', ax: 22, at: 0.8 },
  { from: 'base', to: 'chat', label: 'チャット', at: 0.8 },
  { from: 'base', to: 'editor', label: '作品の会話', at: 0.8 },
  // 声そのものは、ブラウザ・アプリと GPT-Live（OpenAI）の間を直に流れる
  { from: 'audio', to: 'voice', label: '声（OpenAI と直接）', ax: 56, bx: 39, at: 0.5 },
  { from: 'base', to: 'voice', b: 't', bx: 50, label: '通話を準備・横で聞く', at: 0.7 },
  { from: 'base', to: 'editorTalk', a: 'b', b: 'l', label: 'Windows 版のエディター', at: 0.6 },
  { from: 'voice', to: 'router', label: '任せる' },
  { from: 'router', to: 'lookup', label: '調べる' },
  { from: 'router', to: 'stage', label: '見せる', at: 0.75 },
  { from: 'router', to: 'backend', label: '判断する', at: 0.75 },
  { from: 'router', to: 'parallel', a: 't', b: 'l', bx: 40, label: '制作を頼む', at: 0.5 },
  { from: 'chat', to: 'codex', ax: 20, bx: 20, label: '別の部屋へ', at: 0.6 },
  { from: 'chat', to: 'parallel', ax: 50, bx: 22, label: '作業を任せる', at: 0.85, via: [[2030, 74], [2030, 232]] },
  { from: 'backend', to: 'api', label: '手順を再生' },
  // 返事
  { from: 'chat', to: 'reply', ax: 70, b: 't', bx: 90, label: 'チャットに返す', at: 0.75, via: [[1960, 94]] },
  { from: 'editor', to: 'reply', ax: 60, bx: 15, label: '作品の会話に返す', at: 0.5 },
  { from: 'voice', to: 'reply', a: 't', ax: 160, bx: 60, label: '声で返す', at: 0.55, via: [[1500, 470], [1840, 470], [1840, 345]] },
].map(edge => ({a: 'r', b: 'l', ...edge} as ArchEdge));

// ---- 動画を作る・直す時（構成図の「チャットのダン」「エディターのダンと制作」「並行作業」から降りる枝）----
// 2026-11-23 本人「動画の作成や編集がチャットのダンや並行作業に届いて、その後にどういうスキルやコンポーネントがあって、それをどう
// 読み込んでいるからこうなっている。だからここを直せばいいんじゃないかってことが分かるページ」。箱と矢印は11/23にコードで確かめた順。
// 仕組みを変えたら、ここの facts も直すこと。
export const VIDEO_W = 1000;
export const VIDEO_H = 1190;

export const VIDEO_NODES: ArchNode[] = [
  { id: 'v-owner', name: '動画制作', model: '依頼を受けた役割から制作へ', icon: 'editor-screen', x: 360, y: 8, w: 280,
    line: '動画を作って・直して、と頼む。頼む場所で、下の4つのどれに届くかが決まる。' },
  { id: 'v-chat', name: 'チャットのダン', model: '部屋のモデル', icon: 'chat', x: 50, y: 160, w: 215, same: 'chat',
    line: 'ふだんのチャットで頼んだ時。',
    facts: ['作品の名前が話に出た時・その部屋の作品をエディターで開いている時（10分以内）だけ、タイムラインの道具が付く。それ以外の会話では、タイムラインを直接は触れない。']},
  { id: 'v-editor', name: 'エディターのダンと制作', model: '部屋のモデル', icon: 'editor', x: 285, y: 160, w: 215, same: 'chat',
    line: 'エディターの中の会話で頼んだ時。作品ごとの隠れた部屋で、中身はふつうのチャット。',
    facts: ['この部屋では、開いている作品のタイムラインの道具がいつも付く。', '画面に「タイムラインから送った指示の一覧」と「今のタイムラインの様子」が足される。']},
  { id: 'v-parallel', name: '並行作業', model: '部屋の作業用モデル', icon: 'parallel', x: 520, y: 160, w: 215, same: 'parallel',
    line: 'タイムラインのピン・ペン・枠で指示した時と、通話で「作って・直して」と言った時。作品の部屋の会話を引き継いだ別のダンが動く。',
    facts: ['ピン・ペン・枠は、1つの指示ごとに並行作業が1つ起きる。指示した区間・場所・印を付けたコマの絵が依頼に付く。', '通話からは、振り分けが「作る・直す」と決めた時。エディターから話していれば、その時の再生位置と指した所が付く。', '終わると部屋のダンが起こされ、結果を短く返す（エディターの指示は会話に出さない）。']},
  { id: 'v-codex', name: '「ダンに指示」の実行', model: 'Codex（GPT-6 Astra）', icon: 'codex', x: 755, y: 160, w: 215,
    line: 'タイムラインに置いた「ダンに指示」のクリップを実行した時だけ。ほかの3つと違い、制作の決まりを足して読む。'},

  { id: 'v-rules', name: 'チャットのダンと同じ決まり', model: '毎回、決まりの頭に入る', icon: 'v-rules', x: 50, y: 320, w: 685,
    prompts: ['workspace/user', 'workspace/soul', 'workspace/rules', 'work/parallel-job-rules', 'work/confirmation-rule', 'work/editor-handoff'],
    line: 'USER・SOUL・RULES と、並行作業なら並行作業の決まり。動画のためだけの決まりは、ここには無い。',
    facts: ['決まりの中に、手順書（スキル）全部の名前と1行の説明の一覧が入る。動画の手順書の中身は、ここではまだ読まれない。']},
  { id: 'v-prod', name: '制作の決まり', model: 'プログラムの中（読むだけ）', icon: 'v-rules', x: 755, y: 320, w: 215,
    prompts: ['code/editor-runtime-notes', 'code/editor-production-budget', 'code/editor-production-authority', 'code/editor-execution-contract', 'code/editor-creative-direction', 'code/editor-first-artifact', 'code/editor-film-plan'],
    line: '「ダンに指示」の実行だけが読む7つの文（約5,600字）。チャットのダン・エディターの会話・並行作業は読まない。' },

  { id: 'v-skills', name: '手順書を選んで開く', model: 'ダンが一覧から選ぶ', icon: 'v-skills', x: 50, y: 480, w: 440,
    prompts: ['skill/talking-demo-editing', 'skill/video-draft', 'skill/explainer-video', 'skill/post-production', 'skill/video-direction', 'skill/creative-studio', 'skill/popout', 'skill/studio', 'skill/talk-script', 'skill/media-gen'],
    line: 'ダンが「動画の頼みだ」と判断したら、一覧から合う手順書を選んで開く。',
    facts: ['自動で開かれる手順書は無い。開くかどうか・どれを開くかはダンの判断。開かずに作り始めることもできる。', '例外は「/スキル名」と打った時だけで、その時は手順書の本文が頼みに付く。', '話す人の動画は「話しながら見せる動画の編集」の手順書。開くと手順書の本文は読めるが、案件の決まりは一緒には付いてこない。']},
  { id: 'v-home', name: 'Claude Code の本体の棚', model: 'Claude Code に入っている手順書', icon: 'v-skills', x: 520, y: 480, w: 215,
    line: 'HyperFrames（8本）・media-use・motion-graphics・product-launch-video の11本。部屋のモデルが Claude Code の時だけ、Claude Code の Skill の道具で開ける。',
    facts: ['上の一覧には載らず、この画面でも読めない。Codex の部屋では使えない。'] },

  { id: 'v-cases', name: '案件の決まり', model: '手順書が「読め」と書いている', icon: 'v-skills', x: 50, y: 630, w: 440,
    prompts: ['skill/talking-demo-editing/references/suya-youtube', 'skill/talking-demo-editing/references/pornanti-line-gift', 'skill/talking-demo-editing/references/nakamura-line-gift', 'skill/talking-demo-editing/references/new-attack-video', 'skill/talk-script/references/youtube-video', 'skill/talk-script/references/line-gift-video', 'skill/talk-script/references/launch-video'],
    line: 'スヤさん・ポルノアンチ・中村さん・新アタックの好みと、過去の指摘。手順書の「始める前に読む」を見て、ダンが自分で読みに行く。',
    facts: ['読みに行くかどうかもダンの判断。読んだかを確かめるのは、動画を貼る時の関所だけ（手順書の見出しは確かめるが、案件の決まりまでは確かめない）。'] },

  { id: 'v-parts', name: '素材と部品', model: 'その都度ダンが選ぶ', icon: 'v-parts', x: 50, y: 790, w: 290,
    line: 'タイムラインに置く物。撮った映像・制作ライブラリの素材・AIで作る絵と映像・Envato・After Effects・HyperFrames。',
    facts: ['Envatoの部品はエディターの一覧で見本を確認できる。ダンは作品に使う文字や写真を渡し、After Effectsで書き出した映像をタイムラインに置く。', '制作の方法の一覧は5つ。部品の棚（71個）・見せ方の型（6個）・参考の棚（37個）は Windows 版の「話す」からしか引けない。', '11/22 に試した「見せ方の棚」（人気動画30場面）は、試しの中だけで本番の作業には入っていない。']},
  { id: 'v-timeline', name: 'タイムラインの道具', model: '57個', icon: 'v-tltools', x: 365, y: 790, w: 290,
    line: 'クリップを置く・切る・動かす・字幕・音・範囲の効果。1手ごとに形を確かめて、みきさんの画面へすぐ出す。',
    facts: ['どの入口から頼んでも、同じ57個の道具を使う。', '道具を使わず、ダンがその場で書いたプログラムで作品を書き換えることもできてしまう（11/22 の棚の試しの②はこれで、手順書の確かめを通らなかった）。']},
  { id: 'v-frames', name: 'コマを見る・書き出す', model: 'ダンが時刻を選ぶ', icon: 'v-frames', x: 680, y: 790, w: 290,
    line: '好きな時刻のコマを絵にする・一部だけ書き出す・書き出した動画を Gemini に見せる。',
    facts: ['切れ目と、重ねた絵・字幕の切り替えを全部数えて見るプログラムは無い。どの時刻を見るかはダンが選ぶ（11/22 の②はここで2コマしか見ず、ぶつっと切れたのを見落とした）。']},

  { id: 'v-gate', name: '返事の前の関所', model: 'チャットの番の終わりに動く', icon: 'v-gate', x: 50, y: 950, w: 420,
    line: '30秒以上の動画をチャットに貼る番だけ、2つを確かめ、足りなければ返事を止めて差し戻す。',
    facts: ['1. 動画の手順書のどれか1つを、見出しまで全部読んだか。', '2. 前に動画を出してからのみきさんの発言を、指摘として記録したか。', '同じ理由で止めるのは2回まで。エディターの部屋で動画を貼らない番は止めず、裏で指摘を拾う。', '「ダンに指示」の実行（Codex）には、この関所は掛からない。']},
  { id: 'v-show', name: 'みきさんに見せる', model: 'エディター・チャット', icon: 'v-show', x: 500, y: 950, w: 470,
    line: 'タイムラインは直すたびにみきさんのエディターに出る。チャットには、押すとエディターで開くサムネを返す。',
    facts: ['並行作業の結果は、部屋のダンが起こされて短く返す。エディターのピン・ペンの指示の結果は、会話には出さない。']},

  { id: 'v-learn', name: '指摘から手順書を育てる', model: '裏の並行作業（1日3回まで）', icon: 'v-learn', x: 50, y: 1090, w: 600,
    prompts: ['skill/talking-demo-editing/learning', 'skill/talking-demo-editing/sources/generalization-log'],
    line: 'みきさんの指摘を記録すると、裏の作業が案件の決まりを書き足す。2つ以上の案件で同じ失敗が出た時だけ、手順書の本文に上げる。',
    facts: ['指摘はダンの中の記録帳に残る。書き足した後、前と後を伏せて比べてから本番に入れる。', '案件の決まりだけの直しは、案件の決まりと記録帳だけ触れる。手順書の本文の直しには、別の案件での比べが要る。']},
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
  { from: 'v-rules', to: 'v-skills', ax: 220, label: '手順書を開く' },
  { from: 'v-rules', to: 'v-home', ax: 577, dashed: true, label: 'Claude Code の時だけ' },
  { from: 'v-skills', to: 'v-cases', label: '「始める前に読む」' },
  { from: 'v-cases', to: 'v-timeline', ax: 380, bx: 90, label: '手順どおりに組む' },
  { from: 'v-prod', to: 'v-timeline', ax: 60, bx: 250, label: 'タイムラインの道具で直接', at: 0.4 },
  { from: 'v-parts', to: 'v-timeline', a: 'r', b: 'l' },
  { from: 'v-timeline', to: 'v-frames', a: 'r', b: 'l' },
  { from: 'v-frames', to: 'v-gate', ax: 150, bx: 300, label: 'チャットに動画を貼る時', at: 0.55 },
  { from: 'v-gate', to: 'v-show', a: 'r', b: 'l' },
  { from: 'v-show', to: 'v-learn', ax: 150, bx: 480, label: 'みきさんの指摘' },
  { from: 'v-learn', to: 'v-cases', a: 'l', b: 'l', dashed: true, label: '書き足す', at: 0.5 },
];

// 同じボードの上で、動画の枝は本流の下に枠で囲んで置く（本流からは「動画制作の手順」の札で飛ぶ。線は引かない＝本流の箱の裏を通さない）。
// スキルの手順書の一覧は上の「スキルを探す」から開く（ボードには置かない）。
export const VIDEO_AT = { x: 1080, y: 1140 };
export const VIDEO_FRAME = { x: VIDEO_AT.x - 24, y: VIDEO_AT.y - 52, w: VIDEO_W + 48, h: VIDEO_H + 76, name: '動画を作る・直す時' };
export const BOARD_NODES = [...NODES.filter(n => n.id !== 'skills'), ...VIDEO_NODES.map(node => ({
  ...node, x: node.x + VIDEO_AT.x, y: node.y + VIDEO_AT.y,
}))];
export const BOARD_EDGES: ArchEdge[] = [...EDGES, ...VIDEO_EDGES.map(e => ({...e, via: e.via?.map(([x, y]) => [x + VIDEO_AT.x, y + VIDEO_AT.y] as [number, number])}))];
