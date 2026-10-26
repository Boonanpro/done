# deploy: 本番に入れる

本番に入れる道は1本だけ。作業場所の中で `work.py ship` を使う。D:\done で pull・commit・手で写すことはしない。

## 前提

- [modify-and-test.md](modify-and-test.md) で試して、結果に問題がない。`work.py try stop` で試験用のサーバーを止めてある。
- 持ち主がその変更を本番に入れてよいと言っている（ボードの付箋なら「本番に入れる」が押されている）。
- GitHub は人の速さで使う。関係する変更は1つの分岐にまとめ、1回の ship にする。

## 手順

1. 保存していない変更を残さない: `python D:/done/scripts/work.py save "仕上げ"`
2. 1つのコミットに、ダンの仕組み（`app/**`、`.claude/**` など）と成果物（`artifacts/<slug>/**`）を混ぜない（pre-commit hook が止める。分け方は `python scripts/scope_diff.py --working`）。
3. 入れる:
   ```
   python D:/done/scripts/work.py ship "変更の題"
   ```
   ship は、最新の main を取り込み → push → PR → マージ → `follow_github.py`（D:\done を main に合わせる）の順に1回ずつ進む。
   - **main とぶつかったら止まる。** 名前の出たファイルを、この作業場所で直して `save` し、試し直してから、もう一度 ship する。ほかの作業の中身は、ここで初めて混ざる。動いているダンには、混ぜ終わって試した物だけが届く。
   - GitHub が認証・権限で断ったら、その1回でやめて報告する。繰り返さない。
4. ship が出す「入れ替えが要るもの」に従う。
   - 画面: `python D:/done/scripts/frontend_prod.py restart`（会話は止まらない）
   - 本体（Core・サンドボックス）: `python D:/done/scripts/restart_dan_core.py --when-idle --then "<入れ替え後に確かめること>"`（全部の会話が終わってから入れ替わり、結果が部屋に届く）
5. 入れ替わった実物で確かめてから、「できました」と報告する。保存した・マージした・動いている、はダンが自分で区別して確かめることで、本人への返事には書かない。本人には、使えるようになったか・使い方がどう変わるか・本人がすることだけを伝える。
