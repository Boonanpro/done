---
place: prompts
name: ダンを動かしている指示文
open: /prompts
ready: 'textarea, button:has(img[src^="/prompts/arch/"])'
watches: [frontend/src/app/prompts/page.tsx, frontend/src/components/prompts/prompts-screen.tsx, frontend/src/components/prompts/prompts-chat.tsx, frontend/src/components/prompts/reader-skills.tsx, frontend/src/components/prompts/skill-library.tsx, frontend/src/components/prompts/line-diff.ts, frontend/src/components/prompts/architecture.ts, frontend/src/components/prompts/architecture-trace.ts, frontend/src/components/prompts/conversation-circuit.tsx, frontend/src/components/prompts/request-playback.tsx, frontend/src/app/prompts/circuit/page.tsx, frontend/src/lib/prompts-api.ts, app/api/prompts_screen.py, app/services/prompt_store.py, app/prompts/catalog.json]
errors: [ログインが切れています, 失敗しました]
speak: |
  - 構成図の上の「今動いている依頼」で見たいチャット・通話・並行作業を押すと、その依頼だけの作業が箱の横と「作業の様子」に出ます。「前の会話を流し直す」で部屋と依頼を選び、図の下の「流れを再生」で再生・一時停止・コマ送り・速度変更ができます。光った箱を押すと、その段階で記録された指示文・渡した本文・秒数が開きます。「依頼を試す」で渡す直前までか実際に進めるかを選べます。
  - 構成図の緑の枝には、ダンがどんな依頼で読むスキルかが出ます。「すべて」でそのダンの頼み別の枝を開けます。通話で制作を頼んだ時は並行作業につながります。
  - 画面上の「スキル」で全スキルの手順書と参考ページを検索し、編集・復元できます。
  - ダンの各係が読む指示文を、みきさんが読んで直し、前の版に戻す画面です。
  - 試す時は DAN_PROMPTS_DIR を一時の場所にして、本物の指示文を書き換えません。
shows: []
fingerprint: bce8826fedae4176
described: 2f0b80dbec82bcb6
last_review: "2026-11-22 説明は変えない: 依頼を選び、構成図で追う操作は記載どおり"
---
# ダンを動かしている指示文

上に、みきさんの頼みが流れる順の構成図（上から下：みきさん→画面のサーバー→入口→会話の本体／道具と通話のサーバー→チャットのダン・通話のダン・エディター→振り分け→調べもの係・画面係・判断役→作業の部屋）。箱には何の場所かの小さな絵、中で動くモデル、読む指示文の数。箱を押すとその箱が読む指示文の一覧、押すと全文がそのまま出て、その場で書き直して保存できる。誰が読むか・いつ効くか・なぜある文か・元の場所・履歴は全文の下にたたんである。
開発室のボード（artifact:dev-lead）の上の切り替え「部屋／指示文」の「指示文」でも同じ画面が出る（2026-11-17 本人「開発室の中に1要素として」）。

## 中にある物

- 構成図（components/prompts/architecture.ts。箱と矢印はコードで確かめた呼び出し順で、根拠のファイルは同じファイルの頭に書いてある。仕組みを変えたらここも直す）。スマホの幅では図が横に広く、押した箱の所まで横に送る。
- 場所ごとの一覧。札: 直したことのある文は「最終更新 月/日 時:分」だけ（誰が直したか・元の文のままかは出さない。11/22 本人）、灰＝プログラムの中（読むだけ）。
- 全文の欄（「この文は、ここでそのまま書き直せます」。欄は中身の高さまで伸びる）、下に貼り付いた保存の帯（書き直すと「なぜ直したか」・直す前に戻す・保存が出る）、たたんだ「この文について」と「履歴」（押すとその版、この版に戻す・プログラムの中にあった頃に直された日）。
- スマホの幅では、一覧と全文が入れ替わり（「一覧に戻る」）。PC でも 1280 より狭い時（開発室の中など）は、一覧と全文が入れ替わり、右に会話の列が出る。
- 「ダンと話して直す」の会話（2026-11-21 本人「指示文の見直しはお前と一緒にやった方が良いけど、ページにチャットが無いからやりにくい」）。PC は全文の横の列（スクロールしても見えたまま）、スマホは右下の「ダンと話す」で下から出る。部屋は1つ（「ダン開発室: 指示文の見直し」、一覧に出さない。app/api/prompts_screen.py の /prompts/chat、~/.dan/workspace/prompts/.chat/chat.json）で、/prompts と開発室の「指示文」が同じ部屋で話す。
  - 入力欄の上の札に、今開いている文と、全文の中で選んだ所（何行目・何という文）が出る。発言ごとにそれを `<dan-context>` で添える（画面には出ない。本人の吹き出しの上に「どの文の何行目」だけ小さく出る）。保存していない書きかけがあれば、その違いも添える。
  - 会話欄の「チャットのモデル」で、指示文の会話が次の返答に使うモデルを選べます。
  - ダンの返事の画像は1枚ずつ縦横比のまま出て、押すと画面いっぱいに開き、左右で会話の中のほかの画像へ送れる（チャットと同じ見る画面。11/22 本人「クリックしても大きく表示できない」）。
  - ダンが直している所は光る（2026-11-22 本人「編集してる時に編集してる場所を光らせて分かるようにして」）。ダンが scripts/prompts.py mark で直す文と行を知らせると（/prompts/working。画面は3秒ごとに聞く）、図の箱と一覧の札が紫に明滅し、その文が開いて（書きかけがある時は開かず、上に「ダンが「…」を直しています・開く」の帯）、全文のその行が紫に明滅して「ダンが◯行目を直しています」が出る。保存されると変わった行が緑に光る。直してから10分以内に開いた時も同じ。
  - ダンは scripts/prompts.py save で直す（部屋の説明に書いてある）。会話のダンが動いている間は数秒ごとに版の印（/prompts/sha）を見て、変わったら全文がその場で新しい版になり、上に「ダンが直しました：理由」・変わった所（消した行は赤い線、足した行は緑）・「元に戻す」が出る。書きかけがある時は消さずに「ダンの版を開く」を出す。
- 構成図の箱に付いた緑の枝には、頼みの例と、それに使うスキルが出ます。例を押すと全文を開き、「すべて」を押すと、そのダンが読むスキルを頼みの種類ごとにたどれます。全文の上の「手順書・参考ページ」で案件ごとの方針に切り替えられます。
- 構成図の「チャットのダン」「エディターのダンと制作」「並行作業」の緑の枝にある紫の札「動画を作る・直す時の中」（?place=video。2026-11-23 本人「動画の作成や編集がチャットのダンや並行作業に届いて、その後にどういうスキルやコンポーネントがあって、それをどう読み込んでいるからこうなっている。だからここを直せばいいんじゃないかってことが分かるページ」）を押すと、構成図のタブのまま、その中の図に降りる（上の「構成図全体」で戻る）。みきさん→頼みが届く4つ（チャットのダン・エディターのダンと制作・並行作業・「ダンに指示」の実行）→読む決まり（チャットのダンと同じ決まり／「ダンに指示」だけの制作の決まり）→手順書を選んで開く・Claude Code の本体の棚→案件の決まり→素材と部品・タイムラインの道具・コマを見る・書き出す→返事の前の関所→みきさんに見せる→指摘から手順書を育てる（案件の決まりへ戻る）。箱を押すと下に、その箱の動き方（コードで確かめた条件・無い物）・読む文（押すと全文を開いて直せる）・ここで動くプログラム（ファイルと何をするか、読むだけ）が出る。箱と矢印は architecture.ts の VIDEO_NODES・VIDEO_EDGES。
- 画面上の「スキル」を押すと全スキルの一覧が出ます。名前や参考ページの題で検索し、スキルを開いて「手順書」か参考ページを選び、全文を編集して保存できます。「履歴」で過去の版を選び「この版に戻す」で復元できます。並行作業の「作業をほかのダンに頼む時」では、チャットと音声の編集依頼に共通する文を直せます。

## 行き方（みきさんから見て）

ダンの画面の /prompts。URL の ?place=<場所>&id=<文> で、その場所・その文を開いたまま共有できます。

## 道具で動かす

`place_shot.py prompts --base http://localhost:3002 --path '/prompts?place=router&id=call/router-routes' --tag now`。
直す試験は、試しのサーバーを `DAN_PROMPTS_DIR=<一時の場所> work.py try` で立てて行います。

## 落とし穴

- ダンの画面は html と body のスクロールを止めている。この画面は自分の枠（h-dvh・overflow-y-auto）でスクロールする。外すと全文の欄まで下りられなくなる（11/17 の「見るだけで編集できない」の原因）。
- 開発室の中では、開発室の初期化（余白を0にする等）を .promptsPane で外している。
- 会話の列の高さは、この画面をスクロールさせている枠の高さに合わせる（開発室の中は上に切り替えの帯があり、画面の高さで作ると入力欄が下に隠れる）。
- 会話で試すと本物のダンが答え、本物の指示文を直す。直す試験は影響の小さい文（work/relay-header など）で行い、すぐ「元に戻す」で戻す。試した部屋は chat.json から外して、みきさんには新しい部屋で始まるようにする。

- 文の置き場所は ~/.dan/workspace/prompts。本番で保存すると、次の通話・次の作業から本当に効きます。

<!-- place_map:auto:start -->
## コードから（自動）

`python scripts/place_map.py stamp prompts` が書き直す。手で直さない。

- 見張るファイル: `app/api/prompts_screen.py`, `app/prompts/catalog.json`, `app/services/prompt_store.py`, `frontend/src/app/prompts/circuit/page.tsx`, `frontend/src/app/prompts/page.tsx`, `frontend/src/components/prompts/architecture-trace.ts`, `frontend/src/components/prompts/architecture.ts`, `frontend/src/components/prompts/conversation-circuit.tsx`, `frontend/src/components/prompts/line-diff.ts`, `frontend/src/components/prompts/prompts-chat.tsx`, `frontend/src/components/prompts/prompts-screen.tsx`, `frontend/src/components/prompts/reader-skills.tsx`, `frontend/src/components/prompts/request-playback.tsx`, `frontend/src/components/prompts/skill-library.tsx`, `frontend/src/lib/prompts-api.ts`
- ラベル: 「ダンに書く」、「止める」、「送る」、「作業中」、「閉じる」、「指示文の表示」、「動画を作る・直す時の構成図」、「ダンと話す」、「会話を閉じる」、「依頼の流れ」、「時間順の作業」、「再生の操作」、「1段戻る」、「1段進む」、「再生位置」、「再生速度」、「スキル一覧」、「スキル・参考ページを検索」
- 試験の印: 「dan-change」、「dan-working」、「dan-working-elsewhere」、「video-branch」、「node-facts」、「node-programs」
- 見出し: 「プログラムの中にあった頃に直された日」、「ダンを動かしている指示文」、「作業の様子」

<!-- place_map:files {"app/api/prompts_screen.py": "6047951223", "app/prompts/catalog.json": "1bbb2e6ebb", "app/services/prompt_store.py": "750e86435b", "frontend/src/app/prompts/circuit/page.tsx": "f366dafdc9", "frontend/src/app/prompts/page.tsx": "0fb7f5fefc", "frontend/src/components/prompts/architecture-trace.ts": "adb59d4b2e", "frontend/src/components/prompts/architecture.ts": "86441bd3fb", "frontend/src/components/prompts/conversation-circuit.tsx": "9ee082d8b9", "frontend/src/components/prompts/line-diff.ts": "dd4af75399", "frontend/src/components/prompts/prompts-chat.tsx": "ceb98a46cb", "frontend/src/components/prompts/prompts-screen.tsx": "b94472f622", "frontend/src/components/prompts/reader-skills.tsx": "0619791b29", "frontend/src/components/prompts/request-playback.tsx": "2af02d9613", "frontend/src/components/prompts/skill-library.tsx": "d4ed9b43e6", "frontend/src/lib/prompts-api.ts": "93f3485b6b"} -->
<!-- place_map:auto:end -->
