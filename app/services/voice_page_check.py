"""A page is checked against what the owner asked for before the call's screen shows it (2026-11-03).

Why: in the 13:35 call the owner asked for 「百キロぐらいの重り」 and the backend, which had read the pages, showed a 40 kg set,
then on 「これ四十キロじゃん」 a sold-out page. The check that a candidate fits the conditions and can be bought belongs to
the tool that shows it, not to the backend's memory of what it read: a page that does not fit is not shown, and the backend
gets the reason and looks for another one.

The judge is the stage's fast model (voice_stage.ask_model, about a second). A failed check never blocks the page.
"""
import asyncio

TIMEOUT_S = 6.0

SYSTEM = """あなたは、通話中の本人の画面にウェブのページを出す前に、そのページが本人の条件に合うかを確かめる係です。
入力は、本人がこの会話で言った条件（無いこともある）と、ページの本文です。
- 条件の1つでも、ページの本文と食い違っていれば fits=false（例: 条件が100kgなのに40kgのセット、予算5万円なのに6万円）。
- 商品・予約・チケットのページで、売り切れ・在庫なし・販売終了・入荷待ち・受付終了と書かれていれば、条件に関係なく fits=false。
- 本文から確かめられない条件は、合わないとはしない（fits=true のまま、reason にどれが未確認かを書く）。
- facts には、条件に関わるページの事実（商品名・重さや量・値段・在庫）を1〜2文で。本文に無い事を書かない。
JSON だけを返す: {"fits": true|false, "reason": "合わない・未確認の点を短く（合っていれば空）", "facts": "..."}"""


async def check(page_text, conditions, ask=None):
    """{'fits', 'reason', 'facts'} for a page; None when it could not be judged (the page is shown as before)."""
    text = (page_text or '').strip()
    if len(text) < 80:
        return None
    if ask is None:
        from app.services.voice_stage import ask_model as ask
    user = ('本人の条件: ' + (conditions.strip() or '（特に言っていない）') + chr(10) * 2 + 'ページの本文:' + chr(10) + text[:7000])
    try:
        data, _ = await asyncio.wait_for(ask(SYSTEM, user), TIMEOUT_S)
    except Exception:
        return None
    if not isinstance(data, dict) or not isinstance(data.get('fits'), bool):
        return None
    return {'fits': data['fits'], 'reason': str(data.get('reason') or '')[:300], 'facts': str(data.get('facts') or '')[:400]}
