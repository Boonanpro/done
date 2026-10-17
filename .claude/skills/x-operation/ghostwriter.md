# ゴーストライターで記事を作る（運用室の「記事を作る」）

## 前提

記事の型と文章は Ghost Writer（Levela、app.levela.co.jp/ghost-writer）に任せる。私は、題材選び・インタビューへの答え・直した版・表紙と画像・セルフ引用を受け持つ。本人は、Ghost Writer が書いたままの原稿と、このスキル（article-writing.md・title-cover.md）で直した原稿の2本を運用室で見比べて選ぶ。

Ghost Writer が止まった時は、私が代わりに書かない。止まった段階と出ていたエラーを知らせて終える（本人の決定 2026-10-17）。

始まり方は2つ。どちらも運用室の「記事を作る」から並行作業として届き、依頼文に run（運用室の「ゴーストライターそのまま」の行の id）とアカウントが入っている。

| 入口 | 依頼文 | 手順 |
|---|---|---|
| 題材探しから | 参考記事の指定なし | 1 から |
| 参考記事のURLを貼った | 参考記事のURLあり | 2 から（1 は飛ばす） |

## 道具

```
python D:/done/frontend/src/app/artifacts/x-operation/ghostwriter.py <命令> --run <run> ...
```

| 命令 | すること |
|---|---|
| `fetch --url URL --out F` | 参考記事の本文を Ghost Writer で取る（X記事は全文） |
| `begin --title T --memo-file M --ref-file F [--ref-file F2]` | 文体の分析→インタビュー開始。最初の質問を出す |
| `answer --text-file F` | 質問に答える。次の質問を出す。書く準備ができたら1行目が `READY` |
| `generate [--length 2500-3500]` | 本文を生成して raw.md に保存。Ghost Writer が本文に付けた見出しを `title_in_article` で返す |
| `stage --text 説明 [--state running/done]` | 運用室の一覧に出る進み具合を書き換える |
| `reference --file candidates.json` | 題材の候補3件・選んだ1件・理由を運用室に残す |
| `draft --variant raw/edited --file F.md --title T [--cover URL]` | 原稿を運用室に置く（raw は今の行、edited は隣に新しい行） |
| `ask --file questions.json` | 本人に聞く質問を、記事の編集アシスタントの欄に出して答え待ちにする |
| `stop --stage 段階 --error エラー` | 止まったことを運用室と部屋のチャットに知らせる |

作業の控え（参考記事・材料・答え・原稿）は `D:/dan-workspace/jobs/x-ghostwriter/<run>/` に置く。インタビューの会話は同じ場所の state.json と Ghost Writer のセッションに残るので、作業が途中で終わっても続きから進められる。

道具が終了コード3で `GHOSTWRITER_STOPPED: …` を出したら、「止まった時」へ進む。

## 手順

段階が変わるたびに `stage` で一覧の表示を書き換える（例：「題材を探しています」「インタビューに答えています」「本文を書いています（ゴーストライター）」「直した版を作っています」）。

### 1. 題材を選ぶ（題材探しからの時だけ）

1. 最新の `D:/dan-workspace/x_research/rows_*.json`（ろじんXリサーチ、区分「X記事」の1か月・表示順の上位100件）を読む。ファイルの日付が7日より古ければ、ブラウザで https://dashboard.x-research.jp （shub6923 でログイン）を開き、「X記事」×「1ヶ月」×インプレッション順の上位100件を同じ列（区分・投稿日・アカウント・名前・日本語・タイトル・書き出し・投稿文・リポスト・いいね・表示回数・いいね率・URL）で取り直して保存する。数字の注意は x_research/README.md。
2. 日本語の記事だけにする。前に参考にした記事（`jobs/x-ghostwriter/*/candidates.json` の選んだ1件）は外す。
3. 次の順で絞る。
   - タイトルの形が、`x_research/analysis_*.md` の3章の表の形（2種類の人の違い・隠れた仕組み・具体的な結果＋N選・理由・常識の逆・研究や有名人）のどれかに当たる。
   - そのアカウントの読者（SKILL.md の表）に向けて、本人の実体験（記憶と過去の記事にある事実）で、同じ形の中身を全部埋められる。埋められない形は外す。
   - 残りが同じくらいなら表示の多い方。
4. 記事の役目を「届く」か「売る」かに決める（analysis の1章）。
5. 3件を候補にして1件選び、`reference` で残す。理由は「形の名前・本人のどの話を当てはめるか・役目」を1〜2文で書く。

```json
{"candidates":[{"url":"https://x.com/…/status/…","title":"…","author":"@…","impressions":3820000,"reason":"…"}],"chosen":0,"reason":"…"}
```

### 2. 参考記事を読む

`fetch --url <参考記事> --out <控え>/ref.txt`。本文が取れなければ止まった扱いにする（段階「参考記事の取得」）。

### 3. 材料を集める

インタビューに事実で答えるための材料を `<控え>/memo.txt` に箇条書きで集める。1行に事実1つと出どころ（ファイル名・日付）を書く。

| 探す所 | 中身 |
|---|---|
| `~/.dan/workspace/memory/MEMORY.md` と、そこから案内される記憶 | 実績の数字、期間、案件の事実 |
| `D:/dan-workspace/x_articles/` と examples/articles/ の本人の記事 | 本人が既に書いた話と言い方 |
| `D:/done/.data/lifelog/<日付>.jsonl`（ピンの常時録音の文字起こし） | 日々の会話での本人の言葉（題材の言葉で rg） |
| 面談の録音（`D:/dan-hw/meeting-rec/recordings/`、文字起こしがあれば） | 相談者の困りごと |

memo.txt の最後に、アカウント・読者・記事の末尾の案内（SKILL.md の表）と、書かないこと（煽り語・本人が使わない言い方）を足す。この memo.txt を begin の内容メモとして渡す。推測は書かない。

### 4. タイトルを決めて始める

Ghost Writer はタイトルを作らない（タイトル欄が必須で、空だと始まらない）。title-cover.md の「作る手順」でタイトルを1つ決め、`begin --title <タイトル> --memo-file memo.txt --ref-file ref.txt` で始める。

### 5. インタビューに答える

質問ごとに、次のように答える。答えは `<控え>/answer_<番号>.txt` に書いて `answer --text-file` で渡す。

- 材料にある事実は、数字・時期をそのまま答える。
- 材料に無いことで、記事の中心（何をしたか・結果の数字・読む人がまねする手順）に当たるものは、本人に聞く。
- 材料に無いことで、周り（その時の気持ち・細かい作業時間・相場の感じ）に当たるものは、「記録に無いので書かない」と答える。

本人に聞くものがあれば、答えられる部分を先に渡してから `ask --file questions.json`（質問の文字列の配列）で出し、作業を終える。質問は1つにつき1文で、本人が一言で答えられる形にする（例：「LINE登録から面談申し込みまで、平均何日でしたか」）。

`answer` の1行目が `READY` なら6へ進む。6往復しても READY にならなければ、そのまま6へ進む（Ghost Writer の画面の「スキップして生成」と同じ）。

### 6. Ghost Writer の原稿を置く

`generate` で raw.md を作り、`draft --variant raw --file raw.md --title <タイトル>` で運用室に置く。タイトルは、Ghost Writer が本文の頭に付けた見出し（`title_in_article`）があればそれ、無ければ4で渡したタイトル。raw.md は書き換えない（本人が見比べる基準になる）。

### 7. 直した版を置く

raw.md を元に、article-writing.md と title-cover.md の手順で直した `<控え>/edited.md` を作り、`draft --variant edited --file edited.md --title <タイトル>` で隣に置く。

- 事実は raw.md と memo.txt にある物だけを使う。
- Ghost Writer は参考記事の決め台詞・見出しの組み方・語尾をそのままなぞることが多い。本人のアカウントで使わない言い方は、ここで外す。
- 表紙・記事内の画像・動画は、本人が選んだ方に付ける（2本の比較は文章でする）。

最後に `stage --text "原稿2本ができました" --state done`。

## 本人の答えを受けて続ける

本人が編集アシスタントの欄で質問に答えると、その答えを持った並行作業が届く。state.json の会話の続きとして、答えを質問の順に整理して `answer` で渡し、5の続きから進める。答えに無い所は「書かない」で進める。

## 本人が選んだ後

本人が編集アシスタントで「こっちで進めて」のように選んだら、その原稿に article-writing.md の「画像の用意」と title-cover.md の表紙を付ける（運用室への返し方は運用室の決まり）。記事がXに出た後、セルフ引用の案を quote-writing.md で作る（投稿は本人）。

本人が選ばなかった方との違い・本人が直した所は、次にスキルを直す材料になる。直す時は skill-creator の手順で汎化してから入れる。

## 止まった時

止まった扱いにするのは、参考記事の取得・文体の分析・インタビュー・生成が失敗した時だけ。Ghost Writer の下書きの保存（セッション・記事）の失敗は、画面と同じく道具が無視して続ける（会話は state.json に残る）。

道具が `GHOSTWRITER_STOPPED` を出したら、`stop --stage <止まった段階> --error <出ていた文>` を1回だけ実行して終える。私が代わりに記事を書かない。やり直してよいのは、通信が切れた時（ConnectionError・Timeout）に同じ命令を1回だけ。
