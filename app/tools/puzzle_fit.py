"""hCaptcha の「図形をはめる」パズルに、確信が持てる時だけ答える。

誤答は無料ではない。Talon（Epic の hCaptcha ラッパ）は外すたびに警戒を上げ、
次の出題を難しくする。置き場所が分からないまま「一番マシな候補」を出すのは
だから最悪手で、答えずに『更新』で別の問題を引き直す方が期待値が高い。

答えてよいのは次の2つを両方満たした時だけ:

  * 最良候補の形状一致度が ``threshold`` 以上
  * 最良と次点の差が ``margin`` 以上（似た形が並ぶ盤面で外すのを防ぐ）

実測では、一致度 0.93（次点 0.60）の時は突破でき、0.63 の時は「誤った返答が
提供されました」で弾かれた。その境目を毎回の勘ではなく数値で扱うための判定器。

図形を検出できなかった場合も「自信なし」に倒す。答えないことは常に安全側。

座標はすべてスクリーンショット上のピクセルで扱い、実際に掴む直前だけ
``shot_scale`` で CSS ピクセルへ換算する（写真の座標をそのままドラッグに渡すと
掴む位置が図形の外に落ち、図形が1ミリも動かないまま時間切れになる）。
"""
from __future__ import annotations

import asyncio
import base64
import io
import logging
import random
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)

# 答えてよい一致度の下限。0.63 で答えて外し、0.93 で通った実績から引いた線。
MATCH_THRESHOLD = 0.85
# 最良と次点の差。僅差なら「どれか分かっていない」ということなので答えない。
MIN_MARGIN = 0.08
# 引き直しの上限。無限に更新し続けるのもそれ自体が不審な挙動になる。
MAX_REFRESH = 3
# ピースが置かれるトレイ帯の幅（画面幅に対する比）
_TRAY_BAND = 0.22
# 形状比較にかける候補の上限（大きいものから）
_MAX_SHAPES = 24


@dataclass
class Shape:
    area: int
    cx: float
    cy: float
    mask: Any = field(repr=False)


def _to_gray(image_bytes: bytes):
    import numpy as np
    from PIL import Image

    with Image.open(io.BytesIO(image_bytes)) as im:
        return np.asarray(im.convert("L"), dtype=float)


def _shapes(gray) -> list[Shape]:
    """輪郭線で描かれた図形を塊として拾う。

    彩度で分離できない配色（背景がグラデーション、図形は細い白線）が出るので、
    色ではなく勾配を見る。閾値を固定値にすると配色次第で拾いすぎ／拾わなさすぎ
    になるため、勾配の上位数%を輪郭とみなす。
    """
    import numpy as np
    from scipy import ndimage

    edge = ndimage.gaussian_gradient_magnitude(gray, 1.2)
    thr = float(np.percentile(edge, 97.0))
    mask = ndimage.binary_fill_holes(
        ndimage.binary_closing(edge > thr, np.ones((5, 5)))
    )
    lab, n = ndimage.label(mask)
    min_area = max(400, int(gray.size * 0.0004))
    out: list[Shape] = []
    for i in range(1, n + 1):
        m = lab == i
        a = int(m.sum())
        if a < min_area or a > gray.size * 0.2:
            continue
        ys, xs = np.where(m)
        h = ys.max() - ys.min() + 1
        w = xs.max() - xs.min() + 1
        if not (0.35 < w / h < 2.8):
            continue  # 罫線やパネルの縁を拾ったもの
        out.append(Shape(area=a, cx=float(xs.mean()), cy=float(ys.mean()), mask=m))
    out.sort(key=lambda s: -s.area)
    return out[:_MAX_SHAPES]


def _crop(mask):
    import numpy as np

    ys, xs = np.where(mask)
    return mask[ys.min(): ys.max() + 1, xs.min(): xs.max() + 1]


def _center_pad(m, h: int, w: int):
    import numpy as np

    out = np.zeros((h, w), dtype=bool)
    y0 = (h - m.shape[0]) // 2
    x0 = (w - m.shape[1]) // 2
    out[y0: y0 + m.shape[0], x0: x0 + m.shape[1]] = m
    return out


def shape_iou(a, b) -> float:
    """2つの図形の重なり具合（0〜1）。

    大きさを揃えずに中心だけ合わせて比較する。はめ込みパズルではピースと穴の
    寸法が一致するはずなので、スケールを正規化すると「形は似ているがサイズが
    違う」誤答候補を弾けなくなる。
    """
    ca, cb = _crop(a), _crop(b)
    h = max(ca.shape[0], cb.shape[0])
    w = max(ca.shape[1], cb.shape[1])
    pa, pb = _center_pad(ca, h, w), _center_pad(cb, h, w)
    union = int((pa | pb).sum())
    if not union:
        return 0.0
    return float(int((pa & pb).sum()) / union)


def evaluate(
    image_bytes: bytes,
    threshold: float = MATCH_THRESHOLD,
    margin: float = MIN_MARGIN,
) -> dict[str, Any]:
    """スクショ1枚を見て「答えてよいか」を判定する。

    Returns:
        confident が True の時だけ from/to が入る。False の時は reason に
        答えない理由が入る。
    """
    try:
        gray = _to_gray(image_bytes)
    except Exception as exc:  # 画像が壊れている等
        return {"confident": False, "reason": f"画像を読めませんでした: {exc}"}

    height, width = gray.shape
    shapes = _shapes(gray)
    if len(shapes) < 2:
        return {
            "confident": False,
            "reason": f"図形を検出できませんでした（検出数 {len(shapes)}）",
            "detected": len(shapes),
        }

    band = width * _TRAY_BAND
    tray = [s for s in shapes if s.cx < band or s.cx > width - band]
    if not tray:
        return {
            "confident": False,
            "reason": "運ぶ図形（トレイ側）が見つかりませんでした",
            "detected": len(shapes),
        }
    piece = max(tray, key=lambda s: s.area)

    candidates = [
        s for s in shapes
        if s is not piece and 0.3 * piece.area < s.area < 3.3 * piece.area
    ]
    if not candidates:
        return {
            "confident": False,
            "reason": "置き場所の候補が見つかりませんでした",
            "detected": len(shapes),
        }

    scored = sorted(
        ((shape_iou(piece.mask, s.mask), s) for s in candidates),
        key=lambda t: -t[0],
    )
    best_score, best = scored[0]
    runner_up = scored[1][0] if len(scored) > 1 else 0.0
    confident = best_score >= threshold and (best_score - runner_up) >= margin

    result: dict[str, Any] = {
        "confident": confident,
        "score": round(best_score, 3),
        "runner_up": round(runner_up, 3),
        "threshold": threshold,
        "margin": margin,
        "detected": len(shapes),
        "candidates": len(candidates),
        "from": {"x": round(piece.cx), "y": round(piece.cy)},
        "to": {"x": round(best.cx), "y": round(best.cy)},
    }
    if not confident:
        if best_score < threshold:
            result["reason"] = (
                f"一致度 {best_score:.2f} が閾値 {threshold:.2f} に届きません"
            )
        else:
            result["reason"] = (
                f"最良 {best_score:.2f} と次点 {runner_up:.2f} が僅差で、"
                "どの位置か絞り込めていません"
            )
        result.pop("from", None)
        result.pop("to", None)
    return result


_REFRESH_JS = r"""
() => {
  // hCaptcha の「更新（別の問題を引く）」ボタン。表記もクラスもバージョンで
  // 変わるので、当たりそうなものを順に探して最初に見つかった可視要素を返す。
  const sels = ['.refresh', '.button-refresh', '.refresh-button',
                '[aria-label*="challenge" i]', '[aria-label*="更新"]',
                '[title*="更新"]', '[title*="new challenge" i]',
                '[class*="refresh" i]'];
  for (const s of sels) {
    for (const el of document.querySelectorAll(s)) {
      const r = el.getBoundingClientRect();
      if (r.width > 4 && r.height > 4) {
        return {x: r.x + r.width / 2, y: r.y + r.height / 2};
      }
    }
  }
  return null;
}
"""

_IFRAME_RECTS_JS = r"""
() => Array.from(document.querySelectorAll('iframe')).map(f => {
  const r = f.getBoundingClientRect();
  return {src: f.src || '', x: r.x, y: r.y, w: r.width, h: r.height};
})
"""


async def refresh_challenge(page) -> bool:
    """パズルの『更新』を押して別の問題を引く。

    ボタンは hCaptcha の iframe の中にあるので、フレーム内座標にその iframe の
    ページ上の位置を足してから押す。ページ側の座標をそのまま押すと、背後の
    ログインボタンを誤爆する。
    """
    from app.tools.human_pointer import HumanPointer

    try:
        frames = await page.get_frames()
    except Exception as exc:
        logger.warning("更新ボタン: フレーム一覧を取れません: %s", exc)
        return False

    try:
        rects = await page.evaluate(_IFRAME_RECTS_JS) or []
    except Exception:
        rects = []

    for frame in frames:
        url = getattr(frame, "url", "") or ""
        if "hcaptcha" not in url or "checkbox" in url:
            continue
        try:
            spot = await frame.evaluate(_REFRESH_JS)
        except Exception:
            continue
        if not spot:
            continue
        off_x = off_y = 0.0
        for r in rects:
            src = r.get("src") or ""
            if src and (src in url or url in src):
                off_x, off_y = float(r["x"]), float(r["y"])
                break
        pointer = HumanPointer(page)
        await pointer.click(off_x + float(spot["x"]), off_y + float(spot["y"]))
        logger.info("パズルを更新しました（%s）", url[:60])
        return True

    logger.info("更新ボタンが見つかりませんでした")
    return False


async def solve_shape_puzzle(
    page,
    threshold: float = MATCH_THRESHOLD,
    margin: float = MIN_MARGIN,
    max_refresh: int = MAX_REFRESH,
) -> dict[str, Any]:
    """確信が持てる問題に当たるまで引き直し、当たったらドラッグして答える。

    撮影から判定・操作までを1回の呼び出しで終わらせる。人の目で見ながら
    座標を計算していると、調べている間にチャレンジ側が時間切れになって
    最初からやり直しになるため。
    """
    from app.tools.browser import get_last_shot_scale

    from app.tools.human_pointer import HumanPointer

    tries: list[dict[str, Any]] = []
    for attempt in range(max_refresh + 1):
        shot = await page.screenshot_base64()
        if isinstance(shot, dict):
            b64 = shot.get("base64", "")
            scale = float(shot.get("shot_scale") or 0)
        else:
            b64, scale = shot, 0.0
        scale = scale or get_last_shot_scale() or 1.0

        verdict = evaluate(base64.b64decode(b64), threshold=threshold, margin=margin)
        tries.append({
            "attempt": attempt + 1,
            "score": verdict.get("score"),
            "runner_up": verdict.get("runner_up"),
            "confident": verdict["confident"],
            "reason": verdict.get("reason"),
        })
        logger.info("パズル判定 %d回目: %s", attempt + 1, tries[-1])

        if verdict["confident"]:
            src, dst = verdict["from"], verdict["to"]
            pointer = HumanPointer(page)
            await pointer.drag(
                src["x"] / scale, src["y"] / scale,
                dst["x"] / scale, dst["y"] / scale,
            )
            return {
                "answered": True,
                "score": verdict["score"],
                "runner_up": verdict["runner_up"],
                "from": src,
                "to": dst,
                "scale": round(scale, 3),
                "attempts": tries,
            }

        if attempt >= max_refresh:
            break
        if not await refresh_challenge(page):
            return {
                "answered": False,
                "reason": (verdict.get("reason") or "自信なし")
                + "。更新ボタンが見つからないため引き直せませんでした",
                "attempts": tries,
            }
        # 押した直後に撮ると前の問題が写る。差し替わるのを待つ。
        await asyncio.sleep(random.uniform(1.6, 2.8))

    return {
        "answered": False,
        "reason": (
            f"{len(tries)}問すべてで確信が持てなかったため答えていません"
            f"（最後の理由: {tries[-1].get('reason') if tries else '不明'}）"
        ),
        "attempts": tries,
    }
