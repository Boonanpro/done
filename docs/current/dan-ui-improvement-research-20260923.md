# Dan UI改善：調査結果と実施基準

調査日：2026-09-23。対象：PCブラウザ、Android APK、制作エディター。

後続の実装・検証状態は [初回実装レポート](dan-ui-first-pass-20260923.md) を参照。以下の「現在地」は調査完了時点の記録。

## 結論

中心に据えるのは、操作設計の `product-design`、画面品質を扱う `Impeccable` の Operate 方針、実装別の Vercel スキルと公式プラットフォーム指針。Taste Skillを全画面へ適用する方式は採らない。

目指すのは、会話・制作物・現在の作業・次の操作を迷わず見つけられ、作業を中断しても戻れるDan。共通の用語・状態・視覚的な優先順位を揃え、PCのマウス／キーボードとAndroidのタッチ操作は別に設計する。

これは適合性を比較した採用判断であり、スキル間の出力品質を実測した優劣ではない。スキル導入だけでUIが改善されたとは扱わない。

## 現在地

- 完了：外部候補の一次資料確認、主要な実装の所在確認、初期コード調査、採用スキルの追加、改善順序と検証条件の策定。
- 今回追加したスキルは開発側の `C:/Users/Owner/.codex/skills/` 配下。次のターンから自動認識対象になり、この調査では本文を直接参照した。
- Dan自身のスキルローダーやランタイムプロンプトは変更していない。Danの会話で自動選択されることまで確認したという意味ではない。
- UI実装・本番配信・新APK配布は未実施。ライブ会話や編集中のプロセスは停止していない。
- `adb devices` に接続端末なし。実機タッチ、IME、TalkBack、通話継続の合格判定はまだできない。
- 制作エディターのネイティブ画面とブラウザ画面は両方を調査対象に含めた。優先対象はユーザーに任意確認中。回答なしでも両者の構造調査は成立する。

## スキル比較と役割

| 候補 | 確認した強み | 採用判断・限界 |
| --- | --- | --- |
| [product-design](C:/Users/Owner/.codex/skills/product-design/SKILL.md) | 操作の対象・範囲・結果、復帰、到達可能な状態を明文化 | 既存。操作設計の中心。ビジュアル実装は別担当 |
| [Impeccable](https://github.com/pbakaus/impeccable/blob/main/plugin/skills/impeccable/SKILL.md) | アプリ・管理画面・エディターを対象に、設計、整理、状態、レスポンシブ、監査を扱う | 新規導入。Operate方針を採用。装飾的な制約やワークフローを無条件に移植しない |
| [Vercel Web Design Guidelines](https://github.com/vercel-labs/agent-skills/blob/main/skills/web-design-guidelines/SKILL.md) | 名前・フォーカス・フォーム・ジェスチャー・状態などのコード監査 | 新規導入。Web側の確認。見た目や使いやすさの実地確認を代替しない |
| [Vercel React Native Skills](https://github.com/vercel-labs/agent-skills/blob/main/skills/react-native-skills/SKILL.md) | React Native / Expoの一覧・状態購読・描画・ネイティブ操作 | 新規導入。APK実装の補助。FlashList、Reanimated等への一律置換はせず、問題と効果を確認して採用 |
| [Taste Skill](https://github.com/Leonxlnx/taste-skill/blob/main/skills/taste-skill/SKILL.md) | LP・ポートフォリオ・リデザインの視覚的方向付け | 本体UIの中心には不採用。冒頭でダッシュボード・データ表・複雑な製品UIを対象外としている。マーケティング制作時の別候補 |
| [UI UX Pro Max](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill/blob/main/.claude/skills/ui-ux-pro-max/SKILL.md) | スタイル・配色・文字・実装別ルールの検索資料 | 比較資料として確認。今回必要な操作監査との重複が多く、追加導入は見送り。スタイル数を品質の根拠にしない |
| Apple Human Interface Skills | 階層、視認性、部品、アクセシビリティ | 既存。普遍的な原則のみ補助利用。AndroidやWindowsをApple風へ揃える根拠にはしない |
| ui-animation | 状態遷移・ジェスチャー・動きの検証 | 既存。動きが必要な箇所に限定。ページ登場演出の追加は目的にしない |

Impeccableは取得時の本文で4.3.1。導入ファイルのハッシュと出所は `scratch/dan-ui-research-20260923/installed-skills.json` に記録する。

## 実装と適用範囲

| 面 | 実装の所在 | 適用方法 |
| --- | --- | --- |
| PCブラウザ | `frontend/`：Next.js 16、React 19、Tailwind 4、Radix、Lucide。`src/components/layout/main-layout.tsx` / `sidebar.tsx` / `project-chat-panel.tsx` | 既存部品を使い、情報階層・ナビゲーション・プレビューと会話の関係を整理 |
| APK | `mobile/App.tsx`、`voice*.tsx`、`collab.tsx`。Expo 54、React Native 0.81 | WebのCSS修正では反映されない。ネイティブの操作領域、Back、safe area、IME、文字倍率を個別に設計 |
| ブラウザ制作画面 | `frontend/src/components/production/production-workspace.tsx`、`video-review/video-review-editor.tsx` | プロジェクト、素材、レビュー、編集、書き出しの現在地を明示 |
| PCネイティブ編集画面 | `scripts/poc/production_desktop/native_ui/src/main.rs`。Rust / eframe / egui 0.29 | テキスト・選択・タイムライン・パネル・ショートカットをネイティブ実装で改善。Web部品への移植は不要 |
| エディター内の相談画面 | `native_ui/src/assistant_panel.rs` が Wry WebView で `http://127.0.0.1:8000/api/v1/editor-assistant/page` を読み込む。`app/static/editor-*`、`app/api/editor_assistant_routes.py` | Web側の改善が関係するが、Nextのビルドとは別系統。ネイティブとのフォーカス・作品コンテキストの受け渡しも確認 |

`docs/current/README.md` には旧v2構想の記述があるため、現行UI構造の根拠は実装と最近の対象別ドキュメントを優先した。

## 初期調査で確認できたこと

以下はソース確認に基づく改善候補。実機／ブラウザ操作で再現した不具合とは区別する。

| 優先度 | 場所と証拠 | ユーザーへの影響・次の確認 |
| --- | --- | --- |
| P1 | `main-layout.tsx`：プレビュー中のサイドバーを画面外へ移し、左端のマウスホバーで表示 | メニューが見つけにくい可能性。キーボードで表示・選択・復帰できるかを実地確認し、必要なら見える開閉操作を設ける。`rule/keyboard-complete-flow` |
| P1 | 同ファイル：幅調整が `div` の `onMouseDown` / mousemove | マウス以外の同等操作がこの実装にはない。既存の折りたたみとの関係を確認し、キーボード／単クリック代替を設計。`rule/gesture-has-control-alternative` |
| P1 | 同ファイル：モバイルメニューボタンに名前なし。背景クリックと条件描画で開閉 | 読み上げ名・フォーカス制御・Escape・閉じた後の復帰が必要。既存Radix部品の活用を検討。`rule/accessible-name-required`、`rule/keyboard-complete-flow` |
| P1 | `mobile/App.tsx`：チャットの戻る・検索などに明示的なaccessibilityLabelなし | ネイティブツリーで読まれる名前を確認。マイクには名前があり、同じ基準へ揃える。`rule/accessible-name-required` |
| P2・要実測 | 同ファイル：アプリバーのボタンは40単位、呼び出し側にhitSlop=10あり | 見た目40だけでタッチ領域不足とは断定できない。隣接領域の競合・親による制限も含め、実機で48dpを満たす操作領域を確認 |
| P2 | Webは無彩色トークン、APKは暖色系背景＋緑、ネイティブは青いアクセント | 相違自体を欠陥としない。まず「選択」「主操作」「実行中」「失敗」の意味を共通化し、対象別の配色へ写像する |
| P2・仮説 | 9月23日保存の `scratch/conversation-lifecycle-20260923/new-project.png` | 相談画面は大きなオーブと右の相談メモ。次の入力方法や進行状態の伝わり方を評価対象にする。保存画像であり現在のネイティブ全体の確認ではない |

Impeccableの機械検出を `main-layout.tsx` と `production-workspace.tsx` に実行し、結果は空配列。`scratch/dan-ui-research-20260923/web-detector.json` に保存。これは上記の手動所見を否定せず、アクセシビリティ・操作・視覚品質の合格判定にもならない。全画面を採点できる証拠はまだないため、総合点は付けない。

## 設計方針

### 共通

- 主役は会話と成果物。各面の主要操作を一つに定め、補助操作を段階的に開示する。`rule/one-primary-action`、`rule/structure-before-containers`。
- 「選択中」「フォーカス」「実行中」「保存済み」「失敗」を色だけに依存せず区別する。`rule/cover-reachable-states`。
- 日本語本文は読みやすい行間を確保し、名称が長くても主操作が押し出されない。値・時刻・タイムコードの桁を揃える。
- サーフェス、文字、境界、選択、フォーカス、成功、注意、失敗の意味別トークンを定義。Web CSS変数・RNのテーマ定数・Rust定数に写像し、DOM部品の共有は要求しない。
- 静かな背景、明確な文字階層、操作時の短い反応を基本にする。ブランド色・全面的なテーマ変更は現行画面の比較後に決める。全画面へのダーク／ライト両対応を今回の当然の前提にしない。
- 新しい設定やライブラリより、既存の操作・部品・適切な既定値で解決する。`rule/smallest-intervention`。

### PCブラウザ

会話一覧 → 会話 → 成果物／プレビューの位置関係を明確にする。プレビューに集中しても別の会話や元の画面への戻り方が見える。メニュー、パネル開閉、幅変更はマウスとキーボードで行え、隠れた領域へフォーカスが迷い込まない。

### Android APK

片手で会話、音声、成果物へ移れる配置を評価する。OSの戻る操作とアプリの戻る操作を揃える。キーボード表示時も入力欄・送信・エラーが見える。通話を最小化しても「誰／どの部屋と通話中か」が残る。画面移動だけで通話先を切り替えない。

Androidの48dp操作領域を設計基準にする。WebのWCAG 2.5.8の24 CSS px基準（例外あり）とは単位も適用対象も別。ブラウザの狭幅スクリーンショットをAPK実機確認の代わりにしない。

### 制作エディター

選択中の作品／クリップ、現在時刻、変更対象、保存状態、書き出し状態を把握できる構造にする。プレビューは制作物、タイムラインは時間、インスペクターは選択対象の設定、相談画面はDanへの依頼を担う。

高度な操作を隠しすぎず、よく使う操作と詳細操作を整理する。ドラッグには数値入力やメニュー等の代替を検討する。相談中の作品と閲覧中の作品、保存と公開を混同させない。Undoは実際に戻せる範囲だけ提供する。`rule/name-object-scope-consequence`、`rule/undo-only-when-honest`。

## 主要フローの状態と検証

| フロー | 設計・確認する状態 | 完了条件 |
| --- | --- | --- |
| 会話を見つけて開く | 初回、一覧読込、0件、検索0件、長い名前、通信失敗 | 検索0件から条件を解除でき、既存会話を誤って再作成しない |
| 送信する | 入力、送信中、応答待ち、失敗、再接続 | 入力が失われず、再試行で重複送信しない。失敗理由と次の操作が分かる |
| 音声で話す | 権限未許可、接続中、通話中、ミュート、最小化、切断 | 通話先とマイク状態が分かり、終了できる。現行バックグラウンド／Bluetooth動作を回帰確認 |
| 制作物を編集する | 未選択、選択中、変更中、保存中、保存済み、保存失敗、外部更新 | 何に変更を加えるか明確で、復帰／Undoが実態と一致 |
| 書き出す | 設定、実行中、成功、失敗、キャンセル可能／不可 | 保存と書き出しと公開を区別し、実際のファイルを開いて成功を確認 |

全フローに `rule/cover-reachable-states`。入力を伴うフローに `rule/preserve-user-input`。存在しない状態やキャンセル機能を見た目だけで追加しない。

## 実施順序

1. **現行の画面・操作を記録**：PC、APK、ネイティブ編集、埋め込み相談を区別。画像、再現手順、ソース、実行ビルドの対応を記録。機能を残すための基準にする。
2. **操作上の障害を解消**：名前・フォーカス・戻る・入力維持・隠れた主操作を優先。各修正は実際の操作と画面を確認。
3. **共通の視覚基準を適用**：文字階層、余白、境界、選択、状態、ボタンの強弱。まず会話の一覧／入力とエディターの主要パネルで比較し、対象範囲に展開。
4. **面ごとの操作を改善**：PCのパネル、APKの片手操作とIME、編集画面の選択・時間・保存・書き出し。全面置換より既存機能を保持できる単位で進める。
5. **対象ごとに検証・届ける**：Webは必要なビルドと実URL確認、APKは同一署名でビルドして実機確認、ネイティブは実行ファイルと埋め込みWeb両方を確認。ソース保存／試験ビルド／本番反映を明確に区別。

PC用検証候補：1440×900、1280×720、キーボードのみ、200%拡大、長い日本語、Reduced Motion。Webモバイル用：390px幅、狭幅、ソフトキーボード相当の領域変化。APK：実端末、通常／拡大文字、IME、Back、TalkBack、画面復帰。ネイティブ：Windowsの125/150%表示倍率、パネル切替、入力中のショートカット、再生／保存／Undo。

検証は変更した挙動に絞ってまとめて実施し、失敗を直した後に確認する。見た目だけの変更を本番の生成・有料API・全アカウント試験へ拡大しない。

## 指示が競合する場合

- ユーザー要件と `D:/done/AGENTS.md`、既存データ・会話の継続を優先する。
- ImpeccableのOperate方針を採り、LP向けの演出・文字幅・装飾ルールをツールバーやタイムラインへ機械的に適用しない。
- Materialの指針はAndroidの操作設計に使う。Composeへの作り直しや新たな部品ライブラリ導入を必須にしない。
- RNスキルの推奨ライブラリは自動導入しない。現行依存・計測・アクセシビリティを確認する。
- Vercelの英語表記規則は日本語UIへ直訳適用しない。
- 外部スキルの採用を、Danのグローバルプロンプトを大量に増やす理由にしない。作業対象に必要な参照だけを使う。

## 一次資料

- [Impeccable：Operate](https://github.com/pbakaus/impeccable/blob/main/plugin/skills/impeccable/reference/operate.md)
- [Vercel Web Interface Guidelines](https://github.com/vercel-labs/web-interface-guidelines/blob/main/command.md)
- [React Native：Accessibility](https://reactnative.dev/docs/accessibility)
- [Android：Accessibility / touch targets](https://developer.android.com/guide/topics/ui/accessibility/views/apps-views)
- [Android：Adaptive apps](https://developer.android.com/develop/ui/compose/layouts/adaptive/get-started-with-adaptive-apps)
- [Android：Input method visibility](https://developer.android.com/develop/ui/views/touch-and-input/keyboard-input/visibility)
- [Windows：Keyboard interactions](https://learn.microsoft.com/en-us/windows/apps/develop/input/keyboard-interactions)
- [WCAG 2.2：Dragging Movements](https://www.w3.org/WAI/WCAG22/Understanding/dragging-movements.html)
- [WCAG 2.2：Target Size Minimum](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html)

公式指針の対象フレームワークとDanの実装は異なる場合がある。操作・検証の原則と、実装コードの互換性を区別する。
