---
place: script-listen
name: 台本を聞いて直す画面
open: /script-listen?doc=1YrEXisxuge_SOmcFNJ_7ecPjTxGQSVwOice25RYBfbA
ready: '[data-testid="script-editor"] [data-para]'
watches: [frontend/src/app/script-listen/page.tsx, frontend/src/components/script-listen/listen-screen.tsx, frontend/src/components/script-listen/editor-dom.ts, frontend/src/components/script-listen/listen-cards.tsx, frontend/src/lib/script-listen-api.ts, app/api/script_listen_screen.py, app/services/script_listen.py]
errors: [このドキュメントを開けませんでした, 読む文がありません]
speak: |
  - 台本の Google ドキュメントを読み上げで聞き、その場で直し、コメントでダンとやり取りする画面です。
  - 撮る時に開くのは中村さんの台本（④2本目）。開くだけでは台本は変わらない。直す確かめは消してよい写しで scripts/check_script_listen.py を使う。
shows: []
---
# 台本を聞いて直す画面

/script-listen?doc=<Google ドキュメントの ID か URL>。PC とスマホ。台本の正本は Google ドキュメントで、この画面はその中身をそのまま出す。

## 中にある物

- 上の帯: 台本の題、「コメント N」（PC は解決済みの出し入れ、スマホは全部のコメントと提案の欄）、声の選び、「共有」（`[data-testid="share-copy"]`。相手に送るリンクをコピーする。リンク先は作業用ではなくお客さん用の写しで、リンクを知る人は誰でも編集・コメントできる。初めて押した時に写しができ、台本が写しより進んでいれば欄に「今の台本に更新する」が出る。app/services/script_share.py、2026-11-20 本人）、「ドキュメント」（元の Google ドキュメントを開く）。右の「ダンと台本」の会話の欄は白い地（`.theme-light`、11/20 本人「黒じゃなくて白に」）。
- 本文（`[data-testid="script-editor"]`）: タイトル、白い枠の中のサムネ・タイトル・前提と狙い（読まない）、「◎台本」から下の本文。全体が1枚の編集面で、文や段落ごとの枠は無い（2026-11-19 本人「黄色い枠…余計なものを付けるな。Googleドキュメントと同じくらいの使い勝手にしろ」）。
  - 鳴っている文に薄い橙の帯（打っている間は消える）。コメントの付いた文は薄い黄色。提案は緑の下線（足す）・赤の線（消す）。
  - 段落をまたいで選べる。選ぶと、PC は本文と右の札の間、スマホは選んだ所の下に丸いコメントの印（「コメントを追加」）。
  - Enter で改行、Ctrl+Z で戻す、Ctrl+Shift+Z / Ctrl+Y でやり直し、Ctrl+B で太字。打つのを止めると、変わった段落が自動でドキュメントに入る。
- 右の余白（PC）: コメントの札（返事・解決）と提案の札（承認・却下）が、その文の横に並ぶ。スマホは下から出る欄。
- 下の帯: 何文目か・残りの時間、前の文・聞く/止める・次の文、速さ（1〜3倍）。

## 行き方（みきさんから見て）

台本を出した時にダンが貼る「聞いてチェック」のリンク。PC はブラウザ、スマホはアプリの中のブラウザで開く。

## 道具で動かす

- 読む・直す・コメントの裏側: app/services/script_listen.py（read・replace・decide・comments）。
- 通しの確かめ: `python scripts/check_script_listen.py --base https://dan.paina.info --doc <ID> --edit-doc <消してよい写し> [--phone] [--comment]`。写しの作り方と片付けは記憶 project-script-listen-screen-20261118。
