# 作業待ち中の呼びかけ：2026-11-01の切り分け

本人許可：10/31 23:59「有効な実装やテストができるならテストしても良い」。外部電話発信なし。
現在のmain 7ce68543を独立worktreeで読み、実Live/委譲モデルへ合成音声を送った。statusの道具だけ20秒のfixture遅延。通常の部屋や作業を変更しない。スピーカー出力なし。1通話約56秒。

入力は「今進めている台本の作業はどうなってる？」「おい、聞いてる？」「返事だけして。聞こえてる？」。
2回とも遅延した道具の終了前に「聞いてますよ」「聞こえてます」と応答した。マイク音声終了から次の返答文字列到着まで0.707秒、0.729秒。これは文字列到着の時間で、実機の発声開始時間ではない。

既存の指示と並行受信経路で、道具の完了を待たず応答できる事実を確認した。「作業を待つと必ず無応答」という一般化は誤りで、非同期化だけを理由に再設計しない。過去の本人通話の無応答原因が解決済みとは言えない。

作業状態のfixtureは実際の台本作業ではなく、最終的に台本を特定できない返答になった。実作業の状況理解・追加変更・停止はこの試験の評価対象外。prefetchとbackendのjob_statusが別引数で2回始まったが、副次的な最適化に脱線しない。

証拠：このworktreeの .tmp/voice-response-proof/after.json、summary.json、owner.wav、schedule.json。再現用 scripts/check_voice_busy_reply.py。試験ログは合成音声のみ。既存結果は上書き禁止。

次の必要な確認は、専用の試験用メモを実際の制作処理で直す間の呼びかけ、同じ仕事への追加条件と停止。本人の既存成果物・別室の仕事を止めない。voice-run-stopの未公開変更を現在の本番動作と混同しない。本診断だけを本番修正や音声改善の完了として扱わない。


## Real editing and stop, 2026-11-01

Dedicated room eccc6fce-503c-4ab6-a938-5445d21eb27e, real make worker, synthetic microphone, muted output, no external call or publication. Test script: scripts/check_voice_real_edit.py. Immutable evidence directories .tmp/voice-real-edit-proof and .tmp/voice-real-edit-after. Same audio: shorten memo, call out, retain 20 participants, stop.

Before: job 19a120a4-2107-400a-9e53-8bf23f8e6393 acknowledged stop in speech but never invoked cancellation; it later completed and wrote the memo. Recording of the final job-feed event raised a logging keyword collision; this occurred after the missing stop and is fixed in the harness.

After: job aa962653-55a7-4805-9013-67eada74df6e also omitted native stop invocation. The new transcript stop control accepted cancellation at 15:13:13.995745 UTC; runner_process is null and no matching worker remains. Memo was last written at 15:13:11.216902 UTC, before cancellation, and unchanged through the end of observation. Additional instruction revision 1 was applied at 15:13:05.729388 UTC. Speech acknowledged acceptance, not verified completion. Stop fallback receipt is 2.171 seconds after synthetic microphone end (not audible response latency). Call-out was answered while the real worker ran.

Scope: a whole explicit stop utterance, one active job in this room started during this call. Ambiguous/multiple/older jobs and truncated job lists are excluded; negation in the same utterance cancels the debounce. Other-room stopping, broader natural-language stop expressions and overall conversational satisfaction are still unproven. This is a narrow correction to a reproduced omitted action, not evidence that all voice latency is fixed.
