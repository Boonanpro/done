# Recipe: T3 スクロール動画ヒーロー（Royal Pop 型）

## 最初に使う部品

スクロール連動動画のHP/LPでは、まず `frontend/src/components/templates/scroll-video.tsx` の `<ScrollVideo>` を使う。
scratch の実験コードを毎回書き直さない。

```tsx
import { ScrollVideo } from "@/components/templates";

<ScrollVideo
  src="/brand/scroll-main.mp4"
  poster="/brand/scroll-poster.jpg"
  mobileSrc="/brand/scroll-mobile.mp4"
  mobilePoster="/brand/scroll-mobile-poster.jpg"
  heightVh={360}
  chapters={[
    { start: 0, end: 0.34, eyebrow: "Chapter 01", title: "最初の訴求", body: "何が変わるのかを短く見せる。" },
    { start: 0.34, end: 0.67, eyebrow: "Chapter 02", title: "強みの提示", body: "映像と本文を同時に進める。" },
    { start: 0.67, end: 1, eyebrow: "Chapter 03", title: "行動へつなげる", body: "次のCTAへ自然につなぐ。" },
  ]}
/>
```

ファーストビューが動画主役だがスクロール連動ではない場合は `<FullBleedVideoHero>` を使う。
通常の画像/動画背景で十分な場合は `<HeroMedia>` を使う。

## 必須素材

- `scroll-main.mp4`: PC用。スクロールで進めても破綻しない、ゆっくり連続変化する動画。
- `scroll-poster.jpg`: 動画ロード前と reduced motion fallback 用。
- モバイルで構図が崩れる場合は `scroll-mobile.mp4` と `scroll-mobile-poster.jpg` を別で用意する。

Higgsfield / Runway / Sora / Veo を使う場合は、first frame と last frame を決めて、急なカット割りを避ける。スクロールスクラブでは「編集された動画」より「連続したカメラ移動・変化」のほうが向いている。

## 実装ルール

- 本文はDOMに置く。動画に焼き込まない。
- CTAはスクロール動画セクションの直後、または最終章の下に置く。
- `prefers-reduced-motion` では静止画や通常セクションにフォールバックする。
- モバイルでは重すぎる動画を避ける。必要なら静止画heroに落とす。
- 動画だけで情報を伝えない。映像が読めなくても見出しと本文で意味が通るようにする。

## 検証項目

- PC 1440pxで、動画・章テキスト・CTAが重ならない。
- mobile 390pxで、見出しが折り返しても画面外に逃げない。
- スクロール時に動画が進む。
- 動画ロード前にposterまたはLoading状態が出る。
- reduced motionで内容が読める。

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
