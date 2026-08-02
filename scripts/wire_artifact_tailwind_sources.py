#!/usr/bin/env python
"""成果物ディレクトリを Tailwind のスキャン対象に載せる。

## なぜ必要か

`frontend/src/app/artifacts/<slug>/` は .gitignore で
`/frontend/src/app/artifacts/*/` として除外されている（成果物は done-artifacts 側で
管理するため）。Tailwind v4 の自動ソース検出は .gitignore を尊重するので、
成果物の中でしか使っていないクラス（arbitrary値・珍しい variant）は
**一切コンパイルされず、指定したレイアウトが無言で無視される**。

`@source "./artifacts/**/*.tsx"` のように artifacts/ を起点にした glob でも直らない。
walker が `artifacts/` を走査する途中で ignore 対象の `<slug>/` に当たり、そこで
枝刈りされるため。**glob の起点を `<slug>/` の内側にする**と ignore 判定が効かず
スキャンされる（検証済み: Tailwind 4.1.18）。

そこで slug ごとに 1 行ずつ `@source` を書き出す。
`hook_register_artifact.py` から呼ばれるので、新しい成果物を作れば自動で追随する。

手動実行:
    python scripts/wire_artifact_tailwind_sources.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS_DIR = ROOT / "frontend" / "src" / "app" / "artifacts"
OUT_FILE = ROOT / "frontend" / "src" / "app" / "artifact-sources.css"

HEADER = """/* 自動生成 — 直接編集しないこと。
 * 生成元: scripts/wire_artifact_tailwind_sources.py
 *
 * 成果物ディレクトリは .gitignore で除外されており、Tailwind v4 の自動ソース検出
 * （.gitignore を尊重する）から漏れる。artifacts/ を起点にした glob では walker が
 * ignore 対象の <slug>/ で枝刈りされるため効かない。glob の起点を <slug>/ の内側に
 * 置くと ignore 判定を回避できるので、slug ごとに 1 行ずつ列挙する。
 */
"""


GLOB_META = set("[]*?")
SOURCE_EXTS = {".ts", ".tsx", ".js", ".jsx", ".mdx"}


def build_lines() -> list[str]:
    if not ARTIFACTS_DIR.is_dir():
        return []
    lines: list[str] = []
    for d in sorted(ARTIFACTS_DIR.iterdir(), key=lambda p: p.name):
        if not d.is_dir() or d.name.startswith((".", "_")):
            continue
        # Next.js の動的ルート (`[slug]` 等) はディレクトリ名に glob のメタ文字を含む。
        # glob として解釈されて別物にマッチするので、その場合はファイルを直接列挙する。
        if GLOB_META & set(d.name):
            for f in sorted(d.rglob("*")):
                if f.is_file() and f.suffix in SOURCE_EXTS:
                    rel = f.relative_to(ARTIFACTS_DIR).as_posix()
                    lines.append(f'@source "./artifacts/{rel}";')
        else:
            lines.append(f'@source "./artifacts/{d.name}/**/*.{{ts,tsx,js,jsx,mdx}}";')
    return lines


def wire() -> str:
    """artifact-sources.css を再生成する。戻り値は 'updated' / 'unchanged'。"""
    lines = build_lines()
    content = HEADER + ("\n".join(lines) + "\n" if lines else "")
    if OUT_FILE.exists() and OUT_FILE.read_text(encoding="utf-8") == content:
        return "unchanged"
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(content, encoding="utf-8")
    return "updated"


def main() -> int:
    status = wire()
    print(f"[artifact tailwind sources] {status}: {len(build_lines())} slug(s) -> {OUT_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
