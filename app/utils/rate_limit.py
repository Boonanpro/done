"""
短時間に何度も叩かれたら弾く（スライディングウィンドウ）。

【なぜ要るか】
ログインを持たない入口が実際にある。ポルノブロッカーの端末側がそれで、
アプリに焼き付けた合言葉ひとつで通している（端末にログインを持たせると、
ログインが切れた端末から知らせが来なくなる。それこそ避けたい事態のため）。

合言葉ひとつということは、総当たりで当てられる余地が残る。当てられた後も、
端末の呼び名（device_id）を総当たりすれば他人の契約状態や連絡を覗ける。
どちらも「1 回あたり」は防げないが、「短時間に何度も」は防げる。ここがそれ。

【IP で数えるか、相手ごとに数えるか】
正規の利用者を巻き込まない方を選ぶ。携帯回線は多数の契約者が同じ IP を
共有する（CGNAT）ので、IP だけで厳しく数えると無関係の契約者が弾かれる。
だから通常の利用は相手ごと（device_id 等）に数え、IP で厳しく数えるのは
**合言葉を間違えた回数**に絞る。正規の端末は合言葉を間違えない。

【プロセス内で持つ理由】
数え方を DB に置くと、弾くべき相手に叩かれるほど DB が重くなる。
守るために置いた仕組みが、攻める側の道具になっては本末転倒。
プロセスが増えたら 1 台あたりの上限が実質緩むが、桁は変わらない。
"""
from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Deque, Dict, Optional

from fastapi import HTTPException, Request

#: 覚えておく相手の数の上限。
#:
#: 上限を置かないと、IP を変えながら叩かれるだけで記憶が際限なく膨らむ。
#: 弾いているつもりで、こちらのメモリを食い潰される。
MAX_TRACKED_KEYS = 20_000


def client_ip(request: Request) -> str:
    """
    どの回線から来たか。

    手前にプロキシが立つので、素の接続元だけを見ると全員が同じに見える。
    x-forwarded-for の先頭が、いちばん外側の相手。
    """
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


class SlidingWindowLimiter:
    """
    直近 `window_seconds` 秒のうちに `max_requests` 回まで通す。

    `block_seconds` を指定すると、超えた相手をその秒数だけ締め出す。
    合言葉の総当たりのように「1 回超えた時点で相手が正規でないと分かる」
    ものに使う。通常利用の制限では指定しない（正規の利用者が
    たまたま混み合っただけで長時間締め出されると、ただの故障になる）。
    """

    def __init__(
        self,
        max_requests: int,
        window_seconds: int,
        block_seconds: int = 0,
        detail: str = "回数の上限に達しました。しばらく待ってからお試しください。",
    ):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.block_seconds = block_seconds
        self.detail = detail
        self._history: Dict[str, Deque[float]] = defaultdict(deque)
        self._blocked_until: Dict[str, float] = {}

    # ------------------------------------------------------------ 使う側

    def check(self, key: str) -> None:
        """数えたうえで判定する。通常はこれ 1 つでよい。"""
        self.peek(key)
        self.hit(key)

    def peek(self, key: str) -> None:
        """
        判定だけする（数えない）。

        「認証に失敗した回数」のように、**失敗したときだけ数えたい**場合に使う。
        入口では peek で締め出し中かを見て、失敗が確定してから hit を呼ぶ。
        """
        now = time.time()
        until = self._blocked_until.get(key)
        if until and until > now:
            raise self._too_many(int(until - now) + 1)
        if until:
            del self._blocked_until[key]

        hist = self._trim(key, now)
        if len(hist) >= self.max_requests:
            if self.block_seconds:
                self._blocked_until[key] = now + self.block_seconds
                raise self._too_many(self.block_seconds)
            raise self._too_many(int(self.window_seconds - (now - hist[0])) + 1)

    def hit(self, key: str) -> None:
        """1 回ぶん数える。"""
        now = time.time()
        self._trim(key, now).append(now)
        self._evict(now)

    def reset(self, key: str) -> None:
        """数えた分を忘れる。試験と、手で解除するとき用。"""
        self._history.pop(key, None)
        self._blocked_until.pop(key, None)

    # ------------------------------------------------------------ 内部

    def _trim(self, key: str, now: float) -> Deque[float]:
        hist = self._history[key]
        cutoff = now - self.window_seconds
        while hist and hist[0] < cutoff:
            hist.popleft()
        return hist

    def _too_many(self, retry_after: int) -> HTTPException:
        return HTTPException(
            status_code=429,
            detail=self.detail,
            headers={"Retry-After": str(max(1, retry_after))},
        )

    def _evict(self, now: float) -> None:
        """
        古い記録を捨てる。

        毎回まるごと走査すると、叩かれるほど遅くなる。だから
        上限を超えたときだけ動かす。
        """
        if len(self._history) <= MAX_TRACKED_KEYS:
            return

        cutoff = now - self.window_seconds
        for key in [k for k, h in self._history.items() if not h or h[-1] < cutoff]:
            del self._history[key]

        # 全部が窓の中でも、上限は守る。古い順に半分捨てる。
        if len(self._history) > MAX_TRACKED_KEYS:
            ordered = sorted(
                self._history.items(), key=lambda kv: kv[1][-1] if kv[1] else 0.0
            )
            for key, _ in ordered[: len(ordered) // 2]:
                del self._history[key]

        for key, until in list(self._blocked_until.items()):
            if until <= now:
                del self._blocked_until[key]


def retry_after_of(exc: HTTPException) -> Optional[str]:
    """429 に添えた待ち時間。試験で確かめるため。"""
    return (exc.headers or {}).get("Retry-After")
