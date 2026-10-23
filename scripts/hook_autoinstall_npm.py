"""
npm パッケージ自動 install hook (PostToolUse)

ダンが .ts / .tsx / .js / .jsx を Write/Edit した直後、
import している npm パッケージが package.json に無ければ自動で install する。

「Module not found: Can't resolve 'recharts'」のような Next.js dev server の
build-error フリーズを未然に防ぐ。

セキュリティ:
- 既知ホワイトリストに含まれる名前だけ install する
- typo した未知パッケージで悪性ライブラリを引かないようにする

どこに入れるか（2026-10-23）:
- 作業場所（/Users/mikihonda/dan-workspace/<名前>）の frontend: 普通に `npm install <名前>`。package.json に残り、
  ship で本番に入る。node_modules は作業場所ごとの複製（scripts/work.py new）なので、本番には届かない。
- 動いているダン（/Users/mikihonda/done）の frontend（成果物が使う物）: package.json は git が追うので変えない。
  代わりに git が追わない `frontend/.artifact-packages.json` に名前を残し、npm にはそこにある全部を毎回
  まとめて渡す（`npm install --no-save A B C`）。npm は名前を渡されなかった --no-save の物を次の install で
  消すので、まとめて渡さないと前に入れた物が消える。follow_github が package.json の変更を取り込む時も
  install_live() を通るので、そこでも消えない。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from follow_github import live_root  # noqa: E402

PROJECT_ROOT = live_root()
FRONTEND_DIR = PROJECT_ROOT / "frontend"
PACKAGE_JSON = FRONTEND_DIR / "package.json"
NO_SAVE = False  # set per call: True when the edited file is in the running folder
ARTIFACT_PACKAGES = ".artifact-packages.json"

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
    """Named in package.json, or the artifacts' list, or actually present in node_modules."""
    out = set(artifact_packages(FRONTEND_DIR))
    if PACKAGE_JSON.exists():
        try:
            pkg = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))
            for k in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
                out.update((pkg.get(k) or {}).keys())
        except Exception:
            pass
    return out


def _present(front: Path, name: str) -> bool:
    return (front / "node_modules" / name / "package.json").is_file()


def artifact_packages(front: Path) -> list[str]:
    try:
        names = json.loads((Path(front) / ARTIFACT_PACKAGES).read_text(encoding="utf-8"))
        return sorted({n for n in names if isinstance(n, str) and n in ALLOWED_PACKAGES})
    except Exception:
        return []


def _npm(front: Path, args: list[str]) -> tuple[bool, str]:
    try:
        proc = subprocess.run(["npm", *args, "--silent", "--no-fund", "--no-audit"], cwd=str(front),
                              capture_output=True, text=True, timeout=600, shell=(os.name == "nt"))
    except subprocess.TimeoutExpired:
        return False, "timeout"
    except Exception as e:  # noqa: BLE001
        return False, f"install error: {e}"
    return (True, "") if proc.returncode == 0 else (False, (proc.stderr or proc.stdout)[-300:])


def install_live(front: Path, add: list[str] = ()) -> tuple[bool, str]:
    """The running folder's frontend: package.json as committed plus every package artifacts asked for, in one npm
    call, so that none of them is pruned. New names are recorded in .artifact-packages.json first."""
    front = Path(front)
    names = sorted(set(artifact_packages(front)) | {n for n in add if n in ALLOWED_PACKAGES})
    if add:
        tmp = front / (ARTIFACT_PACKAGES + ".tmp")
        tmp.write_text(json.dumps(names, indent=1) + "\n", encoding="utf-8")
        os.replace(tmp, front / ARTIFACT_PACKAGES)
    ok, err = _npm(front, ["install", "--no-save", *names])
    if not ok:
        return False, err
    gone = [n for n in names if not _present(front, n)]
    return (False, "not present after install: " + ", ".join(gone)) if gone else (True, f"{len(names)} artifact packages kept")


def install(name: str) -> tuple[bool, str]:
    if NO_SAVE:
        return install_live(FRONTEND_DIR, [name])
    return _npm(FRONTEND_DIR, ["install", name])


def main() -> int:
    try:
        data = json.loads(sys.stdin.read() or "{}")
    except Exception:
        return 0

    file_path = data.get("tool_input", {}).get("file_path", "")
    if not file_path or not file_path.endswith((".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")):
        return 0
    # 書いたファイルが属する frontend（作業場所ごとに別）。動いているダンでは package.json を変えない（2026-10-18）
    global FRONTEND_DIR, PACKAGE_JSON, NO_SAVE
    front = next((d for d in Path(file_path).resolve().parents if d.name == "frontend" and (d / "package.json").exists()), None)
    if front is None:
        return 0
    FRONTEND_DIR, PACKAGE_JSON = front, front / "package.json"
    NO_SAVE = front.resolve() == (PROJECT_ROOT / "frontend").resolve()

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
    missing = [n for n in wanted if n not in have or not _present(FRONTEND_DIR, n)]
    if not missing:
        return 0

    installable = [n for n in missing if n in ALLOWED_PACKAGES]
    blocked = [n for n in missing if n not in ALLOWED_PACKAGES]

    msgs = []
    if installable:
        for name in installable:
            ok, err = install(name)
            if ok and NO_SAVE:
                msgs.append(f"[npm auto-install] installed {name} for artifacts (kept in frontend/{ARTIFACT_PACKAGES}; "
                            f"{PROJECT_ROOT}'s package.json is not changed).")
            elif ok:
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
