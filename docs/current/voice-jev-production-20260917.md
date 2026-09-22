# 音声Jev入口の本番反映

2026-09-17。音声セッション作成時にroom_idを持つVoiceIntakeを登録する。
スマホ・Web/Atomが使う既存のlive/backend、live/backend/stream経路に適用。
既存APK・既存ファームウェアのまま、新しい通話から利用できる。

## 現在の経路

Live 1 → Jev → 既存の検索/状態/履歴ツール、または作業担当Astra。
本番の音声受付ではVoiceCodexを作成・ウォームアップしない。
古いVoiceCodex実装は互換テスト等のroom_idなし経路に残るが、本番セッション作成には使わない。

- 新規作業は原文と直前会話をdelegate_to_danへ渡す。予約情報や承認を捏造しない。
- Jevが不確かな新規依頼も、窓口Astraを再導入せず担当が原文を解釈する。
- 対象が特定できる既存作業の更新はcontrol_dan_taskへ渡す。
- 状態・履歴・Web検索の高確信判断は直接ツールへ渡し、結果をLiveへ戻す。
- 停止・通話終了・確認承認の低確信判断はそのまま実行しない。
- 確認承認は現に提示されたconfirmation_idと、既存APIの本人発言照合を通す。
- 購入/払戻を直接確定する新しい道具は追加していない。既存の作業側確認が適用される。
- Jev障害時に会話全体でJevを永久無効化しない。次の発言で再試行する。

## 反映・確認

- 稼働中通話、制作ジョブ、Sandbox配下の実行担当・エディターがないことを確認。
- Sandboxのみ管理APIで再起動。Coreと他の端末は再起動していない。
- 本番Sandbox PID12248、health正常。
- 関連43テスト合格: `.tmp/jev-intake-production-tests.log`。
- 実本番/live/session → /live/backend → 各ツール → /live/backendを試験。
  隔離したheadless WebRTC接続を使用。物理スピーカー・Atomは起動しない。
  試験終了時にbackend接続とブラウザを閉じた。

### 本番での実測

| 試験 | Jev受付応答 | 受付/取得 | 結果 |
|---|---|---|---|
| 日本交通の当日ネット予約を検索 | 618.08ms | 検索結果まで2,656.78ms | 5件取得。受付と結果処理ともbackend=jev_intake |
| 過去の仕事を再開せず17+25を計算して報告 | 258.92ms | Core作業受付まで967.96ms | 10,641.85msでcompleted、42と報告 |

試験部屋: 6016ba78-bb79-440b-a8d7-110bcfd1037d。
作業ID: 1368809a-bde7-4ea9-8d4a-ac437cf3029e。
証拠: `.tmp/jev-production-proof.json`、`.tmp/verify-jev-production.py`。
これは発話終了から音声回答開始までの実測ではない。購入・取消・払戻そのものは未試行。
本番会話の自然さ、曖昧な依頼の全ケース、実サイトの処理速度まで合格したという意味ではない。

## 変更箇所

- app/services/voice_intake.py
- app/services/voice_live.py
- app/api/voicelog_routes.py（セッションへroom_idを渡す）
- tests/test_voice_intake.py

テキストチャット全体への共通受付適用は今回の反映に含まない。
