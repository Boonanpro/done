# Recipe: T3 スクロール動画ヒーロー（Royal Pop 型）

## いつ使う
- シネマティックなヒーロー動画がページの主役になるプレミアム製品ショーケース
- ❌ 集客 HP には重すぎる

## スタック
- T2（GSAP + Lenis + framer-motion）に加えて `<ScrollVideo>` コンポーネント
- `<ScrollVideo>`: スクロール進捗に応じて動画を **スクラブ**（コマ送り）
  - 方式A: canvas にフレーム連番を描画（滑らか・堅牢。FFmpeg でフレーム抽出 = `studio` の `studio_encode` / `studio_probe` を流用）
  - 方式B: `video.currentTime` をスクロール進捗にバインド（軽いがシーク品質はエンコード依存）
- GSAP ScrollTrigger が進捗を駆動、Lenis が慣性

## 素材（ヒーロー動画）= media-gen 依存
- 今: `media-gen`（Kling, image-to-video）で生成可能
- より良い: Higgsfield 経由の Veo / Sora（first→last frame 補間）
- ⚠️ 動画は **スクラブ向き** であること（ゆっくり連続変化・first→last フレームの morph。激しいカット割り不可）

## ガードレール
- 資産が大きい → 遅延ロード、プリロード戦略、**モバイルは静止ヒーロー画像にフォールバック**、LCP 予算

## 参照
- 手法の元ネタ: `hamzafarooq/claude-code-starter` の royal-pop（バニラ JS 版。**React に移植**して使う、丸ごと流用しない）
