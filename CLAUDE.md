# プロジェクト固有ルール

## コミット＆プッシュ

「コミットプッシュして」と言われたら、以下の**2つのリポジトリ**を両方コミット＆プッシュする:

1. **D:/done** → `origin/main`（プロジェクトコード）
2. **~/.dan/workspace** → `origin/master`（ダンの運用ルール・計画・メモリ）

どちらかに変更がなければスキップしてよい。

## アーキテクチャ: 2プロセス分離（ダンコア / アプリサンドボックス）

**ダンコア（不変）と アプリサンドボックス（可変）を別プロセスで動かす。**
ユーザーがコードを書き換えてもサンドボックスだけが再起動し、ダンコアは生き続ける。

```
┌─ Dan Core (port 9000) ─────────┐    ┌─ App Sandbox (port 8000) ─┐
│  app/core/main.py              │    │  app/sandbox/main.py      │
│  - chat / voice / credentials  │    │  - 業務系ルーター全部     │
│  - agent (LLM/CLI)             │←──→│  - dan_notion / aix       │
│  - SandboxManager              │    │  - studio / project / etc │
│  - 再起動しない                │    │  - 自由に再起動OK         │
└────────────────────────────────┘    └───────────────────────────┘
              ↑                                    ↑
              └───── Frontend (port 3000) ─────────┘
                     next.config.ts rewrites:
                     /api/v1/chat/* → 9000
                     /api/v1/voice/* → 9000
                     /api/v1/credentials/* → 9000
                     /api/v1/* (それ以外) → 8000
```

### 起動

```bash
python scripts/start_dan_core.py
```

ダンコア(9000)が起動 → 自動でサンドボックス(8000)を spawn。
OS 起動時に自動起動するよう Windows タスクスケジューラに登録済み。

### サンドボックス再起動（コード変更を反映する場合）

```bash
curl -X POST http://127.0.0.1:9000/api/v1/sandbox/restart
```

または auto_deploy.py が git pull 検知時に自動的にこの API を叩く。
**ダンコアは再起動しないので、ユーザーとのチャットセッションは維持される。**

### 環境変数

- `DAN_CORE_PORT` (default: 9000)
- `DAN_SANDBOX_PORT` (default: 8000) — テスト時に変更可能
- `DAN_AUTO_START_SANDBOX` (default: 1) — ダンコア起動時の自動 spawn 有効/無効

### トラブルシュート

- ダンコアが死んだ場合: `python scripts/start_dan_core.py` を再実行
- サンドボックスだけ落ちた場合: `curl -X POST http://127.0.0.1:9000/api/v1/sandbox/restart`
- ポート占有を疑う場合: `netstat -ano | findstr ":8000\|:9000" | findstr LISTENING`

## ⚠️ リモート開発（Claude App コードタブ）のルール ⚠️

Claude Appの「コード」タブはリモートサンドボックスで動作するため、以下の制約がある：

- **自宅PCのプロセス（uvicorn, Next.js）は操作できない**
- **サーバーの再起動は不可能**（「再起動しました」と言わないこと）
- コード変更 → git push → 自宅PCの `auto_deploy.py` が自動検知・反映する

### 必須ルール

1. **ブランチを作らず、mainに直接pushすること**
   - ❌ `git checkout -b claude/xxx` → ブランチ作成は禁止
   - ✅ `git add ... && git commit && git push origin main`
2. **「再起動しました」「反映しました」と言わないこと**
   - `auto_deploy.py` がpullして自動反映するので、リモートから直接反映はできない
   - 「mainにpushしました。約30秒で自動反映されます」と伝えること

### ※ ローカルCLI（自宅PC）の場合

上記はリモート専用ルール。ローカルCLIでpushした場合は `--reload` で即反映されるため、「pushしました。反映済みです」でOK。
3. **DBマイグレーション**: Playwright が使えない場合はSQLファイル作成のみ

## DBマイグレーション実行

SQLマイグレーションファイルを作成したら、**Supabase Management APIで自分で適用すること**。手順はMEMORY.mdの「Supabase DDL実行手順」を参照。
Playwrightが使えない環境ではSQLファイル作成のみで報告する。

## 開発環境

- ダンコア: FastAPI (port 9000) — 不変、再起動しない
- アプリサンドボックス: FastAPI (port 8000) — 業務系、自由に再起動OK
- フロントエンド: Next.js (port 3000)
- データベース: Supabase
- 自動デプロイ: `python scripts/auto_deploy.py` （常駐スクリプト、変更検知でサンドボックス再起動）

## 現在の実装計画

**docs/current/README.md** を参照。

v2アーキテクチャに基づいて開発中。旧計画書（phase*.md）は docs/archive/ に移動済み。

## Agent v2 アーキテクチャ

詳細: `docs/current/architecture_v2.md`

- ツール呼び出し: B方式（キーワード検出 `[TOOL: skill-name action]`）
- スキル定義: `.claude/skills/*/SKILL.md`
- 状態遷移: LLMが `[STATE: xxx]` で宣言
- メインロジック: `app/agent/v2/`

## ⚠️ プロセス操作: PowerShell禁止 ⚠️

**Git Bash（MINGW64）環境からPowerShellを呼び出してはいけない。**

❌ `powershell -Command "..."` （ハングして返ってこなくなる）
❌ `cmd /c "taskkill ..."` （引数が正しく渡らない）

### 代わりに使う方法

- **プロセス終了**: `taskkill //F //PID <PID>`（Git Bashでは`/`を`//`にエスケープ）
- **プロセス操作が複雑な場合**: Pythonスクリプトを書いて `python script.py` で実行

### 理由

Git Bash（mintty）とPowerShellの間でパイプが正しく閉じられず、コマンドが永久にハングする。ハングした状態は「まだ実行中」に見えるため、失敗として検知できない。

## 環境で繰り返しハマった制約

- **Google系サービスにPlaywrightでログインできない**: bot検出でブロックされる。APIキー + Pythonライブラリで操作すること
- **Windowsでasyncio.create_subprocess_execが使えない**: uvicornがSelectorEventLoopを使うため。`subprocess.run` + `asyncio.to_thread()` で代替する

## スキル開発ルール

### 1. ブラウザ自動化のセレクタ規律（焼き込み時のみ調査必須）

| ケース | 事前セレクタ調査 |
|---|---|
| **スキルにセレクタを焼き込む**（salonboard 型・再利用前提のコード） | **必須** |
| **その場限りのブラウザ操作** | **不要**。`browser` ツールの ref 系（`@e1`）で実行時にライブDOMを読む |

**セレクタを焼き込むスキルを新規作成・修正する場合**：

1. **実装前に実際のサイトでセレクタを調査する**
2. 調査スクリプトを作成して実行し、HTMLを取得
3. 取得したHTMLから正確なセレクタを特定
4. 推測やドキュメントだけに基づいてセレクタを書かない

**理由**: サイトの実際のHTML構造は推測と異なることが多く、焼き込みでは動作しないコードを量産してしまう。逆に、その場限りの操作は `browser` ツールが `get_interactive_elements()` でDOMを実行時に読むので事前調査は不要（むしろ過剰）。

### 2. ツール作成後は必ず統合を確認

新しいツールやモジュールを作成したら、以下を確認：

| 確認項目 | 内容 |
|---------|------|
| SKILL.md | ダンが機能の存在を認識できるか |
| executor.py | パラメータが処理されるか |
| actions/*.md | 詳細ドキュメントがあるか |

**ツールを作っただけでは使えない。SKILL.mdに記載しないとダンは機能を知らない。**

## 自己完結の原則

自分で実行できるタスクは自分で完了させる。
テスト実行・ブラウザ操作・動作確認・コマンド実行など、ツールで可能な作業をユーザーに委ねない。
「テストしてください」「確認してください」ではなく、自分でテストし結果を報告する。

## クライアント artifact の公開ルール

### ⚠️ done-artifacts 直編集の成果物（複数PC対策）⚠️

**`kittoku` など `DAN_DONE_ARTIFACTS_NATIVE_SLUGS`（既定: kittoku）に含まれる slug は、`done-artifacts` リポジトリを唯一の正として直接編集する。**

- 編集は `<done-artifacts>/src/app/artifacts/<slug>/`（＝ `frontend/` プレフィックス無し）と `<done-artifacts>/public/<dir>/` を **`git pull` → 編集 → `git commit` → `git push origin main`**。
- **D:/done 側のローカルコピー（`frontend/src/app/artifacts/<slug>/` 等）を編集しないこと。** これは各PC固有・gitignore 済みで共有されないため、別PCの古いコピーが公開時に最新版を巻き戻す事故が起きる（2026-07-18 kittoku）。
- この事故対策として、`artifact_git_publish._publish_one` は native slug のミラー公開（ローカルコピー→done-artifacts 上書き）を**スキップ**する。だから native slug は done-artifacts 直 push でしか公開されない。
- 別PC（デスクトップ）でも同じルール。どちらのPCからでも done-artifacts を pull/push すれば同じ最新版を共有できる。

---

クライアント納品物（`/artifacts/<slug>/`）の編集を**確実に公開URL（`<slug>.vercel.app`）に届ける**ためのワークフロー：

### 編集の置き場所

| 種類 | 置き場所 | 公開URLに反映される？ |
|---|---|---|
| JSXコード変更 | git commit | ✅ 自動（push → Vercel build） |
| 画像/動画ファイル変更 | git commit | ✅ 自動 |
| Inspector の text/style/attr 編集 | DB の `inspector_overrides` | ❌ **書き戻し必要** |

### 「公開して」と言われたら

1. `python scripts/inspector_writeback.py --slug <slug>` で DB の override を JSX に書き戻す
2. `git add frontend/src/app/artifacts/<slug>/` → commit → push
3. Vercel が自動デプロイ（30秒〜2分）
4. ユーザーに「mainにpushしました。約30秒〜2分で <slug>.vercel.app に反映されます」と伝える

### 「ローカルで動いた」≠ 「完了」

ライブプレビュー（`100.x.x.x:3000/artifacts/<slug>`）は DB override が適用されるので、
公開URLとは見た目が違う場合がある。完了報告の前に必ず：
1. writeback 実行（差分があるか確認）
2. commit + push
3. Vercel公開URL を curl もしくはブラウザで確認

を行うこと。

### 一時的な編集 / 試行錯誤

`/scratch/<name>` または `/demo/<id>`（後者は manifest 必須）で行う。
これらは Inspector 編集を残したまま放置してOK。クライアント納品物 (`/artifacts`) には
書き戻し未実施の override を残さない。

## 開発ワークフロー（PR方式）

本プロジェクトのファイルを変更する際は、以下のワークフローに従うこと。

### ワークフロー

1. `check_skill self-dev` でスキルを参照する
2. 自由に実装（コード変更・新規ファイル作成）
3. サンドボックスを再起動して動作確認: `curl -X POST http://127.0.0.1:9000/api/v1/sandbox/restart`
4. `git diff` で変更内容を確認
5. **`python scripts/scope_diff.py --working` で scope を確認**（次節「Scope 規律」参照）
6. ユーザーに「テスト済みです。変更内容:（日本語の要約）」と報告
7. 承認されたら以下を自動実行:
   - ブランチ作成: `git checkout -b dan/<簡潔な変更名>`
   - コミット & プッシュ: `git add → git commit → git push origin dan/<ブランチ名>`
   - PR作成: `gh pr create --title "..." --body "..."`
   - マージ: `gh pr merge --merge --delete-branch`
   - mainに戻る: `git checkout main && git pull`
8. 却下されたら `git restore .` で破棄

### 禁止事項

- ❌ テスト環境で動作確認せずに「完了」と報告する
- ❌ ログやDBを確認せずに推測で原因を断定する
- ❌ ユーザーの承認なしにmainに直接コミットする

## ⚠️ Scope 規律: 1 commit = 1 scope ⚠️

**ダン infra と成果物の変更を同じ commit に混在させてはいけない。**

これは **pre-commit hook と CI workflow で物理的に強制**されている（2026-05-21 以降）。
規則を守らない commit は技術的に作成不可能。

### Scope の分類

| Scope | 例 | コミット時の扱い |
|---|---|---|
| `infra` | `app/**`, `scripts/**`, `frontend/src/{components,lib,hooks,stores,middleware,types}/**`, ダンダッシュボード (`/chat`, `/notes` 等), `.claude/**`, `.github/**`, `supabase/migrations/**`, `mobile/**` | infra 同士なら何個でも同じ commit に入れて OK |
| `artifact:<slug>` | `frontend/src/app/artifacts/<slug>/**`, `frontend/src/app/api/<slug>/**`, 該当する `frontend/public/<dir>/**` | 同じ slug の中なら何個でも OK。**違う slug が混ざったら拒否** |
| `demo:<name>` | `frontend/src/app/{demo,scratch}/<name>/**` | 中立。他の scope と混ざってもOK（プレイグラウンド） |
| `ignored` | `.tunnel_*`, lock files, `node_modules`, `.next/`, `sandbox.log`, `.env*` | 全て自動的に scope 判定から除外 |
| `ambiguous` | どのルールにもマッチしないパス | **拒否**。`scripts/scope_classifier.py` にルール追加してから commit |

### 守らないと何が起きるか

1. **ローカル**: `git commit` の pre-commit hook (`.githooks/pre-commit` → `scripts/hook_mixed_scope_guard.py`) が混在を検出して拒否
2. **リモート**: PR 作成時に `.github/workflows/scope-check.yml` がチェック失敗にして merge をブロック

### 確認コマンド

- `python scripts/scope_diff.py` — staged ファイルの scope を表示
- `python scripts/scope_diff.py --working` — staged + unstaged + untracked
- `python scripts/scope_diff.py --branch main` — main からの差分

### 例外的に混在が必要な場合（極稀）

- ローカル: `OVERRIDE_MIXED_SCOPE=1 git commit ...`
- リモート: PR タイトルに `[scope-override]` を含める

どちらも痕跡が残るので、レビュー時に「本当に必要だったか」を必ず確認する。

### なぜこの規律があるか

2026-05-10 の `d9e49be sync(kittoku): commit local-only production state` で
ダン infra の Inspector writeback 副作用と kittoku 成果物の編集が同じ
commit に混ざり、`<MultiStepInquiry />` がそのまま削除されて本番反映。

2026-05-20 の `stash@{0} "WIP: unrelated changes"` で kittoku contact + Inspector v2
+ voice 機能 + mobile + salonboard が全部一緒に退避されて消失。

これらの事故の構造的原因は「**commit / stash が複数の論理スコープを巻き込めること**」だった。Scope 規律はその根本対策。