# Recipe: T2 スクロールナラティブ

## いつ使う
- ブランドストーリー、製品ローンチ、"体験"を売るサイト（語り > 即 CV）
- ❌ 高速な集客 HP には不向き（重く・SEO で不利になりうる）

## スタック
- GSAP（ScrollTrigger）+ Lenis（慣性スクロール）+ framer-motion
- インストール: `npm i gsap lenis`（プロジェクトインストール）

## 作り方の核
- ルートに Lenis のスムーススクロールプロバイダを置く
- GSAP ScrollTrigger でセクションのピン留め・タイムライン演出・段階的リビール
- コンテンツは **DOM に存在させる**（JS リビール前提にしない）= SEO / アクセシビリティ確保

## ガードレール
- スクロールジャックで操作性を壊さない。読み飛ばし・戻りができること
- `prefers-reduced-motion` で演出オフのフォールバック
- モバイル性能（重い同時アニメを避ける）

## 自己評価の追加チェック
- reduced-motion 時に内容が読めるか / モバイルでカクつかないか / コンテンツが DOM にあるか（SEO）

## Current component policy

- For desktop pinned narrative sections, write them per-case with the `gsap-scrolltrigger` skill. There is no shared pinned-story component (retired — it auto-detected the scroller and was fragile inside custom scroll containers).
- Pin on the default window scroller (artifacts scroll the document), clean up via `useGSAP`, and call `ScrollTrigger.refresh()` after media/layout changes. Only set `scroller` explicitly if the page genuinely uses an internal scroll container.
- On mobile, stack the chapters vertically. Do not shrink a desktop two-column pinned layout onto a phone.
- Before writing GSAP, read the relevant skills: `gsap-scrolltrigger` and `gsap-react` at minimum; for timelines also `gsap-timeline`.
- If `ScrollVideo` already fits the goal, use that component instead of writing one-off animation code. For simple reveals use the `motion/` helpers or framer-motion `whileInView` directly.
