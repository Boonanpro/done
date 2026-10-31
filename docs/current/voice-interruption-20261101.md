# 呼びかけが元の返事に埋もれる場面

作業場所 `voice-scoped-stop`。既存2回の証拠を `.tmp/voice-yield-proof/comparison.json` に同一時計(t0)で抽出。前回説明のログ先頭基準とt0基準を混同しない。

- `voice-intake-proof-v2`: 呼びかけを文字として受け、その直後に「聞いてます」と出力。
- `voice-intake-final`: 呼びかけは文字として届くが「半分くらいに整えるんですね。いま見て直します」と元の説明を継続。後続backend_messageより前にこの発声は始まっており、遅いbackend_messageだけを原因とは断定できない。
- 音声入力の不着ではない。既存Interruption policyにも即座に譲る指示があり、文章を追加するだけで解決済みとは扱わない。

## 試作

`voice_interruption.Interruption` は入力と出力の文字起こしの音声時刻を照合し、発話が重なる時に `session.instructions.append` で今回の割り込みへ注意を戻す。断片ごとに繰り返さず、発話内容に依存する固定返答は注入しない。作業の変更・停止・承認・完了の判定は行わない。送信失敗時は同じ操作を再送せず、その通話の補助を止める。既定OFF (`DAN_VOICE_INTERRUPTION=1` の試験だけ有効)。

公式仕様（2026-11-01取得）:
- https://developers.openai.com/api/docs/guides/live-prompting : 割り込みの指示は精密な停止を保証しない。
- https://developers.openai.com/api/docs/guides/voice-server-controls?api=live : instructions.append は進行中の音声を中断し指示を適用できる。
- https://developers.openai.com/api/reference/resources/live/primary-websocket : appended は受付の確認であり、モデルの動作や再生完了の保証ではない。

## 限定試験

`.tmp/voice-yield-proof` は外部発信・スピーカー再生無し、専用試験部屋とmemoのみ。実際の制作中「ちょっと、今の話は聞こえてますか？」に「はい、聞こえてますよ」と応答。instructions.appended受信あり。制作job656148f7はcompleted、runner_process=None。35関連試験合格。

この1回では無効時との比較や再現性は証明しない。短い相づちへの過剰反応、別の呼びかけへの応答、元の仕事の取りこぼしも確認が必要。終了直前のcontext_injection_incompleteとclosingエラーは別に記録し、会話成功の証拠から除外。全体の完成や公開済みとは扱わない。

2回目 `.tmp/voice-yield-context`: 「ちょっと、今何を頼んだか分かる？」へ「案内文を半分くらいの長さに短くする」と内容に沿って応答した。固定返答ではない。jobd587dd3aもcompleted/runner_process=None。ただし説明が長く、応答全体は20.12〜32.29秒。会話の快適さを達成したとは扱わない。既存の単一受付がこの質問にresponse.createを1回補完したが、制作を重複開始してはいない。

2回の成功だけでは補助の因果効果や相づちへの副作用が未検証のため、既定OFFを維持し本番切替は行わない。次は短い相づち→そのまま続く質問という自然な割り込みで、必要な応答を中断し過ぎないかを確認する。必要なら入力の意味判断と発声制御を分離する。試験文だけを特別扱いする語彙は追加しない。別室stop_runの実音声選択は引き続き未検証。
