"""
Code Executor - Pythonコードをサブプロセスで安全に実行する

Danが動的にPythonコードを実行するためのエンジン。
subprocess.runで別プロセス実行し、FastAPIプロセスを保護する。
"""

import subprocess
import tempfile
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

SANDBOX_DIR = Path.home() / ".dan" / "sandbox"
EXEC_TIMEOUT = 30  # 秒


async def execute_python(code: str) -> dict:
    """
    Pythonコードを実行して結果を返す

    Args:
        code: 実行するPythonコード

    Returns:
        {"success": bool, "output": str, "error": str, "return_code": int}
    """
    SANDBOX_DIR.mkdir(parents=True, exist_ok=True)

    # コードを一時ファイルに書き出し
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", dir=SANDBOX_DIR,
        delete=False, encoding="utf-8"
    ) as f:
        f.write(code)
        script_path = f.name

    try:
        result = subprocess.run(
            ["python", script_path],
            capture_output=True,
            text=True,
            timeout=EXEC_TIMEOUT,
            cwd=str(SANDBOX_DIR),
        )
        # LLMコンテキスト保護のため出力を切り詰め
        output = result.stdout[-5000:] if len(result.stdout) > 5000 else result.stdout
        error = result.stderr[-2000:] if len(result.stderr) > 2000 else result.stderr

        return {
            "success": result.returncode == 0,
            "output": output,
            "error": error,
            "return_code": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "error": f"タイムアウト（{EXEC_TIMEOUT}秒）",
            "output": "",
            "return_code": -1,
        }
    except Exception as e:
        logger.exception(f"Code execution failed: {e}")
        return {
            "success": False,
            "error": str(e),
            "output": "",
            "return_code": -1,
        }
    finally:
        Path(script_path).unlink(missing_ok=True)
