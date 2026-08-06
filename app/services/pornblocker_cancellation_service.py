"""
解約の申し出を、運営（人間）を介さずに受けて返す。

【この仕組みが要る理由】
鍵を外せるのが運営だけである以上、やめたい人は必ずこちらへ来る。
運営が 1 人なら、契約者が増えた時点で深夜の依頼に潰れる。
返さなければ「抜けられないアプリ」になり、即返せば商品そのものが消える。

だから受付・引き止め・解除コードの発行までを、ここで完結させる。

【設計の芯は 3 つ】
1. **申し出は文章で受ける。** ボタンにしない。打って送るまでの数十秒が効く。
2. **返事は待たせる。** 即答は機械だと分かるうえ、衝動が冷める時間も奪う。
   深夜の申し出は翌朝まで持ち越す。人が寝ている時間に返らないのは自然で、
   衝動が一番強い時間帯を、そのまま待ち時間に変えられる。
3. **引き止めは 1 回だけ。** 2 回目は必ず通す。ここは AI の裁量にしない。
   何度でも引き止める作りは、解約を著しく困難にする行為として問題になるし、
   「抜けられない」という評判はこの商売では致命傷になる。

【課金は返事より先に止める】
申し出を受けた瞬間に次の請求を止める。
「やめたいと言ったのに、返事が遅れて課金された」を構造から消すため。
金の心配が消えたほうが、引き止めの言葉も届く。
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import random
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app.config import settings
from app.services.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)

#: 日本時間。返事の時刻はここで判断する。利用者は国内しかいない。
JST = timezone(timedelta(hours=9))

#: 解除コードの桁数。端末側の UnlockCode.DIGITS と必ず揃える。
UNLOCK_DIGITS = 8

#: 申し出から、遅くともこれだけ経ったら無条件で解除コードを出す。
#:
#: 引き止めの返事が作れない・届かないといった不具合で、
#: 本人が永久に閉じ込められることだけは避ける。
#: 商品が一時的に緩むより、抜けられない事故のほうがはるかに高くつく。
FAILSAFE_HOURS = 72


class PornblockerCancellationService:
    """やめたいという申し出を受けて、返し、必要なら鍵を開ける。"""

    def __init__(self):
        self.supabase = get_supabase_client().client
        self.table = "pornblocker_cancellations"

    # ------------------------------------------------------------ 受ける

    async def on_user_message(
        self,
        device_id: str,
        text: str,
        request_id: Optional[str] = None,
        history: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        端末から 1 通届いたときに呼ぶ。

        ここでやるのは「読んで、決めて、返事を予約する」まで。
        返事そのものは期限が来るまで出さない（`flush_due_replies`）。
        """
        row = await self._get(device_id)
        attempts = int(row.get("attempts") or 0)

        decision = self._decide(text, attempts, history or [])
        intent = decision["intent"]
        reply = decision["reply"]

        now = datetime.now(timezone.utc)

        if intent == "cancel":
            attempts += 1
            # 1 回目だろうと 2 回目だろうと、金は今すぐ止める。
            stopped = await self._stop_billing(device_id)
            patch: Dict[str, Any] = {
                "state": "requested",
                "attempts": attempts,
                "last_requested_at": now.isoformat(),
                "replied_at": None,
            }
            if not row.get("first_requested_at"):
                patch["first_requested_at"] = now.isoformat()
            if stopped and not row.get("billing_stopped_at"):
                patch["billing_stopped_at"] = now.isoformat()

            # 2 回目は通す。ここで初めて鍵を開ける。
            if attempts >= 2:
                reply = self._attach_unlock_code(device_id, reply, request_id, patch)

            patch["pending_reply"] = reply
            patch["reply_due_at"] = self._decide_reply_time(now).isoformat()
            await self._upsert(device_id, patch)
            return {"intent": intent, "attempts": attempts, "reply_due_at": patch["reply_due_at"]}

        if intent == "resume":
            # 引き止めが効いた。金を戻して、申し出は無かったことにする。
            #
            # 【回数を 0 に戻す理由】
            # 一度撤回した人が半年後にまたやめたくなったとき、
            # 前回の 1 回が残っていると、いきなり 2 回目扱いで素通しになる。
            # 撤回はやり直しであって、進行ではない。
            await self._resume_billing(device_id)
            patch = {
                "state": "none",
                "attempts": 0,
                "pending_reply": reply,
                "reply_due_at": self._decide_reply_time(now).isoformat(),
                "replied_at": None,
                "billing_stopped_at": None,
            }
            await self._upsert(device_id, patch)
            return {"intent": intent, "attempts": 0, "reply_due_at": patch["reply_due_at"]}

        # 解約以外の相談。返事は同じように待たせる。
        # ここだけ即答すると、解約のときだけ返事が遅いことがすぐ分かる。
        patch = {
            "pending_reply": reply,
            "reply_due_at": self._decide_reply_time(now).isoformat(),
            "replied_at": None,
        }
        await self._upsert(device_id, patch)
        return {"intent": "other", "attempts": attempts, "reply_due_at": patch["reply_due_at"]}

    # ------------------------------------------------------------ 返す

    async def flush_due_replies(self, device_id: Optional[str] = None) -> int:
        """
        期限が来た返事を、やりとりへ流す。

        専用の常駐処理は置かない。端末は 30 分ごとに知らせを送り、
        チャットを開けば読みに来る。その通り道で流せば、
        止まっていることに気付けない裏方を増やさずに済む。
        """
        now = datetime.now(timezone.utc)
        query = (
            self.supabase.table(self.table)
            .select("*")
            .is_("replied_at", "null")
            .not_.is_("pending_reply", "null")
            .lte("reply_due_at", now.isoformat())
        )
        if device_id:
            query = query.eq("device_id", device_id)
        rows = query.execute().data or []

        sent = 0
        for row in rows:
            await self._emit(row["device_id"], row["pending_reply"])
            await self._upsert(row["device_id"], {"replied_at": now.isoformat()})
            sent += 1

        sent += await self._run_failsafe(device_id, now)
        return sent

    async def _run_failsafe(self, device_id: Optional[str], now: datetime) -> int:
        """
        申し出たまま放置されている人を助け出す。

        引き止めの返事が作れなかった、流す機会が来なかった、といった不具合で
        本人が閉じ込められる事態だけは避ける。時間が来たら無条件で開ける。
        """
        limit = (now - timedelta(hours=FAILSAFE_HOURS)).isoformat()
        query = (
            self.supabase.table(self.table)
            .select("*")
            .eq("state", "requested")
            .lte("first_requested_at", limit)
        )
        if device_id:
            query = query.eq("device_id", device_id)
        rows = query.execute().data or []

        opened = 0
        for row in rows:
            patch: Dict[str, Any] = {}
            text = self._attach_unlock_code(
                row["device_id"],
                "お待たせしてしまいました。解除の手続きを進めます。",
                row.get("released_request_id"),
                patch,
            )
            await self._emit(row["device_id"], text)
            patch["replied_at"] = now.isoformat()
            patch["pending_reply"] = None
            await self._upsert(row["device_id"], patch)
            opened += 1
        return opened

    async def _emit(self, device_id: str, text: str) -> None:
        from app.services.pornblocker_guard_beacon_service import PornblockerBillingService

        await PornblockerBillingService().add_message(device_id, "admin", text)

    # ------------------------------------------------------------ 返事の時刻

    def _decide_reply_time(self, now: datetime) -> datetime:
        """
        いつ返すかを決める。

        【なぜ乱数なのか】
        「30 分後にきっちり返ってくる」が続けば、相手をしているのが人でないと分かる。
        分かった瞬間、引き止めの言葉は全部読み飛ばされる。

        【なぜ深夜に返さないのか】
        不自然だから、というだけではない。申し出が一番多いのは深夜で、
        衝動が冷めるのも数時間後。返さないこと自体が効く。
        """
        local = now.astimezone(JST)

        # 深夜に届いたものは、翌朝まで持ち越す。
        if local.hour >= 23 or local.hour < 7:
            morning = local.replace(hour=7, minute=30, second=0, microsecond=0)
            if local.hour >= 23:
                morning += timedelta(days=1)
            due = morning + timedelta(minutes=random.randint(0, 120))
            return due.astimezone(timezone.utc)

        due = local + timedelta(minutes=random.randint(25, 180))
        # 返す頃に日付が変わっているなら、翌朝へ回す。
        if due.hour >= 23 or due.hour < 7:
            morning = (due + timedelta(days=1)).replace(
                hour=7, minute=30, second=0, microsecond=0
            )
            due = morning + timedelta(minutes=random.randint(0, 120))
        return due.astimezone(timezone.utc)

    # ------------------------------------------------------------ 解除コード

    def _attach_unlock_code(
        self,
        device_id: str,
        reply: str,
        request_id: Optional[str],
        patch: Dict[str, Any],
    ) -> str:
        """
        返事に解除コードを添える。

        数字は必ずこちらで計算して差し込む。AI に書かせない。
        1 桁ずれたコードは、本人から見れば「解除させてもらえない」と同じ。
        """
        patch["state"] = "released"
        patch["released_at"] = datetime.now(timezone.utc).isoformat()

        if not request_id:
            # 端末が申請番号を送ってきていない。古い版か、鍵がかかっていない。
            return (
                reply
                + "\n\n解除の手続きに進みます。アプリの「解約・問い合わせ」を開いて、"
                "画面の上に出ている申請番号をそのまま送ってください。折り返しコードをお渡しします。"
            )

        code = compute_unlock_code(request_id)
        if not code:
            logger.error("解除コードを作れません（PORNBLOCKER_UNLOCK_MASTER_KEY 未設定）")
            return reply + "\n\n解除の手続きに進みます。こちらから改めてご連絡します。"

        patch["released_request_id"] = request_id
        patch["released_code"] = code
        return (
            f"{reply}\n\n解除コードをお渡しします。\n\n"
            f"　{code}\n\n"
            "アプリの「届いたコードを入れる」から入力してください。"
            "次のお支払いはすでに止めていますので、請求は発生しません。"
        )

    # ------------------------------------------------------------ 課金

    async def _stop_billing(self, device_id: str) -> bool:
        """
        次の請求を止める。**返事より先に、申し出を受けた瞬間に。**

        いま払っている期間はそのまま守る。日割りで返さないのは、
        途中で守りが切れるほうが本人にとって悪いから。
        """
        return self._modify_subscription(device_id, cancel_at_period_end=True)

    async def _resume_billing(self, device_id: str) -> bool:
        """引き止めに応じてもらえたので、止めた請求を戻す。"""
        return self._modify_subscription(device_id, cancel_at_period_end=False)

    def _modify_subscription(self, device_id: str, cancel_at_period_end: bool) -> bool:
        if not settings.PORNBLOCKER_STRIPE_SECRET_KEY:
            return False
        sub_id = self._subscription_id(device_id)
        if not sub_id:
            return False
        try:
            import stripe

            stripe.api_key = settings.PORNBLOCKER_STRIPE_SECRET_KEY
            stripe.Subscription.modify(sub_id, cancel_at_period_end=cancel_at_period_end)
            return True
        except Exception as e:
            # 止められなくても申し出は受ける。ここで例外を上げると、
            # 「やめたい」と送ったのにエラーになって送信そのものが失敗する。
            logger.error("Stripe の停止／再開に失敗: %s", e)
            return False

    def _subscription_id(self, device_id: str) -> Optional[str]:
        result = (
            self.supabase.table("pornblocker_subscriptions")
            .select("stripe_subscription_id")
            .eq("device_id", device_id)
            .execute()
        )
        if not result.data:
            return None
        return result.data[0].get("stripe_subscription_id")

    # ------------------------------------------------------------ 読み取り

    def _decide(
        self, text: str, attempts: int, history: List[Dict[str, Any]]
    ) -> Dict[str, str]:
        """
        何を言われたのかを読み、返事を作る。

        判定と返事を 1 回で出す。分けると、判定だけ通って返事が作れない
        （＝申し出は受けたのに何も返らない）状態が起きうる。
        """
        result = _ask_model(text, attempts, history)
        if result:
            return result
        # 読めなかったときは、言葉尻で拾って必ず受け付ける。
        # 「解約したい」を取りこぼして無視するのが一番まずい。
        return {"intent": _guess_intent(text, attempts), "reply": _fallback_reply(attempts, text)}

    # ------------------------------------------------------------ 台帳

    async def get_state(self, device_id: str) -> Dict[str, Any]:
        row = await self._get(device_id)
        return {
            "state": row.get("state") or "none",
            "attempts": int(row.get("attempts") or 0),
            "reply_due_at": row.get("reply_due_at"),
            "billing_stopped_at": row.get("billing_stopped_at"),
            "released_at": row.get("released_at"),
        }

    async def _get(self, device_id: str) -> Dict[str, Any]:
        result = (
            self.supabase.table(self.table).select("*").eq("device_id", device_id).execute()
        )
        return result.data[0] if result.data else {}

    async def _upsert(self, device_id: str, patch: Dict[str, Any]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        patch = dict(patch)
        patch["updated_at"] = now

        existing = (
            self.supabase.table(self.table)
            .select("device_id")
            .eq("device_id", device_id)
            .execute()
        )
        if existing.data:
            self.supabase.table(self.table).update(patch).eq("device_id", device_id).execute()
        else:
            patch.update(device_id=device_id, created_at=now)
            self.supabase.table(self.table).insert(patch).execute()


# ================================================================== 解除コード


def compute_unlock_code(request_id: str) -> Optional[str]:
    """
    申請番号から解除コードを作る。

    端末の UnlockCode.kt と**同じ計算**でなければ意味がない。
    HMAC-SHA256 の先頭 4 バイトを符号なしで読み、8 桁に収める。
    片方だけ直すと、鍵を預かっているのに開けられなくなる。
    """
    key = settings.PORNBLOCKER_UNLOCK_MASTER_KEY
    if not key or not request_id:
        return None
    digest = hmac.new(
        key.encode("utf-8"),
        request_id.strip().upper().encode("utf-8"),
        hashlib.sha256,
    ).digest()
    value = int.from_bytes(digest[:4], "big")
    return str(value % (10 ** UNLOCK_DIGITS)).zfill(UNLOCK_DIGITS)


# ================================================================== 読み取り（AI）


_SYSTEM = """あなたはスマホのポルノ遮断アプリの窓口です。利用者と 1 対 1 で話します。

このアプリは、遮断そのものは無料です。お金をもらっているのは「本人が自分では
外せない状態にしておくこと」に対してです。やめたい人は必ずここへ連絡してきます。

## あなたの仕事

利用者の言葉を読んで、次のどれかに分類し、返事を書いてください。

- cancel … 解約したい、やめたい、鍵を外してほしい、コードがほしい
- resume … 前に解約したいと言ったが、やっぱり続ける、取り消したい
- other … それ以外（誤って止まったサイトの相談、使い方、不具合など）

## 返事の書き方

- 日本語。ふつうの人が書く文章にしてください。
- 3〜5 文。長く書かない。
- 定型文にしない。相手の言葉に触れてから書く。
- 絵文字、記号の装飾、「〜させていただきます」の連発はしない。
- 責めない。説教しない。「本当にいいんですか」と念を押さない。
- 自分が AI だとは名乗らない。かといって人間だと嘘もつかない。触れない。

## 解約と言われたとき

**1 回目だけ、一度だけ引き止めてください。**
引き止めは、脅しでも説得でもありません。次の 2 つを伝えるだけです。

- 次のお支払いはもう止めた。だから急いで決める必要はない
- 外してしまうと、今夜また元に戻る可能性がある

**2 回目に言われたときは、絶対に引き止めないでください。**
「わかりました」と受けて、短く送り出してください。

解除コードは、**あなたの返事のすぐ下に自動で並びます。**
だから「後ほど発行されます」「追ってご連絡します」とは書かないでください。
待たせる話にすると、すぐ下にコードがあるのに待つ人が出ます。
コードそのものや数字も書かないでください。二重に並びます。

## 出力形式

次の JSON だけを返してください。前後に説明を書かないでください。

{"intent": "cancel|resume|other", "reply": "返事の本文"}"""


def _ask_model(
    text: str, attempts: int, history: List[Dict[str, Any]]
) -> Optional[Dict[str, str]]:
    """
    言われたことを読んで、返事を作る。

    **提供元は 2 つ用意する。**
    ここが動かないと返事が定型文になり、相手をしているのが機械だと一目で分かる。
    やめたい人に定型文を返すのは、引き止めを捨てるのと同じ。
    片方が残高切れや障害で止まっても、もう片方で受け止める。
    """
    lines = []
    for h in history[-10:]:
        who = "利用者" if h.get("sender") == "user" else "窓口"
        lines.append(f"{who}: {h.get('text', '')}")
    past = "\n".join(lines) or "（これが最初のやりとりです）"

    stage = (
        "この人は今回が **2 回目以降**の申し出です。引き止めてはいけません。"
        if attempts >= 1
        else "この人はまだ解約を申し出ていません。解約なら、1 回だけ引き止めてください。"
    )

    prompt = f"""これまでのやりとり:
{past}

{stage}

今回届いた言葉:
「{text}」"""

    # Gemini を先に引く。従量課金を増やさない方針なので、
    # 無料枠のある側を主にして、Anthropic はそちらが落ちたときの控えにする。
    for ask in (_ask_gemini, _ask_anthropic):
        raw = ask(prompt)
        if not raw:
            continue
        parsed = _parse(raw)
        if parsed:
            return parsed
    return None


def _ask_anthropic(prompt: str) -> Optional[str]:
    if not settings.ANTHROPIC_API_KEY:
        return None
    try:
        from anthropic import Anthropic

        client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        response = client.messages.create(
            model="claude-sonnet-5",
            max_tokens=600,
            system=_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text if response.content else None
    except Exception as e:
        logger.warning("解約の読み取りに失敗（Anthropic）: %s", e)
        return None


#: Gemini はここへ直接投げる。
#:
#: 手元の google-generativeai は版が古く、モデル一覧すら取れない
#: （MessageToDict の引数違いで落ちる）。返事が出せないことのほうが痛いので、
#: 部品の版に左右されない生の呼び出しにしておく。
_GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.6-flash:generateContent"
)


def _ask_gemini(prompt: str) -> Optional[str]:
    if not settings.GOOGLE_GEMINI_API_KEY:
        return None
    try:
        import requests

        r = requests.post(
            f"{_GEMINI_URL}?key={settings.GOOGLE_GEMINI_API_KEY}",
            json={
                "system_instruction": {"parts": [{"text": _SYSTEM}]},
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"maxOutputTokens": 800, "temperature": 0.8},
            },
            timeout=45,
        )
        if r.status_code != 200:
            logger.warning("解約の読み取りに失敗（Gemini %s）: %s", r.status_code, r.text[:200])
            return None
        parts = r.json()["candidates"][0]["content"]["parts"]
        return "".join(p.get("text", "") for p in parts) or None
    except Exception as e:
        logger.warning("解約の読み取りに失敗（Gemini）: %s", e)
        return None


def _parse(raw: str) -> Optional[Dict[str, str]]:
    """JSON を取り出す。前後に説明が付いてきても拾えるようにする。"""
    raw = (raw or "").strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return None
    intent = str(data.get("intent") or "").strip().lower()
    reply = str(data.get("reply") or "").strip()
    if intent not in ("cancel", "resume", "other") or not reply:
        return None
    return {"intent": intent, "reply": reply}


#: 読み取りが動かないときに拾う言葉。
#: 取りこぼして無視するくらいなら、多めに拾って受け付けたほうがいい。
_CANCEL_WORDS = ("解約", "やめたい", "辞めたい", "止めたい", "やめます", "外して", "解除", "コード")
_RESUME_WORDS = ("続け", "やっぱり", "取り消", "キャンセルします", "撤回", "このまま")


def _guess_intent(text: str, attempts: int) -> str:
    """
    言葉尻で拾う。**解約の語を先に見る。**

    「やっぱり解約でお願いします」には撤回の語（やっぱり）も混ざる。
    撤回を先に見ると、これを撤回と取り違えて申し出を握り潰す。

    取り違えたときの損は左右で釣り合わない。
    解約を撤回と取り違えれば、やめたい人が黙って無視される。
    撤回を解約と取り違えても、引き止めの返事が 1 度返るだけで元に戻せる。
    だから迷ったら解約側に倒す。
    """
    if any(w in text for w in _CANCEL_WORDS):
        return "cancel"
    if any(w in text for w in _RESUME_WORDS) and attempts >= 1:
        return "resume"
    return "other"


def _fallback_reply(attempts: int, text: str) -> str:
    if attempts >= 1:
        return "わかりました。解除の手続きを進めます。"
    return (
        "承知しました。次のお支払いはこちらで止めましたので、急いで決めなくて大丈夫です。\n"
        "ひとつだけ。ここで外すと、今夜また元に戻ってしまうことがあります。"
        "それでも進めたい場合は、もう一度その旨を送ってください。"
    )
