# 通話の画面（voice stage）— 2026-10-25

声のダンと話している間、本人の画面に「今の話」の札と、話の中身に合った図（矢印の図・大きな数字・表・グラフ）を出す。

## 作り

- **話を聞く係** `app/services/voice_stage.py`。通話の裏側（`voice_sideband`）に届く文字起こしを読み、ダンの話の区切り（0.9秒の間、または文末で28文字以上）と本人の言葉の後（1秒）に、速いモデルへ「そのまま / 札だけ替える / 新しい図に替える」を聞く。答えの図は OpenUI Lang（チャットの「答えの形」と同じ部品）。新しい判断が先に着いたら古い答えは捨てる。
- **モデル** `DAN_VOICE_STAGE_MODEL`（既定 gpt-5.4-mini、`DAN_VOICE_STAGE_REASONING=none`）。`scripts/check_voice_stage_latency.py` で測った: gpt-5.4-mini 1.2秒中央値・最長1.5秒・7枚とも描ける、gpt-5.4-nano 1.6/2.5秒、deepseek-flash 4.6/6.1秒、gpt-5-nano は描かない。`DAN_VOICE_STAGE=0` で止まる。
- **画面が読む所** `GET /api/v1/voicelog/stage/{room_id}?after=<version>`（long poll、最長25秒）。中身は `~/.dan/voice-calls/<room>.stage.json`（sideband が書く。どのプロセスからも読める）。
- **画面** `frontend/src/components/voice/voice-stage.tsx`（PC の通話の枠が直接描く）と `frontend/src/app/voice-stage/page.tsx`（`/voice-stage?room=…`。スマホのアプリが WebView で埋め込む。`mobile/voice.tsx` が done-token を localStorage に入れてから開き、図が出ている時だけ場所を空ける）。
- **部品 Flow** `frontend/src/lib/chat-shapes/schema.ts`（箱・矢印・アイコン・tone now=今ここ）。PC は `chat-shapes.tsx`、スマホは `mobile/chat-shapes.tsx`。指示文は `npm run generate:shapes`、スマホへの写しは `npm run sync:mobile-shapes`。チャットのダンも Flow を使える。
- **「図にして」** 声の裏側の道具 `show_on_stage`（`voice_responses.py`）→ 同じ係が今すぐ描く。
- **通話の後** 出した図を1通のメッセージ（🖼 通話中に出した画面）にして、通話の行の直後に残す。

## あわせて変えた物

- 声のモデル名は `DAN_VOICE_LIVE_MODEL`（`voice_live.MODEL`）の1か所。動画エディタ・3Dコンテ・撮影所もここから読む。Live 1.1 が API に来たら設定を変えて通話を1回確かめる。
- Atom（声で話す小さな機器）を削除: `devices/atom-echo-s3r`、`app/api/atom_relay_routes.py`、PC の `atom-wifi-transport`、スマホの中継（`DanAtomRelay`・`DanAtomSocket`・設定画面の欄）。ピン（`DanPinBle`）はそのまま。

## 確かめ方

- 裏側: `pytest tests/test_voice_stage.py`。本物のモデル: `python scripts/check_voice_stage_latency.py [--model …]`。
- 画面: `work.py try` で 8001/3002 を立て、試験用アカウントの部屋に `voice_stage.Stage(...)._apply(札, program)` で図を置き、`http://localhost:3002/voice-stage?room=<room>` を開く（done-token を localStorage に）。
