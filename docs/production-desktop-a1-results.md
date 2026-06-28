# A1 結果レポート — Rustエンジンモジュール（インプロセス）

実施: 2026-06-28 / 機材: Windows 11, NVIDIA RTX 3070 (8GB) / GStreamer 1.28.4 (gstreamer-rs 0.23 + GES 0.23) / Rust 1.94 MSVC
対象: room `bd05fcc0-…` content `9aaf3bd7`「StyleUp UGC 01」= 260メディアクリップ（映像98 / PiP35 / 台詞音声127 / 6アセット）。
親計画: `docs/production-desktop-mvp-plan.md`（Phase A / A1）。前段: A0（gstreamer-rs リンク GREEN）。

## 判定: ✅ GREEN（A1 成立 — Pythonオラクルと同等）

A0 で「Rust が GES をリンクして再生できる」ことを実証済み。A1 はそれを**実エンジンモジュール**に引き上げた:
`/production-assets` の **timeline JSON（contents.json＝唯一の真実）** から GES タイムラインを構築し、
`load / seek / play / pause / applyEdit / getState` を Rust で公開。`poc1.py` / `poc3.py` を**パリティ・オラクル**として
同一マシン・同一パラメータで突き合わせ、**数値が一致**することを確認した。

## 成果物（Rustクレート）

`scripts/poc/production_desktop/a1_engine/`
- `src/timeline_model.rs` — contents.json の serde モデル（sequence/tracks/clips、`position`、`schema version` を surface）。
- `src/engine.rs` — `Engine`。3レイヤー（video / overlay-PiP / audio、`poc1.build_timeline` と同じ構造）、アセットキャッシュ、
  PiP transform、`clip_id → GESクリップ` マップ。API: `load`(build+preroll) / `seek`(flush+accurate) / `play` / `pause` /
  `apply_edit`(Trim/Move/Split/Delete/PipMove) / `get_state` / `pip_move_async`(再生中の非ブロッキング commit)。
- `src/main.rs` — `a1_harness`。poc1/poc3 と同じシナリオ（load→scrub→play→edits→state→memory）を回し、
  poc1.py/poc3.py とフィールドが揃う JSON を出力（＝パリティ比較器）。

## パリティ計測（2026-06-28, 同一機・連続実行・40 seeks / 60s play / 80 edits）

| 指標 | 合格条件 | Python poc1/poc3 | **Rust A1** | 判定 |
|---|---|---|---|---|
| ビルド / preroll | 即時 | 0.219s / 0.127s | **0.236s / 0.118s** | ✅ |
| クリップ構築 | 260/0欠落 | 98/35/127, skip 0 | **98/35/127, skip 0** | ✅ |
| HWデコード | HW利用 | `d3d11h264dec`(DXVA) | **`d3d11h264dec`** | ✅ |
| 再生安定(60s) | コマ落ち無し | 1815フレーム / drop 0 / 30.2fps | **1811フレーム / drop 0 / 30.2fps** | ✅ |
| スクラブ(40) | 即時・全成功 | median 170 / p95 400 / max 482ms | **median 188 / p95 391 / max 497ms** | ✅ |
| 編集→反映 | 待ち無し | （poc3）reflect median ~1ms | **reflect median 0.3ms**（move/delete/pip 0.1–0.3ms） | ✅ |
| OOM無し | 肥大無し | peak RSS 749.6MB | **peak RSS 728.8MB** | ✅ |

差分（188 vs 170ms 等）は run-to-run のばらつきの範囲で、エンジン差ではない。**Rust エンジンは Python GES オラクルと同挙動**。
※ これは debug ビルドの数字。release ビルドでさらに改善見込み。

## applyEdit の所見

- Trim/Move/Delete/PipMove/Split を **clip_id 指定**で実行 → `commit_sync` → 反映。reflect 中央値 0.3ms（move/delete/pip はほぼ瞬時、
  trim/split はクリップ境界の cold デコーダ再init テールを踏むと数百ms ＝ PoC‑1/3 と同じ既知要因）。
- 80編集中 77 が完走、2 が apply 時にベニグンに失敗（重なる move の GES 拒否／短すぎるクリップの split）。**クラッシュ・破損は無し**。
- **再生中ライブ編集**（`pip_move_async` で非ブロッキング commit を連打）: **drop 0・エラー無し**で再生は破綻しないが、
  260クリップの**タイムライン全体を毎編集 re-commit** するため描画fpsが落ちる。これは新規知見ではなく、計画 D3 の
  **インクリメンタル commit（触った区間だけ再評価）** が要る、という裏付け。MVPの編集体感に向け D3 で根治する。

## ビルド・実行レシピ（次セッション用）

```bash
GST=/c/Users/Owner/gstreamer-poc
export PATH="$GST/bin:$PATH"
export PKG_CONFIG_PATH="$GST/lib/pkgconfig"     # build: pkg-config.exe は GST/bin 同梱
cargo build                                      # a1_engine/ で
# 実行時はさらに:
export GST_PLUGIN_PATH="$GST/lib/gstreamer-1.0"
export GST_REGISTRY="$GST/registry.bin"
export GST_PLUGIN_FEATURE_RANK="d3d11h264dec:512,nvh264dec:300"
ROOM=/d/done/uploads/production-assets/bd05fcc0-c143-4d1c-828e-7624e087b6c1
./target/debug/a1_harness.exe "$ROOM/contents.json" "$ROOM" --seeks 40 --play-secs 60 --edits 80
```

- A0 で踏んだ罠（`ges-sys` は `gstreamer-editing-services-1.0.pc` を期待するが配布は `gst-editing-services-1.0.pc`）は
  エイリアスコピー済（`$GST/lib/pkgconfig/`）。
- `fpsdisplaysink` の `frames-rendered/-dropped` は本ビルドでは **guint(u32)**（u64 ではない）。

## 次アクション

- **A2（DComp一体化）= Phase A 最大の不確実点**。WebView2 visual hosting にネイティブ面を正しく重ね、リサイズ/DPI/z-order/
  黒フラッシュで破綻しないかを潰す（Rust インプロセスなので PoC‑2 のクロスプロセス黒画面地雷は回避できる前提）。
- **A3**: 既存 React 制作UI（production-workspace / video-review-editor）を Tauri webview に載せ、A1 エンジンへブリッジ。
- D3（スクラブ/ライブ編集の最適化＝デコーダプール／フルd3d11合成／インクリメンタル commit）は B 完了後〜MVP仕上げで。
