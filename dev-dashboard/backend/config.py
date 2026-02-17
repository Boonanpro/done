"""
Dev Dashboard Configuration
"""
from pathlib import Path
from dotenv import load_dotenv

# ダンのプロジェクトルート
DAN_PROJECT_ROOT = Path("D:/done")

# ダン本体の.envを読み込む（override=Trueで確実に環境変数をセット）
env_path = DAN_PROJECT_ROOT / ".env"
if env_path.exists():
    load_dotenv(env_path, override=True)
else:
    print(f"Warning: .env not found at {env_path}")

# ポート設定
PORT = 8001

# ブラウザログディレクトリ（スクショ・HTML保存先）
BROWSER_LOGS_DIR = DAN_PROJECT_ROOT / "app" / "logs" / "browser"

# CORS許可オリジン
CORS_ORIGINS = [
    "http://localhost:3001",
    "http://127.0.0.1:3001",
]
