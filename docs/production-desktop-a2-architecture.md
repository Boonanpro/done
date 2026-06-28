# A2 アーキテクチャ決定 — DComp一体化（WebView2 visual hosting）

計画書 `docs/production-desktop-mvp-plan.md` Phase A / **A2**。Phase A 最大の不確実点。
前段：A0(Rustリンク)✅ / A1(Rustエンジン parity)✅ / PoC‑2(別窓オーバーレイ=「貼り付け」限界)🟡。

## 問題（PoC‑2 の限界）
PoC‑2 は `d3d11videosink` 自前ウィンドウ(`GSTD3D11`)を **borderless+topmost+SetWindowPos** で青枠に追従させた。
が、これは**独立した最前面ウィンドウ＝「貼り付け」**：タスクビューで分離・別ウィンドウが間を通る・クリップ無し・黒フラッシュ。
原因は **HWND airspace**（子HWND webview の背後に映像を透過合成できない）。

## 決定：単一プロセス・DirectComposition ビジュアルツリー
**別ウィンドウを作らない。** 1プロセス1ウィンドウの DComp ツリーに、映像と WebView2 を**ビジュアルとして**同居させる。

```
HWND (1枚)
└ IDCompositionTarget → root IDCompositionVisual
   ├ [下] video visual   : SetContent(swapchain)  ← GES d3d12swapchainsink の swapchain
   │                       SetOffsetX/Y = プレビュー枠の矩形、clip でハミ出し抑止
   └ [上] webview visual : WebView2 (composition mode) の RootVisualTarget
                           HTML UI。#preview を transparent にして“穴”を空ける
                           → 下の video visual が穴から透けて見える＝一体化
```

- **WebView2 は composition mode**：`CreateCoreWebView2CompositionController(hwnd)` →
  `put_RootVisualTarget(webviewVisual)`、`put_DefaultBackgroundColor(透明)`、`Bounds` 設定、
  入力は `SendMouseInput`/`SendPointerInput` で転送。HWND子窓ではないので airspace 問題が消える。
- **GES→DComp の経路＝`d3d12swapchainsink`**（"DXGI composition swapchain sink"）。
  GESパイプラインの video-sink にこれを使い、`swapchain` プロパティ（DXGI composition swapchain handle）を
  video visual の `SetContent` に渡す。枠リサイズ時は sink の `resize` アクション＋visual再配置＋`device.Commit()`。
  （対抗案 `d3d11videosink draw-on-shared-texture` は手動 present が要るので不採用。swapchainsink が圧倒的に楽。）
- **エンジンは A1 の `a1_engine` を lib として再利用**（load/seek/play/applyEdit）。映像 sink だけ差し替える。
- **DPI**：per-monitor v2。枠矩形は JS が `devicePixelRatio` 込みで IPC（PoC‑2 と同じ）。

## 合格条件（計画より）
1. WebView内プレビュー枠にネイティブ面が**正しく重なる**
2. **リサイズ/DPI/スクロール/表示非表示で破綻しない**
3. **黒フラッシュ無し・貼り付け感無し**（別ウィンドウ廃止で構造的に解消）

## 段階ビルド（de-risk 順・各段スクショ自己検証）
- **✅step1**：Win32窓＋DComp device/target＋**色付き composition swapchain** を1枚合成 → スクショで magenta 矩形(478×358px)を検出。DComp自体の素性 GREEN。bin=`dcomp_color`。
- **✅step2**：その上に **composition-mode WebView2** を載せ、**不透明chrome＋透明stage** で下の映像層を透かす → スクショで「stageに映像(magenta)＋chromeが上に合成・別ウィンドウ無し」を確認。合格条件①③の核 GREEN。bin=`webview_hole`。
- **step3（次）**：色 visual を **GES `d3d12swapchainsink`**（A1で実タイムライン再生）に差し替え → stage に実映像。
- **step4**：IPCで #preview 矩形(device px = `getBoundingClientRect()*devicePixelRatio`)を受け、映像 visual をその矩形に配置/リサイズ（移動/リサイズ/DPI/スクロール追従）。黒フラッシュ無しを時間方向スクショで検証。

## step1/2 で判明した要点（実装者向け・ハマり）
- **crate ABI 統一**：`webview2-com 0.34` は `windows 0.58` 依存。DComp/D3D を叩く `windows` も **0.58 にピン**しないと COM 型(PCWSTR/IUnknown/IDCompositionVisual)が別物で interop 不可。
- **WebView2 環境/コントローラ生成**＝`webview2_com::*CompletedHandler::wait_for_async_operation`（内部でメッセージポンプ同期待ち）。COMは **STA(`CoInitializeEx(APARTMENTTHREADED)`)**。
- **DComp z-order**：`AddVisual(v, insertAbove, ref)` は ref=NULL のとき insertAbove=TRUE が**リスト先頭=最背面**。webview を映像の上に置くには ref に映像 visual を渡して明示。
- **透明は祖先全体**：ある領域で映像を透かすには、その要素と **`<html>` までの全祖先が transparent** であること。途中に1つでも不透明(`.body{background}`等)があると映像が隠れる。
- **DPI**：アプリは per-monitor-aware（physical px）だが WebView2 は CSS px でレイアウト。`#preview` の矩形は **device px(`*devicePixelRatio`)** でエンジンへ渡す（step4 IPC）。これが PoC‑2 の dpr 付き IPC の理由。
- **見た目検証**：class名 `A2WebViewHole` で `FindWindow`→`GetWindowRect`→PIL でタイトトリミング撮影（タイトルの em-dash で `FindWindow(None, title)` は不可）。`Read` ツールで PNG を直接目視できる＝ユーザー往復不要。

## 自己検証
PoC‑2 の ImageGrab/PrintWindow 自己確認パターンを継続（ユーザー往復不要で大半を検証可能）。
構造上「別ウィンドウ＝貼り付け」は廃止済みなので、最終の目視サインオフは「色味/操作感」中心で軽い。

## 環境メモ
- crates: `windows 0.59`, `webview2-com 0.34`(+sys)。Evergreen WebView2 Runtime は導入済(PoC‑2でwry稼働実績)。
- GStreamer 1.28.4 同梱（`C:\Users\Owner\gstreamer-poc`）に `d3d12swapchainsink` 在り（`d3d12` プラグイン）。
