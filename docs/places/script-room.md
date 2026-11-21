---
place: script-room
name: 台本を聞く画面の「ダンと台本」（右の会話の欄）
reach: 台本を出した時にダンが貼る「聞く」のリンクで台本を聞く画面を開く。PC は右の欄、スマホは上の「ダン」を押すと下から開く
open: /script-listen?doc=1xxfzb0_99_KNNwWZHSjp9eu8LxIqDg3iw-AO367jNAc
ready: '[data-testid="script-chat"]'
speak: |
  - この部屋は台本を聞く画面（台本を読み上げで聞いて、その場で直す画面）の右の欄（PC は約400px、スマホは下から開く欄）。左に台本の本文があり、みきさんは台本を見ながら・聞きながら話している。台本1本につき1部屋。2026-11-20 から、台本を作る・直す時はこの画面が中心で、Google ドキュメントはほかの人への共有用。
  - 前置きの「みきさんの画面の今」が、みきさんのカーソルの文・選んでいる文字。「ここ」「この文」はそれ。
  - 本文を直す時は、コメントへの対応と同じ決まりで直す: 触る前に /Users/mikihonda/done/.claude/skills/talk-script/SKILL.md と revision.md を読み、文書の「◎前提と狙い」を確かめる。直す前後に `/Users/mikihonda/dan-venv/bin/python /Users/mikihonda/done/scripts/script_learning.py before|after --file <台本のID>` を実行する（本人の添削と混ぜないため）。直しは通常の Dan ブラウザで Google ドキュメントを提案モードにして入れる（Docs API で本文を直接書かない）。入れた提案は数秒で左の画面に緑と赤の線で出て、みきさんがその場で承認・却下する。
  - サムネを直してと言われたら、前置きの「台本の上のサムネ」の作品を thumb.py で直す。みきさんがサムネの編集を開いていれば、その画面がその場で変わる。閉じていても、直した形は数秒でドキュメントの絵に入る。
  - みきさんがサムネの編集を開いている間は、前置きの「みきさんの画面の今」に開いている作品（content_id）と選んでいる部品が入る。「このサムネ」「この文字」「これ」はそれ。部品を押す・ペンで描くと、みきさんの発言の後ろに「［画面から添えた物］」として部品の中身・書き込みの範囲が付き、赤い枠や線を重ねたサムネの絵が添付される。頼まれた部品だけを直し、ほかの部品と人物の絵には触らない。
  - 欄は狭い。返事は短く、何をどこに入れたかだけ言う。本文の全文をチャットに貼らない（左に出ている）。
  - 本体の部屋とは別の会話だが、ダンは一人。本体の部屋の話は前置きの room_id を lookup で読む。
probe: {classes: "prose prose-base prose-dan max-w-none"}
shows: [番号の並び, 点の並び, 表, 見出し, 太字, コード]
watches:
  - frontend/src/components/script-listen/listen-screen.tsx
  - frontend/src/components/script-listen/listen-chat.tsx
  - app/services/script_rooms.py
fingerprint: fb583cb8d8ae2589
described: f877eedf19142b46
---
# 台本を聞く画面の「ダンと台本」

台本を聞いて直しながら、ダンと話す場所。コメントは文に付けるやり取り、ここは台本全体の相談・作り直し・サムネの相談。

## 中にある物

- `chat` 右の欄（PC）。上の帯の「ダン」で開け閉めする。スマホは上の「ダン」を押すと下から大きく開く。地は白（`.theme-light`。11/20 本人「黒じゃなくて白にして」）。
- `share-copy` 上の帯の「共有」。押すと相手に送るリンク（お客さん用の写し。誰でも編集・コメントでき、コメントと未承認の提案は入らない）がコピーされる。写しが無ければ初めて押した時にできる。写しは台本を直すと数秒で自動で同じ文に書き換わる（提案の色は出ず直接。未承認の提案は写らない。11/21 本人「原本編集したら中村さんの方にも反映されて書き換わる」）。欄には最後に写した時刻と、相手が写しを直した数。共有して、と言われたらこのボタンを案内する。
- `client-suggestion` 相手が写しの本文を直すと、台本に「相手の直し」の提案の札として入る。承認で台本に入り、却下で写しも元の文に戻る。決めるまで写しのその所は相手の文のまま。
- 提案の文字を書き換えても提案のまま（承認・却下だけが決める。11/21 本人）。ダンの提案を書き換えると「みきさんの提案」に変わり、Google ドキュメントの画面からは消えて、この画面にだけ出る。
- `decide-all` 下の再生の段の右にある「すべて承認」「すべて却下」。提案が1つでもある時だけ出る。
- `dan-mark` ダンがドキュメントで文字を選んでいる・打ち込んでいる間だけ、その文が青く光り左に青い線が出る。考えている間は光らない。入った提案は一瞬光って、普通の緑と赤の線になる。
- `screen-state` みきさんのカーソルの文・選んだ文字・サムネの編集を開いているか（開いていればその作品と選んだ部品）。画面が数秒ごとに知らせ、ダンの前置きに入る。
- `attached` サムネの編集を開いている時、入力欄の上に付く札（「選んだ部品：文字「…」」「ペンの書き込み N本」）。部品を押す・ペンで描くと付き、×で外せる。送ると中身と絵が一緒にダンへ届く。スマホでは右下の会話のボタンに数の印が出る。案内文もサムネ向けになる。

## 行き方（みきさんから見て）

台本の「聞く」のリンク → 台本を聞く画面 → 右の欄（スマホは上の「ダン」）。

## 道具で動かす

- 台本の中身: `python -m app.services.script_rooms text <台本のID>`（段落番号つき、画面と同じ並び）
- サムネ: `python scripts/thumb.py show <部屋> <作品>` ほか。ドキュメントの絵へ入れるのは `python -m app.services.script_listen_thumbs sync <台本のID>`

<!-- place_map:auto:start -->
## コードから（自動）

`python scripts/place_map.py stamp script-room` が書き直す。手で直さない。

- 見張るファイル: `app/services/script_rooms.py`, `frontend/src/components/script-listen/listen-screen.tsx`
- ラベル: 「書き方」、「画像を入れる」、「声」、「ドキュメント」、「ダンの作業の様子を見る」、「前の文」、「次の文」、「ダンと台本」、「閉じる」、「ダンが直している所へ」、「コメントを追加」
- 試験の印: 「script-editor」、「chat-toggle」、「compare-toggle」、「image-add」、「dan-bar」、「ref-panel」、「listen-thumb」、「dan-glow」

<!-- place_map:files {"app/services/script_rooms.py": "a1b6c7f5f6", "frontend/src/components/script-listen/listen-screen.tsx": "807dee8758"} -->
<!-- place_map:auto:end -->
