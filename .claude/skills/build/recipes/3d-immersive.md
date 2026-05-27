# Recipe: T4 3Dイマーシブ

## いつ使う
- 製品コンフィギュレータ / インタラクティブ 3D ショーケース
  （例: 特装車の部品を回して見せる = `new-attack/truck-model` が実証済み）
- ❌ 集客 HP には重すぎる・要 perf 配慮

## スタック（導入済み）
- `@react-three/fiber` + `@react-three/drei` + `three` + framer-motion（UI オーバーレイ）

## 作り方の核
- `<Canvas>` + `useGLTF` でモデル読み込み + `OrbitControls` / `Stage`
- クリック可能なメッシュ選択（`getObjectByName` でノード → 部品対応）
- `Suspense` フォールバック、モデルは遅延ロード
- **種パターン**: `frontend/src/app/artifacts/new-attack/components/truck-model.tsx`

## 素材（3Dモデル GLTF/GLB）の入手 ⚠️ Higgsfield 非対応
- Higgsfield は画像 / 動画は作れるが **3D モデルは作れない**
- 入手元: 3D アセットライブラリ（Sketchfab 等）/ 受注制作 / 3D 生成ツール（Meshy・Tripo 等、別系統）
- 既存 truck-model は `/models/garbage_truck/scene.gltf` を使用

## ガードレール
- モバイル性能（ポリゴン予算、Draco 圧縮）、WebGL 非対応 / `prefers-reduced-motion` 時の非 3D フォールバック
- 3D で LCP をブロックしない（遅延ロード）、a11y 代替コンテンツ

## 自己評価の追加チェック
- モバイルで動くか / WebGL 無し環境のフォールバック / モデルロードで LCP を阻害しないか
