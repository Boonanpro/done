# 変更の記録（self-dev）

## 2026-10-23 Mac の住所と、work.py の test・venv・選んで保存・取り込み後の再試験に合わせた
- 種類: 操作
- 変更するファイル: actions/modify-and-test.md、actions/deploy.md
- 何を直したか: 2つの資料が Windows の住所（D:/done/scripts/work.py、D:\dan-workspace）と、10/18 の work.py の動き（node_modules は動いているダンのものをつなぐ、save は全部を保存、ship は試験を見ない）を書いていた。ダンの本体は 10/23 から Mac mini（/Users/mikihonda/done）で動き、10/18 に確かめた別の目の指摘で work.py を次のとおり直したので、手順を合わせた: node_modules は作業場所ごとの写し（APFS の複製）、Python を足すのは `work.py venv` の .venv（共用の Python への pip install は関所が止める）、save は追っているファイルの変更とリポジトリにあるフォルダの新しいファイルだけ（`--only` で指定）、`work.py test -- <コマンド>` が試験を覚え、ship は main を取り込んで新しい物があればもう一度流し、通らなければ何も出さずに止まる、follow_github が失敗したら ship も失敗で終わる、関所は書けてしまった物を操作の直後に `wip/<日付>-<セッション>` へ移して戻す。
- 確かめたこと: 2026-10-23 に作業場所 /Users/mikihonda/dan-workspace/parallel-dev-isolation で試験123件が通った（直す前の版では新しい試験54件が落ちる）。本番を写した一時フォルダと手元の bare リポジトリ（GitHub の代わり）で `work.py test` → `work.py ship --no-follow` → `rescue_wip.py --apply` → `follow_github.py` を通し、書きかけ1,030件が全部、分岐か元の場所に残ったことを中身の照合で確かめた。試験が落ちる時に ship が push 前に止まることも、この写しで見た（試験の書き方の誤りで2件落ちた時に「試験が通りませんでした」で止まった）。Mac の本物の Claude Code と Codex（直接・部屋の中継の両方）で、関所が書き込みを止め、スクリプトの書き込みを直後に分岐へ移すことを見た。

## 2026-10-18 試す・本番に入れるを work.py の1本の道にした
- 種類: 操作
- 変更するファイル: actions/modify-and-test.md、actions/deploy.md
- 何を直したか: 2つの資料が、存在しない scripts/start_test_backend.py と、D:\done で直して HMR で見る・D:\done から git push する古い手順を指していた。作業は worktree ごとに分け、D:\done には書かない形（scripts/hook_live_tree_guard.py が止める）に変えたので、手順を `work.py new / save / try / try stop / ship` の1本にした。8001 は app.sandbox を作業場所のコードで、3002 は next dev --webpack で立ち、画面の API は 8001 へ向く。チャット（Core 9000）は本物のまま。本番に入れた後の入れ替え（frontend_prod.py restart / restart_dan_core.py --when-idle）は ship が出す案内に従う。
- 確かめたこと: 2026-10-18 に作業場所 D:\dan-workspace\parallel-dev-isolation で `work.py try` を実際に動かし、8001 は11秒、3002 は約30秒で応答した。3002 の /api/v1/projects への要求が 8001 の記録に届いたことを見た（401 が返った）。`try stop` で両方が止まり、ポートが空いた。作業場所の tsconfig は書き換わらなかった。ship は試験（tests/test_work.py 6件）で、push・PR・マージ・follow_github まで通ること、同じファイルを2つの作業が直した時に2つ目の分岐で止まり、動いているフォルダには届かないことを確かめた。

## 2026-10-18 成果物の裏側は再起動なしで替わる・完了の根拠は本人と同じ経路だけ
- 種類: 操作
- 変更するファイル: SKILL.md
- 何を直したか: 確認の段に次を足した。成果物の _server（sandbox 8000 が動かす）は app/services/artifact_backends.py が変更を見て数秒で差し替えるので、そのためだけに本体を再起動しない。裏で thread を回す routes.py は `dan_unload()` を持たせる（無いと二重に動くのを避けて差し替えず、再起動待ちと出る）。artifact_seen.py は画面・裏側・公開版（スマホのアプリが開く写し）の3つを見るので、その出力を完了の根拠にし、8001 の確認用サーバーや worktree の確認は途中の試験として扱う。確かめずに終えると Stop の関所（hook_artifact_verify_gate.py）が止める。背景: 10/18 本人「あなたのテスト環境が私の環境と違うことがズレの原因になっているなら根本から直す」。面談受付で画面だけ新しく裏側が再起動待ちのまま長く続いた。
- 確かめたこと: 実際の uvicorn で _server を書き換えて連続アクセス中に失敗0件で替わり thread が1本のままだったこと、構文エラー・dan_unload 無しの時に古い版のまま理由を記録すること。Claude CLI と Codex CLI の両方で関所が止め、artifact_seen.py の結果どおりに書くと通ること。

## 2026-10-18 成果物タブに映る変更は本人の画面の版で確かめる
- 種類: 操作
- 変更するファイル: SKILL.md
- 何を直したか: UI の確認の段に、成果物のページが読み込む frontend/src のコードを変えた時は、ダンのブラウザの確認とは別に `python scripts/artifact_seen.py` で本人が開いている成果物の画面が今の版になったかを確かめてから報告する、と足した。ダッシュボード（3000）は本番ビルドで、成果物タブ（/preview）は開発サーバー（3001）なので、どちらに映る変更かで確かめ方が違うことも1文で書いた。背景: 10/18 ダンのブラウザでは直った表紙の×ボタンが、本人の画面では古い部品のせいで出ず、本人に何度も確かめさせた。
- 確かめたこと: 本人の Chrome の成果物タブ（X運用室）が今の版を知らせ、artifact_seen.py が OK を出したこと。テスト用アカウントの画面を除いて本人の画面だけを出すこと。ファイルを直した直後、HMR が生きている本人の画面は読み直されずに新しい版を知らせたこと（試験中の数十回の版の変化で本人の画面の読み直し回数は0）。

## 2026-10-25 本人への報告から、確かめ方と仕組みの状態を外す
- 種類: 操作
- 変更するファイル: SKILL.md、actions/deploy.md
- 何を直したか: 2つの資料が「保存した・マージした・動いている、を分けて書く」「Report saved, tested and running states separately」と、仕組みの状態を本人への報告に書かせていた。そのせいでダンの返事が「本体がまだ入れ替わっていません」「入れ替わったら試します」「テスト用アカウントで Claude と GPT の両方で…」で埋まった。本人 10/25「意味分からん難しい話を長々されるのは困る。それは人間同士の会話としておかしい」。区別して確かめるのはダンの仕事のまま残し、本人へは使えるようになったか・使い方の変わり方・本人がすることだけを伝える、に変えた。話し方の決まり（~/.dan/workspace/SOUL.md）にも同じ線（人に話して通じて役に立つ話か）を足した。
- 確かめたこと: 2つの資料の該当文を読み直し、確かめる段（artifact_seen.py・入れ替え後の実物の確認）は1つも消していないこと。SOUL.md の新しい文が部屋の指示に組み込まれること（bootstrap_context の読み込み）。

