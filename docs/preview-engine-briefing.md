# 制作タブ・プレビューエンジン 相談用ブリーフィング

外部レビュー（Codex等）に「現状のコードを見てもらいながら今後の方針を相談する」ための整理資料。
2026-06-26 時点。書いた人＝ダン（Claude）。**正直に言うと現状はユーザーの基準を満たせていない。**

---

## 1. やりたいこと（ゴールと受け入れ基準）

制作タブ（Web上の動画編集UI）の**プレビューをダビンチ/プレミア級に安定**させたい。
ユーザー（＝この製品のオーナー、動画編集の素人ではあるが要求は明確）の受け入れ基準：

1. **編集の瞬間に黒落ちしない**（カット・クリップ移動・リップル削除・静止画挿入など）。
2. **停止状態でスクラブ（再生ヘッドを動かす）したとき**、映像が映り続けて素早くヘッド位置の絵に追いつく。
   - カクつき（処理能力次第の遅延）は**許容**。
   - 黒くなる／「いつまでも表示されない」は**NG**。←ダビンチは絶対に黒くせず、直前フレームを出し続けて追いつく。
3. **再生時、シーケンスの実体（クリップの timeline 位置）とプレビュー表示が一致**。
   - 例：timeline 10秒に置いたクリップは、再生ヘッドが10秒のとき画面に出る（10.1や9.9ではない）。
   - 映像と音声が同期。
4. **再生中・再生開始・クリップ境界で黒フラッシュ／ちらつきが出ない**。

最終目標：プレビューが信用できる状態＝**書き出しのGO判断ができる**こと。

---

## 2. 技術コンテキスト

- スタック：Next.js (React 19) フロントエンド。
- 主要ファイル：
  - `frontend/src/components/video-review/timeline-preview.tsx` … プレビュー本体（canvas合成＋再生制御）。
  - `frontend/src/components/video-review/frame-source.ts` … WebCodecsデコード＋フレームキャッシュ。
  - `frontend/src/components/video-review/mp4box.d.ts` … mp4boxの最小型定義。
- 素材：プロキシ動画＝H.264/avc1/yuv420p/MP4＋AAC音声。
  - 注意：検証に使った主アセットのプロキシは **60fps・720p・13分**（＝デコード負荷が高い）。新規生成プロキシは30fps目標だが、このアセットのは旧60fps。
- デコード経路：fetch(proxy) → mp4box demux → WebCodecs `VideoDecoder` → `createImageBitmap` でGPU ImageBitmap化 → frame index別キャッシュ。
- **重要な検証上の制約**：ユーザーはローカルPC（GPUハードウェアデコード, Chromium）。一方ダン（Claude）は**headless Chrome（ソフトウェアデコード）でしか検証できず、挙動が乖離**。headlessで「合格」でも実機で問題が出る、という誤検証を繰り返してしまった。

---

## 3. これまでにやったこと（時系列・PR付き）

**元の問題**：旧プレビューはクリップごとにHTML5 `<video>`要素を並べて合成。編集のたびに要素が再ロード/再シーク → その非同期中にデコード済みフレームが無く**黒落ち**。

- **PR#366** WebCodecsデコードキャッシュ型に全面刷新（`frame-source.ts` 新規）。アセット毎に1デコーダ、ImageBitmapキャッシュ、`peek`で同期描画。→ **編集時の黒落ち・スクラブのフレーム精度は解決**。
  - 実装でハマった点（すべて対処済み、コードに反映）：
    - デコーダ出力バッファ枯渇でストール（VideoFrameを溜めると~19枚で停止）→ `createImageBitmap`で複製し`VideoFrame`は即`close()`。
    - `flush()`がハング → 廃止し、キーフレーム(IDR)から target+数フレーム先までfeedして自然出力を待つ。
    - 重複timestampチャンクの再feedでデコーダ再起動ストール → 連続run `[fedFrom..fedThrough]`を追跡して二重feed禁止。
    - B-frame（decode順≠表示順, cts非単調を実測確認）→ 出力`VideoFrame.timestamp`(=cts µs)で sample index に逆マッピング、表示はpresentation順インデックス。
    - 高速スクラブ → latest-winsコアレッシング（中間target破棄）。
- **PR#367** 再生の音ズレ・停止中ジャダー対策（audio-masterクロック試行＋`readyTick`重複防止でチャットパネル再レンダ起因の再シーク連発を停止）。
- **PR#368** 「カットされた部分が再生中に映る」根治。`peek`のフォールバックをクリップのソース範囲`[source_start, source_end]`内に限定（他クリップ/トリミング外の映像を構造的に出せない）。
- **PR#369** 純WebCodecsで再生まで賄うと再生が悪化（後述）したため **ハイブリッド** に決着：
  - **編集・停止・スクラブ = WebCodecsキャッシュ**（黒落ち根治・フレーム精度を維持）。
  - **再生 = ミュート`<video>`要素**をハードでリアルタイム再生し、音声`<video>`と同一クロックで流す＝自然に同期。`drawFrame`は再生中`<video>`をcanvasに合成。`videosRef`プール復活（**描くのは再生中だけ**なので編集時のプールchurnは不可視＝編集黒落ちは再発しない）。
  - 受け渡し：`frameFor`は「`<video>`が要求時刻に居る(`|currentTime-expected|<0.12`)時はそれを描く」判定。再生→停止のWebCodecs再デコード待ち黒を解消。
  - カット境界：次クリップの`<video>`がseek中の一瞬はWebCodecsの先読み1フレームで補完（セーフティネット）。
  - 副次：WebCodecs非対応環境（非セキュアhttp/旧ブラウザ）でも`<video>`経由で映像が出る。
- **PR#370** 再生中のヘッド⇄表示ズレを **映像マスタークロック** で根治。再生ヘッド時刻を「表示中のベース`<video>`の`currentTime`」から導出し、ヘッド＝表示中の絵を定義上一致させた。
  - 実測（headless, 改善前→後）：系統的な遅れ mean -0.05〜-0.11秒 → **≈0**、境界の出現 4.13/8.09秒 → **4.011/8.015秒**（intended 4.0/8.0にほぼ一致）。

### 純WebCodecsで再生まで賄おうとして悪化した内容（＝ハイブリッドにした理由）
- 二重クロック（映像rAF/音声`<video>`）で音ズレ。
- 目的フレーム未デコードの一瞬、peekが遠い別クリップを拾い「カット部分が流れる」。
- 毎フレーム`createImageBitmap`（GPUコピー）でジャダー。
- 同一アセットの遠ジャンプ（例 source 5s→200s）で1デコーダが追いつかず黒。

---

## 4. 現状＝まだ安定していない（ユーザー実機報告）

- **(A) 停止スクラブで映らない／真っ暗。しかも「いつまでも表示されない」ことがある。**
  - ダビンチは処理が重くても映像が出続けてすぐヘッドに追いつくが、こちらは**永続的に黒**になる場合がある。
  - 特定クリップ依存ではなく、同じクリップでも映る時/映らない時がある。2クリップ重なりで片方/両方消えて真っ黒も。
- **(B) 隣接（ギャップ無し）クリップを再生が跨ぐ瞬間＆停止→再生ボタン押下の瞬間に、黒フラッシュ/ちらつき（PR#369-370で新規発生）。**

### ダン（Claude）の最新の診断（仮説、未確定）
- **最有力：`drawFrame`が毎フレーム、canvasを黒で塗りつぶしてから描いている**（`ctx.fillStyle='#000'; ctx.fillRect(...)`）。フレーム未準備の瞬間は黒が見える。
  - ダビンチは「直前フレームを保持し、用意できたら差し替える＝絶対に黒くしない」。この規律を実装していないのが(A)(B)の主因と推定。
- もう一つ：スクラブ時に「最終位置を確実にデコードして再描画し、ヘッドに追いつく」経路が脆い（latest-winsコアレッシング／single-flight／redrawのcancelで詰まる可能性）。
- 96枚キャッシュの追い出しで、戻った位置のフレームが消えている可能性。

---

## 5. アーキテクチャ詳細（コードを読む取っ掛かり）

### `timeline-preview.tsx`
- ref：`framesRef`(WebCodecs `FrameSourceManager`)、`videosRef`(再生用muted `<video>`, クリップ毎・アセット使い回し)、`audiosRef`(音声`<video>`)、`playingRef`。
- `frameFor(clip, t)`：返す描画ソースを決定。
  - 再生中 or WebCodecs非対応 → `<video>`要素（`readyState>=2 && videoWidth`、かつ停止時は`|currentTime - expected|<0.12`）。
  - それ以外 → WebCodecs `fs.peek(clipSourceTime(clip,t), source_start, source_end)`。
- `drawFrame(t)`：**黒clear** → active visualClip を layer 昇順で描画（transform/crop/shape/position対応）→ effect/blur → caption はHTML overlay別。
- SCRUB effect（`!playing`）：`drawFrame(currentTime)`即時 → supported時は active各clipに`fs.ready.then(seekTo)` → `Promise.all().then(drawFrame)`。非対応時は`<video>`シーク＋setTimeoutで再描画。deps に `readyTick`。
- PLAYBACK effect（`playing`）：rAFループ`step`。
  - `t` = 壁時計(provisional) → **マスタークロック**（activeなベース`<video>`の`currentTime`から `timeline_start + (currentTime - source_start)`）で上書き → `clock`にミラー。
  - active video：activation時/0.15sドリフト時にシーク、`play()`。inactiveは`pause()`。
  - PRE-ROLL(1.5s先)：次クリップの`<video>`を source_start にシーク＋WebCodecs `seekTo(source_start)`先読み。
  - audio：activation/0.3sドリフトでシーク、`play()`、role別volume。
  - `drawFrame(t)`、`onTimeChange(t)`。

### `frame-source.ts`（`AssetFrameSource`）
- 初期化：fetch → mp4box `onReady`(codec, avcC description) → `onSamples`で全sample収集 → `samples[]`(decode順, cts/dur/isSync/data) ＋ `presOrder`(cts昇順) ＋ `ctsToIndex`。
- `VideoDecoder` configured（avcC description, optimizeForLatency）。`cache: Map<decodeIndex, ImageBitmap>`(上限`MAX_CACHED_FRAMES=96`)＋LRU＋`protectedIndex`。
- `peek(timeSec, rangeLo, rangeHi)`：完全一致キャッシュ、無ければ`[rangeLo,rangeHi]`内の近傍キャッシュ、無ければ`null`。
- `seekTo(timeSec)`：`pendingTargets`に積んで`drainSeeks`（latest-first、staleは>=4でclear）。`decodeExact(target)`：連続run判定でkeyframe〜target+REORDER(3)をfeed、`waitForFrame`で待つ（**flush不使用**）。
- `prefetch`：**再生では未使用**（ハイブリッドで再生は`<video>`担当）。`onFrame`：`createImageBitmap`→`VideoFrame.close()`→cache。
- `FrameSourceManager`：URL別にsource保持、`retain`で不要を`close`。

---

## 6. Codexに相談したい論点

1. **「絶対に黒くしない・直前フレーム保持」をこのアーキで綺麗に実装する最善策は？**
   - 案：drawFrameで未準備時は再描画をスキップして直前canvasを残す／オフスクリーン二重バッファで完成時のみswap／クリップ毎に「最後に成功したImageBitmap」を保持してフォールバック。どれがベスト？
2. **スクラブで「確実にヘッド位置へ追いつく」デコード経路**の設計。latest-winsコアレッシング＋single-flightで詰まる/再描画されない問題の堅牢化。
3. **ハイブリッド（WebCodecs+`<video>`）は妥当か**、それとも純WebCodecsでキャッシュをもっと大きく＋デコード先読みして再生も賄う方が seam が減って安定するか。境界/再生開始のちらつきは seam 起因か。
4. **96枚キャッシュ上限**の妥当性、追い出し方針。
5. **60fpsプロキシ**は重い。30fpsに落とす（バックエンド `_run_proxy_job`）べきか。
6. **そもそもブラウザ内でダビンチ級の安定は現実的か。** ダビンチ受け渡し（ダンで粗編集→XML/EDL/AAF書き出し→ダビンチで仕上げ・確認）に切り替える方が、製品としては正しいのか。
   - 補足：ダビンチAPIは自動化用＋デスクトップアプリで、**Web UI内にプレビューを埋め込むことは不可**。連携＝工程の受け渡しになり、アプリ内プレビューの品質問題そのものは解決しない。

---

## 7. 検証の現実（重要）

ダン側は headless Chrome（software decode）でしか自動検証できず、ユーザー実機（GPU）と挙動が乖離する。
そのため「headlessでは黒0・合格」でも実機でちらつく、という**誤検証**が起きている。
→ 実機での再現可能な検証手段（オンスクリーンの状態表示＋スクショ、画面録画、あるいは実機でのデバッグ手順）を相談したい。
