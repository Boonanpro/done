"""
npm パッケージ自動 install hook (PostToolUse)

ダンが .ts / .tsx / .js / .jsx を Write/Edit した直後、
import している npm パッケージが package.json に無ければ自動で install する。

「Module not found: Can't resolve 'recharts'」のような Next.js dev server の
build-error フリーズを未然に防ぐ。

セキュリティ:
- 既知ホワイトリストに含まれる名前だけ install する
- typo した未知パッケージで悪性ライブラリを引かないようにする
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(r"D:/done")
FRONTEND_DIR = PROJECT_ROOT / "frontend"
PACKAGE_JSON = FRONTEND_DIR / "package.json"

# bare import を抽出: `from "<name>"` `from '<name>'` `require("<name>")`
# scoped (@org/pkg) と subpath (lib/foo) も拾う
IMPORT_RE = re.compile(
    r"""(?:from|require\s*\()\s*['"](?P<name>(?:@[a-z0-9-_]+/)?[a-z0-9-_][a-z0-9-_.]*)(?:/[^'"]*)?['"]"""
)

# 既知の安全なパッケージ。これに無い名前は install しない。
# ※ ここに足したいパッケージがあればこのリストに追記する。
ALLOWED_PACKAGES = {
    # チャート / ビジュアル
    "recharts", "chart.js", "react-chartjs-2", "d3", "victory", "@nivo/core",
    # 日付
    "date-fns", "dayjs", "moment", "luxon",
    # フォーム / バリデーション
    "zod", "react-hook-form", "@hookform/resolvers", "yup", "valibot",
    # アニメ
    "framer-motion", "@motionone/react", "lottie-react", "react-spring",
    # アイコン
    "lucide-react", "react-icons", "@heroicons/react",
    # 状態
    "zustand", "jotai", "valtio", "@tanstack/react-query", "@tanstack/react-table",
    # ルーティング (Next 内では原則不要だが)
    "react-router-dom",
    # マークダウン
    "react-markdown", "remark-gfm", "rehype-raw", "marked", "showdown",
    # コードハイライト
    "react-syntax-highlighter", "highlight.js", "shiki", "prism-react-renderer",
    # ユーティリティ
    "clsx", "tailwind-merge", "class-variance-authority",
    "lodash", "lodash-es", "ramda",
    # HTTP
    "axios", "ky", "ofetch",
    # シリアライズ / 暗号
    "uuid", "nanoid", "ulid",
    # テスト系 (dev だが import 拾う可能性あるので)
    "vitest", "@testing-library/react", "@testing-library/jest-dom",
    # AI / LLM
    "openai", "@anthropic-ai/sdk", "@google/generative-ai",
    # Supabase
    "@supabase/supabase-js", "@supabase/auth-helpers-nextjs",
    # 画像 / メディア
    "sharp", "react-player", "html2canvas", "react-pdf",
    # Drag & drop
    "@dnd-kit/core", "@dnd-kit/sortable", "react-beautiful-dnd",
    # i18n
    "i18next", "react-i18next", "next-i18next",
    # その他 UI
    "sonner", "vaul", "react-resizable-panels", "embla-carousel-react",
    "cmdk", "input-otp", "react-day-picker",
}

# 標準の Next/React/シャドウン関連は package.json にあるはずなので除外
SKIP_NAMES = {
    "react", "react-dom", "next", "tailwindcss", "typescript",
    "@types/react", "@types/node", "@types/react-dom",
    "eslint", "postcss", "autoprefixer",
}


def extract_imports(text: str) -> set[str]:
    found = set()
    for m in IMPORT_RE.finditer(text):
        name = m.group("name")
        # 自前 alias (@/, ~/, ./, ../) は除外
        if name.startswith("@/") or name.startswith("~"):
            continue
        # node 標準 (fs, path 等) は除外
        if name in {"fs", "path", "os", "crypto", "child_process", "stream", "util", "url", "http", "https"}:
            continue
        found.add(name)
    return found


def installed_packages() -> set[str]:
    if not PACKAGE_JSON.exists():
        return set()
    try:
        pkg = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))
    except Exception:
        return set()
    out = set()
    for k in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
        out.update((pkg.get(k) or {}).keys())
    return out


def install(name: str) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            ["npm", "install", name, "--silent", "--no-fund", "--no-audit"],
            cwd=str(FRONTEND_DIR),
            capture_output=True,
            text=True,
            timeout=180,
            shell=True,
        )
    except subprocess.TimeoutExpired:
        return False, f"timeout installing {name}"
    except Exception as e:
        return False, f"install error: {e}"
    if proc.returncode == 0:
        return True, ""
    return False, (proc.stderr or proc.stdout)[-300:]


def main() -> int:
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except Exception:
        return 0

    file_path = data.get("tool_input", {}).get("file_path", "")
    if not file_path or not file_path.endswith((".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")):
        return 0
    try:
        Path(file_path).resolve().relative_to(FRONTEND_DIR.resolve())
    except ValueError:
        return 0

    p = Path(file_path)
    if not p.exists():
        return 0
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return 0

    wanted = extract_imports(text) - SKIP_NAMES
    if not wanted:
        return 0

    have = installed_packages()
    missing = [n for n in wanted if n not in have]
    if not missing:
        return 0

    installable = [n for n in missing if n in ALLOWED_PACKAGES]
    blocked = [n for n in missing if n not in ALLOWED_PACKAGES]

    msgs = []
    if installable:
        for name in installable:
            ok, err = install(name)
            if ok:
                msgs.append(f"[npm auto-install] added: {name}")
            else:
                msgs.append(f"[npm auto-install] FAILED {name}: {err[:200]}")

    if blocked:
        msgs.append(
            "[npm auto-install] BLOCKED (unknown package, install manually if intended): "
            + ", ".join(blocked)
        )

    if msgs:
        sys.stderr.write("\n".join(msgs) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
