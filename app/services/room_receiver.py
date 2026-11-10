"""A notice that wakes a room (a watch, a contact that came in, a follow-up Dan scheduled) never stops the work the owner
asked for in that room.

Why (2026-11-10): while Dan rewrote 中村さん's launch script in the room, an hourly watch woke the room twice and each wake
stopped the running turn ("[Request interrupted by user]"); five Chatwork notices then woke the room one at a time. The
poller in the shared core only looked at its own process for a running turn, so a turn in the release core looked idle,
and the release took the wake as the owner's follow-up, which interrupts. 本人の決め: 作業中は受ける係を別に起こし、作業中の
ダンは止めない。続けて来た連絡はまとめて読む。作業の前提が変わる連絡だけ作業中のダンに伝える。作業していない時は今までどおり。

Every path that wakes a room for something that is not the owner's own message asks lane() first:
- 'turn'     the room is idle: the wake is a turn of the room, as before (held in background() while it runs).
- 'wait'     the room is running such a background turn: the wake waits for it (the caller retries).
- 'receiver' the room is running the owner's work: the wake goes to the room's receiver (hand_over), a parallel job
             branched off the room's conversation whose answer is posted in the room as Dan's message. One receiver per
             room at a time; notices that come while it runs are added to it, so a burst is read together.
"""
from __future__ import annotations

import asyncio
import logging
import shlex
import sys
import time
from contextlib import contextmanager

logger = logging.getLogger(__name__)

# Turns this process started in a room for a notice (not the owner's message), room -> start time. The pollers and the
# inbox that wake rooms all run in the shared core, so a process-local table is enough.
_background: dict[str, float] = {}
_lock = asyncio.Lock()

TITLE = '作業中に届いた知らせ'


@contextmanager
def background(room_id):
    _background[room_id] = time.time()
    try:
        yield
    finally:
        _background.pop(room_id, None)


async def lane(room_id):
    from app.services.work_continuity import room_busy
    if not await room_busy(room_id):
        return 'turn'
    return 'wait' if room_id in _background else 'receiver'


async def wait_turn(room_id, limit=600):
    """Wait while the room runs another background turn; the lane once it is not 'wait' (or 'wait' after limit)."""
    deadline = time.monotonic() + limit
    current = await lane(room_id)
    while current == 'wait' and time.monotonic() < deadline:
        await asyncio.sleep(5)
        current = await lane(room_id)
    return current


def tell_command(room_id):
    from app.paths import DONE_ROOT
    return shlex.join([sys.executable, str(DONE_ROOT / 'scripts' / 'tell_room_work.py'), '--room', room_id])


def rules(room_id):
    return f"""## この作業について（作業中に届いた知らせの受け口）
部屋のダンは今、本人に頼まれた作業の途中。その作業を止めないために、作業中に届いた知らせ（相手からの連絡・見張りの定刻・予約した続報）をここで受ける。
- 今の作業が何かは、この部屋の会話の最後の方（本人の最新の依頼）で分かる。その作業が書いているファイル・ドキュメント・画面には触らない。
- 知らせに書かれた手順どおりに、必要な作業をする。最後の返事は、そのまま部屋のダンの発言として本人の部屋に出る。本人に伝えることが無い時は、返事を正確に「WATCH_NO_CHANGE」とだけ書く（何も出ない）。
- 途中で知らせが追加で届くことがある（追加の発言として届く）。続けて届いた分はまとめて読み、本人への報告は最後に1つにまとめる。1通ごとに報告しない。
- 届いた知らせで、作業中のダンが進めている作業の前提が変わる時だけ（相手が中身・方向・締め切り・使ってよい物を変えた、本人の依頼と食い違う事実が分かった、など）、次のコマンドで作業中のダンに伝える。標準入力で本文を渡す。何が変わったか・どこに書いてあるかを2〜4行で。迷ったら伝える。前提が変わらない知らせ（お礼・了解・日程・別の件・見張りの定刻）は伝えない。
  {tell_command(room_id)}

## 届いた知らせ
"""


def _active_receiver(room_id, user_id):
    from app.services import command_job_state as state
    if not state.ROOT.exists():
        return None
    for p in state.ROOT.glob('*.json'):
        s = state.read(p.stem)
        if (s and s.get('receiver') and s.get('room_id') == room_id and s.get('user_id') == user_id
                and s.get('state') not in state.TERMINAL):
            return s
    return None


async def hand_over(room_id, user_id, prompt):
    """Give a notice to the room's receiver (started when there is none). Returns the job id."""
    from app.services import parallel_job_runner
    async with _lock:
        current = await asyncio.to_thread(_active_receiver, room_id, user_id)
        if current:
            await parallel_job_runner.control(room_id, user_id, current['id'], 'update',
                                              '[続けて届いた知らせ]\n' + prompt)
            logger.info('[receiver] room=%s notice added to %s', room_id[:8], current['id'])
            return current['id']
        s = await parallel_job_runner.start(room_id, user_id, rules(room_id) + prompt, title=TITLE, receiver=True)
        logger.info('[receiver] room=%s busy with the owner\'s work: notice -> %s', room_id[:8], s['id'])
        return s['id']
