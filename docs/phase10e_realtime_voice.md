# Phase 10E: 双方向AI音声会話（リアルタイム音声会話）

## 概要

Twilio Media StreamsとElevenLabs Conversational AIを連携し、電話でのリアルタイム双方向音声会話を実現する。
現在の「固定メッセージ再生」から「AIとの自然な会話」へアップグレードする。

## 現状と目標

### 現状（課題）
- 架電すると固定TwiMLメッセージ「音声会話機能は準備中です」を再生するだけ
- 双方向会話ができない
- STT/TTS処理が実装されていない

### 目標
- 電話相手と日本語でリアルタイム会話
- AIエージェント「ダン」が応答
- 会話内容を文字起こし・要約してDBに保存
- 通話終了後にチャットへ通知

---

## アーキテクチャ

```
┌─────────────────────────────────────────────────────────────────────┐
│                        リアルタイム音声会話                           │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│   電話網 (PSTN)                                                      │
│       ↕                                                             │
│   Twilio Voice                                                      │
│       ↕ (Media Streams WebSocket)                                   │
│   FastAPI WebSocket Endpoint (/api/v1/voice/stream/{call_sid})      │
│       ↕                                                             │
│   ┌─────────────────────────────────────────────────────────────┐   │
│   │              音声処理パイプライン                              │   │
│   │                                                             │   │
│   │   音声入力 (μ-law 8kHz)                                      │   │
│   │       ↓                                                     │   │
│   │   ElevenLabs STT (Speech-to-Text)                           │   │
│   │       ↓                                                     │   │
│   │   Claude API (応答生成)                                      │   │
│   │       ↓                                                     │   │
│   │   ElevenLabs TTS (Text-to-Speech)                           │   │
│   │       ↓                                                     │   │
│   │   音声出力 (μ-law 8kHz)                                      │   │
│   │                                                             │   │
│   └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 技術仕様

### 1. Twilio Media Streams

**TwiML設定:**
```xml
<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Connect>
        <Stream url="wss://your-domain.com/api/v1/voice/stream/{call_sid}">
            <Parameter name="call_sid" value="{call_sid}" />
            <Parameter name="direction" value="outbound" />
        </Stream>
    </Connect>
</Response>
```

**Media Streamsプロトコル:**
- WebSocket接続
- 音声フォーマット: μ-law 8kHz（base64エンコード）
- メッセージタイプ:
  - `connected`: 接続確立
  - `start`: ストリーム開始
  - `media`: 音声データ
  - `stop`: ストリーム終了

### 2. 音声フォーマット変換

| 方向 | Twilio | 変換 | ElevenLabs |
|------|--------|------|------------|
| 入力 | μ-law 8kHz | audioop.ulaw2lin → resample | PCM 16kHz |
| 出力 | μ-law 8kHz | resample → audioop.lin2ulaw | PCM 16kHz |

### 3. ElevenLabs Conversational AI

**使用API:**
- Speech-to-Text: `POST https://api.elevenlabs.io/v1/speech-to-text`
- Text-to-Speech: `POST https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream`

**推奨設定:**
```python
ELEVENLABS_MODEL_ID = "eleven_turbo_v2_5"  # 低遅延モデル
ELEVENLABS_VOICE_ID = "pNInz6obpgDQGcFmaJgB"  # 日本語対応音声（Adam）
```

### 4. Claude応答生成

```python
VOICE_SYSTEM_PROMPT = """
あなたはAI秘書「ダン」です。電話で相手と会話しています。

ルール:
- 簡潔に応答する（1〜2文程度）
- 質問には直接答える
- 予約や問い合わせの要件を聞き取る
- 必要な情報を確認する
"""
```

---

## APIエンドポイント

### WS /api/v1/voice/stream/{call_sid}

Twilio Media Streamsからの接続を受け付け、リアルタイム音声会話を処理する。

**WebSocket接続フロー:**
```
1. Twilio → FastAPI: WebSocket接続
2. Twilio → FastAPI: {"event": "connected", "protocol": "Call", ...}
3. Twilio → FastAPI: {"event": "start", "streamSid": "...", ...}
4. 会話ループ:
   4a. Twilio → FastAPI: {"event": "media", "media": {"payload": "<base64>"}}
   4b. FastAPI: 音声をバッファリング
   4c. FastAPI: 無音検知で発話終了を判定
   4d. FastAPI → ElevenLabs: STT処理
   4e. FastAPI → Claude: 応答生成
   4f. FastAPI → ElevenLabs: TTS処理
   4g. FastAPI → Twilio: {"event": "media", "media": {"payload": "<base64>"}}
5. Twilio → FastAPI: {"event": "stop", ...}
6. FastAPI: 通話記録を保存
```

**Twilioへの音声送信フォーマット:**
```json
{
    "event": "media",
    "streamSid": "MZxxxxxx",
    "media": {
        "payload": "<base64 encoded μ-law audio>"
    }
}
```

---

## データモデル

### voice_calls テーブル（既存、更新）

```sql
-- 以下のカラムを活用
transcription TEXT,  -- 通話内容の文字起こし（全会話）
summary TEXT,        -- AI要約
```

### voice_call_messages テーブル（既存）

```sql
-- リアルタイムで各発話を記録
CREATE TABLE voice_call_messages (
    id UUID PRIMARY KEY,
    call_id UUID REFERENCES voice_calls(id),
    role VARCHAR(20),  -- 'user' or 'assistant'
    content TEXT,
    timestamp TIMESTAMP
);
```

---

## 実装順序

### Step 1: Media Streams WebSocket基盤
1. `app/api/voice_routes.py`にWebSocketエンドポイント追加
2. Twilio Media Streamsプロトコル処理
3. 動作確認（接続確立、音声受信ログ）
4. 自動テスト追加
5. README更新
6. コミット

### Step 2: 音声フォーマット変換
1. μ-law ↔ PCM変換ユーティリティ
2. サンプルレート変換（8kHz ↔ 16kHz）
3. 動作確認（変換したデータの検証）
4. 自動テスト追加
5. コミット

### Step 3: ElevenLabs STT連携
1. `VoiceService.speech_to_text()`実装
2. 音声バッファリングと無音検知
3. 動作確認（電話で話した内容がテキストになるか）
4. 自動テスト追加
5. コミット

### Step 4: Claude応答生成
1. `VoiceService.generate_response()`実装
2. 会話コンテキスト管理
3. 動作確認（適切な応答が生成されるか）
4. 自動テスト追加
5. コミット

### Step 5: ElevenLabs TTS連携
1. `VoiceService.text_to_speech()`実装
2. ストリーミングTTS対応
3. 動作確認（AIの応答が音声で再生されるか）
4. 自動テスト追加
5. コミット

### Step 6: 統合テスト・通話記録保存
1. 全パイプラインの統合
2. 文字起こし・要約のDB保存
3. E2Eテスト（実際に電話して会話）
4. README更新
5. コミット

---

## テストケース

| # | テスト内容 | 期待結果 |
|---|----------|---------|
| 1 | WebSocket接続確立 | connectedイベントを正しく処理 |
| 2 | 音声データ受信 | mediaイベントからbase64デコード成功 |
| 3 | μ-law→PCM変換 | 正しいPCMデータに変換 |
| 4 | PCM→μ-law変換 | 正しいμ-lawデータに変換 |
| 5 | STT変換 | 日本語音声をテキストに正しく変換 |
| 6 | 応答生成 | 会話コンテキストに基づいた応答 |
| 7 | TTS変換 | テキストを自然な日本語音声に変換 |
| 8 | 通話記録保存 | 文字起こし・要約がDBに保存 |
| 9 | 通話メッセージ記録 | 各発話がvoice_call_messagesに保存 |

---

## 必要なパッケージ

```txt
# requirements.txt に追加
audioop-lts>=0.2.0  # Python 3.13+対応のaudioop
websockets>=12.0
aiohttp>=3.9.0  # ElevenLabs API呼び出し用
```

---

## 環境変数

```env
# ElevenLabs (既存)
ELEVENLABS_API_KEY=xxx
ELEVENLABS_VOICE_ID=xxx
ELEVENLABS_MODEL_ID=eleven_turbo_v2_5

# Voice設定
VOICE_WEBHOOK_BASE_URL=https://your-domain.com  # ngrok等
VOICE_SILENCE_THRESHOLD_MS=1000  # 無音検知の閾値（ミリ秒）
VOICE_MAX_BUFFER_SIZE=32000  # 音声バッファの最大サイズ
```

---

## セキュリティ考慮事項

1. **WebSocket認証**: call_sidの検証
2. **音声データの保護**: 通話中のデータは暗号化
3. **録音の同意**: 録音時は相手に通知（設定で制御）
4. **レート制限**: 1通話あたりのAPI呼び出し制限

---

## 既知の制限・今後の改善

1. **遅延**: STT+LLM+TTSの合計遅延は700-1500ms程度
2. **ターンテイキング**: 無音検知ベースのため、割り込みは難しい
3. **音声品質**: Twilioの8kHz制限により、音声品質には限界がある
4. **コスト**: ElevenLabsのAPI使用量に応じた課金

---

## 関連ファイル

- `app/api/voice_routes.py` - APIエンドポイント
- `app/services/voice_service.py` - VoiceService
- `app/models/voice_schemas.py` - スキーマ
- `tests/test_voice_api.py` - テスト


