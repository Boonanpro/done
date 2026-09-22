# Done voice

Latest (2026-09-16): Atom can select Gemini 3.8 Live Extended Thinking alongside Live 1,
sharing the same Astra backend. See [implementation, deployment and comparison](atom-gemini-comparison-20260916.md).
The historical sections below describe successive configurations; the current backend is Astra CLI.

Done is the shared text/voice entry point. Its role instructions apply only to projects marked `metadata.role=command_center`; other rooms retain their capabilities.

The Atom/browser conversation uses **gpt-live-1**, WebRTC and client delegation. The application runs a **gpt-5.6-terra** Responses conversation for reasoning and existing tools. API credentials and the previous-response chain remain on the authenticated server. Large room histories stay in that backend; only its answer is passed to Live. Legacy `/voicelog/session` remains for older clients and is not a fallback for this connection.

`command_center.overview` returns the latest four messages from rooms with human activity in the last 30 days, plus rooms with active work. `days`, `limit` and `offset` allow further reading. There is no model classifier, citation validator or background overview job. Retrieval errors remain errors.

`command_center.search` searches the user's own room titles, summaries and message contents, including older rooms. Dan chooses keywords from the user's description and reads matching conversations to identify the room. `read` provides more history and editor state. Reading does not start or post to another room. Delegation still creates a durable handoff with a report back to Done.

Done's screen has a conversation and Atom status. The former overview column and duplicate sidebar logo have been removed.

Live owns simultaneous listening/speaking. Standby waits for the actual audio tail; a new utterance cancels pending standby. The headless controller observes session start and reconnects independently of the user's browser. Authenticated local diagnostic commands can play a test utterance or inject WAV audio without desktop focus.

Validation: 19 tests cover room ownership, recent/historical retrieval, parallel tools, duplicate delegation, stale-action suppression and server continuation. Actual WAV speech through the Atom connection identified the vehicle-video room without its title and found the two pending decisions. “今日はここまで、また呼ぶね” returned the device to standby. An injected spoken interruption stopped a longer explanation and received “聞こえたよ”. Desktop/mobile layouts and the old hub URL redirect were checked in isolated headless browsers.

Past voice answers are not embedded into startup instructions. A test exposed a wrong name propagating through that old injection; removing it restored retrieval from the project conversation. Speech can still paraphrase a correct backend answer imperfectly. Authenticated `/command` diagnostics expose the latest backend answer separately from the stored spoken transcript for comparison.

## Normal Dan execution from voice (2026-09-15)

`delegate_to_dan` now submits authenticated `command_center` action `work`, resolving the current project on the server. It uses the same durable handoff/run/report path as cross-room work, with the normal Dan runner, room history and tools. Voice no longer uses the legacy silent WebSocket executor. Progress is available through `check_dan_status`; results survive voice disconnection and are delivered through the existing report poller. An Atom session omits desktop screen capture: browser navigation belongs to the normal Dan runner and does not require screen sharing. The tool description now names browser inspection, login, shopping and booking as supported tasks within the user's authorization.

Validation: 19 backend tests and 11 frontend tests passed; production frontend built and deployed. Three real backend cases (Amazon inspection, train booking preparation, and correcting a prior capability denial after reading history) selected `delegate_to_dan`. In an isolated voice test room, a real Live session with text test input dispatched normal Dan, opened example.com with the browser tool, saved and read back a proof file, and spoke the returned report. A synthesized spoken request also dispatched browser/file work and persisted its final report. That audio request misrecognized the literal Windows path and marker; the exact-string assertion was not passed, and the test was stopped after inspecting the actual saved file and report. It does not establish physical microphone accuracy or successful checkout on a shopping/booking site.

Duplex input remains continuous in 10 ms PCM packets. No 200 ms turn-switching is implemented. The existing synthetic AEC test passes for echo attenuation and simultaneous near-end audio preservation, but does not explain the reported physical interruption failure. Bridge `audio_health` events now retain one-second numeric input/output RMS, frame-gap and send-failure measurements, without audio recordings or transcripts, for diagnosing the next occurrence.

Delayed reports now retain the originating Live client delegation ID within a session; reconnecting clears that association while retaining durable report IDs. The additional frontend dispatch test passes (12 frontend tests total). Final production build `.next-prod-1789449821` was verified with synthesized speech entering the normal Atom PCM worklet, without replacing the microphone track: normal Dan opened example.com, read its H1, saved the run/report, and Live spoke “主見出しは『Example Domain』です。” Test watch `cabf8e05-21a0-4cc7-a1eb-45eefa718b67` completed. The earlier replacement-track audio harness did not demonstrate spoken final delivery; the normal PCM-path test did. Four bridge tests also pass. The physical Atom is connected and in standby; no firmware change was required.

## Call lifecycle repair (2026-09-13)

The user reported repeated ready chimes and “じゃあ切るね” without disconnection. Logs showed a spoken promise without a standby tool call. Firmware also played the ready chime on every transient network-readiness recovery.

Call termination now has a separate semantic intent check on paused user speech, using GPT-5.6-Luna, independent of Live's decision to delegate. A newer utterance invalidates an older decision. Confirmed termination is latched and allows at most 700 ms for playback to finish before closing; continuing model speech cannot hold the call open. This does not cancel project work already dispatched.

The firmware change plays the accepted ready cue on the requested OFF→ON transition and the standby cue on ON→OFF. Network readiness changes are silent. The local recognizer checks stable partial recognition instead of waiting for final silence: a recorded test recognized the phrase at audio position 0.69 s, compared with the former final result at 1.35 s.

Validation: eight actual semantic classification cases included the reported end-call phrases, negation, temporary silence, quoted instructions and ending video work. An isolated browser with real Live speech input and a simulated Atom control transport issued exactly one stop for “この電話を切ってください” (4.17 s after input playback ended). Four lifecycle regression tests pass. Firmware was flashed to the verified Atom (MAC b4:3a:45:bc:c0:20), app partition only, with hash verification. Physical intent-toggle testing completed one ready cue before network readiness and one standby cue after connection; network readiness did not add another ready cue. Device counters reported started/completed=1,1,0, zero cue errors and maximum output-lock wait of 8 ms. The device returned to requested=0, ready=0. This verifies device cue writes, not listener-perceived latency or a physical microphone end-call test; those remain user acceptance checks.


## Live-generated connection greeting

The headless Atom controller requests a brief Japanese greeting only after Live is connected and the device audio readiness lease is active. Live receives a one-time instructions append to say moshi-moshi and then listen; no recorded clip is used. Both controller and session latch the request to suppress duplicates within a connection. Standby still closes the paid Live session.

Validation: two isolated Live 1 sessions in the dedicated test room generated only the requested greeting, with one instructions append despite duplicate triggers. The second test verified nonzero speaker PCM (peak 27457). Both then closed exactly once on spoken end-call input (3.69 s and 3.52 s after input ended). Transport was simulated; physical audibility remains user acceptance. Production frontend build and existing lifecycle/backend/controller checks passed; frontend and headless controller were updated.


## Reliability and idle policy (2026-09-14)

Voice readiness no longer relies on an unscored partial wake hypothesis: the local recognizer waits for a confident final prefix. The cue still acknowledges intent immediately rather than waiting for cloud connection. Wake and non-wake WAV fixtures respectively produced one and zero detections. This reduces one known false-wake path; it does not prove zero false positives.

The headless controller returns the device to standby after 600 seconds without a user transcript. Speech refreshes the clock; greeting, connection retries and cloud reconnection do not. The clock belongs to the device intent (boot/revision). On idle expiry, the current browser is closed and no new paid session is opened while the stop is retried. This covers both abandoned startup and abandoned conversations.

Cross-room requests now leave an attributed system message and create an explicit run linked to the request. Autonomous background runs retain parent_run_id. A durable command_report watch follows this lineage and retrieves saved final messages by execution-event turn IDs (ai_context.turn_id), instead of treating an empty initial result as completion. Active descendants remain pending; empty outcomes are reported as unconfirmed rather than success. Completion reports survive voice disconnection, and routine room activity does not cancel command watches.

command_center status/read and check_dan_status expose the existing run/process-monitor events. Voice restores pending report IDs on connection and adds arriving reports to the reasoning backend as well as the spoken context.

Validation: 28 targeted tests passed (15 backend, 5 device/controller, 8 frontend lifecycle/backend). A real isolated handoff calculated 7+8 in a new test project, persisted its attributed request/run/events, and delivered 15 to the existing voice test room. A read-only replay using last night's actual parent and background runs selected the correct three-article report. No business rooms were used for new test work.
# Luna 判定層の撤去（2026-09-15）

`command_handoff.deliver` の完了再判定と、その判定に基づく最大3回の自動再実行を削除した。
実行中の子runを待ち、実行担当が保存した回答を安定したmessage IDで依頼元へ届ける。
配達済みを `outcome=reported` とし、タスク全体の成功とは区別する。実行失敗・空の結果は失敗として報告する。
配達は追加のモデルAPIを呼ばないため、そのAPIの残高不足で保存済みの回答が止まることはない。

音声の各発言後に呼んでいた `/live/intent`、Luna classifier、CallLifecycleタイマーも削除。
会話の終了は既存のLive delegation → 会話バックエンド → `enter_voice_standby` を使う。
Live 1と `gpt-5.6-terra` の会話バックエンドは継続しており、CLIへの全面移行ではない。
会話バックエンドの残高不足はHTTP 503と具体的な日本語の理由を返す。

検証: Python 22件・フロントエンド8件成功。本番ビルド `.next-prod-1789456148` を起動し、
無通話・実行中runなしを確認してCoreと音声APIを持つSandboxを更新した。
本番の `/live/intent` は404、音声ページと両プロセスのhealthは200を確認。
停止していたwatch `df9abf95-f859-47d6-9738-78bacb623a39` が自動回収され、Doneに
報告 `4a5fe356-2f87-5184-ac4e-de00917d24f1` が1件保存されたことを確認。
新幹線の検索や購入を再実行していない。

OpenAI APIの20ドル追加は認証画面へのブラウザ確認で未完了。実APIでの終了動作は
チャージ後に再検証が必要。実接続テストはLive session作成が502となり、開始待ちでタイムアウトした。
コード上のツール経路とAPI不要の配達の検証を、実音声の合格と混同しない。

## 音声からの独立作業・途中指示（2026-09-15）

新規の work/delegate は `steerable_cli` エンジンで実行する。Coreの即時起動経路と永続watchを使い、
最大4作業を独立したGPT-6 Astra Codex app-serverで実行する。既存watchは旧経路を維持する。
音声会話はLive 1、会話バックエンドはTerraのまま。作業実行にLuna APIは使わない。
作業ごとの非表示ブラウザを使い、同じ部屋への複数依頼もブラウザを共有しない。

`control_dan_task` は同じjobへの追加条件・一時停止・再開・停止・提示内容への承認を扱う。
追加条件はCodex `turn/steer` に送り、受領応答前は次のMCP操作を止める。
確認内容はjob/revision/実画面/操作引数に結びついた一回限りの承認で保護し、条件変更で失効する。
音声承認は最新の本人の発言が確認提示後に保存されていることも確認する。
購入・送信等を示すブラウザ操作と不明な外部ツールは確認待ちになる。
任意のブラウザJavaScriptと直接シェル経由でこの境界を迂回する経路は開放しない。
サイト固有の独自操作すべてを意味判定できる保証はなく、送信済みの操作を後から取り消す機能でもない。

進捗・確認待ち・追加指示の受領・結果をローカル永続状態に保存し、音声画面は1.5秒間隔で取得する。
細かい進捗をまとめ、完了の二重配達を避ける。依頼・実行ログ・最終報告は元の部屋にも残す。
Core再起動で不確かな実行を自動再開せず、停止として報告する。

検証：Python関連34件、フロントエンド10件成功。本番ビルド `.next-prod-1789465801` を起動。
実Astra CLI＋Dan MCP＋非表示ブラウザの模擬購入試験を2回実施した。
確認待ち中に別ブラウザが完了し、途中の座席変更を同じ実行が受領、古い承認は拒否され、
変更後への承認で模擬購入が一度だけ実行された。2回目は承認経由の実行を最終回答も正しく説明した。
実購入は行っていない。証跡は `.tmp/command-jobs-e2e-proof.json`。

本番Live 1との通し試験では、テキストで渡した依頼から新エンジンを起動し、実ブラウザで
Example Domainの見出しを確認、途中報告と最終回答を音声で受信した（作業開始から結果保存まで約35秒）。
音声入力の試験では自発的な「もしもし」と、録音した「この電話を切ってください」に対する一度だけの停止を確認した。
入力終了から停止まで3.75秒。最初の音声依頼試験は同じテスト部屋の別試験の実況と競合しタイムアウトしたため、
通しの閲覧依頼は独立して再試験した。物理マイクによる途中条件・承認の認識はユーザー試験が残る。
現在の実行ツール名・ブラウザ操作名・開始時刻も状態照会に含める。報告配達だけ失敗した場合は
保存した結果を再配達し、作業本体は繰り返さない。

## 過剰な確認と操作負担の修正（2026-09-15 夜）

実利用job `ef812301-e83a-42e9-b622-32875878dd80` は462.97秒。
その時間帯のbrowser tool計測は19回・計50.81秒、内包する画面観測は計4.09秒。
OTP送付に24.76秒の承認待ちがあり、予約確認/変更/払戻メニューは未承認のまま停止した。
後者の確認提示から最終回答までは約197秒。ブラウザが実際に予約一覧へのクリックを
送信して固まったという証拠はなく、確認境界で止まっていた。残りを推論時間と断定はしない。

本人ログイン用の認証コード送付と入力、予約一覧メニュー、履歴閲覧を確定操作と区別する。
購入・実際の外部メッセージ送信・削除等の確認は維持。ローカル編集、下書き作成、内部状態照会等の
可逆な道具の一律確認も撤去。任意シェル実行は引き続き個別確認が必要。
job_progressの公開と呼び出し義務を削除。自然に出るcommentary、ツールの状態と時間、最後の画面観測を
アプリが保存し、音声窓口の状態照会で読めるようにする。別の報告用モデル呼び出しは追加しない。

独立ブラウザは同じユーザー・同じ窓口の終了済み作業から再利用し、並行中のブラウザは借りない。
旧jobの既存プロファイルも再利用対象とする。直近8件の部屋の会話を作業開始時に渡す。
音声作業は通常DOM観測（本文・見出し・入力値・要素参照）を使い、画像が必要なときはscreenshotを使う。
通常プロジェクトの既存デフォルトは変更しない。一括入力・期待結果付きクリックは共通実装を継続する。

76件の関連テスト成功。実Astra CLI＋Dan browserで模擬SMS→予約メニュー→詳細を確認なしで完了（48.51秒）。
別の実ブラウザ試験で購入確認、並行閲覧、途中条件変更、古い承認拒否、一度だけの模擬購入を再検証した。
異なる模擬課題なので、実サイトが何倍速くなったという比較ではない。実SMS送付・購入・取消は行っていない。
証跡：`.tmp/voice-fast-path-proof.json`、`.tmp/command-jobs-e2e-proof.json`。
GPT-6 Astraのコードによる複数操作方式は公式資料でも推奨されるが、この修正で汎用Playwrightコード実行環境へ
全面移行したわけではない：https://developers.openai.com/api/docs/guides/tools-computer-use

## Live窓口のAstra CLI統合（2026-09-15 夜）

Terra Responses API呼び出しを撤去。Live 1のclient delegationは、会話ごとの永続
`VoiceCodex` → GPT-6 Astra Codex app-server（ChatGPT認証）へ渡す。相談・状態確認・
作業起動・途中指示・通話終了を同じAstraが判断し、長い作業は既存の独立jobへ渡す。
ツール結果は元のCLI要求へ返す。終了済みの結果は再実行せず拒否する。
通話中の後続発言でも同じthreadを使う。画像入力も画像として引き継ぐ。
接続時にCLIとthreadのみ準備し、依頼前にモデル生成は開始しない。
音声切断でCLIを閉じ、異常な切断に備え10分の無活動時にも閉じる。
音声Live APIの課金は継続するが、窓口用Terra API・代替APIへのフォールバックはない。

本番frontend `.next-prod-1789472613`。実CLIで道具→結果→後続質問の文脈保持を確認。
実Live 1のテキスト依頼→Astra→ブラウザ→音声回答も成功。
通話終了は初回の他試験と並行した試験が12秒でタイムアウト、独立再試験では6.59秒で一度だけ停止。
この後、CLI準備を音声接続時へ前倒しした。
前倒し後の実音声再試験も停止1回・6.47秒で成功したが、通話終了の大幅な短縮は確認できていない。

`browser_script` は制限されたPython風のawait文で、最大20操作をまとめて既存browser道具に渡す。
role/name・表示テキストの完全一致で対象を解決し、各操作で確認・停止・revisionを検査する。
import、任意Python/JS、ネットワーク直接操作は実行しない。汎用Playwright実行環境ではない。
結果が異なれば停止し、実行済みのstepと承認されたstepを返す。
実Astraの同一模擬課題1回ずつで通常50.47秒、コード利用46.75秒。コード側も画面確認のため分割実行した。
大幅な速度差の根拠にはならないため通常操作を廃止せず、適した部分をまとめる能力として追加した。
既存browser出力の一律「個人情報入力はRed・確認必須」追記も削除し、共通の確認規則と矛盾させない。

## 音声再接続時の部屋の記憶（2026-09-15 夜）

`/live/session` が部屋の履歴を取得していなかったため、21:01の「新幹線の話を覚えている？」に
記録がないと回答した。同じ部屋には20:06の予約・取消条件の報告が保存されていた。
接続時に会員権限を検査した上で直近96件を一度取得し、LiveとAstraの両方に渡す。
Liveは7,400 UTF-8 bytes、Astraは60,000 bytesを上限に新しい記録から選び、古い順に並べる。
通常のメッセージは途中で切らず、最新一件だけで上限を超える場合は中略を明示して先頭と末尾を残す。
古い全文は既存の部屋履歴ツールで参照できる。履歴取得失敗を空の記憶として黙って続行しない。

Liveのsession.inputには過去の記録として引用したテキストを渡す。
旧発話をassistantの発言として再現した試行では、終了依頼を聞いても委譲されないケースが再現した。
引用したuserデータとして渡す形で同じテスト部屋の終了が成功（6.25秒）。
Astraは最初の依頼にだけ履歴を付け、以後は同じCLI threadで継続する。過去の依頼は再実行しない。
CLI準備はLive接続のHTTP待ちと並行して開始し、接続失敗時には準備したCLIも閉じる。
通話間で有料のLive接続を維持する方式ではない。

実Liveで別sessionへの再接続後に直前の旅行希望を回答、実Astraでも別接続で希望を復元できた。
記憶のみのLive回答ではバックエンド呼び出し0回を確認。最終試験の証跡は
`.tmp/voice-reconnect-proof.json`。13件の関連Pythonテストを実行。
ブラウザ実作業全体や通話終了が大幅に高速化したことを示す比較ではない。

## 2026-09-16 voice error isolation and steering (saved and verified, deployment pending)

- Removed frontend disconnect on backend HTTP 409. A failed reasoning/tool request no longer tears down Live audio.
- Backend exceptions log their class, source frame locations, thread/turn IDs and pending/result IDs, without transcript or tool-output bodies. The original 2026-09-15 exception remains unidentified because its detail was not recorded.
- Fresh requests may recreate a failed VoiceCodex instance; orphan tool outputs never trigger recovery/replay.
- LiveBackend forwards additional delegations through /live/backend/steer while a turn is active. Codex turn/steer acknowledgements use a separate reply queue so they cannot steal ongoing turn events. Rejected steering falls back to a new turn; uncertain transport failures are not automatically resent.
- Newly returned actions from an outdated request revision are suppressed. Already running worker operations still use existing control_dan_task/confirmation behavior.
- Confirmed closed/failed peer connections bypass the 100-poll wait in the headless controller; transient connecting/disconnected states keep their existing grace period.
- Validation: 18 Python tests and 8 JS tests passed across the voice/editor transport and headless tests. A real Astra 20-second sleep was interrupted by steering; revised answer arrived in 2.219 seconds. A separate browser running build .next-prod-1789488294 maintained a real Live 1 peer connection after an injected HTTP 409 and accepted another request without closing.
- Production reload was rejected by automatic approval review (only reason returned: blocked by policy). Existing production processes were not changed. Prepared manual apply script: .tmp/apply-voice-repair.py; checks idle sessions and process ownership. Device firmware unchanged.
- Official protocol reference: https://developers.openai.com/codex/app-server (turn/steer).
