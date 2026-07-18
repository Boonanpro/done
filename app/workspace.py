"""ダンのCLI作業ディレクトリの解決。

優先順位:
1. 環境変数 DAN_CLI_WORKSPACE（明示指定）
2. D:/dan-workspace（デスクトップPCの従来レイアウト。存在する場合のみ）
3. <project root>/.dan-workspace（ノートPC等、D: が無い環境のフォールバック）

どのマシンでも同じコードで動かすため、パスのハードコードはここに集約する。
"""
from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

_LEGACY_WORKSPACE = Path("D:/dan-workspace")


def resolve_cli_workspace() -> Path:
    env = os.environ.get("DAN_CLI_WORKSPACE")
    if env:
        return Path(env)
    if _LEGACY_WORKSPACE.exists():
        return _LEGACY_WORKSPACE
    return PROJECT_ROOT / ".dan-workspace"
