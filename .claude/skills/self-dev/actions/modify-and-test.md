# modify-and-test: 直して試す

ダンのコードは、作業ごとの作業場所（worktree）で直す。動いているダン（D:\done）には書かない。書こうとすると `scripts/hook_live_tree_guard.py` が止めて、ここへ案内する。

## 手順

1. 作業場所を作る（続きなら `--from <分岐>`。救い出した書きかけは `wip/...` の分岐にある。`work.py list` で一覧）:
   ```
   python D:/done/scripts/work.py new <名前>
   ```
   `D:\dan-workspace\<名前>` に分岐 `dan/<名前>` ができる。frontend の node_modules は D:\done のものをつないである。
2. そこで直す。区切りごとに保存する（コミットした物は、ほかの作業に上書きされず、消えない）:
   ```
   python D:/done/scripts/work.py save "何をしたか"
   ```
3. 変えた所に合わせて試す。
   - 試験: 作業場所で `python -m pytest tests/<関係するもの>`。
   - 動かして見る: 作業場所の中で
     ```
     python D:/done/scripts/work.py try        # API 8001（作業場所のコード）と画面 3002（API は 8001 へ）
     python D:/done/scripts/work.py try stop   # 終わったら必ず止める
     ```
     立ち上がりは 8001 が十数秒、3002 が約30秒。記録は作業場所の `.data/try/`。チャット（Core 9000）は本物のままなので、Core の変更は本番に入れた後に確かめる。チャット画面をテスト用アカウントで見る手順は記憶の project-chat-ui-test-with-test-account。
   - 8001・3002 が使われていたら、ほかの作業が試している。止めずに終わるのを待つ。
4. 証拠を添えて報告する（試験の結果、curl の応答、画面の写真）。「できました」だけで報告しない。

本番に入れるのは [deploy.md](deploy.md)。
