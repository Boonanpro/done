# 変更の記録（self-dev）

## 2026-10-18 試す・本番に入れるを work.py の1本の道にした
- 種類: 操作
- 変更するファイル: actions/modify-and-test.md、actions/deploy.md
- 何を直したか: 2つの資料が、存在しない scripts/start_test_backend.py と、D:\done で直して HMR で見る・D:\done から git push する古い手順を指していた。作業は worktree ごとに分け、D:\done には書かない形（scripts/hook_live_tree_guard.py が止める）に変えたので、手順を `work.py new / save / try / try stop / ship` の1本にした。8001 は app.sandbox を作業場所のコードで、3002 は next dev --webpack で立ち、画面の API は 8001 へ向く。チャット（Core 9000）は本物のまま。本番に入れた後の入れ替え（frontend_prod.py restart / restart_dan_core.py --when-idle）は ship が出す案内に従う。
- 確かめたこと: 2026-10-18 に作業場所 D:\dan-workspace\parallel-dev-isolation で `work.py try` を実際に動かし、8001 は11秒、3002 は約30秒で応答した。3002 の /api/v1/projects への要求が 8001 の記録に届いたことを見た（401 が返った）。`try stop` で両方が止まり、ポートが空いた。作業場所の tsconfig は書き換わらなかった。ship は試験（tests/test_work.py 6件）で、push・PR・マージ・follow_github まで通ること、同じファイルを2つの作業が直した時に2つ目の分岐で止まり、動いているフォルダには届かないことを確かめた。
