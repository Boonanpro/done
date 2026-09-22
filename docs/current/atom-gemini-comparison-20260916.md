# Atom音声：Live 1とGemini Extended Thinkingの比較

2026-09-16。Gemini音声の切り替えを本番へ反映済み。
本番frontend: `.next-prod-1789519309`。音声APIを持つSandboxとheadless controllerを更新。
通話・Coreの会話セッション・実行中runがないこととプロセス所有者を確認して反映した。
Core・ファームウェアは変更していない。

## 構成

- 現行 `gpt-live-1` と候補 `gemini-3.8-live-extended-thinking` を選択できる。
- Geminiはthinking=`high`、voice=`Puck`。通常版Geminiへのフォールバックはない。
  比較試験時は`low`。ユーザー指示で`medium`へ変更し、frontend `.next-prod-1789520290`に反映。
  変更時の通話は切断せず、次の接続から適用する。
  その後、ユーザーからmediumで会話改善の報告があり、highへの変更を依頼された。
  highのソース変更と本番用ビルド `.next-prod-1789520759` は完了。
  別ポートの同ビルドでsession要求がprovider=gemini、thinking=high、device=trueとなることを検証した。
  当初の本番反映操作は自動承認レビューで拒否された（詳細理由は返されず）。
  再依頼後、本番が同highビルドで稼働していることとヘルス正常を確認。
  本番URLのブラウザから実際に送るsession要求もthinking=highとなることを確認した。
  確認時点で実機はオフライン。次の実機接続からhighを使用する。
  初回low通話の評価は [初回利用レビュー](atom-gemini-first-use-review-20260916.md) を参照。
- 両方で同じ部屋権限、履歴取得、Astra CLI、既存ツール、作業ジョブを使用する。
- 通話終了も比較条件を合わせてAstraを経由する。Jevや終了専用の分類器は追加していない。
- Gemini接続は制約付き短期トークンを発行し、ブラウザからWebSocketで直接接続。
  通常のAPIキーをブラウザに渡さない。
- Atomの48kHz PCMを入力16kHzへ変換し、Gemini出力24kHzを48kHzで再生する。
  割り込み時は予約済み音声とAtom出力キューを破棄する。
- `turnComplete`を処理完了と見なさず、`interactionStatus`を別に保持。
  非同期ツールID、取り消し、重複、追加指示を扱う。
- 接続復旧用のhandleと送信待ちの結果を保持する。長時間の接続更新は未実測。

## 検証

Python 11件、JS 17件が成功。権限拒否、発行失敗時の後始末、履歴、Astraの継続、
非同期状態、古い呼び出し、割り込み音声破棄、20ms PCMを確認した。
本番用ビルドが成功し、実画面も確認した。

実Gemini＋実Astraの独立試験では、状態確認ツール→結果の音声出力と、
録音「この電話を切ってください」→待機ツールを確認。
証跡: `.tmp/gemini-voice-transport-proof.json`。

通常のVoiceSessionとAtom用PCMワークレットで同じ録音を使用した比較:

| 試験 | Live 1 | Extended Thinking |
| --- | --- | --- |
| 挨拶のスピーカーPCM | 成功 | 成功 |
| 説明中の録音割り込みへの「聞こえた」の返答 | 成功 | 成功 |
| 通話終了 | 停止1回 | 停止1回 |
| 入力終了→停止（隔離frontend、各1回） | 6.265秒 | 6.859秒 |

本番frontend/API経路でもGeminiを再試験。挨拶、割り込み応答、停止1回が成功し、
入力終了→停止は7.063秒。HTTPエラー・ページエラーはゼロ。
証跡: `.tmp/voice-compare-openai.json`、`.tmp/voice-compare-gemini.json`。

最初の試験はPython側で音声を刻んで送ったことで欠落があり、比較として不採用。
最終試験はブラウザ内で10ms PCMを通常のAtom入力ワークレットへ送り、
その後のマイクトラック・モデル接続・出力経路は実装どおりに動かした。
実機の制御とスピーカー出力先は模擬であり、物理マイク・スピーカー・AECの合格ではない。
少数回の結果なのでモデル性能の順位付けはしない。終了の高速化は確認できていない。

## 試用と戻し方

次の呼びかけはGeminiを使用する設定にした。実機は作業終了時点でオフライン。
Atomを給電して設定済みWi-Fiへ接続すればよく、PCへの有線接続は不要。
実機での日本語の聞こえ方、割り込み、距離・環境音、長時間利用は未確認。

通話終了後に選択する。進行中の通話を強制切り替えしない。

```powershell
python scripts/set_atom_voice_model.py gemini
python scripts/set_atom_voice_model.py openai
```

設定は`.tmp/atom-voice-provider.json`に保持する。キーは既存の認証経路だけで使用する。
再現試験は`python -m scripts.compare_atom_voice_models --base http://localhost:3000 --provider gemini --deployed`。
既存`test_audio`のWebRTCトラック差し替え診断はGeminiでは明示的に拒否する。
Geminiの録音比較は上記PCMワークレット経路を使用する。

公式仕様:
- https://ai.google.dev/gemini-api/docs/models/gemini-3.8-live-extended-thinking
- https://ai.google.dev/gemini-api/docs/live-api/thinking
- https://ai.google.dev/gemini-api/docs/live-api/ephemeral-tokens
