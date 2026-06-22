"""成果物の favicon を「自前アイコン」に配線する。

各 ``frontend/src/app/artifacts/<slug>/`` に対して:
  1. アイコン PNG を生成（無ければ）— ensure_artifact_icons
     ``frontend/public/artifacts/<slug>/icon-{192,512}.png`` / ``apple-touch-icon.png``
  2. ``layout.tsx`` の metadata に icons / manifest を **inline** で仕込む
     （salonboard-styleup と同じ実証済み方式。``_seo`` 等への import 依存を作らず
       done-artifacts へ publish しても壊れない）
     - layout が無ければ server layout をテンプレ生成
     - server layout はあるが未配線なら inline 注入
     - ``"use client"`` layout は metadata を export できない。
       layout.tsx を server 化し、クライアント挙動を theme-shell.tsx 等へ
       分離してから配線する必要がある（このスクリプトは client-skip を返すので
       手動対応する。kittoku / yonago-gojo* が対応済みの実例）
     - 既に配線済みならスキップ

使い方:
  python scripts/wire_artifact_icons.py                # 全成果物
  python scripts/wire_artifact_icons.py kittoku paina  # 指定 slug のみ
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.services.artifact_public_assets import ensure_artifact_icons  # noqa: E402

ARTIFACTS_DIR = PROJECT_ROOT / "frontend" / "src" / "app" / "artifacts"


def _pascal(slug: str) -> str:
    return "".join(part.capitalize() for part in re.split(r"[-_]", slug) if part) or "Artifact"


def _icons_block(slug: str, *, include_icons: bool = True, include_manifest: bool = True) -> str:
    """metadata に差し込む icons / manifest ブロック。

    既存の metadata に同名キーがあると `next build` の型チェックが
    「重複プロパティ」で失敗するため、欠けているキーだけを生成する。
    """
    base = f"/artifacts/{slug}"
    out = ""
    if include_icons:
        out += (
            "  icons: {\n"
            "    icon: [\n"
            f"      {{ url: '{base}/icon-192.png', sizes: '192x192', type: 'image/png' }},\n"
            f"      {{ url: '{base}/icon-512.png', sizes: '512x512', type: 'image/png' }},\n"
            "    ],\n"
            f"    apple: '{base}/apple-touch-icon.png',\n"
            "  },\n"
        )
    if include_manifest:
        out += f"  manifest: '{base}/manifest.webmanifest',\n"
    return out


def _new_layout(slug: str) -> str:
    return (
        "import type { Metadata } from 'next';\n\n"
        "export const metadata: Metadata = {\n"
        f"{_icons_block(slug)}"
        "};\n\n"
        f"export default function {_pascal(slug)}Layout({{\n"
        "  children,\n"
        "}: {\n"
        "  children: React.ReactNode;\n"
        "}) {\n"
        "  return children;\n"
        "}\n"
    )


def _is_client(text: str) -> bool:
    head = text.lstrip()
    return head.startswith('"use client"') or head.startswith("'use client'")


def _already_wired(text: str) -> bool:
    return "/icon-192.png" in text or "apple-touch-icon.png" in text


def _ensure_metadata_type_import(text: str) -> str:
    if re.search(r"import\s+type\s+\{[^}]*\bMetadata\b[^}]*\}\s+from\s+['\"]next['\"]", text):
        return text
    return "import type { Metadata } from 'next';\n" + text


def _patch_existing(text: str, slug: str) -> str | None:
    # 既存キーは再生成しない（重複プロパティで next build が失敗するため）
    block = _icons_block(
        slug,
        include_icons="icons:" not in text,
        include_manifest="manifest:" not in text,
    )
    if not block:
        return text  # 追加するものが無い（呼び出し側で no-op 扱い）
    m = re.search(r"export\s+const\s+metadata(?:\s*:\s*[\w.]+)?\s*=\s*\{", text)
    if m:
        insert_pos = m.end()
        return text[:insert_pos] + "\n" + block + text[insert_pos:]

    # metadata export が無い → default export の前に追加
    dm = re.search(r"export\s+default\s+", text)
    meta = "export const metadata: Metadata = {\n" + block + "};\n\n"
    if dm:
        patched = text[: dm.start()] + meta + text[dm.start():]
    else:
        patched = text.rstrip() + "\n\n" + meta
    return _ensure_metadata_type_import(patched)


def wire_slug(slug: str, *, force: bool = False) -> str:
    slug_dir = ARTIFACTS_DIR / slug
    if not slug_dir.is_dir():
        return "missing-dir"

    ensure_artifact_icons(slug, slug.replace("-", " ").replace("_", " "), force=force)

    layout = slug_dir / "layout.tsx"
    if not layout.exists():
        layout.write_text(_new_layout(slug), encoding="utf-8")
        return "created"

    text = layout.read_text(encoding="utf-8")
    if _already_wired(text):
        return "already"
    if _is_client(text):
        # client layout は metadata 不可。ファイル規約 icon.png に任せる。
        return "client-skip"

    patched = _patch_existing(text, slug)
    if not patched or patched == text:
        return "manual-needed"
    layout.write_text(patched, encoding="utf-8")
    return "patched"


def _all_slugs() -> list[str]:
    return [
        p.name
        for p in sorted(ARTIFACTS_DIR.iterdir())
        if p.is_dir()
        and not p.name.startswith("_")
        and p.name not in ("publish",)
        and not (p.name.startswith("[") and p.name.endswith("]"))
        and (p / "page.tsx").exists()
    ]


def main() -> int:
    raw = sys.argv[1:]
    force = "--force" in raw
    slugs = [a for a in raw if a != "--force"] or _all_slugs()
    counts: dict[str, int] = {}
    for slug in slugs:
        status = wire_slug(slug, force=force)
        counts[status] = counts.get(status, 0) + 1
        print(f"{status:>13}  {slug}")
    print("\nsummary:", ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
