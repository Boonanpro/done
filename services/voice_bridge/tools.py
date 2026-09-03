"""
電話中のダンが使える道具。

チャットの音声モードではブラウザがツールを実行しているが、電話にはブラウザが
いない。なのでブリッジ自身が実行する。中身はチャット側と同じ実装を呼ぶ
（Tavily検索・ChatService・cli_runner）ので、能力の差が出ない。
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

import httpx

log = logging.getLogger("voice_bridge.tools")


TOOLS = [
    {
        "type": "function",
        "name": "search_history",
        "description": (
            "あなた自身の記憶（すべての部屋のチャット履歴・過去の電話の記録）を探す。"
            "既定で全部屋を横断して探すので、この通話の部屋で話していないことも見つかる。"
            "相手の名前・案件・金額・日付など、事前に渡された記憶に無いことを聞かれたら、推測せずまずこれで確認する。"
            "keyword なしで呼ぶと、この通話に紐づく部屋の直近のやり取りを読む。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "description": "探したい語（例: 差し押さえ、金先生、口座振替）"},
                "scope": {
                    "type": "string",
                    "enum": ["all", "room"],
                    "description": "all=全部屋横断（既定）、room=この通話の部屋だけ",
                },
                "limit": {"type": "integer", "description": "読む件数（既定30、最大80）"},
            },
            "required": [],
        },
    },
    {
        "type": "function",
        "name": "get_personal_info",
        "description": (
            "本人の保存済み個人情報（住所・生年月日・事業所整理記号・基礎年金番号・口座など）を取り出す。"
            "field_key を省略すると、保存されている項目の一覧（値は伏せ字）を返すので、まず一覧で項目名を確かめてから取り出す。"
            "取り出した値を相手に伝えるのは、その相手がそれを求める正当な立場（本人・行政窓口・取引先の担当者）のときだけ。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "field_key": {"type": "string", "description": "項目名（例: address, birth_date, jigyosho_seiri_kigo）。省略で一覧"},
            },
            "required": [],
        },
    },
    {
        "type": "function",
        "name": "web_search",
        "description": (
            "webを検索して結果（タイトル・要旨・URL）を受け取り、自分で読んで答える。"
            "最新情報・事実確認などの軽い調べ物はこれで数秒で自己完結する。"
        ),
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "検索クエリ（日本語可）"}},
            "required": ["query"],
        },
    },
    {
        "type": "function",
        "name": "delegate_to_dan",
        "description": (
            "あなた自身の本体（深い作業モード）に頼む。本体はあなたが普段できることを全部できる: "
            "予定やリマインドの登録、決まった時刻に電話をかける（モーニングコール等）、見張り・続報、メール送信、"
            "ブラウザ操作、ファイル操作、実装、込み入った調査。"
            "『後で〜して』『明日〜に電話して』『〜しておいて』と頼まれたら、できないと言わずこれに渡す。"
            "数分かかるので通話中に結果は返らない。呼んだら『任せてください、あとでチャットにも残しておきます』と口頭で伝えて会話を続ける。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "task": {"type": "string", "description": "作業指示。自己完結した具体的な文で書く"},
            },
            "required": ["task"],
        },
    },
    {
        "type": "function",
        "name": "end_call",
        "description": (
            "電話を切る。締めの言葉の最後に「失礼します」と言ってから呼ぶ。"
            "呼ぶと、あなたの声が相手に届き切ってから切れる。"
            "切りどきは、渡された用件・完了条件と会話の流れ（達成した／これ以上進展しない）から自分で判断する。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "reason": {"type": "string", "description": "切る理由（例: 用件が済んだ）"},
            },
            "required": [],
        },
    },
]


def _label(cfg: dict, m: dict) -> str:
    st = m.get("sender_type")
    if st in ("human", "user"):
        return "みきさん"
    return "あなた"


def _clean(content: str) -> str:
    content = (content or "").strip()
    if content.startswith("🎙"):
        content = content[1:].strip()
    return content


def _user_room_ids_sync(user_id: str) -> dict:
    """user が属する全部屋 {room_id: name}"""
    from app.services.chat_service import ChatService

    svc = ChatService()
    mem = svc.supabase.table("chat_room_members").select("room_id").eq("user_id", user_id).execute()
    ids = [r["room_id"] for r in (mem.data or [])]
    if not ids:
        return {}
    names = {}
    for i in range(0, len(ids), 100):
        chunk = ids[i:i + 100]
        rooms = svc.supabase.table("chat_rooms").select("id,name").in_("id", chunk).execute()
        for r in rooms.data or []:
            names[r["id"]] = r.get("name") or ""
        # 表示名は projects.title が正（chat_rooms.name は「新しいプロジェクト」のまま残りがち）
        try:
            projs = svc.supabase.table("projects").select("room_id,title").in_("room_id", chunk).execute()
            for pr in projs.data or []:
                if pr.get("title"):
                    names[pr["room_id"]] = pr["title"]
        except Exception:
            pass
    return names


def _search_all_rooms_sync(user_id: str, keyword: str, limit: int, sender_type: Optional[str] = None) -> list[dict]:
    """全部屋横断で keyword を含む発言を新しい順に返す（room_name 付き）"""
    from app.services.chat_service import ChatService

    rooms = _user_room_ids_sync(user_id)
    if not rooms:
        return []
    svc = ChatService()
    escaped = keyword.replace("%", "\\%").replace("_", "\\_")
    ids = list(rooms.keys())
    out: list[dict] = []
    for i in range(0, len(ids), 100):
        chunk = ids[i:i + 100]
        res = (
            svc.supabase.table("chat_messages")
            .select("room_id,sender_type,content,created_at")
            .in_("room_id", chunk)
            .ilike("content", f"%{escaped}%")
        )
        if sender_type:
            res = res.eq("sender_type", sender_type)
        res = res.order("created_at", desc=True).limit(limit).execute()
        for m in res.data or []:
            m["room_name"] = rooms.get(m["room_id"], "")
            out.append(m)
    out.sort(key=lambda m: m.get("created_at") or "", reverse=True)
    return out[:limit]


async def search_history(cfg: dict, keyword: Optional[str] = None, scope: str = "all", limit: int = 30) -> dict:
    """記憶検索。既定は全部屋横断。keyword なしはこの部屋の直近。"""
    from app.services.chat_service import ChatService

    user_id = cfg.get("user_id")
    room_id = cfg.get("room_id")
    limit = max(1, min(int(limit or 30), 80))
    if not user_id:
        return {"error": "本人が特定できないため記憶を読めません"}

    keyword = (keyword or "").strip()
    try:
        if not keyword or scope == "room":
            if not room_id:
                return {"error": "この通話は特定の部屋に紐づいていません。keyword を付けて全部屋を探してください"}
            svc = ChatService()
            if keyword:
                messages = await svc.search_messages(room_id, user_id, keyword, limit=limit)
            else:
                messages = await svc.get_messages(room_id, user_id, limit=limit)
            lines = [f"- {_label(cfg, m)}: {_clean(m.get('content'))[:500]}" for m in messages if _clean(m.get("content"))]
        else:
            messages = await asyncio.to_thread(_search_all_rooms_sync, user_id, keyword, limit)
            lines = []
            for m in messages:
                c = _clean(m.get("content"))
                if not c:
                    continue
                # keyword の周辺だけ切り出す（長文回答の中から該当箇所を見せる）
                idx = c.find(keyword)
                if idx > 200:
                    c = "…" + c[idx - 200:]
                lines.append(f"- [{m.get('room_name') or '部屋名なし'} / {(m.get('created_at') or '')[:10]}] {_label(cfg, m)}: {c[:500]}")
    except Exception as e:
        log.error("search_history failed: %s", e)
        return {"error": "履歴を読めませんでした"}

    if not lines:
        return {"found": 0, "note": "見つかりませんでした。別の言い方の keyword でもう一度探すか、正直に知らないと言う"}
    return {"found": len(lines), "history": "\n".join(lines)[-8000:]}


async def get_personal_info(cfg: dict, field_key: Optional[str] = None) -> dict:
    from app.services.personal_info_service import get_personal_info_service

    user_id = cfg.get("user_id")
    if not user_id:
        return {"error": "本人が特定できません"}
    svc = get_personal_info_service()
    try:
        if not field_key:
            items = await asyncio.to_thread(svc.list_masked_sync, user_id)
            return {
                "items": [
                    {"field_key": i.get("field_key"), "label": i.get("label"), "category": i.get("category"), "hint": i.get("masked_hint")}
                    for i in items
                ]
            }
        row = await svc.get(user_id, field_key)
        if not row:
            return {"found": False, "note": "その項目は保存されていません。field_key なしで一覧を確認する"}
        log.info("personal info read on call: %s", field_key)
        return {"found": True, "field_key": row["field_key"], "label": row.get("label"), "value": row.get("value")}
    except Exception as e:
        log.error("get_personal_info failed: %s", e)
        return {"error": "取り出せませんでした"}


def _brief_keywords(cfg: dict) -> list[str]:
    """用件・相手から検索語を切り出す（記憶の事前収集用）"""
    import re

    text = " ".join(str(cfg.get(k) or "") for k in ("counterpart", "purpose", "success_condition"))
    # 日本語は分かち書きされないので、漢字連・カタカナ連・英数連を語として拾う
    parts = re.findall(r"[一-鿿]{2,}|[゠-ヿー]{2,}|[A-Za-z0-9][A-Za-z0-9._-]{1,}", text)
    stop = {"確認", "電話", "本人", "相手", "不明", "用件", "動作確認", "提出", "可否", "内容", "場合", "必要", "今日", "明日"}
    words = []
    for w in parts:
        w = w.strip()
        if w in stop or w in words:
            continue
        words.append(w)
    # 長い語を優先（固有名詞・案件名が先に来る）
    words.sort(key=len, reverse=True)
    return words[:6]


async def related_memory_digest(cfg: dict) -> str:
    """発信/受電前に、用件と相手に関係する記憶を全部屋から集めて注入する。

    「この部屋の直近25件」だけでは、その部屋しか知らないダンになる（2026-08-29 ユーザー指摘）。
    """
    user_id = cfg.get("user_id")
    if not user_id:
        return ""
    keywords = _brief_keywords(cfg)
    if not keywords:
        return ""
    seen = set()
    lines = []
    this_room = cfg.get("room_id")
    for kw in keywords:
        try:
            hits = await asyncio.to_thread(_search_all_rooms_sync, user_id, kw, 8)
        except Exception as e:
            log.warning("related search failed for %s: %s", kw, e)
            continue
        for m in hits:
            if m.get("room_id") == this_room:
                continue  # この部屋の分は _room_memory_digest が持っている
            key = (m.get("room_id"), m.get("created_at"))
            if key in seen:
                continue
            seen.add(key)
            c = _clean(m.get("content"))
            idx = c.find(kw)
            if idx > 150:
                c = "…" + c[idx - 150:]
            lines.append(f"- [{m.get('room_name') or '部屋名なし'} / {(m.get('created_at') or '')[:10]}] {_label(cfg, m)}: {c[:300]}")
        if len(lines) >= 20:
            break
    if not lines:
        return ""
    digest = "\n".join(lines[:20])[-6000:]
    return (
        "\n\n【他の部屋にある関連記憶（検索語: " + "、".join(keywords) + "。あなた自身の過去の記録であり、いまの会話ではない）】\n"
        + digest
        + "\n足りなければ search_history で自分で探す。"
    )


async def identify_caller(cfg: dict) -> dict:
    """受電時、発信者番号から相手と関係を同定する。{"counterpart": str, "relation": str}"""
    from_number = (cfg.get("from_number") or "").strip()
    user_id = cfg.get("user_id") or os.getenv("VOICE_BRIDGE_USER_ID", "")
    if not from_number or not user_id:
        return {"counterpart": "", "relation": "external"}
    cfg.setdefault("user_id", user_id)
    for n in await _owner_numbers(user_id):
        if _same_number(n, from_number):
            return {"counterpart": "みきさん（本人）", "relation": "principal"}
    candidates = [from_number]
    if from_number.startswith("+81"):
        candidates.append("0" + from_number[3:])
    local = candidates[-1]
    if len(local) == 11:
        candidates.append(f"{local[:3]}-{local[3:7]}-{local[7:]}")
    for cand in candidates:
        try:
            hits = await asyncio.to_thread(_search_all_rooms_sync, user_id, cand, 3)
        except Exception:
            continue
        if hits:
            m = hits[0]
            c = _clean(m.get("content"))
            idx = c.find(cand)
            snippet = c[max(0, idx - 80): idx + 80].replace("\n", " ")
            return {"counterpart": f"{from_number}（記憶に一致: [{m.get('room_name')}] …{snippet}…）", "relation": "known"}
    return {"counterpart": "", "relation": "external"}


async def web_search(query: str) -> dict:
    key = os.getenv("TAVILY_API_KEY", "")
    if not key:
        return {"error": "検索キーが未設定です"}
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                "https://api.tavily.com/search",
                json={"api_key": key, "query": query, "max_results": 5, "include_answer": False},
            )
        if resp.status_code != 200:
            return {"error": f"検索に失敗しました (HTTP {resp.status_code})"}
        data = resp.json()
        return {
            "query": query,
            "results": [
                {
                    "title": (r.get("title") or "")[:120],
                    "snippet": (r.get("content") or "")[:400],
                    "url": r.get("url", ""),
                }
                for r in (data.get("results") or [])[:5]
            ],
        }
    except Exception as e:
        log.error("web_search failed: %s", e)
        return {"error": "検索に失敗しました"}


async def delegate_to_dan(cfg: dict, task: str) -> dict:
    """ダン本体（CLI）に作業を投げる。結果は部屋に残るので通話中は待たない。"""
    room_id = cfg.get("room_id")
    user_id = cfg.get("user_id")
    if not room_id or not user_id:
        return {"error": "この通話は特定の部屋に紐づいていないため本体に渡せません。用件を復唱して持ち帰ると伝える"}

    async def _run():
        try:
            from app.agent.cli_runner import process_message_cli

            note = (
                f"（電話中の私から引き継ぎ。相手: {cfg.get('counterpart')}）{task}\n"
                "時刻指定の電話は、見張り(watch)を登録し、その時刻に voice_bridge の /call を叩く形で実現する。"
            )
            async for _event in process_message_cli(
                room_id=room_id, user_id=user_id, content=note, skip_save=False
            ):
                pass
            log.info("delegate finished: %s", task[:80])
        except Exception as e:
            log.error("delegate failed: %s", e)

    asyncio.create_task(_run())
    log.info("delegate started: %s", task[:80])
    return {"started": True, "note": "本体に渡しました。結果はチャットに残ります。通話中は待たずに会話を続けてください。"}


async def hangup_now(cfg: dict) -> None:
    """Twilio 側から通話を終わらせる（呼ぶ側が再生完了を待ってから呼ぶ）"""
    call_sid = cfg.get("call_sid")
    if not call_sid:
        log.warning("hangup_now: call_sid unknown")
        return

    def _hangup():
        from twilio.rest import Client

        client = Client(os.getenv("TWILIO_ACCOUNT_SID", ""), os.getenv("TWILIO_AUTH_TOKEN", ""))
        client.calls(call_sid).update(status="completed")

    await asyncio.to_thread(_hangup)
    log.info("call ended by dan: %s", call_sid)


def _digits(s: str) -> str:
    return "".join(ch for ch in (s or "") if ch.isdigit())


def _same_number(a: str, b: str) -> bool:
    da, db = _digits(a), _digits(b)
    if not da or not db:
        return False
    # +81 70... と 070... を同一視（末尾9桁比較）
    return da[-9:] == db[-9:]


async def _owner_numbers(user_id: str) -> list[str]:
    from app.services.personal_info_service import get_personal_info_service

    if not user_id:
        return []
    svc = get_personal_info_service()
    nums = []
    try:
        items = await asyncio.to_thread(svc.list_masked_sync, user_id)
        for it in items:
            if (it.get("category") or "") == "phone" or "phone" in (it.get("field_key") or ""):
                row = await svc.get(user_id, it["field_key"])
                if row and row.get("value"):
                    nums.append(str(row["value"]))
    except Exception as e:
        log.warning("owner numbers lookup failed: %s", e)
    return nums


async def infer_relation(counterpart: str, to_number: str, user_id: str) -> str:
    """発信時の相手との関係を推定: principal / known / external"""
    if any(k in (counterpart or "") for k in ("みきさん", "本人")):
        return "principal"
    for n in await _owner_numbers(user_id):
        if _same_number(n, to_number):
            return "principal"
    if user_id and counterpart:
        try:
            # 「面識あり」= 本人がその相手について話したことがある（ダンが調べただけの相手は外部扱い）
            hits = await asyncio.to_thread(_search_all_rooms_sync, user_id, counterpart[:20], 1, "human")
            if hits:
                return "known"
        except Exception:
            pass
    return "external"


async def dispatch(name: str, args: dict, cfg: dict) -> dict:
    if name in ("search_history", "read_room_history"):
        return await search_history(cfg, args.get("keyword"), args.get("scope") or "all", args.get("limit", 30))
    if name == "get_personal_info":
        return await get_personal_info(cfg, args.get("field_key"))
    if name == "web_search":
        return await web_search(args.get("query", ""))
    if name == "delegate_to_dan":
        return await delegate_to_dan(cfg, args.get("task", ""))
    if name == "end_call":
        return {"error": "end_call はブリッジ本体が処理する"}
    return {"error": f"unknown tool: {name}"}
