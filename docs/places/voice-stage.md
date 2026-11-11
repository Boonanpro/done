---
place: voice-stage
name: 通話中の画面
open: /voice-stage
ready: '[data-stage-card]'
watches:
  - frontend/src/components/voice/voice-stage.tsx
  - frontend/src/components/voice/stage-message-editor.tsx
  - frontend/src/app/voice-stage/page.tsx
fingerprint: fa7152e6f02e24f4
described: ff4c37fcaed9a52e
---
# 通話中の画面

スマホの通話画面とPCの通話パネルに、同じ送信案を表示する。

## 中にある物

- 送信案の宛先、本文、下書きの状態。
- 未送信の本文を通話画面で直接編集し、「保存」で同じ送信案に反映する。保存に失敗しても入力した文章は残る。保存済みの本文は画面を開き直しても表示される。

## 行き方

通話で送信案を作ると通話画面に表示される。

## 道具で動かす

確認用アカウントの部屋と未送信の送信案を用意し、`/voice-stage?room=<部屋ID>` を開く。電話は発信しない。

## 落とし穴

本人の送信案を試験で書き換えない。確認用の写しで編集・保存・再読み込みを確認し、送信経路は呼ばない。

<!-- place_map:auto:start -->
## コードから（自動）

`python scripts/place_map.py stamp voice-stage` が書き直す。手で直さない。

- 見張るファイル: `frontend/src/app/voice-stage/page.tsx`, `frontend/src/components/voice/stage-message-editor.tsx`, `frontend/src/components/voice/voice-stage.tsx`
- ラベル: 「送信案の本文」

<!-- place_map:files {"frontend/src/app/voice-stage/page.tsx": "79db203460", "frontend/src/components/voice/stage-message-editor.tsx": "fc6b037dcc", "frontend/src/components/voice/voice-stage.tsx": "4d2378c2cd"} -->
<!-- place_map:auto:end -->
