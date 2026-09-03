"""Realtime 音声レイヤー API（gpt-realtime-2）。

  POST /api/v1/realtime/session  — ブラウザ用 ephemeral トークン発行
  WS   /ws/realtime-delegate     — delegate_to_dan ブリッジ
                                   （process_message_cli を起動し進捗を stream）

音声そのものはブラウザ ↔ OpenAI の WebRTC 直結。このサーバーは
「トークン発行」と「実作業の委譲（実行エンジンへの橋渡し）」だけを担当する。
"""
import logging
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect

from app.services.auth_service import decode_access_token
from app.services.realtime_service import RealtimeConfigError, mint_client_secret

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/realtime", tags=["realtime"])
ws_router = APIRouter()

DEFAULT_USER_ID = "00000000-0000-0000-0000-000000000001"


@router.post("/session")
async def create_realtime_session(request: Request):
    """gpt-realtime-2 用の ephemeral クライアントシークレットを発行する。

    Body (optional JSON):
        {"chat_title": "...", ...}
            起動元チャットのタイトル。指定があれば session instructions に注入し、
            音声 AI が「今いる会話の文脈」を持って返答できるようにする。

    ブラウザはこの ek_ トークンで OpenAI に WebRTC 直結する。
    OpenAI API キーはサーバーから外に出さない。
    """
    chat_title: Optional[str] = None
    try:
        body = await request.json()
        if isinstance(body, dict):
            raw = body.get("chat_title")
            if isinstance(raw, str) and raw.strip():
                # ノイズ・誤注入対策で 120 文字に切る
                chat_title = raw.strip()[:120]
    except Exception:
        # 旧クライアント（body 無し）でも動くように静かに無視
        pass

    try:
        return await mint_client_secret(chat_title=chat_title)
    except RealtimeConfigError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:  # noqa: BLE001
        logger.exception("realtime session mint failed: %s", e)
        raise HTTPException(status_code=502, detail="Realtime セッションの発行に失敗しました")


@ws_router.websocket("/ws/realtime-delegate")
async def realtime_delegate_websocket(websocket: WebSocket):
    """delegate_to_dan ブリッジ WebSocket。

    gpt-realtime-2 が delegate_to_dan を呼ぶと、ブラウザがこの WS 経由で
    実作業を依頼する。サーバーは process_message_cli（Claude Code CLI、
    既存の実行エンジン）を起動し、進捗イベントを逐次 stream で返す。

    Client -> Server:
      {"type": "auth", "token": "JWT"}
      {"type": "delegate", "task": "...", "room_id": "..."}
      {"type": "ping"}

    Server -> Client:
      {"type": "auth_success", "user_id": "..."}
      {"type": "delegate_started", "room_id": "..."}
      {"type": "reasoning", "text": "..."}   ← 内部思考/独り言（UI 表示用）
      {"type": "tool_use", "name": "..."}    ← ツール実行（UI 表示用）
      {"type": "text", "text": "..."}        ← 途中テキスト
      {"type": "result", "text": "..."}      ← 委譲タスク完了（音声で報告される）
      {"type": "error", "message": "..."}
      {"type": "busy"} / {"type": "pong"}
    """
    await websocket.accept()

    user_id: Optional[str] = None
    is_running = False

    try:
        auth = await websocket.receive_json()
        if auth.get("type") != "auth":
            await websocket.send_json({"type": "error", "message": "Authentication required"})
            await websocket.close()
            return

        token = auth.get("token")
        user_id = DEFAULT_USER_ID
        if token:
            token_data = decode_access_token(token)
            if token_data:
                user_id = token_data.user_id
        await websocket.send_json({"type": "auth_success", "user_id": user_id})

        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")

            if msg_type == "ping":
                await websocket.send_json({"type": "pong"})
                continue

            if msg_type != "delegate":
                await websocket.send_json(
                    {"type": "error", "message": f"Unknown message type: {msg_type}"}
                )
                continue

            task = (data.get("task") or "").strip()
            if not task:
                await websocket.send_json({"type": "error", "message": "Empty task"})
                continue

            if is_running:
                # 1 接続で 1 委譲ずつ。先行タスク完了まで新規は受け付けない。
                await websocket.send_json({"type": "busy"})
                continue

            # room_id は CLI セッションのキー。同じ値なら会話が継続（--resume）する。
            room_id = (data.get("room_id") or "").strip() or f"voice-{uuid.uuid4()}"
            is_running = True
            await websocket.send_json({"type": "delegate_started", "room_id": room_id})

            try:
                from app.agent.cli_runner import process_message_cli

                async for event in process_message_cli(
                    room_id=room_id,
                    user_id=user_id,
                    content=task,
                    # サイレント委譲（2026-08-23 ユーザー選択）: ダンの回答を部屋へ投稿しない。
                    # 部屋に残るのは音声の文字起こし（🎙）だけ。ダンのCLIセッション自体は
                    # 同じ room キーで継続するため、委譲内容の記憶はダン側に残る。
                    skip_save=True,
                ):
                    et = event.get("type", "")
                    if et == "reasoning":
                        step = (event.get("text") or "").strip()
                        if step:
                            await websocket.send_json({"type": "reasoning", "text": step})
                    elif et == "tool_use":
                        await websocket.send_json(
                            {"type": "tool_use", "name": event.get("name", "")}
                        )
                    elif et == "text":
                        chunk = (event.get("text") or "").strip()
                        if chunk:
                            await websocket.send_json({"type": "text", "text": chunk})
                    elif et == "result":
                        await websocket.send_json(
                            {"type": "result", "text": (event.get("text") or "").strip()}
                        )
                    elif et == "error":
                        await websocket.send_json(
                            {"type": "error", "message": event.get("message", "Unknown error")}
                        )
                    elif et == "cancelled":
                        await websocket.send_json(
                            {"type": "result", "text": "（作業は中断されました）"}
                        )
                    # "keepalive" は WS 接続維持目的なので素通り
            except Exception as exc:  # noqa: BLE001
                logger.exception("realtime delegate failed: %s", exc)
                try:
                    await websocket.send_json(
                        {"type": "error", "message": "委譲タスクの処理に失敗しました"}
                    )
                except Exception:
                    pass
            finally:
                is_running = False

    except WebSocketDisconnect:
        logger.info("realtime delegate WS disconnected (user=%s)", user_id)
    except Exception as exc:  # noqa: BLE001
        logger.error("realtime delegate WS error: %s", exc)
