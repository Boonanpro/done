# LIVE1側が更新する8項目の制作相談シート

## 変更

新規エディター音声セッションをclient delegationから、公式仕様のResponses delegationへ切替。
LIVE1が会話し、バックグラウンドのGPT-6 Astra API（low）がツールを選ぶ。
会話側APIが整理した短い文章でシートを更新し、Jevは参考検索に使う。
旧Jevの発言分類・引用貼付による相談メモ更新は新規接続経路から外れた。
既存の制作担当・生成エンジンを今回全面置換したわけではない。

8項目は動画の種類／題材／公開先／作る目的／想定する視聴者／尺／使いたい素材／参考として選んだ作品。
各項目はunknown（未確認）、undecided（相談して未定で進む）、confirmed（決定）。
検索で表示した候補は採用欄へ自動記録しない。参考方向への合意と全8項目の確認でready_for_draft。
これは次の制作への相談状態であり、本番生成や支払いを自動許可しない。

get_consultation_state / update_consultation_sheet / search_reference_library / control_reference /
run_editor_task とweb_searchを接続。シートは作品ごとのlocalStorageに保存。サーバーが入力を検証する。
原文は既存会話履歴に保持し、シートには重複引用しない。v2の誤分類済みメモをv3の確定事項へ変換しない。
再接続時はツールでシートを読み、会話記録から不足を整理する。

Responsesの全function_call_outputを返してから一度response.createを送る。
更新は呼び出し順に実行し、呼び出し開始時の作品へ固定。マイクOFF時もバックエンド応答中は接続終了しない。
実装確認UIも8項目と確認数、参考方向への合意状態へ更新。

## 検証

- Python38件、既存と新規の音声JS49件合格。
- 実LIVE1 WebRTC接続と実GPT APIで3ターンのテキスト入力を実行。題材／公開先を分離し、未発言の目的・視聴者を未確認で保持。題材訂正後も他項目を保持。尺の未定を保持。最後の条件回答と合意でready_for_draftに変化。
- 音声の聞き取り・自然さを試したテストではない。ブラウザーのマイクを使わず、バックエンドへのテキスト入力で実ツールの実行を確認した。
- 新ツールから実Jev検索→既存提示API→ブラウザーへ3本を表示。最終検索1,724ms。これは音声から画面までの時間ではない。シートが検索によって変更されないことを確認。YouTube埋込のサムネイルまで目視し、動画全編の再生・品質審査は未実施。
- 実ページでメモ更新・別作品への切替・開閉・390px幅を確認しスクリーンショットを目視。
- テスト用提示は`sheet-reference-test`に隔離。ユーザーの作品やタイムラインは編集していない。

接続・制作ジョブなしを確認しsandboxを管理APIから再起動、PID36764 healthy。
静的JSはno-storeで配信され、エディターを開き直した新しい音声接続から適用。

証拠: `scratch/live-consultation-sheet/result.json`、`sheet.png`、`reference-result.json`、`references.png`。
再現: `scripts/check_live_consultation_tools.py`、`scripts/check_live_reference_tool.py`、`scripts/check_consultation_inspector.py`。
公式接続仕様: https://developers.openai.com/api/docs/guides/live-delegation
