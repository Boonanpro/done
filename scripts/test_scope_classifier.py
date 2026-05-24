"""Unit tests for scope_classifier.

Run with:
    python scripts/test_scope_classifier.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from scope_classifier import classify, detect_mix  # noqa: E402


CASES: list[tuple[str, str]] = [
    # === Dan infra ===
    ("app/api/chat_routes.py", "infra"),
    ("app/services/inspector_writeback_core.py", "infra"),
    ("app/core/main.py", "infra"),
    ("scripts/auto_deploy.py", "infra"),
    ("scripts/hook_destructive_guard.py", "infra"),
    ("tests/test_salonboard_browser_policy.py", "infra"),
    ("tests_e2e/test_project_chat_recovery.py", "infra"),
    ("supabase/migrations/057_chat_artifact_room_scope.sql", "infra"),
    (".github/workflows/scope-check.yml", "infra"),
    (".githooks/pre-commit", "infra"),
    (".claude/settings.json", "infra"),
    ("mobile/App.tsx", "infra"),
    ("frontend/next.config.ts", "infra"),
    ("frontend/package.json", "infra"),
    ("frontend/tsconfig.json", "infra"),
    ("frontend/src/middleware.ts", "infra"),
    ("frontend/src/components/templates/lp-shell.tsx", "infra"),
    ("frontend/src/components/preview/preview-pane.tsx", "infra"),
    ("frontend/src/lib/artifact-paths.ts", "infra"),
    ("frontend/src/hooks/useRealtimeVoice.ts", "infra"),
    ("frontend/src/stores/preview-store.ts", "infra"),
    ("frontend/src/types/api.ts", "infra"),
    ("frontend/src/app/layout.tsx", "infra"),
    ("frontend/src/app/page.tsx", "infra"),
    ("frontend/src/app/globals.css", "infra"),
    ("frontend/src/app/chat/page.tsx", "infra"),
    ("frontend/src/app/dan-notion/page.tsx", "infra"),
    ("frontend/src/app/voice/page.tsx", "infra"),
    ("frontend/src/app/test-inspector/page.tsx", "infra"),
    ("frontend/src/app/artifacts/layout.tsx", "infra"),
    ("frontend/src/app/artifacts/publish/page.tsx", "infra"),
    ("frontend/src/app/api/v1/inspector-overrides/route.ts", "infra"),
    ("frontend/public/favicon.ico", "infra"),
    ("frontend/public/icon-192x192.png", "infra"),
    ("frontend/public/manifest.json", "infra"),
    ("frontend/public/sw.js", "infra"),
    ("frontend/public/audio-worklet-processor.js", "infra"),
    ("CLAUDE.md", "infra"),
    (".gitignore", "infra"),
    # === Artifacts ===
    ("frontend/src/app/artifacts/kittoku/page.tsx", "artifact:kittoku"),
    ("frontend/src/app/artifacts/kittoku/v2/page.tsx", "artifact:kittoku"),
    ("frontend/src/app/artifacts/kittoku/contact/page.tsx", "artifact:kittoku"),
    ("frontend/src/app/artifacts/kittoku/components/site-nav.tsx", "artifact:kittoku"),
    ("frontend/src/app/artifacts/salonboard-styleup/page.tsx", "artifact:salonboard-styleup"),
    ("frontend/src/app/artifacts/test-edit/page.tsx", "artifact:test-edit"),
    ("frontend/src/app/artifacts/aix-dashboard/page.tsx", "artifact:aix-dashboard"),
    ("frontend/src/app/artifacts/inspection-report/page.tsx", "artifact:inspection-report"),
    ("frontend/src/app/api/kittoku/contact/route.ts", "artifact:kittoku"),
    ("frontend/public/kikkawa/hero-pc-v4.mp4", "artifact:kittoku"),
    ("frontend/public/kikkawa/v2/parts/bolt-set.png", "artifact:kittoku"),
    ("frontend/public/inspection-template.docx", "artifact:inspection-report"),
    ("frontend/public/annual-inspection-template.xlsm", "artifact:inspection-report"),
    # === Demos / scratch ===
    ("frontend/src/app/demo/amagasaki-sales-dashboard/page.tsx",
     "demo:amagasaki-sales-dashboard"),
    ("frontend/src/app/demo/new-attack/page.tsx", "demo:new-attack"),
    ("frontend/public/amagasaki-hero.mp4", "demo:amagasaki-sales-dashboard"),
    # === Ignored ===
    (".tunnel_core_url", "ignored"),
    ("frontend/package-lock.json", "ignored"),
    ("frontend/.next/static/chunk.js", "ignored"),
    ("sandbox.log", "ignored"),
    (".env.local", "ignored"),
]


def main() -> int:
    failed: list[tuple[str, str, str]] = []
    for path, expected in CASES:
        actual = str(classify(path))
        if actual != expected:
            failed.append((path, expected, actual))

    print(f"Tested {len(CASES)} paths. {len(failed)} failures.")
    for path, expected, actual in failed:
        print(f"  FAIL: {path!r}\n    expected={expected!r}\n    actual=  {actual!r}")

    # === Mix detection cases ===
    print()
    mix_cases: list[tuple[str, list[str], bool]] = [
        (
            "all infra, ok",
            ["app/api/chat_routes.py", "frontend/src/lib/foo.ts"],
            True,
        ),
        (
            "same artifact, ok",
            [
                "frontend/src/app/artifacts/kittoku/page.tsx",
                "frontend/public/kikkawa/hero-pc-v4.mp4",
            ],
            True,
        ),
        (
            "infra + artifact, BLOCK",
            [
                "app/api/chat_routes.py",
                "frontend/src/app/artifacts/kittoku/page.tsx",
            ],
            False,
        ),
        (
            "two artifacts, BLOCK",
            [
                "frontend/src/app/artifacts/kittoku/page.tsx",
                "frontend/src/app/artifacts/salonboard-styleup/page.tsx",
            ],
            False,
        ),
        (
            "infra + ignored + demo, ok",
            [
                "app/api/chat_routes.py",
                ".tunnel_core_url",
                "frontend/src/app/demo/foo/page.tsx",
            ],
            True,
        ),
        (
            "artifact + demo, ok (demo is neutral)",
            [
                "frontend/src/app/artifacts/kittoku/page.tsx",
                "frontend/src/app/demo/foo/page.tsx",
            ],
            True,
        ),
    ]
    mix_failed = 0
    for name, paths, expected_ok in mix_cases:
        v = detect_mix(paths)
        if v.ok != expected_ok:
            mix_failed += 1
            print(f"  FAIL: {name}\n    expected ok={expected_ok}, got ok={v.ok}\n    reason: {v.reason}")
        else:
            print(f"  OK:   {name}")

    if failed or mix_failed:
        print(f"\n{len(failed)} classify failure(s), {mix_failed} mix-detect failure(s).")
        return 1
    print("\nAll tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
