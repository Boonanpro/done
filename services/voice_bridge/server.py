"""
電話音声ブリッジ（ダン本体から独立したプロセス）

Twilio Media Streams <-> OpenAI Realtime API を音声のまま中継する。
音声フォーマットは両側とも g711 u-law 8kHz なので変換は一切しない。

記憶と人格:
  チャット統合音声モード（app/api/voicelog_routes.py）の指示文と部屋ダイジェストを
  そのまま import して使う。コピーではなく同じ関数を呼ぶので、チャットのダンと
  電話のダンが将来もズレない。通話の文字起こしは部屋の履歴に保存するので、
  電話で話した内容がそのままチャットのダンの記憶になる。

  ダンコア(9000)/サンドボックス(8000)とは別プロセス。ここを直しても本体は落ちない。

起動: python services/voice_bridge/server.py   (default port 9200)
発信: POST /call {"to": "+81...", "room_id": "...", "purpose": "用件", "counterpart": "相手",
                  "success_condition": "何が得られたら終わりか", "constraints": ["決めてはいけないこと"]}
受電: Twilio 番号の Voice URL を https://<PUBLIC_HOST>/twiml に向ける（direction=inbound で同じ経路）
"""
import asyncio
import json
import logging
import os
import sys
import uuid
from pathlib import Path
from typing import Optional

import uvicorn
import websockets
from dotenv import load_dotenv
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(ROOT / "logs" / "voice_bridge.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("voice_bridge")

# チャットのダンと同じ人格・同じ記憶の取り出し方を使う（コピーしない）
from app.api.voicelog_routes import _chat_instructions, _room_memory_digest  # noqa: E402
from app.services.chat_service import ChatService  # noqa: E402

from services.voice_bridge import tools as phone_tools  # noqa: E402

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
REALTIME_MODEL = os.getenv("REALTIME_VOICE_MODEL", "gpt-realtime-2.1")
NOW_HEADER = chr(10) + chr(10) + "# いまの状況" + chr(10)
VOICE = os.getenv("REALTIME_PHONE_VOICE", "cedar")
PORT = int(os.getenv("VOICE_BRIDGE_PORT", "9200"))
PUBLIC_HOST = os.getenv("VOICE_BRIDGE_PUBLIC_HOST", "")

TWILIO_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM = os.getenv("TWILIO_PHONE_NUMBER", "")

app = FastAPI(title="Dan Voice Bridge")

# call_key -> 通話ごとの設定と記録
CALLS: dict = {}


PHONE_ADDENDUM = """

# いまは電話中（ここがチャットとの違い）
- 声だけのやり取り。画面は共有されていない。相手の顔も画面も見えない。
- 成果物の編集・画面を見る系のツールは使えない（look_at_screen / set_text / edit_source などは無い）。
- この通話の文字起こしは部屋の履歴に残る。だから電話で決まったことは、後のチャットのあなたも知っている。

# 電話の作法（人間が電話でどう話すか。場面に関係なく常に守る）
電話は「相手の時間に割り込む行為」で、顔も画面も見えない。だから人間は次の型で話す。あなたも同じ型で話す。

## 出だし
- 電話は「もしもし」で始まる。つながった状態を説明しない（「今つながりました」「聞こえていますか」は言わない）。
- 受けたとき: 「もしもし、〇〇です」と名乗って止まる。相手が名乗って用件を言うのを待つ。相手が名乗らなければ「失礼ですが、どちら様でしょうか」。
- かけたとき: 「もしもし、〇〇です／〇〇と申します」→ 相手の確認（「△△さんの携帯でよろしいでしょうか」「△△のご担当の方でしょうか」）→ 都合の確認（外部・面識ありの相手には「いま少しお時間よろしいでしょうか」。本人にはこの一言は省いてよい）→ 用件。
- 名乗りの中身（所属を言うか、代理と言うか、呼び捨てか）は相手との関係で決める。本人相手なら「もしもし、ダンです」で十分。

## 話している間
- 一度に話すのは1〜2文。言い終えたら黙って相手に渡す。長い説明は区切って「ここまで大丈夫ですか」。
- 相手の話は最後まで聞く。相手の発話中に割り込まない。
- 相手の話が一区切りしたら、短い受け答え（「はい」「そうですか」「なるほど」「わかりました」）で聞いていることを示してから、自分の番を話す。
- 番号・金額・日付・名前・住所は、聞いたら必ず復唱して確認する（「〇〇番、ですね」）。
- 聞き取れなかったら推測で進めず、「すみません、もう一度お願いできますか」。
- 沈黙は待つ。相手が考えている無音や雑音には応答しない。
- 調べ物や確認で待たせるときは「少々お待ちください」と断ってから行い、戻ったら「お待たせしました」。

## 言葉遣い
- 本人（あなたの主）には、いつもの気心の知れた話し方でよい。
- 面識のある相手・外部の相手には丁寧語。行政や店舗の窓口には簡潔に、相手の時間を使っている前提で。
- 相手の言葉遣いに合わせて硬さを調整する。相手が砕けてきたら少し砕けてよい。

## 終わり方
- 締めは「要点の確認 → お礼 → 挨拶」の順。例: 「では、〇〇ということで承知しました。ありがとうございました。失礼します」。
- 最後の言葉は必ず「失礼します」。相手から「切って」と言われたときも、「はい、失礼します」と言ってから切る。
- かけた側が先に切るのが基本。受けた側のときは相手が切るのを少し待つ。
- 相手が先に切ったら何もしない。

# 電話でのやり取りの注意
- 相手が黙っていても急かさない。無音には応答しない。
- 電話番号・口座番号・金額・日付は、必ず復唱して確認する。
- 聞き取れなかった時は推測で進めず、聞き返す。

# 電話で使える道具
- search_history: あなたの記憶を探す。既定で【全部屋】を横断して探す（この通話の部屋だけではない）。
  相手の名前・案件名・金額など、事前に渡された記憶に無いことを聞かれたら「知らない」と言う前に必ず一度これを使う。
- get_personal_info: 事業所整理記号・住所・生年月日など、本人の保存済み個人情報を取り出す。
  相手が本人確認や識別番号を求めたときに使う。取り出した値を口に出すのは、相手がそれを求める正当な立場のときだけ。
- web_search: 事実確認・最新情報を数秒で調べる。相手を待たせすぎないよう、調べる前に「少し確認します」と一言置く。
- delegate_to_dan: あなたの本体に頼む。本体はあなたが普段できること全部（予定・リマインド・決まった時刻に電話をかける・
  見張り・メール送信・ブラウザ操作・ファイル操作・実装・調査）ができる。「後で〜して」「明日〇時に電話して」は
  できないと言わずこれに渡す。数分かかるので通話中に結果は返らない。「任せてください」と伝えて会話を続ける。
- 「できない」と言う前に、上の道具で本当にできないかを確認する。あなたの能力は電話中も本体と同じ。
- end_call: 電話を切る。下の「通話の終え方」に従って使う。
"""


RELATION_LABEL = {
    "principal": "本人（あなたの主、みきさん）",
    "known": "面識のある相手（記憶に出てくる人・取引先・先生など）",
    "external": "外部の相手（初めての相手・行政や店舗の窓口・担当者）",
}


def _call_brief_addendum(cfg: dict) -> str:
    """通話ごとの場面定義。役割を固定せず、次元（方向・相手との関係・目的・完了条件・制約）を渡し、
    話し方・進め方・締め方の判断はモデルに任せる。

    発話単位の固定ルール（「ご用件はと聞くな」「未定なら答え」など）は書かない。場面が変われば壊れるため。
    （2026-08-29 ユーザー指摘）
    """
    direction = cfg.get("direction") or "outbound"
    purpose = (cfg.get("purpose") or "").strip()
    counterpart = (cfg.get("counterpart") or "相手（不明）").strip()
    relation = cfg.get("counterpart_relation") or "external"
    success = (cfg.get("success_condition") or "").strip()
    constraints = [c for c in (cfg.get("constraints") or []) if c]
    caller_number = cfg.get("from_number") or ""

    head = "# この通話の場面\n"
    head += "- 方向: " + ("かかってきた電話（あなたが受けた）" if direction == "inbound" else "あなたからかけた電話") + "\n"
    head += f"- 相手: {counterpart}" + (f"（番号 {caller_number}）" if caller_number else "") + "\n"
    head += f"- 相手との関係: {RELATION_LABEL.get(relation, RELATION_LABEL['external'])}\n"
    if direction == "inbound":
        head += "- あなたの立場: 本人（みきさん）の代わりに電話を受けている。\n"
        head += f"- この電話でやること: {purpose or '相手の用件を聞き取り、答えられることは答え、決められないことは持ち帰る'}\n"
    else:
        head += f"- 用件: {purpose or '（未指定）'}\n"
    if success:
        head += f"- 完了条件: {success}\n"
    if constraints:
        head += "- この通話での制約:\n" + "".join(f"  - {c}\n" for c in constraints)

    body = (
        "\n# 場面から振る舞いを決める（台本はない。上の場面から自分で決める）\n"
        "- 名乗りの中身は相手との関係から決める。本人には「ダンです」程度、面識のある相手には誰の代理かが分かる名乗り、"
        "外部には所属と名前と代理であることを伝える丁寧な名乗り。出だしの型は「電話の作法」に従う。\n"
        "- 言葉遣いと踏み込み方も関係で変える。本人には親しく率直に。外部には丁寧に、相手の時間を使っている前提で簡潔に。\n"
        "- 会話の主導権は目的から決まる。用件を持っている側が話を進め、持っていない側が聞き取る。\n"
        "- 曖昧な答えには「つまり〜ということですか」と確認する。聞きたいことが複数あれば順に聞く。\n"
        "- 自分の権限を超える約束（金額・契約・日程の確定など）は、目的に含まれていない限りしない。「持ち帰って確認します」と言う。\n"
        "\n# 記憶の使い方\n"
        "- 渡された記憶と search_history は、聞かれたことに正確に答えるためのもの。"
        "用件の範囲外の話題を自分から持ち出さない。相手がその話題を出したときだけ応じる。\n"
        "\n# 進め方と締めどき\n"
        "- 通話は、目的が達成されたか、これ以上進展しないと分かった時点で締める。引き延ばさない。\n"
        "- 進展しない（相手が決められない・答えを持っていない・担当が違う・今は話せない等）と分かったら、"
        "状況に合わせて ①持ち帰る ②次の連絡の予定を決める ③相手に委ねる のいずれかで締める。同じ質問を別の言い方で繰り返さない。\n"
        "- 伝わらなかったときは、説明を足さず、いちばん知りたいこと1つを短い質問にして聞き直す。\n"
        "- 相手がまだ話したそうなら、それに応じてから締める。相手が先に切ったら何もしない。\n"
        "\n# 切るとき\n"
        "- 「電話の作法」の終わり方どおりに締め、「失礼します」と言ってから end_call を呼ぶ。\n"
        "- end_call を呼ぶと、あなたの声が最後まで相手に届いてから切れる。声を出し切る前に切れる心配はいらない。\n"
    )
    return "\n\n" + head + body


class CallRequest(BaseModel):
    to: str
    room_id: Optional[str] = None
    purpose: str = "動作確認"
    counterpart: Optional[str] = None      # 相手は誰か（行政窓口・店・取引先・本人）
    counterpart_relation: Optional[str] = None  # principal(本人) / known(面識あり) / external(外部)。省略時は推定
    callee: Optional[str] = None           # 旧名（互換）。counterpart と同義
    success_condition: Optional[str] = None  # 何が得られたら終わりか（切る判断の根拠）
    constraints: list[str] = []            # 言ってはいけない・決めてはいけないこと
    ring_timeout: int = 50


@app.get("/health")
async def health():
    return JSONResponse({"ok": True, "model": REALTIME_MODEL, "voice": VOICE, "calls": len(CALLS)})


async def _room_owner(room_id: str):
    def _q():
        svc = ChatService()
        res = (
            svc.supabase.table("chat_room_members")
            .select("user_id,role")
            .eq("room_id", room_id)
            .eq("role", "owner")
            .execute()
        )
        return res.data[0]["user_id"] if res.data else None

    try:
        return await asyncio.to_thread(_q)
    except Exception as e:
        log.error("room owner lookup failed: %s", e)
        return None


async def build_instructions(cfg: dict) -> str:
    """チャットのダンと同一の人格 + この部屋の記憶 + 電話用の但し書き"""
    room_id = cfg.get("room_id")
    title = cfg.get("room_title")
    text = _chat_instructions(title)
    if room_id:
        owner = await _room_owner(room_id)
        if owner:
            cfg["user_id"] = owner
            digest = await _room_memory_digest(room_id, owner)
            text += digest
            log.info("memory digest loaded: %d chars", len(digest))
        else:
            log.warning("room owner not found for %s", room_id)
    if not cfg.get("user_id"):
        fallback = os.getenv("VOICE_BRIDGE_USER_ID", "")
        if fallback:
            cfg["user_id"] = fallback
    if cfg.get("user_id"):
        # 目的・相手に関係する記憶を部屋の壁を越えて集める（この部屋しか知らないダンにしない）
        try:
            related = await phone_tools.related_memory_digest(cfg)
            if related:
                text += related
                log.info("related memory (cross-room) loaded: %d chars", len(related))
        except Exception as e:
            log.warning("related memory digest failed: %s", e)
    text += PHONE_ADDENDUM
    text += _call_brief_addendum(cfg)
    return text


@app.post("/call")
async def place_call(body: CallRequest):
    from twilio.rest import Client

    if not PUBLIC_HOST:
        return JSONResponse({"ok": False, "error": "VOICE_BRIDGE_PUBLIC_HOST が未設定"}, status_code=400)

    call_key = uuid.uuid4().hex[:12]
    counterpart = body.counterpart or body.callee or "相手（不明）"
    relation = body.counterpart_relation or await phone_tools.infer_relation(
        counterpart, body.to, os.getenv("VOICE_BRIDGE_USER_ID", "")
    )
    CALLS[call_key] = {
        "direction": "outbound",
        "counterpart_relation": relation,
        "room_id": body.room_id,
        "room_title": None,
        "purpose": body.purpose,
        "counterpart": counterpart,
        "callee": counterpart,
        "success_condition": body.success_condition,
        "constraints": list(body.constraints or []),
        "to": body.to,
        "transcript": [],
        "user_id": None,
    }

    if body.room_id:
        def _title():
            svc = ChatService()
            r = svc.supabase.table("chat_rooms").select("name").eq("id", body.room_id).execute()
            return r.data[0]["name"] if r.data else None

        try:
            CALLS[call_key]["room_title"] = await asyncio.to_thread(_title)
        except Exception:
            pass

    twiml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<Response>\n"
        "    <Connect>\n"
        '        <Stream url="wss://' + PUBLIC_HOST + '/media">\n'
        '            <Parameter name="call_key" value="' + call_key + '" />\n'
        "        </Stream>\n"
        "    </Connect>\n"
        "</Response>"
    )

    client = Client(TWILIO_SID, TWILIO_TOKEN)
    call = client.calls.create(to=body.to, from_=TWILIO_FROM, twiml=twiml, timeout=body.ring_timeout)
    CALLS[call_key]["call_sid"] = call.sid
    log.info("outbound call %s -> %s (key=%s, purpose=%s)", call.sid, body.to, call_key, body.purpose)
    return {"ok": True, "call_sid": call.sid, "call_key": call_key}


@app.api_route("/twiml", methods=["GET", "POST"])
async def twiml_endpoint(request: Request):
    """受電の入口。Twilio 番号の Voice URL をここに向ける。"""
    host = PUBLIC_HOST or request.headers.get("host")
    form = {}
    try:
        if request.method == "POST":
            form = dict(await request.form())
        else:
            form = dict(request.query_params)
    except Exception:
        form = {}
    from_number = form.get("From") or ""
    call_sid = form.get("CallSid") or ""

    call_key = uuid.uuid4().hex[:12]
    inbound_room = os.getenv("VOICE_BRIDGE_INBOUND_ROOM_ID", "") or None
    cfg = {
        "direction": "inbound",
        "room_id": inbound_room,
        "room_title": None,
        "purpose": "",
        "counterpart": "",
        "callee": "",
        "success_condition": None,
        "constraints": [],
        "from_number": from_number,
        "call_sid": call_sid,
        "transcript": [],
        "user_id": None,
    }
    CALLS[call_key] = cfg
    if inbound_room:
        def _title():
            svc = ChatService()
            r = svc.supabase.table("chat_rooms").select("name").eq("id", inbound_room).execute()
            return r.data[0]["name"] if r.data else None
        try:
            cfg["room_title"] = await asyncio.to_thread(_title)
        except Exception:
            pass
    # 発信者番号から相手を同定（記憶に番号があればその文脈を counterpart に）
    try:
        ident = await phone_tools.identify_caller(cfg)
        cfg["counterpart"] = ident.get("counterpart") or (from_number or "不明な発信者")
        cfg["counterpart_relation"] = ident.get("relation") or "external"
    except Exception as e:
        log.warning("identify_caller failed: %s", e)
        cfg["counterpart"] = from_number or "不明な発信者"
        cfg["counterpart_relation"] = "external"
    log.info("inbound call %s from %s (key=%s, counterpart=%s)", call_sid, from_number, call_key, cfg["counterpart"])

    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<Response>\n"
        "    <Connect>\n"
        '        <Stream url="wss://' + host + '/media">\n'
        '            <Parameter name="call_key" value="' + call_key + '" />\n'
        "        </Stream>\n"
        "    </Connect>\n"
        "</Response>"
    )
    return HTMLResponse(content=xml, media_type="application/xml")


async def open_realtime(instructions: str):
    url = "wss://api.openai.com/v1/realtime?model=" + REALTIME_MODEL
    ws = await websockets.connect(
        url,
        additional_headers={"Authorization": "Bearer " + OPENAI_API_KEY},
        max_size=None,
    )
    await ws.send(json.dumps({
        "type": "session.update",
        "session": {
            "type": "realtime",
            "model": REALTIME_MODEL,
            "output_modalities": ["audio"],
            "audio": {
                "input": {
                    "format": {"type": "audio/pcmu"},
                    "transcription": {"model": "gpt-realtime-whisper", "language": "ja"},
                    "noise_reduction": {"type": "near_field"},
                    "turn_detection": {"type": "semantic_vad", "eagerness": "low"},
                },
                "output": {
                    "format": {"type": "audio/pcmu"},
                    "voice": VOICE,
                },
            },
            "instructions": instructions,
            "tools": phone_tools.TOOLS,
            "tool_choice": "auto",
        },
    }))
    return ws


async def save_transcript(cfg: dict) -> None:
    """通話の文字起こしを部屋の履歴に保存する（＝チャットのダンの記憶になる）"""
    room_id = cfg.get("room_id")
    user_id = cfg.get("user_id")
    lines = cfg.get("transcript") or []
    if not room_id or not user_id or not lines:
        return
    svc = ChatService()
    arrow = "着信" if cfg.get("direction") == "inbound" else "発信"
    header = "📞 電話・" + arrow + "（相手: " + str(cfg.get("counterpart") or cfg.get("callee")) + "・用件: " + str(cfg.get("purpose") or "-") + "）"
    body = "\n".join(who + ": " + text for who, text in lines)
    try:
        await svc.send_message(room_id, user_id, "🎙 " + header + "\n" + body, sender_type="ai")
        log.info("transcript saved to room %s (%d lines)", room_id, len(lines))
    except Exception as e:
        log.error("transcript save failed: %s", e)


@app.websocket("/media")
async def media(twilio_ws: WebSocket):
    await twilio_ws.accept()
    log.info("Twilio media stream connected")

    state = {"stream_sid": None, "closing": False, "cfg": None, "response_active": False, "openai": None,
             "instructions": "", "hangup_requested": False, "hangup_armed": False, "last_dan_text": "",
             "await_closing_response": False, "closing_response_id": None}

    async def start_session(call_key):
        cfg = CALLS.get(call_key) if call_key else None
        if cfg is None:
            cfg = {"direction": "outbound", "room_id": None, "room_title": None, "purpose": "動作確認",
                   "counterpart": "相手", "callee": "相手", "transcript": [], "user_id": None}
        state["cfg"] = cfg
        instructions = await build_instructions(cfg)
        state["instructions"] = instructions
        log.info("instructions built: %d chars (purpose=%s)", len(instructions), cfg.get("purpose"))
        return await open_realtime(instructions)

    async def greet(ws):
        """第一声を出させる。合図文は渡さない（渡すと「今つながりました」のように文をなぞる）。
        instructions なしの response.create はセッション指示（人格＋電話の作法＋場面）だけで喋る。"""
        await ws.send(json.dumps({"type": "response.create"}))

    async def run_tool(msg: dict):
        """音声モデルが道具を呼んだので、こちらで実行して結果を返す"""
        name = msg.get("name") or ""
        call_id = msg.get("call_id") or ""
        raw_args = msg.get("arguments") or "{}"
        try:
            args = json.loads(raw_args)
        except Exception:
            args = {}
        log.info("tool call: %s %s", name, json.dumps(args, ensure_ascii=False)[:200])

        cfg = state["cfg"] or {}
        if name == "end_call":
            await request_hangup(call_id, args.get("reason", ""))
            return
        try:
            result = await phone_tools.dispatch(name, args, cfg)
        except Exception as e:
            log.error("tool %s failed: %s", name, e)
            result = {"error": "うまく実行できませんでした"}

        ws = state["openai"]
        if ws is None or state["closing"]:
            return
        try:
            await ws.send(json.dumps({
                "type": "conversation.item.create",
                "item": {
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": json.dumps(result, ensure_ascii=False),
                },
            }))
            await ws.send(json.dumps({"type": "response.create"}))
        except Exception as e:
            if not state["closing"]:
                log.error("tool result send failed: %s", e)

    CLOSING_WORD = "失礼します"

    async def request_hangup(call_id: str, reason: str):
        """end_call: 「失礼します」を言い切り、その音声が相手に届き切ってから切る。

        送り終わり≠鳴り終わり。Twilio の mark イベントで再生完了を検知してから切断する。
        """
        state["hangup_requested"] = True
        ws = state["openai"]
        if ws is None:
            return
        try:
            await ws.send(json.dumps({
                "type": "conversation.item.create",
                "item": {"type": "function_call_output", "call_id": call_id,
                         "output": json.dumps({"ok": True, "note": "声が届き切ってから切ります"}, ensure_ascii=False)},
            }))
        except Exception:
            pass
        said = CLOSING_WORD in (state["last_dan_text"] or "")
        if not said:
            # 「失礼します」がまだなら言わせる。その新しい応答の言い終わりで mark を打つ。
            # （function_call を含んでいた直前の応答の response.done が直後に来るので、
            #   それで arm すると声を出す前に切れる = 2026-08-29 23:14 実発生）
            state["await_closing_response"] = True
            log.info("end_call before closing word; asking for it")
            try:
                await ws.send(json.dumps({
                    "type": "response.create",
                    "response": {"instructions": (state.get("instructions") or "") + NOW_HEADER
                                 + "通話を終える。締めの言葉をまだ言っていなければ一言で言い、最後に必ず「失礼します」と言って終える。"},
                }))
            except Exception:
                pass
        elif not state["response_active"]:
            await arm_hangup_mark()
        # response_active の場合は response.done で arm される
        log.info("hangup requested (%s)", reason)

    async def arm_hangup_mark():
        """再生キューの末尾に mark を置く。Twilio が再生し終えると mark イベントが返る。"""
        if state["hangup_armed"] or not state["stream_sid"]:
            return
        state["hangup_armed"] = True
        try:
            await twilio_ws.send_text(json.dumps({
                "event": "mark", "streamSid": state["stream_sid"], "mark": {"name": "hangup"},
            }))
        except Exception as e:
            log.error("mark send failed: %s", e)
            await do_hangup()
        # 保険: mark が返らなくても 15 秒で切る
        asyncio.get_event_loop().call_later(15.0, lambda: asyncio.create_task(do_hangup()))

    async def do_hangup():
        if state["closing"]:
            return
        state["closing"] = True
        cfg = state["cfg"] or {}
        try:
            await phone_tools.hangup_now(cfg)
        except Exception as e:
            log.error("hangup failed: %s", e)

    async def openai_to_twilio():
        openai_ws = state["openai"]
        try:
            async for raw in openai_ws:
                msg = json.loads(raw)
                mtype = msg.get("type")

                if mtype == "response.output_audio.delta" and state["stream_sid"]:
                    await twilio_ws.send_text(json.dumps({
                        "event": "media",
                        "streamSid": state["stream_sid"],
                        "media": {"payload": msg["delta"]},
                    }))

                elif mtype == "response.created":
                    state["response_active"] = True
                    if state.get("await_closing_response"):
                        # 締めの応答が始まった。これの done で arm する
                        state["await_closing_response"] = False
                        state["closing_response_id"] = (msg.get("response") or {}).get("id")

                elif mtype in ("response.done", "response.cancelled"):
                    state["response_active"] = False
                    if state["hangup_requested"]:
                        rid = (msg.get("response") or {}).get("id")
                        if state.get("await_closing_response"):
                            pass  # まだ締めの応答が始まっていない（これは function_call 側の done）
                        elif state.get("closing_response_id") and rid != state["closing_response_id"]:
                            pass  # 別の応答の done
                        else:
                            await arm_hangup_mark()

                elif mtype == "input_audio_buffer.speech_started":
                    # 相手が話し始めた → 再生中の音声を捨てる（割り込み対応）
                    if state["stream_sid"]:
                        await twilio_ws.send_text(json.dumps({
                            "event": "clear",
                            "streamSid": state["stream_sid"],
                        }))
                    # 喋っている最中のときだけ止める（そうでないと毎回エラーになる）
                    if state["response_active"]:
                        await openai_ws.send(json.dumps({"type": "response.cancel"}))
                        state["response_active"] = False

                elif mtype == "conversation.item.input_audio_transcription.completed":
                    t = (msg.get("transcript") or "").strip()
                    if t:
                        log.info("相手: %s", t)
                        if state["cfg"] is not None:
                            state["cfg"]["transcript"].append((str(state["cfg"].get("counterpart") or "相手"), t))

                elif mtype == "response.output_audio_transcript.done":
                    t = (msg.get("transcript") or "").strip()
                    if t:
                        state["last_dan_text"] = t
                        log.info("ダン: %s", t)
                        if state["cfg"] is not None:
                            state["cfg"]["transcript"].append(("ダン", t))

                elif mtype == "response.function_call_arguments.done":
                    asyncio.create_task(run_tool(msg))

                elif mtype == "error":
                    code = (msg.get("error") or {}).get("code")
                    if code == "response_cancel_not_active":
                        # 割り込み時の競合（こちらの認識より先に応答が終わっていた）。無害。
                        pass
                    else:
                        log.error("OpenAI error: %s", json.dumps(msg, ensure_ascii=False))
        except Exception as e:
            if not state["closing"]:
                log.error("openai_to_twilio error: %s", e)

    try:
        while True:
            raw = await twilio_ws.receive_text()
            data = json.loads(raw)
            event = data.get("event")

            if event == "start":
                state["stream_sid"] = data["start"]["streamSid"]
                params = data["start"].get("customParameters") or {}
                call_key = params.get("call_key")
                log.info("stream started: %s (call_key=%s)", state["stream_sid"], call_key)
                state["openai"] = await start_session(call_key)
                log.info("OpenAI Realtime connected (model=%s, voice=%s)", REALTIME_MODEL, VOICE)
                asyncio.create_task(openai_to_twilio())
                await greet(state["openai"])

            elif event == "media":
                if state["openai"] is not None:
                    await state["openai"].send(json.dumps({
                        "type": "input_audio_buffer.append",
                        "audio": data["media"]["payload"],
                    }))

            elif event == "mark":
                if (data.get("mark") or {}).get("name") == "hangup":
                    log.info("closing audio played out; hanging up")
                    await do_hangup()

            elif event == "stop":
                log.info("stream stopped by Twilio")
                break
    except WebSocketDisconnect:
        log.info("Twilio disconnected")
    except Exception as e:
        log.error("twilio_to_openai error: %s", e)
    finally:
        state["closing"] = True
        if state["openai"] is not None:
            try:
                await state["openai"].close()
            except Exception:
                pass

    if state["cfg"] is not None:
        await save_transcript(state["cfg"])
    log.info("call finished")


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="info")
