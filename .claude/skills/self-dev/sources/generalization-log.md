# 変更の記録（self-dev）

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
