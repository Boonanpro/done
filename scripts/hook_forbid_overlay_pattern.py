"""
overlay div / background-image div 禁止 hook (PostToolUse)

dan が `.tsx` を Write/Edit した直後に、build SKILL.md のルール 4
「ヒーロー画像/動画は <HeroMedia> を使う」に違反するパターンを検出して警告する。

検出パターン:
1. <img>/<video> と兄弟の <div className="absolute inset-0 ..."> (overlay div)
2. <div style="backgroundImage" or className="bg-[url(..)]"> (背景画像 div)

検出時は stderr に警告 + dan のターン中に「修正しろ」と気づかせる。
ファイルの書き込み自体は阻止しない (PostToolUse なので) が、warning が dan の
context に流れ込んで次のステップで自動修正されることを期待する設計。

stdin から JSON: { "tool_input": { "file_path": "..." } }
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(r"D:/done")
FRONTEND_DIR = PROJECT_ROOT / "frontend" / "src"

# ---- 検出ヘルパ ---------------------------------------------------------

def _strip_strings_and_comments(text: str) -> str:
    """文字列リテラルとコメントを潰す (誤検出防止)。雑だが概ね十分。"""
    # ブロックコメント
    text = re.sub(r"/\*[\s\S]*?\*/", "", text)
    # 行コメント
    text = re.sub(r"^\s*//.*$", "", text, flags=re.M)
    return text


def detect_background_image_divs(text: str) -> list[str]:
    """<div style={{ backgroundImage: 'url(...)' }} ...> パターンを拾う。"""
    hits = []
    # JSX inline style style={{ backgroundImage: "url(...)" }}
    pattern = re.compile(
        r"<(?:div|section|figure)\b[^>]*\bstyle\s*=\s*\{\{[^}]*backgroundImage\s*:[^}]*\}\}",
        re.I | re.S,
    )
    for m in pattern.finditer(text):
        snippet = m.group(0)[:140].replace("\n", " ")
        hits.append(snippet)
    # Tailwind-arbitrary bg-[url(...)] パターン
    pattern2 = re.compile(
        r"<(?:div|section|figure)\b[^>]*className\s*=\s*[\"`'][^\"`']*\bbg-\[url\(",
        re.I,
    )
    for m in pattern2.finditer(text):
        snippet = m.group(0)[:140].replace("\n", " ")
        hits.append(snippet)
    return hits


def detect_media_with_overlay_siblings(text: str) -> list[str]:
    """<img>/<video> + 兄弟 <div absolute inset-0 ...> パターンを拾う。

    ざっくり: 同じ <section>/<div> の中に
      - 'absolute inset-0' を持つ <img> or <video>
      - 'absolute inset-0' を持つ <div> (pointer-events-none 無し)
    が両方ある場合に検出する。
    """
    hits = []
    # 兄弟関係の厳密検出は AST 必要だが、ここではざっくり同じブロック内に
    # <img/video absolute inset-0> と <div absolute inset-0 ...> が両方あるかで判定
    # ブロック単位 = <section ...> ... </section> の塊
    block_pattern = re.compile(
        r"<(section|div|main|header|article)\b[^>]*>([\s\S]*?)</\1>",
        re.I,
    )
    media_pattern = re.compile(
        r"<(?:img|video)\b[^>]*\b(?:className|class)\s*=\s*[\"`'][^\"`']*absolute[^\"`']*inset-0",
        re.I,
    )
    overlay_pattern = re.compile(
        r"<div\b[^>]*\b(?:className|class)\s*=\s*[\"`'](?P<cls>[^\"`']*absolute[^\"`']*inset-0[^\"`']*)[\"`']",
        re.I,
    )

    for block_match in block_pattern.finditer(text):
        block = block_match.group(2)
        if not media_pattern.search(block):
            continue
        for ov in overlay_pattern.finditer(block):
            cls = ov.group("cls")
            # pointer-events-none があれば許可
            if "pointer-events-none" in cls or "pointer-events:none" in cls:
                continue
            snippet = ov.group(0)[:140].replace("\n", " ")
            hits.append(snippet)

    return hits


# ---- メイン -------------------------------------------------------------

def main() -> int:
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except Exception:
        return 0

    file_path = data.get("tool_input", {}).get("file_path", "")
    if not file_path or not file_path.endswith((".tsx", ".jsx")):
        return 0

    # frontend/src/ 配下のみ対象
    try:
        Path(file_path).resolve().relative_to(FRONTEND_DIR.resolve())
    except ValueError:
        return 0

    p = Path(file_path)
    if not p.exists():
        return 0
    try:
        raw = p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return 0

    # template ファイル本体は対象外 (HeroMedia 等の実装そのもの)
    if "components/templates/hero-media" in file_path.replace("\\", "/"):
        return 0

    text = _strip_strings_and_comments(raw)

    bg_hits = detect_background_image_divs(text)
    overlay_hits = detect_media_with_overlay_siblings(text)

    if not bg_hits and not overlay_hits:
        return 0

    rel = file_path.replace(str(PROJECT_ROOT), "").replace("\\", "/").lstrip("/")
    msgs = [f"[forbid-overlay] build SKILL.md ルール 4 違反検出: {rel}"]
    if bg_hits:
        msgs.append("  ❌ background-image を持つ div を検出 (代わりに <HeroMedia kind='image'> or <img> を使う):")
        for h in bg_hits[:3]:
            msgs.append(f"    {h}")
    if overlay_hits:
        msgs.append("  ❌ <img>/<video> の上に重ねた overlay div を検出 (<HeroMedia darken={N} blur={N} fade='left'>) を使う、もしくは pointer-events-none を付ける):")
        for h in overlay_hits[:3]:
            msgs.append(f"    {h}")
    msgs.append("  → import { HeroMedia } from '@/components/templates' で書き直してください。")

    sys.stderr.write("\n".join(msgs) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
