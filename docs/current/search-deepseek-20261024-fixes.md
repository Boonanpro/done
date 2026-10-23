# 検索 DeepSeek の点検で出た指摘の直し（2026-10-24）

`search-deepseek-20261023.md` の変更を本番に入れる前に、別のダンの点検で出た重い3点と、すぐ直せる軽いものを直した。

## 重い3点

1. **DeepSeek が遅い日に通話が2分以上黙る。** `web_search.find()` に締め切りを入れた。DeepSeek 全体で10秒、OpenAI に戻した分も含めて40秒（前の通話の検索と同じ）。DeepSeek が失敗・時間切れになったら、その後2分は DeepSeek を飛ばして OpenAI に直接行く。
   実測（本物の API、DeepSeek だけ60秒待たせた）: 19.5秒で OpenAI の答え。次の検索は DeepSeek を飛ばして5.2秒。普段の DeepSeek は3.1秒。
2. **終わりの言葉の判定が特定の文字列で指数的に遅くなり、Core 全体を止める。** 正規表現をやめ、文字の位置を1回なめるだけの判定 `voice_prefetch.is_ending()` にした。「なん」×200 でも即座に返る（テスト）。
3. **先回りの結果が別の問いの検索に渡る。** 先回りの結果を渡すのは、裏のモデルがその問いで最初に呼んだ関数が web_search の時だけにした。places（近くの店）や get_location（場所の無い天気）を先に呼んだ後の web_search は、本人の言葉より狭いことを聞いているので、自分で検索する。ラーメンの問いはこの形なので、先回りは効かなくなる（変更前の 20.2秒 → DeepSeek だけの 11.8秒の側になる見込み）。

## 軽いもの

- 先回りの検索は OpenAI に戻らない（DeepSeek が落ちている日に OpenAI の残高を1問3回まで使っていた）。
- `DAN_VOICE_PREFETCH=0` を `.env` に書いても効くようにした（再起動不要）。
- 通話中の言葉の判定で例外が出ても、通話の裏側が止まらないようにした。
- 検索結果に URL の無い行があっても、DeepSeek 側がまるごと失敗しないようにした。
- `DAN_API_JOB_TOOLS` で道具を絞った時は、検索の一覧・本文取りの道具もその指定に従う。
- Mac に無い `msvcrt` でロックを取っていた3か所（作業の状態 `command_job_state`、作業の順番 `work_locks`、Jev の予算）を、共通の `app/services/file_lock.py`（Windows は msvcrt、Mac は fcntl）にした。Mac の本番では、通話から頼んだ作業や裏の作業が状態を書けずに落ちていた。

## テスト

`tests/test_voice_prefetch.py`（12本）、`tests/test_web_search_deadline.py`（4本）、`tests/test_file_lock.py`（1本）が通る。関係するテスト全体で、落ちるのは origin/main でも同じく落ちる6本（Windows の住所を前提にしたテスト、ブラウザの follow が増えたのに合わせていないテスト、job_feed の順のテスト）。
