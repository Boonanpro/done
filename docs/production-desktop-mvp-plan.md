# 制作タブ デスクトップアプリ化 — MVP 計画書

前提：**PoC‑1/2/3 すべて GREEN**（2026-06-28, 詳細＝`docs/production-desktop-poc1-results.md`）。
エンジン素性・プレビュー合成/追従・編集即時反映が実機で裏付けられ、MVP着手の go 判定。
設計の親ドキュメント＝`docs/production-desktop-app-design.md`。

---

## 確定した方針（2026-06-28, ユーザー＋Codex＋Claude で合意）

### 1. エンジン言語＝**Rust(gstreamer-rs/ges) 本線**。Python はオラクル限定。
- 理由：本気の制作アプリが目的。Python GESサービスは最速だが配布・プロセス管理・Tauri連携・将来のRust移植が二重投資。
- **決定打**：A2(DComp一体化)は映像スワップチェーンとWebView2コンポジションを**同一プロセスで協調**させる必要がある。Pythonサイドカーだと PoC‑2 で踏んだ**クロスプロセス描画の地雷**（外部HWNDに`set_window_handle`で黒画面）を再び踏む。Rustインプロセスなら問題自体が消える。
- **Pythonハーネス（poc1/poc3/poc2_player）は捨てない**＝GES挙動の比較・parity検証・テストオラクルとして活用。

### 2. 編集の真実＝既存 `/production-assets` の **timeline JSON を唯一の真実**。
- Web/Desktop/DAN/書き出しが**同じtimeline JSON**を見る。Desktop独自形式を真実にしない。
- **schema version フィールドを入れる**（将来移行に備える）。
- `desktop_preview_state` 等のキャッシュ/プレビュー状態は**別持ち**で編集の真実に混ぜない。

### 3. **A2(DComp一体化)を Phase A で先に潰す**。
- 理由：本プロジェクトの価値は「プレビューがアプリとして一体化＆編集に即応」。DComp/ネイティブ面の位置同期・DPI・z-order・リサイズ・ちらつきが後で破綻するとエンジンが良くてもUXが死ぬ。技術リスクが高いので早期に白黒。
- **A2 合格条件**（完成度100%でなくこの線）：
  - WebView内プレビュー枠にネイティブ面が**正しく重なる**
  - **リサイズ/DPI/スクロール/表示非表示で破綻しない**
  - **黒フラッシュ無し・貼り付け感無し**（PoC‑2で見えた「別ウィンドウが間を通る/タスクビュー分離」を解消）

---

## フェーズ・マップ

### Phase A — 背骨＆一体感
| # | 内容 | 依存 | 規模 |
|---|---|---|---|
| **A0** | **Rust+GES ビルド/インプロセス再生の premise**：gstreamer-rs/ges を Windows MSVC でリンク（pkg-config/system-deps 配線、devel一式は導入済 `C:\Users\Owner\gstreamer-poc`）→ timeline をRustで組んで自前ウィンドウに再生。**PoC‑1のRust版＝言語切替の早期de-risk** | PoC harness | M |
| A1 | **Rustエンジンモジュール（インプロセス）**：`/production-assets` timeline JSON から構築＋`load/seek/play/pause/applyEdit/getState`。Pythonハーネスで parity 検証 | A0 | M |
| A2 | **DComp一体化**（WebView2 visual hosting / `CoreWebView2CompositionController`）＝上記合格条件 | A0 | L |
| A3 | 既存React制作UI（production-workspace/video-review-editor）を Tauri webview に載せる | A1,A2 | M |

→ 完了で「実プロジェクトが1つのアプリ内で本物のUIで一体表示」。

### Phase B — 操作できる（ここでNLE化）
| B1 | 再生トランスポート（play/pause/スクラブ）→ engine 配線（PoC‑1で性能実証済） | A | M |
| B2 | **編集**（カット/トリム/移動/分割）→ engine applyEdit→即時プレビュー（PoC‑3実証済）。編集は timeline JSON(schema版付き)に集約 | A,B1 | L |

### Phase C — 一周つながる
| C1 | 書き出し（サーバFFmpeg or ローカル）→ **generated asset で共通DB登録 → Web側DANが認識**（design §2の核） | B | M |

### Phase D — 製品化＆最適化（§7 known-work）
| D1 | 認証（デスクトップ用トークン/保存/更新）／ローカル素材管理／プロキシ方針／成果物アップロード経路 | C | M〜L |
| D2 | 配布（インストーラ・コード署名・自動更新・GStreamer同梱） | — | L |
| D3 | **スクラブ/ライブ編集の最適化**（デコーダプール／フルd3d11合成）＝PoC‑1/3のテール（クリップ境界デコーダ再init 150-650ms）解消で“バター感” | B | M |

---

## 主要リスク／メモ
- **A0 gstreamer-rs Windows リンク**：pkg-config 実行体の有無、`PKG_CONFIG_PATH`/`SYSTEM_DEPS_*` 配線が最初の関門。gstreamer crate のバージョンと GStreamer 1.28 の整合（必要featureを上げ過ぎない）。
- **A2 DComp**：MVP最大の不確実点。だからこそ Phase A 先行。
- **クリップ境界デコーダ再init**：スクラブ/ライブ編集のテール要因。D3で根治（プール/フルd3d11）。
- Pythonハーネスは parity オラクルとして維持（Rustで詰まったら GES 挙動切り分けに使う）。

## 現状の資産
- 検証ハーネス：`scripts/poc/production_desktop/`（poc1.py/poc3.py/poc2_player.py/poc2_overlay/）。
- GES実行環境：`C:\Users\Owner\gstreamer-poc`（1.28.4, devel一式・同梱gi=cp39）。導入レシピは PoC‑1 結果ドキュメント参照。
