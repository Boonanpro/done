# Visual refinement acceptance

Goal: verify actual voice conversation and visible proposals across captions, character/environment and motion. Evaluator knows the visual target; Dan receives only ordinary spoken user requests and feedback. No target spec, code, tool names or correct tool sequence is injected into Dan.

Timing goals from end of user speech: relevant voice response <=10s; first usable visual comparison <=90s; focused revision <=30s. Reach target after at most three comparison/feedback cycles. Preserve unrequested content, disclose actual visual limitations, retain previous candidates, no unexpected timeline edits. Distinguish acknowledgements from answers, initial drafts from finished production quality, tool execution from visible readiness.

Private evaluator targets fixed before testing (this file is not supplied to the tested conversation):

1. Caption: calm editorial Japanese subtitle, warm off-white on dark background, readable weight and spacing, restrained single soft entrance, no bouncing or word-by-word popping. Secondary emphasis on one short phrase; cannot lose readability. User initially knows personal-story purpose and credible-but-not-stiff feeling, cannot name fonts or easing. A later targeted color/placement correction must preserve wording and timing.
2. Person/environment: anonymous adult in a quiet lived-in evening room, warm lamp against cool window, believable perspective, seated posture and subtle movement rather than a mannequin floating in empty space. User knows they want an empathetic recollection, cannot name 3D/documentary styles. Initial candidates must expose a meaningful stylistic difference. Selected direction then changes lighting or camera distance without changing identity/setting.
3. Motion/data: an understandable before/after of repeated back-and-forth versus one clear handoff, coherent visual grouping and hierarchy, restrained movement that explains the difference rather than decorative bouncing. User knows the communication purpose but cannot prescribe the visualization. Later correction changes only the selected motion speed or emphasis, preserving the rest.

These are diverse production samples, not proof of every possible video genre. New scenarios and repeated corrections are needed if a failure reveals a shared mechanism problem. No UI design skill or fixed questionnaire is prescribed.

## 2026-09-16 実施結果

通常環境（8000）で、自然音声のユーザー役 → LIVE 1 → GPT-6 Astra CLI → 実際の提示画面、という経路で3題材を検証した。答えやコードは制作側に渡していない。ユーザー役は実物を見てから次の発言を決めた。録画は画面と双方の音声を含む、無編集の会話記録。発言を考えるオペレーターの待ち時間も含むため、録画の長さと処理時間は区別する。

| 題材 | 最初の実物 | 次の依頼 | その次の依頼 |
|---|---:|---:|---:|
| カフェの落ち着いた文字 | 3案 20.362秒 | 出現を柔らかく 4.872秒 | 「ひと息」だけ着色 26.507秒 |
| 問い合わせの往復と一括伝達 | 2案 50.895秒 | 5つを集めてから届ける 30.012秒 | 届く速さだけ変更 4.671秒 |
| 疲れて帰った人物・部屋 | 写真2案 87.247秒 | 選んだ方向で新しい3D見本 65.280秒 | 寄りの固定構図に変更 17.836秒 |

計測はユーザー音声の終了からブラウザーの表示確認まで。最初の応答は0.04〜8.913秒。ただし相槌・受け答えを含み、完成報告までの時間ではない。初回表示90秒の目標は3題材で達成。局所修正は約5〜30秒で、30.012秒の1回は30秒目標の境界値。3D見本の新規作成65秒は局所修正ではない。一般的な上限時間を保証する結果ではない。

各題材で実物の比較→選択→2回までのフィードバックで、事前に定めた見た目・動きの条件に到達した。字幕だけのテストではない。図解の最後の修正はプログラム本体が完全に同じで、到着時間のパラメーターだけが1秒から1.6秒へ変化。人物の最後の修正はカメラ位置・注視点・固定化だけで、部屋の形、色、小物、呼吸、カーテンの動きのコードは保持。実画面を複数時刻で描画して確認した。字幕のフォント・サイズ・背景・動きも差分と実画面で確認。元の案は履歴に残り、タイムラインへの意図しない変更はない。

### 直した共通原因

- sceneの任意パラメーターとプログラム再利用を追加。作品固有の色・構図・速度を小さな変更値で更新できる。決め打ちのジャンル別テンプレートではない。
- 提示の同一ターン内の改訂を音声で何度も完成報告しない。表示自体は即時、音声報告は最終状態を一度伝える。
- エディター内の見本制作に、別環境のHyperFrames制作手順が暗黙に割り込む設定を対話担当だけで無効化。明示的な資料読み込みと制作担当側の機能は維持。
- 読み込んだスキルが参照するMarkdown資料を安全な範囲で読めるようにした。以前は存在する資料にも「ありません」と返していた。
- 好みの相談でも、実物を見たいという希望を提示依頼として扱うようLIVEの委譲条件の重複を解消。提示後の説明も短くする方針へ変更。
- 参考検索は候補発見に絞り、頼まれていない制作手順の長文レポートを同時に作らせない。同じ検索語の単発計測は49.7秒から37.5秒になったが、検索先・負荷による変動はある。
- 最新の比較を見ている時は次の案を画面内へ表示。大きな比較は先頭を見せ、過去を振り返っている時のスクロール位置は保持。
- 引数の誤りは修正可能な結果として返し、HTMLの500エラーから「接続し直す」方向へ誤誘導しない。新しいsceneパラメーターと配列末尾への追加も対応。

### 失敗と再確認

初期人物テストは113秒、別の試行では検索と不適切な資料読み込みで160秒を超えた。これらを成功扱いせず原因を修正した。画像検索の速度は今も最も余裕が小さい。

通常環境の字幕着色テストでは、配列末尾への1レイヤー追加が未対応で一度失敗し、全レイヤーを書き直して26.5秒で回復した。この失敗も直した。最後に通常環境を更新し、**失敗したものと同じ引数を実HTTPで再実行**。12ミリ秒で成功し、回復後の完成形と同じ内容になった。元の案・タイムラインの不変と実表示も確認した。この12ミリ秒は道具だけの時間で、音声からの修正時間ではない。最終追加修正後に同じ音声会話を丸ごと再実行したわけではない。

途中のテストでは、テスト側のTTSが文末を省く問題、PowerShell経由の日本語が「?」になる問題があった。これらはダンの失敗として数えていない。発話を文ごとに生成する方式と日本語入力の検査に改めた。上表の通常環境3本は文字化けした発話を含まない。途中の失敗録画は保持し、納品用の3本と分けた。

### 品質と検証範囲

生成した見本は、文字の雰囲気・図解の伝え方・3Dの構図と照明を比較して詰めるためのもの。3D人物は簡素なモデルで、実写や本番品質の人物映像ではない。字幕も実際のカフェ映像に重ねた最終検品はしていない。有料動画生成・長編の仕上げ・あらゆるスタイルの品質を今回の結果で合格としない。

録画はGeminiによる映像・音声レビューも実施。ただしレビューは観測補助であり、誤読もある。例えば写真の検索を「画像生成」、画面の「一度」を「一言」と扱った箇所はログ・実画面で訂正して判断した。指摘された低ポリゴン感、単純な動き、最初の参考表示の長さは残る課題。相槌が発言に重なる場面もあるが、通常環境3本で依頼が消えたり音声が途中終了する事象はなかった。

### 反映・記録

- Python関連48テスト、音声クライアント19テストが成功。実ブラウザーでパラメーター描画、比較の追従と履歴閲覧、文字列の安全な表示も確認。
- 通常サンドボックス8000へ反映。通話終了と制作ジョブなしを確認して再起動。Core9000とfrontend3000は再起動していない。JSは配信元とローカルの一致、LIVEのinstructions_hashとclient_buildの一致を確認。
- AstraはChatGPT契約のCLI、対話処理は設定済みFast（priority）。APIのAstraへ切り替えていない。テストの音声・動画レビューにはAPIを使用。
- 通常環境のテスト部屋だけを使用。ユーザーの制作物は変更していない。コミット・プッシュはしていない。

エクスプローラーで開くフォルダー：`D:\done\scratch\visual-refinement-20260916`

- `1-captions.mp4`：文字の比較、出現の変更、一部分の着色。
- `2-motion.mp4`：2種類の図解、集めて届ける変更、到着速度のみ変更。
- `3-person.mp4`：参考写真の比較、その方向の3D見本、構図のみ変更。
- 同名の`.timings.json`、`.review.txt`：実測と独立レビュー。
- `replayed-append.json`、`replayed-append.png`：最後に直したレイヤー追加の通常環境での確認。
