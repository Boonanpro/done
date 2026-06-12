# DESIGN.md — OBANZAI bar 五条【別案・GPT Image 2 画像主導 (comp)】

> これは現行案（/yonago-gojo）とは別の、独立した代替HP。
> ユーザー指定により **GPT Image 2 の画像コンプを主役** にした写真主導の高級表現で作る。
> 生成した料理・店内・外観は **後で本物に差し替える前提のプレースホルダー**。偽造の懸念は考慮しない方針（ユーザー明示）。

## ゴール（共通）
- 集客と認知の拡大。新規来店とInstagramフォロー/DM予約増。
- 行動: 地図で来店 / Instagramフォロー・DM予約。

## レンダリング方針
- `comp-guided-dom` + 画像主導（image-led）。
- GPT Image 2 で生成した高品質ビジュアルを**全画面/大判**で使い、その上にDOMでテキスト・CTA・メニュー・地図を重ねる。
- 重要情報（店名・住所・営業時間・主要CTA・メニュー）はDOMで保持しSEO/編集性を確保。
- 文字は画像に焼き込まず、DOMで重ねる（差し替え・レスポンシブのため）。

## 現行案との差別化
| | 現行案 /yonago-gojo | 別案 /yonago-gojo-comp（本書） |
|---|---|---|
| 主役素材 | 実写カラグレ動画 | **GPT Image 2 の写真コンプ** |
| ナビ | 左固定の縦ナビ＋右縦タブ | **上部センターナビ（透過→スクロールで固体化）** |
| トーン | 夜の隠れ家・映像 | 高級飲食店の写真誌的グラビア |
| メニュー | 和紙の明セクション＋文字 | **料理写真を大判で見せる画像主導メニュー** |

## GPT Image 2 生成素材（public/yonago-gojo-comp/）
- hero-comp.jpg … ヒーロー（夜のカウンター・灯り・料理と酒、左に暗部）
- exterior-noren.jpg … 外観（暖簾と提灯・縦）
- interior-counter.jpg … 店内カウンター（無人）
- dish-obanzai.jpg … おばんざい3種
- dish-chawanmushi.jpg … 冷製茶碗蒸し
- dish-sujikomi.jpg … 牛すじ煮込み
- sake-pour.jpg … 日本酒を注ぐ
- plating.jpg … 盛り付けの手元
- ロゴ・地図は現行案と共有（/yonago-gojo/logo.jpg, Google Maps埋め込み）

## セクション構成
1. 上部ナビ（透過→固体化）＋予約ボタン常時
2. ヒーロー（hero-comp 全画面＋DOM見出し・CTA・スクロール誘導）
3. ファクト帯（営業/定休/席/酒）
4. About（exterior-noren 縦写真＋店名の由来テキスト）
5. 名物・お品書き（dish系を大判グリッド＋名前・価格をDOM、画像主導メニュー）
6. 店内フィーチャー（interior-counter 全画面＋引用コピー）
7. メニュー詳細（定番/季節 DOMリスト・dark）
8. アクセス（地図＋営業情報＋予約CTA）
9. CTA（plating/sake 上に「今夜、五条で。」）
10. フッター

## トーン
- 配色: 墨黒基調＋灯りの琥珀。写真の暖色を活かす。
- フォント: 見出し=Zen Old Mincho / 本文=Noto Sans JP / ラベル=Zen Kaku Gothic New。
- モーション: framer-motion `whileInView` フェード、ナビのスクロール固体化、画像hover微ズーム。`prefers-reduced-motion` 尊重。

## 店舗情報（出典: na-na.media, tabelog, Instagram @yonago_gojo）
- 鳥取県米子市富士見町2丁目8番 新英会館1F / 18:00–23:00 / 火・水休 / カウンター6＋テーブル2
- 定番: おばんざい3種¥800 / 冷製茶碗蒸し¥500 / 冷トマトおでん¥500 / 牛すじ煮込み¥800 / 大山豚の角煮¥950
- 季節: 岩牡蠣の昆布締め・アヒージョ（隠岐島産）、銀鮭の黒焼き（境港）
- Instagram: https://www.instagram.com/yonago_gojo/
