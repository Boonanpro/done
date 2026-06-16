# インスペクタ クロスオリジン化 設計書

作成日: 2026-06-16
ステータス: 提案中（実装前・ユーザー合意待ち）
関連: 成果物リポジトリ分離（done-artifacts）、`inspector_redesign.md`（データモデルv2、実装済）

## 1. 目的と背景

成果物を別リポジトリ/別デプロイ(done-artifacts)へ分離した結果、ダッシュボードのライブプレビュー
(iframe)が **同一オリジンでなくなった**。現行Inspectorは「親(ダッシュボード)が
`iframe.contentDocument` / `iframe.contentWindow` を直接いじる」同一オリジン前提のため、
クロスオリジンでは編集が壊れる（SecurityError）。

**ゴール**: ライブプレビューの **閲覧＋Inspector編集が、ローカルでもデプロイ版でも、
成果物がどのオリジンで配信されていても動く**。

**制約（ハード）**:
- ライブ納品物(paina.info / kittoku 等)の配信方法に **一切手を入れない**（assetPrefix等の
  グローバル変更は不採用＝本番事故リスク回避）。
- **公開デプロイ(done-artifacts)はDB書き込み権限を持たない**（読み取りのみ）。保存は
  認証済みダッシュボード(親)のみが行う。
- 既存のデータ層（v2 EditModel / inspector-model / render / migrate / DB / writeback /
  publish）は **変更しない**。変えるのは「親⇄iframe の通信方式」だけ。

## 2. 採用アーキテクチャ（業界標準）

Webflow / Framer / Builder.io / WordPressブロックエディタ等と同じ
**「親エディタ ＋ 別オリジンのプレビューiframe を postMessage で通信」** 方式。

```
┌─ ダッシュボード(親, 認証済) ───────┐        ┌─ iframe(成果物, done-artifacts等) ─┐
│ ・Inspector パネルUI               │  post   │ ・要素のホバー/選択/ハイライト     │
│ ・Undo/Redo (file snapshot)        │ Message │ ・インライン編集(contentEditable) │
│ ・保存(認証付きPOST → DB)          │ ◀────▶ │ ・computedStyle等の読み取り        │
│ ・編集intentをコマンド送信         │         │ ・編集の即時(楽観的)DOM反映        │
└────────────────────────────────────┘         │ ・選択内容/編集intentを親へ通知   │
        ↑ 認証Cookieで /api へ保存              └────────────────────────────────────┘
   ※ iframe は backend へ書き込まない（読み取りすら親が代行可）
```

**役割の移動**: 現在 `frontend/src/components/preview/iframe-inspector.ts`（親側、DOM直いじり）
にある相互作用ロジックを **iframe内ランタイム**(`components/dan/inspector-runtime.tsx`)へ移す。
親はUI＋保存＋コマンド送信に専念。

### 現状の確認（調査結果）
- iframe内ランタイムは **既に**: `[data-edit-id]` 列挙・キー計算(`computeElementKey`)・
  override適用(`applyModelToElement`)・v1→v2移行 ができる（自己完結）。
- iframe内ランタイムに **無い**（今は親のiframe-inspector.tsにある）: ホバー/選択/
  インライン編集/プロパティ読み取り/**postMessage**。これらを移植する。
- 保存APIは全て **body駆動**(`artifact_slug` + `element_key` + `styles`/`attrs`)で、
  リクエスト元が成果物ページである必要は **無い**。親(認証済)が全保存を代行できる。

## 3. postMessage プロトコル（契約）

双方向。両側で `event.origin` を許可リスト検証する（親は成果物配信オリジン、iframeは
ダッシュボードオリジンを許可）。メッセージは全て JSON シリアライズ可能。

### iframe → 親
| type | payload | 用途 |
|---|---|---|
| `inspector:ready` | `{slug}` | ランタイム起動完了。親はこれを待ってモード/overridesを送る |
| `inspector:selected` | `{elementKey, tagName, rect, computedStyles(必要分), text, className, ancestors[], bgColor, isTextLeaf, media?{src,alt,...}}` | 要素クリック時の選択スナップショット（現行 `selectElement` payload相当。**liveTarget参照は渡さない**） |
| `inspector:hover` | `{elementKey, rect}` | ホバー中要素（任意。オーバーレイはiframe内で描くので親は不要にできる） |
| `inspector:text-committed` | `{elementKey, model(EditModel)}` | インライン編集確定 |
| `inspector:selection-range` | `{elementKey, start, end}` | 部分テキスト選択（**UTF-16オフセット**。live Rangeは渡さない） |
| `inspector:reloaded` | `{}` | iframe内ナビゲーション/再描画後（親は再度モード/overridesを送る） |

### 親 → iframe
| type | payload | 用途 |
|---|---|---|
| `inspector:set-mode` | `{mode: 'off'|'edit'|'comment'}` | 編集/コメント/無効の切替（iframeがリスナ/オーバーレイをON/OFF） |
| `inspector:apply` | `{elementKey, model|styles|attrs}` | 編集を即時DOM反映（楽観的）。スライダー連続操作もこれ |
| `inspector:apply-overrides` | `{overrides: [{element_key, styles, attrs}]}` | 既存overrides一括適用（編集モード開始時に親が認証付きで取得して投入） |
| `inspector:clear-selection` | `{}` | 選択解除 |
| `inspector:request-snapshot` | `{elementKey}` | パネルが最新computedStyleを要求 → iframeが `inspector:selected` で返す |

### 廃止される同一オリジン依存（postMessageに置換）
- `liveTarget: Element`（親state保持）→ `selectedElement` メタデータ＋`elementKey` のみ
- `selectedRange: Range`（親state保持）→ `{start,end}` オフセット
- `iframe.contentWindow.getComputedStyle` / `iframe.contentDocument` 直アクセス → 全て上記メッセージ
- `window.__DAN_INSPECTOR__` 横断呼び出し → iframe内ローカル呼び出し＋メッセージ

## 4. 保存フロー（クロスオリジン適合への変更）

**現状**: 既定保存は `/direct-write`（D:/doneディスク上のJSXを直接書換）。ローカルfrontendの
HMRで即反映される前提。→ クロスオリジンではiframeがdone-artifacts配信を見るので、
ローカルJSX書換はpublishまで反映されない。

**新設計**:
1. 編集 → iframeが **楽観的に即時DOM反映**（`inspector:apply`、リロード不要で即見える）
2. 親が **DBへupsert保存**（認証付き `POST /api/v1/inspector-overrides`）
3. 編集モード開始時、親が認証付きで overrides を取得 → `inspector:apply-overrides` でiframeへ投入
   （iframeはbackendに触れない＝公開デプロイは読み取り権限すら不要）
4. 公開反映は従来通り `inspector_writeback.py`（DB override → JSX焼込）→ `artifact_git_publish.py`
   → done-artifacts へ publish。焼込後にoverride行は削除（既存挙動）

これにより「編集中＝楽観反映＋DB永続」「公開＝JSX焼込（フラッシュ無し・DB非依存）」が両立。
フラッシュは既存の pre-paint(localStorage)スクリプトで緩和。

## 5. コードの置き場所と vendor 同期

Inspector関連は全て infra(`D:/done/frontend`) にあり、iframe内ランタイム部分は
done-artifacts にコピー(vendor)済み。本設計で **iframe内ランタイム**を拡張するため、
変更は done-artifacts 側にも反映が必要。

**方針**: `components/dan/inspector-runtime*` と `lib/inspector-*` を「成果物ランタイムの
共有ソース」として、変更時に done-artifacts へ同期する手順を1つにまとめる（`scripts/
sync_inspector_runtime.py` 等）。親側(`preview/*`)はダッシュボード専用なので done-artifacts
には不要（むしろ置かない）。

## 6. 実装ステップ（各段でユーザー確認）

| # | 内容 | 検証 |
|---|---|---|
| 1 | 本設計合意 | - |
| 2 | postMessageプロトコルの型定義＋origin許可リスト（親/iframe共通の型ファイル） | typecheck |
| 3 | iframe内ランタイムに「選択・ホバー・ハイライト・プロパティ読取・インライン編集」を移植（iframe-inspector.ts のロジックを移す） | **使い捨てデプロイ**で単体動作 |
| 4 | 親(preview-pane/iframe-inspector/inspector-panel/stores)を postMessage 駆動に書換（liveTarget/Range 廃止） | ローカル(同一オリジン)で従来同等に動くこと |
| 5 | iframe src をクロスオリジン(done-studio)へ。保存をDB upsert＋楽観反映＋overrides投入に | **使い捨てデプロイのダッシュボード**でクロスオリジン編集が動くこと |
| 6 | done-artifacts へランタイム同期、本番ダッシュボードで検証（ライブ納品物に影響しないこと） | 本番デプロイ版で編集動作＋既存サイト無影響 |
| 7 | コメントモード/Undo-Redo/画像/動画セクションの postMessage 対応確認 | 全機能 |
| 8 | 旧同一オリジンコード削除、ドキュメント更新 | - |

ステップ3→5は使い捨てデプロイで段階検証し、本番(ステップ6)は無影響確認後のみ。

## 7. リスクとロールバック
- **リスク**: 相互作用ロジックの移植は範囲が大きい（選択/ドリル/インライン編集/部分選択）。
  → 段階的に使い捨てデプロイで検証。ライブ納品物の配信には触れないので本番事故リスクは低い。
- **コメントモード**: 既にserializableな`selectedElement.rect`依存で、選択捕捉部分のみpostMessage化すれば動く。
- **ロールバック**: iframe src を相対(同一オリジン)に戻し、親を旧コードに戻せばローカル編集は即復旧。
  プロトコルは追加なのでDB/データ層は不変＝破壊しない。

## 8. ユーザー確認が必要な点
1. 保存先を `/direct-write`(JSX直書) から **DB upsert＋楽観反映＋writeback** に寄せる方針でよいか
   （クロスオリジン適合のため。公開JSXは従来通りwritebackで焼込）
2. iframe内ランタイムの done-artifacts への同期は「変更時に同期スクリプトで反映」でよいか
3. ステップ3/5/6 の使い捨てデプロイ検証 → 本番反映の段取りでよいか
