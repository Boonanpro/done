"""
create_feature ガードhook

Claude CodeのPreToolUse hookとして動作。
Writeツールで本番パスに新規ファイルを作ろうとした時、
create_featureが先に実行されていなければブロックする。

stdinからJSON（tool_input.file_path）を受け取る。
"""
import sys
import os
import json
import re


PROJECT_ROOT = r"D:\done"
FEATURE_REGISTRY = os.path.join(PROJECT_ROOT, ".claude", "feature_registry.json")

# 監視対象のパスパターン（新規ファイル作成時のみ）
GUARDED_PATTERNS = [
    (r"app[/\\]api[/\\](\w+)_routes\.py", "routes"),
    (r"app[/\\]services[/\\](\w+)_service\.py", "service"),
    (r"app[/\\]models[/\\](\w+)_schemas\.py", "schemas"),
    (r"frontend[/\\]src[/\\]app[/\\]dashboard[/\\]([\w-]+)[/\\]page\.tsx", "page"),
    (r"frontend[/\\]src[/\\]app[/\\]demo[/\\]([\w-]+)[/\\]page\.tsx", "demo_page"),
    (r"supabase[/\\]migrations[/\\]\d+_([\w]+)\.sql", "migration"),
]

# 既知の既存機能（create_feature以前から存在するもの）
EXISTING_FEATURES = {
    "chat", "project", "collab", "voice", "studio", "gmail", "calendar",
    "dashboard", "note", "meeting", "bank_account", "otp", "credentials",
    "file", "content", "detection", "push", "gemini_voice", "agent",
    "block", "trigger", "document",
    "ai-b2b-sales", "dx", "components",
}


def get_registered_features() -> set:
    if not os.path.exists(FEATURE_REGISTRY):
        return set()
    try:
        with open(FEATURE_REGISTRY, "r", encoding="utf-8") as f:
            return set(json.load(f).keys())
    except Exception:
        return set()


def check_file_path(file_path: str) -> str | None:
    """ブロックすべきならエラーメッセージ、OKならNone"""
    rel_path = file_path.replace(PROJECT_ROOT, "").replace("\\", "/").lstrip("/")

    for pattern, file_type in GUARDED_PATTERNS:
        match = re.search(pattern.replace("\\\\", "/"), rel_path.replace("\\", "/"))
        if not match:
            continue

        feature_name = match.group(1).lower().replace("-", "_")

        if feature_name in EXISTING_FEATURES:
            return None

        if feature_name in get_registered_features():
            return None

        # ファイルが既に存在する場合は編集なので許可
        if os.path.exists(file_path):
            return None

        return (
            f"create_feature未実行: '{feature_name}' は feature_registry に登録されていません。\n"
            f"新機能の実装を開始する前に create_feature('{feature_name}') を実行してください。"
        )

    return None


def main():
    try:
        stdin_data = sys.stdin.read()
        if not stdin_data.strip():
            return 0

        data = json.loads(stdin_data)
        file_path = data.get("tool_input", {}).get("file_path", "")

        if not file_path:
            return 0

        error = check_file_path(file_path)
        if not error:
            return 0

        # ブロック
        output = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": error,
            }
        }
        print(json.dumps(output))
        return 0

    except Exception as e:
        # hookがクラッシュしても本体をブロックしない
        return 0


if __name__ == "__main__":
    sys.exit(main())
