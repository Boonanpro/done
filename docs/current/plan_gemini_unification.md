# Gemini統一 & 自律基盤計画

## 背景

### 現状の問題
1. **3つのLLMがバラバラに動いている** — テキスト=Claude Haiku, 音声=Gemini Flash, リサーチ=Claude Sonnet
2. **音声とテキストで挙動が違う** — プロセスモニター、回答傾向、推論深度が一貫しない
3. **Extended Thinkingが実質オフ** — Haiku 4.5は非対応だが設定だけある
4. **ダンが開発できない** — Claude Codeツールがないため、コード変更は全て人間がClaude Codeで実施
5. **ハートビートが無効** — フレームワークはあるが `enabled: false`

### 目指す姿
- **脳は1つ（Gemini 2.5 Flash）** — 音声でもテキストでもハートビートでも同じLLMが判断
- **重い仕事は専門ツールに委譲** — 開発=Claude Code(Opus), 調査=Claude Sonnet, Web操作=ブラウザ
- **ユーザーから見るとDan 1人** — どの入力方法でも同じ人格、同じ能力

### 設計思想（OpenClaw参照）
> LLMにツールと目を渡せば、AIは思っている以上に何でもやってくれる

- OpenClaw: 1つのLLM + ツール群。音声はSTT/TTSパイプライン（どのモデルでも可）
- VisionClaw: Gemini 2.5 Flash 1本。ネイティブ音声 + Function Calling + OpenClaw連携
- **Dan: Gemini 2.5 Flash（ネイティブ音声）+ 専門ツール（Claude Code, Deep Research等）**

旧Visual Agent問題（同じ仕事を2つのLLMが二重にやる）とは異なり、
今回は「脳=Gemini」「手足=各ツール（一部にLLM搭載）」という明確な役割分担。

---

## アーキテクチャ

```
ユーザー（音声 or テキスト or ハートビート）
  ↓
Dan（Gemini 2.5 Flash + Thinking）← 唯一の意思決定者
  ↓                ↓                ↓              ↓
browser_*        claude_code      deep_research   その他ツール
(Playwright)     (Opus 4.6)      (Sonnet 4.5)    (検索, メモリ等)
Web操作          開発・成果物作成  深い調査         日常タスク
```

### モデル配置

| 役割 | モデル | 変更 |
|------|--------|------|
| 脳（テキスト+音声+ハートビート） | Gemini 2.5 Flash (native audio) | Haiku→Gemini に変更 |
| 開発ツール | Claude Code CLI (Opus 4.6) | **新規** |
| 深い調査ツール | Claude Sonnet 4.5 | 据え置き |
| ブラウザ操作 | Dan自身が判断 | 変更なし |
| Web検索 | Gemini google_search (組み込み) | Anthropic web_search から移行 |

---

## 実装フェーズ

### Phase 1: 音声体験の統一（プロセスモニター + 音声フィードバック）

**目的**: 音声で話しかけたときも、テキストと同じレベルの可視性を得る

#### 1-1. プロセスモニターをobserverイベントに接続
- **ファイル**: `frontend/src/app/chat/[sessionId]/page.tsx`
- **内容**: observer の `onProcessStep`, `onToolStart`, `onToolResult` を `addProcessStep` に接続
- **現状**: イベントは受信しているがプロセス表示に反映されていない

#### 1-2. Gemini Thinking Budget 有効化
- **ファイル**: `app/agent/gemini/live_runner.py` → `app/agent/gemini/client.py`
- **内容**: Live API接続時に `thinkingConfig: {thinkingBudget: 2048}` を設定
- **効果**: 音声時もGeminiが内部推論してからツール実行・応答する

#### 1-3. 音声プロンプト強化（行動前発言）
- **ファイル**: `app/agent/gemini/live_runner.py` の `VOICE_SYSTEM_RULES`
- **内容**: ツール実行前に「今から調べます」「少し考えます」等の発言を明示的に指示
- **既存**: テキスト側には `VOICE_ANNOUNCEMENTS` dict があるが、音声側にはない

---

### Phase 2: テキストチャットをGemini統一

**目的**: テキストチャットもGemini 2.5 Flashで動かし、LLMを1つに統一する

#### 2-1. GeminiTextRunner 作成
- **新規ファイル**: `app/agent/gemini/text_runner.py`
- **内容**: 既存の `runner.py` (AgentRunner) と同等の機能をGemini APIで実装
  - システムプロンプト構築（既存の `_build_system_prompt` を共通化）
  - ツール定義変換（既存の `tool_converter.py` を利用）
  - セッション管理（既存の `session.py` SessionStore を利用）
  - プロセスステップのSSE報告
  - Thinking Budget 設定

#### 2-2. chat_routes.py の切り替え
- **ファイル**: `app/api/chat_routes.py`
- **内容**: `AgentRunner` → `GeminiTextRunner` に差し替え
- **互換性**: SSEイベント形式は維持（フロントエンド変更不要）

#### 2-3. システムプロンプト共通化
- **ファイル**: 新規 `app/agent/gemini/prompt_builder.py`
- **内容**: `live_runner.py` と `text_runner.py` で共通のプロンプト構築ロジック
- **ブートストラップ**: USER → MEMORY → daily memory → SOUL → RULES（順序統一）

#### 2-4. 旧Claude AgentRunner の退役
- **ファイル**: `app/agent/v2/runner.py`
- **内容**: テキストチャットからの参照を削除。ディープリサーチ内部のSonnet呼び出しは残す
- **session.py**: セッション管理は引き続き利用（LLM非依存のため）

---

### Phase 3: Claude Code ツール（Developerスキル）

**目的**: DanがClaude Code CLIを呼び出して開発・成果物作成を委譲できるようにする

#### 3-1. claude_code ツール実装
- **新規ファイル**: `app/tools/claude_code.py`
- **内容**:
  ```
  async def execute_claude_code(prompt: str, working_dir: str = None) -> dict:
      # claude CLI をサブプロセスで実行
      # --print フラグで非対話モード
      # 結果をテキストで返す
  ```
- **安全策**:
  - タイムアウト設定（最大10分）
  - working_dir のホワイトリスト
  - 実行結果のサイズ制限

#### 3-2. ツール定義の追加
- **ファイル**: `app/agent/v2/tools.py`
- **内容**: `claude_code` ツールを定義（name, description, parameters）
- **パラメータ**: `prompt`（何をするか）、`working_dir`（任意）

#### 3-3. Gemini Function Declaration への変換
- **ファイル**: `app/agent/gemini/tool_converter.py`
- **内容**: `claude_code` ツールがGemini側でも呼べることを確認（既存変換で対応可能なはず）

#### 3-4. Developerスキル SKILL.md 更新
- **ファイル**: `.claude/skills/developer/SKILL.md`
- **内容**: 既存のファイル操作系ツールに加えて `claude_code` ツールの使い方を記述
- **ユースケース**: アプリ作成、Stripe連携、デプロイスクリプト等

---

### Phase 4: ハートビート有効化

**目的**: Danが自律的に起動し、自己改善・タスク実行を行う

#### 4-1. ハートビートのLLM切り替え
- **ファイル**: `app/services/heartbeat_service.py`
- **内容**: `AgentRunner` → GeminiTextRunner に切り替え
- **プロンプト**: 既存の `HEARTBEAT_PROMPT_TEMPLATE` を維持

#### 4-2. HEARTBEAT.md の有効化
- **ファイル**: `~/.dan/workspace/HEARTBEAT.md`
- **内容**: `enabled: true` に変更
- **初期設定**: interval=30分, quiet_hours=23:00-07:00, max_tool_calls=10

#### 4-3. ハートビートからClaude Code 呼び出し
- **内容**: ハートビート中にDanが `claude_code` ツールを使えるようにする
- **ユースケース**:
  - エラーログ検知 → 自動修正
  - スキル改善 → SKILL.md 更新
  - 新機能提案 → コード実装 → PR作成
- **安全策**: ハートビートでの `claude_code` は確認なしで実行可能な範囲に制限（テスト、lint等）

#### 4-4. ハートビートからの通知
- **既存**: `voice_push` でcompanionセッションに音声プッシュ
- **追加**: chat_messages にも結果を投稿（PCで確認可能）

---

### Phase 5: ビジネス実行基盤

**目的**: Danがビジネスタスクを実行できる環境を整える

#### 5-1. Stripe連携
- Dan → `claude_code` → Stripe SDKのコード実装
- Dan → `browser_*` → Stripeダッシュボード操作
- 決済webhook、報酬受け取り設定

#### 5-2. アプリ開発・公開
- Dan → `claude_code` → アプリコード作成
- Dan → `browser_*` → ストア申請操作
- VRゲーム、YouTube動画生成パイプライン等

#### 5-3. OTP/メール連携強化
- Dan → `browser_*` → OTP入力自動化
- Dan → メールAPI → 請求書確認・支払い通知

---

## 依存関係

```
Phase 1 (音声体験統一)
  ↓
Phase 2 (テキストGemini統一) ← Phase 1の知見を活かす
  ↓
Phase 3 (Claude Codeツール) ← Phase 2でGemini統一後に追加
  ↓
Phase 4 (ハートビート) ← Phase 2+3が必要
  ↓
Phase 5 (ビジネス実行) ← Phase 3+4が基盤
```

## 重要な注意

- **Phase 3以降はDan自身が実装を手伝える可能性がある** — Claude Codeツールが動けば、
  「この計画のPhase 4を実装して」とDanに頼むことも理論上可能
- **各Phaseは独立してテスト可能** — Phase 1だけでも音声体験は大幅に改善する
- **旧コードの段階的退役** — `app/agent/v2/runner.py` はPhase 2完了後に退役。
  `session.py`, `tools.py` はLLM非依存のため引き続き利用
