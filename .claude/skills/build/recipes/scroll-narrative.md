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

- Use `PinnedStory` for desktop pinned narrative sections. It is backed by GSAP ScrollTrigger, not custom scroll listeners.
- On mobile, use the built-in `MobileStoryRail` fallback or the standalone `MobileStoryRail` component: vertical scroll pins the section while cards move horizontally, then normal vertical scrolling resumes. Do not shrink a desktop two-column pinned layout onto a phone.
- Before writing custom GSAP code, read the relevant skills: `gsap-scrolltrigger` and `gsap-react` at minimum. For timelines, also read `gsap-timeline`.
- If `PinnedStory` or `ScrollVideo` already fits the goal, use the component instead of writing one-off animation code.
- If writing one-off ScrollTrigger code, include cleanup via `useGSAP`, set `scroller` when the page uses an internal scroll container, and call `ScrollTrigger.refresh()` after media/layout changes.
