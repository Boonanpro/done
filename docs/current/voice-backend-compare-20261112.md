# 通話の裏のモデルの比べ（2026-11-12 夜）

本人「早くて正確な方を採用して」。通話の頼みのうち、決まった行き先の無いもの（voice_router.Router.luna: メッセージ・文書・ほかの部屋・相談・Jev が迷ったもの）と、調べもの（voice_lookup）を、同じ頼みで比べた。

## 決まった行き先の無い頼み（scripts/voice_backend_compare.py、tests/voice_backends/ の8件）

本人の 11/11・11/12 の通話の頼み。読む道具は本物、送る・作業を始める・画面に出す・通話を切る道具は実行せず記録だけ。

| モデル | 合格 | 秒（真ん中） | 秒（9割） |
|---|---|---|---|
| gpt-6-luna low（今） | 43/44 | 6.4 | 11.2 |
| deepseek-flash low | 38/40 | 4.4 | 9.2 |
| deepseek-flash high | 35/36 | 6.3 | 13.3 |
| deepseek-v4-pro low | 16/16 | 8.2 | 21.1 |
| deepseek-v4-pro high | 16/16 | 11.3 | 26.2 |

（luna と flash high には、下書きの決まりを試した追加の回を含む。その決まりは入れていない。）
flash は短い答えが1〜2秒速いが、返信の下書きは10〜15秒かかり、知り合いに「はじめまして」と書いた（7回中3回）。決まりを足しても4回中1回残った。luna は0回。
結論: luna のまま。モデルは DAN_VOICE_ROUTER_BACKEND_MODEL / _REASONING で替えられる（DeepSeek は全履歴を毎回送る）。

## 調べもの（scripts/voice_lookup_compare.py、tests/voice_lookups/ の4件）

| モデル | 合格 | 秒（真ん中） | 秒（9割） |
|---|---|---|---|
| gpt-6-luna low | 17/24 | 30.4 | 57.1 |
| gpt-6-luna medium | 14/16 | 82.8 | 135.5 |
| deepseek-v4-pro high（朝から夜まで） | 11/16 | 107.7 | 150.0 |
| deepseek-v4-pro low | 14/16 | 84.8 | 150.0 |
| deepseek-flash low | 7/8 | 73.2 | 96.5 |
| deepseek-flash high（採用） | 16/16 | 81.7 | 111.2 |

V4 Pro high は16回中4回が150秒の時間切れで何も言わなかった。luna low は速いが、仲江先生の最初の頼みは6回中1回。
結論: deepseek-flash high。1回 約0.013ドル（V4 Pro は約0.045ドル）。

## 本人の通話での実測（voice-sideband.jsonl）

調べものの1回の考える時間: 11/11 まで（luna）真ん中 2.6 秒、11/12（V4 Pro high）6.2 秒。11/12 22:44 の通話では「中村さんから連絡ありましたか」の答えまで約70秒。
