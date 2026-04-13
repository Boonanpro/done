"""
create_feature ガードhook

ダン(Claude Code)がwrite_fileやeditで本番パスに新規ファイルを作ろうとした時、
対応するcreate_featureが先に実行されていなければブロックする。

対象パス:
- app/api/*_routes.py (新規)
- app/services/*_service.py (新規)
- app/models/*_schemas.py (新規)
- frontend/src/app/dashboard/**/page.tsx (新規)
- supabase/migrations/*.sql (新規)

既存ファイルの編集はブロックしない（既存機能の修正は自由）。
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
    (r"supabase[/\\]migrations[/\\]\d+_([\w]+)\.sql", "migration"),
]

# 既知の既存機能（create_feature以前から存在するもの。これらはブロックしない）
EXISTING_FEATURES = {
    "chat", "project", "collab", "voice", "studio", "gmail", "calendar",
    "dashboard", "note", "meeting", "bank_account", "otp", "credentials",
    "file", "content", "detection", "push", "gemini_voice", "agent",
    "block", "trigger", "document",
    # ダッシュボードの既存ページ
    "ai-b2b-sales", "dx", "components",
}


def get_registered_features() -> set:
    """feature_registryに登録済みの機能名を取得"""
    if not os.path.exists(FEATURE_REGISTRY):
        return set()
    try:
        with open(FEATURE_REGISTRY, "r", encoding="utf-8") as f:
            registry = json.load(f)
        return set(registry.keys())
    except Exception:
        return set()


def check_file_path(file_path: str) -> str | None:
    """
    ファイルパスをチェックし、ブロックすべきならエラーメッセージを返す。
    問題なければNoneを返す。
    """
    # 相対パスに変換
    rel_path = file_path.replace(PROJECT_ROOT, "").lstrip("/\\")

    for pattern, file_type in GUARDED_PATTERNS:
        match = re.search(pattern, rel_path)
        if not match:
            continue

        feature_name = match.group(1).lower().replace("-", "_")

        # 既存機能は許可
        if feature_name in EXISTING_FEATURES:
            return None

        # feature_registryに登録済みなら許可
        registered = get_registered_features()
        if feature_name in registered:
            return None

        # ファイルが既に存在する場合は編集なので許可
        full_path = os.path.join(PROJECT_ROOT, rel_path)
        if os.path.exists(full_path):
            return None

        # 新規ファイルでcreate_feature未実行 → ブロック
        return (
            f"create_feature未実行: '{feature_name}' は feature_registry に登録されていません。\n"
            f"新機能の実装を開始する前に、まず create_feature('{feature_name}') を実行してください。\n"
            f"これにより DB migration, schemas, service, routes, frontend page の雛形が自動生成されます。\n"
            f"詳細: python -c \"from app.tools.create_feature import create_feature; create_feature('{feature_name}')\""
        )

    return None


if __name__ == "__main__":
    # hookから呼ばれる: 引数なし、stdinからツール情報を受け取る
    # Claude Codeのhookは環境変数やstdinでツール情報を渡す
    # ここではファイルパスを引数で受け取る簡易版
    if len(sys.argv) > 1:
        file_path = sys.argv[1]
        error = check_file_path(file_path)
        if error:
            print(error, file=sys.stderr)
            sys.exit(1)
        sys.exit(0)
    else:
        # テスト用
        test_paths = [
            r"app\api\inventory_routes.py",  # 新規 → ブロック
            r"app\api\chat_routes.py",  # 既存 → 許可（ファイルが存在）
            r"app\api\block_routes.py",  # 既存機能 → 許可
        ]
        for p in test_paths:
            full = os.path.join(PROJECT_ROOT, p)
            result = check_file_path(full)
            status = "BLOCK" if result else "ALLOW"
            print(f"  {status}: {p}")
