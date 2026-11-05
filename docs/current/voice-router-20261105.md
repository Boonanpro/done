# 通話の頼みの行き先を Jev が選ぶ（2026-11-05）

本人の 11/5 0:59 の通話（10分49秒）で、美容院と眉毛サロンの空きの確認が、通話用の短い調べもの（gpt-6-luna）に回り、3回とも「確認できなかった」で終わった。同じ頼みをチャットのダンは1分54秒で済ませた。「今どういう状況？」は裏の判断役の1往復（約6秒）を待ち、声のモデルの「確認してる」と裏の答えの2回で答えていた。画面に出た8枚は、話を描き直した図が3枚、空の画像が5枚だった。

## 作り

- 通話の委譲は client（`voice_router.session_delegation()`、`acknowledgement_delay_ms` 800）。委譲が来たら、このサーバー（`voice_sideband` → `voice_router.Router`）が答える。
- Jev が行き先を選ぶ（`ROUTES`、中央値約150ms）。選択肢は話題ではなく「どこで・何を使ってやるか」で書いてある。動いている作業ごとに、最後の言葉がその作業に何をしているか（様子を聞く・止める・変える・別の話）を別の問いで聞く（`questions` / `decide`）。
  - status: 作業の記録と調べものの状態をその場で読んで答える（`status_text`）。
  - calendar（今日・明日・7日間）: カレンダーを読んで答える。
  - lookup / show（知らないページ）: 裏の調べもの（`voice_lookup`）。読むだけ。サイトやアプリの中が要る時、時間内に答えが出ない時、仕組みが止まった時は、分かったことを付けてチャットのダンに渡す（`hand_over`）。本人には何も言わない。
  - show（成果物の名前が分かった時）: その画面を出す。
  - site / app / make / dan: チャットのダン（部屋のモデルの並行作業、engine `make`）。頼みの文は書き直さず、本人の言葉と通話の文字起こし（`TRANSCRIPT` の後）をそのまま渡す。部屋のチャットには本人の言葉だけが出る（`make_job_runner.note_request`）。
  - document / message / rooms / other、Jev が迷った時（確率 0.6 未満）、Jev が使えない時: 前の裏の判断役（gpt-6-luna と通話の道具）をこのサーバーで回す（`Router.luna`）。
  - end: 挨拶の後に通話を閉じる。
- 委譲への答えは、自動の受け答えの前（800ms 以内）なら commentary で1回だけ言う。過ぎていれば、作業を始めた知らせは thinking（黙って渡す）にする。
- 作業の今の様子は、変わるたびに thinking で声のモデルに渡す（`voice_sideband.tell_state`、1作業6秒に1回まで）。声のモデルの指示に「渡された作業の様子で答えられる時は委譲しない」を1行足した（`voice_plain.ROUTED`）。作業が「【途中】」で始めて書いた事実だけを声で伝える（`CALL_JOB_NOTE`）。
- 画面: 話を図に描く仕組み（`Stage.decide` の自動の呼び出し）は止めた（`Stage.listening`、`DAN_VOICE_STAGE_LISTEN=1` で戻る）。真っ白・真っ黒の写真は出さない（`voice_screen_media.blank`）。チャットのダンのブラウザは、作業が進むたびにまた画面に戻る（`voice_worker_screen.Follower`、本人に出したページは12秒保つ）。
- 話している途中の Jev の判断（`voice_prefetch`）も同じ選択肢を同じ呼び出しで聞き、言い終わった言葉が同じなら委譲の時に聞き直さない（`Router.early_route`）。

## 切り替え

`DAN_VOICE_ROUTER=0` で前の Responses 委譲に戻る（`DAN_VOICE_PLAIN` と `DAN_VOICE_BACKGROUND` が有効な時だけ動く）。試験は既定で `DAN_VOICE_ROUTER=0`（tests/conftest.py）、振り分けの試験は自分で 1 にする。

## 確かめ方

- 選択肢: `python scripts/voice_route_eval.py <本人のid> [cases] --repeat 2`。`tests/voice_routes/real_requests.json`（本人が通話で言った50件、説明を直すのに使った）と `held_out.json`（使っていない15件）。11/5: 最初の説明で 38/50、問いを分けて説明を直した後 98/100、held_out 30/30。
- 裏だけで頼みから結果まで: `python scripts/voice_route_backend_run.py tests/voice_routes/salon_backend.json <出力> --model astra`（試験用の部屋を作って消す。通話はしない。OPENAI_API_KEY は改行を含めずに渡す）。
- 委譲の設定が受け付けられるか: WebSocket で `session.start` してすぐ閉じる（音声なし）。11/5 に client + 800ms が受け付けられた。
