/**
 * /scratch/realtime-voice — Phase 0 実験のセッション設定（共有モジュール）。
 *
 * サーバー（api/session/route.ts のトークン発行）とクライアント
 * （page.tsx の session.update）の両方から使うため、純粋データのみ。
 *
 * 実験の目的:
 *   gpt-realtime-2.1 に「編集ツールを直接持たせて」音声→数秒で画面が変わる
 *   ループが成立するかの実測。ボタン方式（セマンティックツール）と
 *   生JS直書き方式を同条件で比較できるよう、車線（lane）を切り替えられる。
 */

export type RealtimeModel =
  | 'gpt-realtime-2.1'
  | 'gpt-realtime-2.1-mini'
  | 'gpt-realtime-2';

export type ReasoningEffort = 'minimal' | 'low' | 'medium' | 'high' | 'xhigh';

/** semantic=ボタン方式のみ / raw=生JSのみ / both=両方渡して選ばせる */
export type ToolLane = 'semantic' | 'raw' | 'both';

/** intent=ツール実行前に一言宣言（barge-in検問所） / silent=黙って実行 */
export type PreambleMode = 'intent' | 'silent';

/** practice=練習用LP(揮発) / lp=本物の成果物ページ(inspector_overridesに永続化) */
export type Surface = 'practice' | 'lp';

export interface ExperimentConfig {
  model: RealtimeModel;
  effort: ReasoningEffort;
  lane: ToolLane;
  preamble: PreambleMode;
  surface: Surface;
}

export const DEFAULT_CONFIG: ExperimentConfig = {
  model: 'gpt-realtime-2.1',
  // 実測(2026-08-22): xhigh は品質は出るが現行TPM枠では毎応答レート制限に当たり
  // 1手20〜30秒の牛歩になる。既定は high（速度と質のバランス）。枠を上げたら
  // xhigh をドロップダウンで解禁するのが推奨運用。
  effort: 'high',
  lane: 'semantic',
  preamble: 'intent',
  surface: 'practice',
};

// ---------------------------------------------------------------- tools

const GET_PAGE_STATE = {
  type: 'function',
  name: 'get_page_state',
  description:
    'いま画面に表示されているLPの編集可能な要素の一覧（id・タグ・テキスト・現在のインラインスタイル）を取得する。' +
    '編集の前に対象を確認したいときに使う。',
  parameters: { type: 'object', properties: {}, required: [] },
};

const SET_TEXT = {
  type: 'function',
  name: 'set_text',
  description: 'LP上の要素のテキストを書き換える。対象は get_page_state で得られる id で指定する。',
  parameters: {
    type: 'object',
    properties: {
      id: { type: 'string', description: '対象要素の id（例: hero-title）' },
      text: { type: 'string', description: '新しいテキスト' },
    },
    required: ['id', 'text'],
  },
};

const SET_STYLE = {
  type: 'function',
  name: 'set_style',
  description:
    'LP上の要素のスタイルを変更する。styles は camelCase の CSS プロパティ名と値のオブジェクト' +
    '（例: {"fontSize": "32px", "color": "#c0392b"}）。指定したプロパティだけが上書きされる。',
  parameters: {
    type: 'object',
    properties: {
      id: { type: 'string', description: '対象要素の id（例: hero-title）' },
      styles: {
        type: 'object',
        description: 'camelCase CSSプロパティ→値 のオブジェクト',
        additionalProperties: { type: 'string' },
      },
    },
    required: ['id', 'styles'],
  },
};

const RUN_JS = {
  type: 'function',
  name: 'run_js',
  description:
    'ページ上で任意の JavaScript を実行して LP を編集する。編集対象の要素は ' +
    'data-rt-id 属性で特定できる（一覧は get_page_state）。' +
    '例: document.querySelector(\'[data-rt-id="hero-title"]\').style.fontSize = "32px"。' +
    'return した値が結果として返る。',
  parameters: {
    type: 'object',
    properties: {
      code: { type: 'string', description: '実行する JavaScript コード' },
    },
    required: ['code'],
  },
};

const GENERATE_IMAGE = {
  type: 'function',
  name: 'generate_image',
  description:
    'GPT Image 2 で画像を生成し、完成したら指定要素に自動適用する（背景 or img の src）。' +
    '生成には20〜60秒かかるので、呼んだら「生成を始めました」とだけ伝えて会話を続けてよい。' +
    '完成すると通知が届く。prompt にはユーザーの要望をそのまま渡すこと' +
    '（自分でデザインの方向性・形容・スタイル指定を付け足さない。デザイン判断はユーザーがする）。',
  parameters: {
    type: 'object',
    properties: {
      prompt: {
        type: 'string',
        description:
          '生成したい画像の内容を表す説明文。会話の発言をそのまま貼り付けない。' +
          'ユーザーが内容を指定したときはその言葉を使う。ユーザーが「任せる」と言ったときは' +
          'ページの題材・文脈に合う内容を自分で決めてよい。' +
          'どちらの場合もスタイル・画風・形容の指定を勝手に足さない（デザイン判断はユーザーがする）。',
      },
      target_id: { type: 'string', description: '適用先要素の id（get_page_state で確認）' },
      mode: {
        type: 'string',
        enum: ['background', 'src'],
        description: 'background=要素の背景画像として適用 / src=img要素のsrcとして適用',
      },
      size: {
        type: 'string',
        description: '画像サイズ WxH。省略時は 1520x800（横長の背景向け）。両辺16の倍数。',
      },
    },
    required: ['prompt', 'target_id', 'mode'],
  },
};

const DELEGATE_TO_DAN = {
  type: 'function',
  name: 'delegate_to_dan',
  description:
    '直接ツールでは表現できない依頼を、バックグラウンドの開発エージェント（Claude）に委譲する。' +
    '対象: 要素の追加・削除・レイアウト変更などの構造変更、複数箇所にわたる大きな仕上げ' +
    '（例:「全体をプロっぽく」）、コード修正が必要な依頼。数分かかるので、委譲したら' +
    '「作業を任せました、完了したら報告します」と伝えて会話を続ける。完了すると通知が届く。' +
    '小さなテキスト・スタイル・画像の変更は委譲せず直接ツールでやる。',
  parameters: {
    type: 'object',
    properties: {
      task: {
        type: 'string',
        description:
          '開発エージェントへの作業指示。ユーザーの依頼を具体的かつ自己完結した形で書く' +
          '（何を・どこに・期待する結果）。ユーザーの意図を要約で歪めず、発言内容を含める。',
      },
    },
    required: ['task'],
  },
};

const LIST_SOURCE = {
  type: 'function',
  name: 'list_source_files',
  description: '編集中の成果物のソースファイル一覧（ファイル名とサイズ）を取得する。',
  parameters: { type: 'object', properties: {}, required: [] },
};

const READ_SOURCE = {
  type: 'function',
  name: 'read_source',
  description: '成果物のソースファイル（page.tsx 等）を読む。構造の把握や編集の前に使う。',
  parameters: {
    type: 'object',
    properties: {
      file: { type: 'string', description: 'ファイル名（例: page.tsx）。一覧は list_source_files' },
    },
    required: ['file'],
  },
};

const EDIT_SOURCE = {
  type: 'function',
  name: 'edit_source',
  description:
    'ソースファイルを部分編集する（完全一致の文字列置換・1箇所のみ）。要素の追加・削除・' +
    'レイアウト変更などの構造変更を自分で行うために使う。編集は1〜2秒でHMRにより画面へ自動反映される。' +
    '編集後は look_at_page で結果を自分の目で確認すること。',
  parameters: {
    type: 'object',
    properties: {
      file: { type: 'string', description: 'ファイル名（例: page.tsx）' },
      old_string: { type: 'string', description: '置換前の文字列（ファイル内で一意になるよう前後を含める）' },
      new_string: { type: 'string', description: '置換後の文字列' },
    },
    required: ['file', 'old_string', 'new_string'],
  },
};

const WRITE_SOURCE = {
  type: 'function',
  name: 'write_source',
  description:
    'ソースファイルを丸ごと書き換える（または新規作成する）。大規模な作り直しに使う。' +
    '部分的な変更は edit_source を優先すること。',
  parameters: {
    type: 'object',
    properties: {
      file: { type: 'string', description: 'ファイル名（例: page.tsx）' },
      content: { type: 'string', description: 'ファイルの完全な新しい内容' },
    },
    required: ['file', 'content'],
  },
};

const LOOK_AT_PAGE = {
  type: 'function',
  name: 'look_at_page',
  description:
    '編集中のLPの全体を、文字が読める高解像度タイル数枚（上から順・スクロール全域・' +
    'draft編集も反映されたユーザーと同じ状態）で見る（あなたの「目」）。' +
    '文字の可読性、配色の破綻、レイアウト崩れ、デザインの良し悪しなど、' +
    '悪いところに自分の目で気付くために使う。許可ダイアログは不要。' +
    '編集を数回行ったら、また委譲が完了したら、必ずこれで自分の目で確認してから報告すること。',
  parameters: { type: 'object', properties: {}, required: [] },
};

const LOOK_AT_SCREEN = {
  type: 'function',
  name: 'look_at_screen',
  description:
    'ユーザーの画面そのもの（このタブに今映っている範囲）をスクリーンショットで見る。' +
    '「今見えてるここが変」のようにユーザーの視点を共有したいときに使う。' +
    'ページ全体の確認には look_at_page を使うこと。初回はユーザーに画面共有の許可ダイアログが出る。',
  parameters: { type: 'object', properties: {}, required: [] },
};

const LOOK_AT_SECTION = {
  type: 'function',
  name: 'look_at_section',
  description:
    '指定した要素（セクション）だけを原寸・高画質のスクリーンショットで見る。' +
    '全体スクショ（look_at_page）は縮小されるため小さい文字の細部は読めない。' +
    '文字の可読性・細部の仕上がりを確認するときはこちらを使う。',
  parameters: {
    type: 'object',
    properties: {
      id: { type: 'string', description: '対象要素の id（例: te-section-wrapper）' },
    },
    required: ['id'],
  },
};

const CHECK_CONTRAST = {
  type: 'function',
  name: 'check_contrast',
  description:
    '補助lint（任意）: ページ内の全テキスト要素の文字色×背景色のコントラスト比（WCAG基準）を' +
    '機械計算し、基準未達の要素一覧を返す。確認の主軸はあくまで look_at_page での自分の目。' +
    '網羅的な数値の裏取りが欲しいときだけ使う。',
  parameters: { type: 'object', properties: {}, required: [] },
};

const CHECK_DAN_STATUS = {
  type: 'function',
  name: 'check_dan_status',
  description:
    '委譲した開発エージェント（ダン）の作業が進行中かどうかと、直近の活動を確認する。' +
    'ユーザーに「作業は続いてる？」と聞かれたら推測で答えず、必ずこれで確認して答える。',
  parameters: { type: 'object', properties: {}, required: [] },
};

export function buildTools(lane: ToolLane, surface: Surface = 'practice'): object[] {
  const semantic: object[] = [GET_PAGE_STATE, SET_TEXT, SET_STYLE];
  const lpExtras = [
    GENERATE_IMAGE,
    LIST_SOURCE,
    READ_SOURCE,
    EDIT_SOURCE,
    WRITE_SOURCE,
    LOOK_AT_PAGE,
    LOOK_AT_SECTION,
    CHECK_CONTRAST,
    LOOK_AT_SCREEN,
    CHECK_DAN_STATUS,
    DELEGATE_TO_DAN,
  ];
  if (surface === 'lp') semantic.push(...lpExtras);
  const raw: object[] = [GET_PAGE_STATE, RUN_JS];
  if (surface === 'lp') raw.push(...lpExtras);
  if (lane === 'semantic') return semantic;
  if (lane === 'raw') return raw;
  return [...semantic, RUN_JS];
}

// ---------------------------------------------------------- instructions

export function buildInstructions(
  lane: ToolLane,
  preamble: PreambleMode,
  surface: Surface = 'practice',
): string {
  const parts: string[] = [];

  if (surface !== 'lp') {
    parts.push(
      'あなたは、目の前の画面に表示されているランディングページ（LP）を' +
        'ユーザーと会話しながらその場で編集する音声アシスタントです。' +
        '日本語で短く自然に話します。長い説明はしません。',
    );
  } else {
    // OpenAI 公式 Realtime Prompting Guide の8セクション骨格に準拠（2026-08-23 全面書き換え）。
    // 方針: 禁止ルールの堆積をやめ、性格・流れ・ルールを公式テンプレの型で肯定形中心に定義する。
    // lp はこの骨格が全てで、後段の lane / preamble 追記は適用しない（重複・矛盾の温床のため）。
    return `# 役割と目的
- あなたは、画面に表示されたLPをユーザーと音声で一緒に編集する制作パートナー。
- 成功 = ユーザーの意図どおりにページが変わり、それを自分の目で確認して伝えられること。

# 性格とトーン
- 人柄: 気心の知れた制作仲間。落ち着いていて頼れる。
- 口調: 自然な話し言葉。丁寧すぎず、砕けすぎず。
- 熱量: 穏やか。感情は控えめ、事実は率直に。
- 相槌・つなぎ: 「ええ」「なるほど」程度をたまに。多用しない。
- ペース: ゆったり。1回の発話は1〜3文。
- バリエーション: 同じ言い回しや枕詞を続けて使わず、毎回言い方を変える。
- 挨拶には挨拶だけを返す。用件はユーザーが言うまで待つ。
- 発話例:
  - 「見出し、大きくしました」
  - 「ちょっと全体を見ますね」
  - 「ここ、写真が暗くて文字が沈んでます。直しましょうか」

# 文脈
- ページは本物の制作物。編集はdraftとして保存され、リロードしても残る。公開は別の操作。
- set_text / set_style の編集（draft）は、ソースコードより表示が優先される。

# ツール
- 軽い編集（文言・色・サイズ）: set_text / set_style。数秒で画面に反映される。
- 構造・レイアウト: read_source で読んでから edit_source / write_source。1〜2秒で反映される。
- 画像: generate_image（20〜60秒。待つ間も会話してよい）。
- 目: look_at_page（全体を高解像度で見る）/ look_at_section（細部を原寸で）/ check_contrast（可読性の数値検査）。
- 委譲: delegate_to_dan は自分で試して手に余ったときの第二手段（数分かかる）。進行確認は check_dan_status。
- ツールの結果に案内文が含まれていたら、その内容をそのまま伝える。
- まとまった作業の前にひとこと意図を伝え（言い回しは毎回変える）、作業中は静かに進める。進行状況は画面に表示されている。

# ルール
- 常に日本語で話す。
- 軽微な聞き間違いは意図を汲んで進める。意味が取れないときだけ聞き返す。
- 【確認できた事実だけを「できた」と言う】。見ていないことは「まだ確認していない」と言う。
- 複数の修正はまとめて実行し、確認は最後に1回。
- ページの題材（何の会社・商品のLPか）に沿った内容だけを作る。

# 会話の流れ
1. 依頼を聞く。不明瞭なら聞き返す。曖昧でも解釈できるなら、一番自然な解釈で進めて後で一言確認する。
2. 実行する。ひとこと意図 → 静かに作業。
3. 確認する。look_at_page で自分の目で見る（必要なら check_contrast）。
4. 報告する。確認できた結果を短く伝えて、待つ。

# 安全と引き継ぎ
- 同じやり方で2回失敗したら、別の方法に切り替えるか、delegate_to_dan への委譲を提案する。
- 公開・削除など取り返しのつきにくい操作は、実行する前に口頭で確認する。`;
  }


  if (lane === 'semantic') {
    parts.push(
      '編集は set_text / set_style ツールで行います。' +
        '対象が曖昧なときは get_page_state で現状を確認してから編集します。',
    );
  } else if (lane === 'raw') {
    parts.push(
      '編集は run_js ツールに JavaScript を書いて行います。' +
        '対象要素は data-rt-id 属性で特定します（一覧は get_page_state）。',
    );
  } else {
    parts.push(
      '編集ツールは set_text / set_style（定型編集）と run_js（自由な編集）があります。' +
        '定型で足りる編集は set_text / set_style を、構造変更など定型で表現できない編集は run_js を使います。',
    );
  }

  if (preamble === 'intent') {
    parts.push(
      '作業のまとまりを始める直前に、方針をごく短く一言だけ（例:「読めない文字を洗い出して直しますね」）宣言してから実行します。' +
        'ツール1つ1つには宣言しません。ユーザーが途中で遮ったら中止して聞き直します。',
    );
  } else {
    parts.push('編集は黙って実行し、終わってから結果だけをごく短く伝えます。');
  }

  parts.push(
    '編集が終わったら結果を一言で伝えます。うまくいかなかったときは正直にそう言います。',
  );

  return parts.join('\n\n');
}

// -------------------------------------------------------- session config

/** OpenAI /v1/realtime/client_secrets に渡す session 設定を組み立てる。 */
export function buildSessionConfig(cfg: ExperimentConfig): Record<string, unknown> {
  return {
    type: 'realtime',
    model: cfg.model,
    instructions: buildInstructions(cfg.lane, cfg.preamble, cfg.surface),
    audio: {
      input: {
        transcription: { model: 'gpt-realtime-whisper', language: 'ja' },
        noise_reduction: { type: 'near_field' },
        // 発話終了を音量でなく意味で判定する。食い気味の応答・文の途中での
        // 切り込み（実機で観測）への対策。eagerness=low で「急がず聞き切る」寄りに
        // （ユーザーの好み: ChatGPT音声の落ち着いた間合い。2026-08-22）。
        turn_detection: { type: 'semantic_vad', eagerness: 'low' },
      },
      // cedar = 自然系の男声（ユーザー指定: 男声・ナチュラルなイントネーション）
      output: { voice: 'cedar' },
    },
    tools: buildTools(cfg.lane, cfg.surface),
    reasoning: { effort: cfg.effort },
    // note: temperature は GA の realtime session では廃止済み（指定すると 400）。調整レバーではない。
  };
}

export function normalizeConfig(raw: unknown): ExperimentConfig {
  const b = (raw && typeof raw === 'object' ? raw : {}) as Record<string, unknown>;
  const models: RealtimeModel[] = ['gpt-realtime-2.1', 'gpt-realtime-2.1-mini', 'gpt-realtime-2'];
  const efforts: ReasoningEffort[] = ['minimal', 'low', 'medium', 'high', 'xhigh'];
  const lanes: ToolLane[] = ['semantic', 'raw', 'both'];
  const preambles: PreambleMode[] = ['intent', 'silent'];
  const surfaces: Surface[] = ['practice', 'lp'];
  return {
    surface: surfaces.includes(b.surface as Surface) ? (b.surface as Surface) : DEFAULT_CONFIG.surface,
    model: models.includes(b.model as RealtimeModel) ? (b.model as RealtimeModel) : DEFAULT_CONFIG.model,
    effort: efforts.includes(b.effort as ReasoningEffort) ? (b.effort as ReasoningEffort) : DEFAULT_CONFIG.effort,
    lane: lanes.includes(b.lane as ToolLane) ? (b.lane as ToolLane) : DEFAULT_CONFIG.lane,
    preamble: preambles.includes(b.preamble as PreambleMode)
      ? (b.preamble as PreambleMode)
      : DEFAULT_CONFIG.preamble,
  };
}
