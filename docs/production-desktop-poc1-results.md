# PoC‑1 結果レポート — ネイティブエンジン(GES)の素性検証

実施: 2026-06-28 / 機材: Windows 11, NVIDIA GeForce RTX 3070 (8GB) / GStreamer 1.28.4 (GES) + Python 3.9 (同梱PyGObject)
対象: room `bd05fcc0-…` の content `9aaf3bd7`「StyleUp UGC 01」= 5トラック/334クリップ/6アセット。
うちメディア260クリップ（映像98=レイヤー0／PiPオーバーレイ35=レイヤー1／台詞音声127=レイヤー2）を GES タイムラインに構築。

## 判定: ✅ GREEN（premise 成立）

ブラウザ(WebCodecs)が同一クラスのコンテンツで **OOMクラッシュ＋固まり** に陥ったのに対し、
ネイティブGESエンジンは **即時ロード・安定再生・メモリ有界（OOM無し）** を実機の数字で達成。

| 指標 | 合格条件(§5) | 実測 | 判定 |
|---|---|---|---|
| Win導入・実行 | GESがビルド/実行できる | Inno Setup形式、**昇格なしのサイレント導入**で成立。同梱PyGObject(cp39)をPython3.9で駆動 | ✅ |
| ロード(260クリップ) | 即時 | timeline構築 **0.24s** ＋ preroll(PAUSED到達) **0.14s** | ✅ |
| 再生安定 | 安定・コマ落ち無し | 60s連続再生で **1817フレーム描画 / ドロップ0 / 30.2fps**（多数のクリップ境界遷移を含む） | ✅ |
| OOM無し | クラッシュ・肥大無し | ピーク **RSS 766MB** / **GPU VRAM +54MB**、150スクラブ+60s再生でも増加せず（リーク無し） | ✅ |
| スクラブ | 即時 | 全シーク **100%成功・全て1秒未満**。下記の通り「ウォーム」と「コールド」で二極化 | ⚠️ 実用域・要最適化 |
| ハードデコード | HW利用 | **`d3d11h264dec`(DXVA)** が稼働（software avdec_h264 へのフォールバック無し） | ✅ |

## スクラブ詳細（唯一の要注意点）

フレーム精度(accurate)フラッシュシークのレイテンシ:

| シーク種別 | min | median | p95 | max |
|---|---|---|---|---|
| ウォーム（同一クリップ内＝再生ヘッドをドラッグ） | **22ms** | ~90ms | — | ~95ms |
| コールド（クリップ/アセット境界を跨ぐジャンプ） | 95ms | **160–340ms** | 400–640ms | ~920ms |

- 原因: GESの既定`nlecomposition`は **再生ヘッド直下のソースだけをアクティブ化** する。これがメモリ有界（=OOM無し）の源泉である一方、クリップ境界を跨ぐと **HWデコーダを破棄→再生成** するため 150〜650ms のコストが出る。
- 平均クリップ長 ~2.5s で隣接クリップが別アセットを参照するため、ランダムシークはほぼ毎回この「コールド再init」を踏む。
- これは premise を脅かさない **MVP段階の最適化項目**（既知の打ち手あり）:
  1. **デコーダ・プーリング/keep-warm**（境界前後のソースを先読みで保持）
  2. **フル d3d11 ゼロコピー合成パス**（現状は HWデコード→system memへdownload→software `gescompositor`。`d3d11convert`+`d3d11compositor`+`d3d11videosink` に置換でCPU転送とscrubコスト削減）

## 合成パスの実測

`d3d11h264dec`(HW) → `videoconvert`×5 / `videoscale`×2 → `gescompositor`/`compositor`(**CPU**) → sink。
**CPU合成のままでも30fps/ドロップ0** を達成 → HW合成化(d3d11compositor)でさらに余裕が出る見込み。

## 計測方法（再現手順）

- エンジンを表示系から切り離すため `fakesink`（sync=true）で計測（実画面表示=オーバーレイ統合は PoC‑2 の範囲）。`fpsdisplaysink` の rendered/dropped で再生安定を、bus の `ASYNC_DONE` 到達時間でシーク遅延を、`psutil` RSS と `nvidia-smi` VRAM をサンプリングしてメモリを測定。
- ハーネス: `poc1.py`（timeline構築→preroll→スクラブ→再生→メモリ）/ `run_poc1.sh`（環境変数とHWデコーダrank設定）。

## 導入レシピ（次セッション用・重要）

- GES本体: 公式 `gstreamer-1.0-msvc-x86_64-1.28.4.exe`（839MB, **Inno Setup 6.7.0**）。
  - WiX/MSI用の `/install /quiet` は**ハングする**。正しいのは Inno フラグ:
    `gst-rt.exe //VERYSILENT //SUPPRESSMSGBOXES //NORESTART //SP- "//DIR=C:\Users\Owner\gstreamer-poc"`（Git Bashでは`/`→`//`）。
  - **昇格不要**でユーザーフォルダに導入可（`C:\Users\Owner\gstreamer-poc`）。`ges-launch-1.0` ほか一式入る。
  - 同梱の `lib/site-packages/gi` は **Python 3.9(cp39)** 用 → システムのPython3.10では読めない。**Python 3.9** を別途導入（winget `Python.Python.3.9`, per-user）して併用。
- 実行env: `PATH=$GST/bin`, `PYTHONPATH=$GST/lib/site-packages`, `GI_TYPELIB_PATH=$GST/lib/girepository-1.0`, `GST_PLUGIN_PATH=$GST/lib/gstreamer-1.0`, `GST_PLUGIN_FEATURE_RANK=d3d11h264dec:512,nvh264dec:300`。

## 配布リスクの所見（§7関連）

- GES自体のWin導入は **成立**（地獄ではない）。ただし配布視点では: ①ランタイム ~1.2GB ②同梱PyGObjectがcp39固定 ③Inno形式の癖（MSIフラグ誤用でハング）。Tauri同梱時は GES をアプリ同梱(bundled)し、Pythonブリッジではなく **Rust(gstreamer-rs/ges)** で叩く方が配布が綺麗（Rust 1.94導入済・本命スタック）。

## 次アクション

1. **PoC‑2**: ネイティブ絵を Tauri/WebView2 のプレビュー枠に重ねる（位置/リサイズ/重なり順の同期）。
2. **PoC‑3**: カット/伸縮/移動の即時反映（seek/差し替え遅延）。
3. 上記スクラブ最適化（デコーダプール / フルd3d11合成）を PoC‑3 or MVP 初期に実装し「バターのようなスクラブ」を実証。

---

# PoC‑3 結果 — 編集の即時反映（2026-06-28）= GREEN

同一260クリップ・タイムラインに対し、代表的なNLE編集op（トリム/移動/分割/削除/PiP位置変更）を
ライブで打ち、`commit_sync` → 編集領域への flushing re-seek までを「編集→プレビュー反映」遅延として計測。
80編集・**0エラー**。

## 判定: ✅ GREEN（離散編集は実質ゼロ遅延）

| op | 反映 median | 反映 p95 | 反映 max |
|---|---|---|---|
| move（スライド） | **1ms** | 36ms | 36ms |
| delete | **1ms** | 44ms | 44ms |
| split（カミソリ） | 1ms | 864ms | 864ms |
| trim（伸縮） | 0ms | 444ms | 444ms |
| pip_move（PiP移動） | 1.5ms | 444ms | 444ms |
| **全op** | **1ms** | **246ms** | 864ms |

- 再生ヘッド直下のフレームがデコード済み（ウォーム）なら、編集はほぼ**瞬時に反映（median 1ms）**。
- テール（p95 ~250ms, max 864ms）は PoC‑1 のスクラブと**同一原因**＝編集が境界跨ぎの再シークを誘発しデコーダ再init。**同じMVP最適化（デコーダプール / フルd3d11合成）で同時に解消**。

## 再生中ライブ編集（連続ドラッグ相当）

10秒の再生中に PiP 位置を 38回変更：**クラッシュ無し・ドロップ0**。ただし1編集ごとに GES が再ネゴ
するため出力が間引かれ実効 ~11fps に低下。
→ **「一時停止して編集→再生」という通常運用は即時**。「再生しながら連続ドラッグ編集」は要最適化
（軽量ライブ更新パス or デコーダプール）。NLE編集の大半は前者なので premise は green。

メモリ: ピークRSS 553MB・0エラー。

## premise 進捗

- ✅ **PoC‑1（エンジン素性）** — GREEN
- ⬜ **PoC‑2（プレビュー面のWebView統合）** — 未着手。本質的にGUI＋Tauriビルド＋目視での位置同期確認が必要な人間ループの節目。
- ✅ **PoC‑3（編集の即時反映）** — GREEN

→ 残りは **PoC‑2 のみ**。3つgreenでMVP着手。

---

# PoC‑2 — プレビュー面の WebView 統合（2026-06-28）= 実装完了・目視検証待ち

§6 推奨①「ネイティブ・オーバーレイ面」を、**別プロセス分離**で実装：
- **Rust(wry + tao + WebView2)** がシェル。webviewに「素材パネル＋青いプレビュー枠(div)」のダミーUIを表示。
- webview の JS が preview div の矩形(devicePixel)を `window.ipc` で Rust に送信（load時＋resize＋ResizeObserver＋300ms間隔）。
- Rust は親ウィンドウの**子HWND(STATIC)をwebviewの上**に作り、その矩形へ `SetWindowPos` で追従。
- **GES映像は別プロセス**(`poc2_player.py`)が、その子HWNDに `GstVideoOverlay.set_window_handle` で直接描画（d3d11videosink、ループ再生）。
- → gstreamer-rs を Rust から直リンクせず、PoC‑1の実証済みPython harnessをそのまま映像源に再利用。

## ステータス: ✅ ビルド＆起動チェーン成立 / ⏳ 視覚的整列はユーザー目視待ち

headlessで確認できた範囲：
- `cargo build` 成功（wry 0.50 / tao 0.31 / Win32 FFIで`CreateWindowExW`+`SetWindowPos`、`windows`クレート不使用）。
- 起動で **Rustが子HWND生成→GES playerをそのHWNDにspawn→player が PLAYING(ループ)** まで到達、クラッシュ無し。
- IPC(div矩形→Rust→SetWindowPos)の配線完了。

**残（要ユーザー画面）**: 青枠に映像がピタリ重なるか／リサイズ追従の遅延・ちらつき／WebView2のairspace(ネイティブ子がweb内容の上に出るか)。これらは目視でしか判定できないため、ユーザーが起動して確認する。

## 触り方（ユーザー）

Claude Code の入力欄で（Git Bash の `!`）：
```
! bash "C:/Users/Owner/AppData/Local/Temp/claude/<session>/scratchpad/poc2_overlay/run_poc2.sh"
```
ウィンドウが開き、青い枠内に縦型UGCタイムライン(6分・260クリップ)がループ再生。**ウィンドウをリサイズ**して映像が枠に追従するか見る。閉じる＝ウィンドウを閉じる。
（repoから再ビルドする場合：`scripts/poc/production_desktop/poc2_overlay/` で `cargo build` → `run_poc2.sh`。要 GStreamer導入＋Python3.9、レシピは本書PoC‑1節。）

## premise 進捗（更新）
- ✅ PoC‑1 GREEN / ✅ PoC‑3 GREEN / 🟡 PoC‑2 実装完了・**視覚検証待ち**（OKなら3つ揃いMVPへ）
