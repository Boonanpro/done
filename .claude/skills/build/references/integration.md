## 1. 不変条件（配線。ここだけは必ず守る）

### 1-1. 置き場所と page 構造

- 成果物は **`frontend/src/app/artifacts/<slug>/`** に作る（クライアント案件も社内LPも同じ）。
  独立した Next.js プロジェクトは切らない。`demo/` `scratch/` は試行錯誤用。
- `page.tsx` は **server component** にして `release.gen.json`（初期値 `{}` で作る）を
  `EditableProvider` に渡し、本体は `"use client"` の `page-body.tsx` に書く:

```tsx
// page.tsx（server）
import { EditableProvider } from "@/components/dan/editable";
import { toEditableOverrides, type ReleaseOverrides } from "@/lib/editable-release";
import releaseJson from "./release.gen.json";
import { PageBody } from "./page-body";

export default function Page() {
  return (
    <EditableProvider overrides={toEditableOverrides(releaseJson as ReleaseOverrides)}>
      <PageBody />
    </EditableProvider>
  );
}
```

  新規 slug はこの雛形を `python scripts/editable_artifact.py init --slug <slug> --title "…"` で
  作れる（既存 slug には実行しない。保存済み編集が消える）。
- `layout.tsx` は server component にする（favicon の `metadata.icons` が書けるように）。
  client の中身は `theme-shell.tsx` 等に分離する。実例: `artifacts/kittoku`。

### 1-2. 編集対象は `EditableText` / `EditableElement`（`data-edit-id`）

ユーザーが手動編集・チャット編集で触りうる要素には、`@/components/dan/editable` の
`EditableText`（文字）・`EditableElement`（画像・セクション・複合要素）を使い、
**durable な ID** を付ける。ID が無いと DOM パスで識別され、構造が変わると編集が孤立し、
同構造の別ページと衝突し、公開ページに反映されない。

- ID は `{slug}-{page}-{role}` 形式で全ページ通してユニーク。チャット修正でも維持する。
- 付ける: h1〜h4、本文 `<p>`、CTA の `<a>`/`<button>`、主要な `<img>`/`<video>`、
  余白や背景を編集させたい `<section>`。
- 付けない: 単なるラッパー div、アイコン専用 span。`map()` で生成する項目は並び順でなく
  項目の安定キーで ID を作る。
- 共通フッター・共通ナビを複数ページで同じ ID にして「1回の編集で全ページ反映」させるのは仕様。
- 公開済み編集（`release.gen.json` に載っている editId）は **JSX を書き換えても公開ページに
  出ない**（オーバーライドが勝つ）。チャットで文言を直す前に必ず `release.gen.json` を見て、
  載っていれば公開済みテキストを土台に JSX を直し、`inspector_overrides` の draft 行を更新
  または削除して再公開する。
- 文字は画像に焼き込まず、ネイティブなテキスト要素にする。alt や透明テキストは編集可能性の
  代わりにならない。

### 1-3. ヒーロー画像・動画の暗転/ぼかしは媒体自体の CSS で行う

`<img>`/`<video>` の上に半透明の overlay `<div>` を重ねると、インスペクタで媒体をクリック
選択できず、Overlay スライダーも効かない。暗転は `filter: brightness()`、ぼかしは
`filter: blur()`、方向フェードは `mask-image` を **媒体自体に** 当てる。
`<HeroMedia kind="video|image" src darken blur fade>` がこれを済ませてある。
自前で書く場合も同じ原則で書く（`alt`、`autoplay loop muted playsInline` を忘れない）。

### 1-4. ログイン / 初期設定ゲートは `useSetupGate`

ログインや初回登録が必須なページでは `@/hooks/use-setup-gate` の `useSetupGate` を使う。
チャット右ペインのプレビューは iframe なので、自前ゲートだとプレビューでもログインを求められ
編集できなくなる。`useSetupGate` はプレビュー（`isDanPreview()`）を検出して自動でバイパスする。
実例: `artifacts/salonboard-styleup/page.tsx`。

### 1-5. Tailwind のスキャン漏れ

`artifacts/<slug>/` は `.gitignore` 対象で、Tailwind v4 の自動ソース検出は `.gitignore` を
尊重する。成果物の中でしか使わないクラス（`max-w-[34rem]`、`xl:` など）が **無言で無視**
される。`hook_register_artifact.py` が `scripts/wire_artifact_tailwind_sources.py` を自動で
走らせるが、手で slug を作った直後にレイアウトが効かない時はこれを実行する。

### 1-6. 登録＝公開、リンク、ドメイン

- `artifacts/<slug>/page.tsx` を書くと PostToolUse hook (`hook_register_artifact.py`) が
  dan-core の登録API (`POST /api/v1/chat/internal/artifacts/register`) に渡し、公開処理を依頼する。登録だけで公開成功とは判断せず、状態と実URLを確認する。公開URLは成果物カードの `share_url` に入る。
  hook 以外の場所（サンドボックスやスクリプトの裏方スレッド）で公開を起こさない。
  再公開は `POST /api/v1/chat/internal/artifacts/<artifact_id>/publish`。
  手動登録: `echo '{"tool_name":"Write","tool_input":{"file_path":"<絶対パス>"}}' | DAN_ROOM_ID=<room> DAN_PROJECT_ID=<project> python scripts/hook_register_artifact.py`
- 成果物内のページ間リンクは `next/link` ではなく `@/components/artifacts/artifact-link` の
  `ArtifactLink`（`/preview/<slug>`・`/artifacts/<slug>`・独自ドメインを混ぜないため）。
- 独自ドメインは middleware の `ARTIFACT_CUSTOM_DOMAINS` / `NEXT_PUBLIC_ARTIFACT_CUSTOM_DOMAINS`
  に `slug=domain.example` で追加。
- favicon は hook が自動生成して `layout.tsx` の `metadata.icons` に焼き込む。差し替えは
  `python scripts/set_artifact_icon.py --slug <slug> --image <path>`（画像生成は自分でやる）。

### 1-7. ダン管理画面（ダッシュボード）はダンの UI 体系に合わせる

ダンのダッシュボード内に置くページは既存画面と同じ操作感にするため、`globals.css` の
セマンティックトークン（`bg-background` `text-foreground` `text-muted-foreground`
`border-border` `bg-primary` …）と `frontend/src/components/ui/` の shadcn/ui、Lucide アイコン
を使う。チャートは shadcn の chart（Recharts）。サイドバーに導線を足す。

**これはダッシュボード限定**。クライアント HP・LP・ブランドページは成果物内で固有の配色・
書体・部品を自由に定義してよく、shadcn を使う義務はない。

### 1-8. 変更の分離

成果物と ダン infra は同じ commit に混ぜない（`AGENTS.md` の変更分離）。
既存成果物は現在の公開サービスでsource ownershipとnative slug処理を確認し、保存先を維持する。共有作業ツリーをそのままデプロイしない。

---

