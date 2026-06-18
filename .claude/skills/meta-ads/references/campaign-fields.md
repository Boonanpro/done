# キャンペーン/広告セット/広告のフィールド

`scripts/meta_ads_cli.py` で使う主なパラメータ。Meta Marketing API（ODAX 体系）準拠。

## キャンペーン目的（objective）

| objective | 用途 |
|---|---|
| `OUTCOME_TRAFFIC` | サイト誘導（LP/フォームへのクリック）。ドライテスト既定 |
| `OUTCOME_LEADS` | リード獲得（フォーム/メッセージ） |
| `OUTCOME_ENGAGEMENT` | エンゲージメント/メッセージ/動画再生 |
| `OUTCOME_SALES` | 購入・コンバージョン（要ピクセル/CAPI） |
| `OUTCOME_AWARENESS` | 認知・リーチ |
| `OUTCOME_APP_PROMOTION` | アプリインストール/利用 |

`campaign --objective <上記>`。常に `PAUSED` で作成される。

## 広告セット（adset）

- `--daily-budget <額>`: 1日予算。**アカウント通貨の単位**で渡す。JPY等の小数なし通貨は円そのまま、
  それ以外（USD等）は CLI が ×100 して送る（cents 変換）。
- `--optimization-goal`: 最適化対象。代表値:
  - `LINK_CLICKS`（クリック）/ `LANDING_PAGE_VIEWS`（LP表示）/ `IMPRESSIONS` / `REACH`
  - `OFFSITE_CONVERSIONS`（CV、要ピクセル）/ `LEAD_GENERATION`（リード）
- `--billing-event`: 課金イベント。既定 `IMPRESSIONS`（`LINK_CLICKS` も可）。
- `--bid-amount <額>`: 入札上限（通貨単位）。未指定なら `LOWEST_COST_WITHOUT_CAP`（自動入札）。
- ターゲティング:
  - 簡易: `--countries JP`（カンマ区切り可）、`--age-min 25 --age-max 45`
  - 詳細: `--targeting-file targeting.json`（指定時は簡易指定を無視）。例:
    ```json
    {
      "geo_locations": {"countries": ["JP"], "cities": [{"key": "2420877", "radius": 10, "distance_unit": "kilometer"}]},
      "age_min": 25, "age_max": 45,
      "genders": [2],
      "interests": [{"id": "6003139266461", "name": "Beauty"}],
      "publisher_platforms": ["instagram"], "instagram_positions": ["stream", "story", "reels"]
    }
    ```
- 期間: `--start-time` / `--end-time`（ISO8601）。

## 広告（ad）

リンク広告（object_story_spec の link_data）を作成 → Ad を作成（共に PAUSED）。

- `--link <URL>`（必須・遷移先。UTM を付けておく）
- `--message "本文"`（必須・プライマリテキスト）
- `--headline "見出し"` / `--description "説明"`
- `--image <ローカルパス>`（CLI がアップロードして image_hash を取得）または `--image-hash <既存hash>`
- `--cta <type>`: CTA ボタン。代表値: `LEARN_MORE` `SHOP_NOW` `SIGN_UP` `BOOK_TRAVEL`
  `CONTACT_US` `SUBSCRIBE` `GET_OFFER` `DOWNLOAD` `MESSAGE_PAGE`
- Instagram 配置: connect 時に `--ig-user-id` を保存していれば自動で `instagram_user_id` を付与し IG にも出る。

## 出稿・運用

- `publish --campaign-id <ID> --confirm`（または `--adset-id` / `--ad-id`）→ status を ACTIVE に。**課金開始**。
- `pause --campaign-id <ID>` → PAUSED に戻す（キルスイッチ）。
- `insights --campaign-id <ID> --date-preset last_7d [--level adset]`
  - 取得 fields: `spend, impressions, clicks, ctr, cpc, cpm, reach, actions, cost_per_action_type`
  - `--date-preset`: `today` `yesterday` `last_7d` `last_14d` `last_30d` `maximum` 等。

## 予算の目安（ドライテスト）

`dry-test-launcher` の既定に合わせ、初期は 1日 500〜2,000 円・合計 3,000〜10,000 円・3〜7日から。
シグナルが出るまで小さく。閾値到達で iterate / 本予算 / 停止を判断。
