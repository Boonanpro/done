"""
Error Tracker - エラーログの追跡と永続化

ダンが自身の実行エラーを追跡するための共通基盤。
インメモリバッファ + Supabase永続化のハイブリッド方式。
"""

import logging
import threading
import traceback as tb_module
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
import uuid

logger = logging.getLogger(__name__)

# プロジェクトルート
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent

# ログディレクトリ（フォールバック用）
LOG_DIR = PROJECT_ROOT / "logs"

# ダン専用エラーログファイル（フォールバック用）
DAN_ERROR_LOG = LOG_DIR / "dan_errors.log"


@dataclass
class LogEntry:
    """ログエントリ"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=datetime.now)
    level: str = "ERROR"
    source: str = ""
    message: str = ""
    traceback: Optional[str] = None
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    context: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換"""
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat(),
            "level": self.level,
            "source": self.source,
            "message": self.message,
            "traceback": self.traceback,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "context": self.context,
        }

    def to_db_dict(self) -> Dict[str, Any]:
        """DB保存用の辞書形式に変換"""
        return {
            "id": self.id,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "source": self.source,
            "level": self.level,
            "message": self.message,
            "traceback": self.traceback,
            "context": self.context,
            "created_at": self.timestamp.isoformat(),
        }


class ErrorTracker:
    """
    エラートラッカー

    インメモリバッファ + Supabase永続化のハイブリッド方式。
    - 高速なインメモリアクセス
    - 永続化によるデータ保持
    - セッション・ユーザーとの紐付け
    """

    def __init__(self, buffer_size: int = 100):
        """
        初期化

        Args:
            buffer_size: インメモリバッファのサイズ
        """
        self._buffer: deque = deque(maxlen=buffer_size)
        self._lock = threading.Lock()
        self._supabase = None
        self._supabase_available = None  # None=未確認, True/False=確認済み

    def _get_supabase(self):
        """Supabaseクライアントを遅延取得"""
        if self._supabase_available is False:
            return None

        if self._supabase is None:
            try:
                from app.services.supabase_client import get_supabase_client
                self._supabase = get_supabase_client()
                self._supabase_available = True
            except Exception as e:
                logger.warning(f"Supabase client unavailable: {e}")
                self._supabase_available = False
                return None

        return self._supabase

    def capture(
        self,
        source: str,
        message: str,
        traceback: Optional[str] = None,
        level: str = "ERROR",
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> LogEntry:
        """
        エラーをキャプチャ

        Args:
            source: エラー発生元（例: "ex_reservation.search"）
            message: エラーメッセージ
            traceback: スタックトレース
            level: ログレベル（ERROR, WARNING, INFO）
            session_id: エージェントセッションID
            user_id: ユーザーID
            context: 追加コンテキスト（パラメータ等）

        Returns:
            作成されたLogEntry
        """
        entry = LogEntry(
            timestamp=datetime.now(),
            level=level,
            source=source,
            message=message,
            traceback=traceback,
            session_id=session_id,
            user_id=user_id,
            context=context,
        )

        # インメモリバッファに追加
        with self._lock:
            self._buffer.append(entry)

        # Supabaseに保存（非同期で実行、失敗しても続行）
        self._save_to_db(entry)

        # ファイルにも書き込み（フォールバック）
        self._save_to_file(entry)

        return entry

    def _save_to_db(self, entry: LogEntry) -> None:
        """Supabaseに保存"""
        try:
            supabase = self._get_supabase()
            if supabase is None:
                return

            data = entry.to_db_dict()
            supabase.client.table("error_logs").insert(data).execute()

        except Exception as e:
            logger.warning(f"Failed to save error log to DB: {e}")

    def _save_to_file(self, entry: LogEntry) -> None:
        """ファイルに保存（フォールバック）"""
        try:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            with open(DAN_ERROR_LOG, "a", encoding="utf-8") as f:
                f.write(f"[{entry.timestamp.isoformat()}] [{entry.level}] [{entry.source}]\n")
                f.write(f"  {entry.message}\n")
                if entry.session_id:
                    f.write(f"  Session: {entry.session_id}\n")
                if entry.traceback:
                    for line in entry.traceback.split("\n"):
                        f.write(f"  {line}\n")
                f.write("\n")
        except Exception:
            pass  # ファイル書き込み失敗は無視

    def get_recent(
        self,
        limit: int = 20,
        source_filter: Optional[str] = None,
        session_id: Optional[str] = None,
        minutes: Optional[int] = None,
        level: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        最近のエラーを取得（インメモリから）

        Args:
            limit: 取得件数
            source_filter: ソースでフィルタ（部分一致）
            session_id: セッションIDでフィルタ
            minutes: 直近N分以内
            level: ログレベルでフィルタ

        Returns:
            エラーエントリのリスト（新しい順）
        """
        with self._lock:
            entries = list(self._buffer)

        # 時間フィルタ
        if minutes:
            cutoff = datetime.now() - timedelta(minutes=minutes)
            entries = [e for e in entries if e.timestamp >= cutoff]

        # ソースフィルタ
        if source_filter:
            entries = [e for e in entries if source_filter.lower() in e.source.lower()]

        # セッションIDフィルタ
        if session_id:
            entries = [e for e in entries if e.session_id == session_id]

        # レベルフィルタ
        if level:
            entries = [e for e in entries if e.level == level]

        # 新しい順でlimit件
        entries = sorted(entries, key=lambda e: e.timestamp, reverse=True)[:limit]

        return [e.to_dict() for e in entries]

    def query_db(
        self,
        limit: int = 50,
        source_filter: Optional[str] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        minutes: Optional[int] = None,
        level: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        DBからエラーを検索

        Args:
            limit: 取得件数
            source_filter: ソースでフィルタ（前方一致）
            session_id: セッションIDでフィルタ
            user_id: ユーザーIDでフィルタ
            minutes: 直近N分以内
            level: ログレベルでフィルタ

        Returns:
            エラーエントリのリスト（新しい順）
        """
        try:
            supabase = self._get_supabase()
            if supabase is None:
                logger.warning("Supabase not available, returning empty result")
                return []

            query = supabase.client.table("error_logs").select("*")

            # フィルタ適用
            if source_filter:
                query = query.ilike("source", f"{source_filter}%")

            if session_id:
                query = query.eq("session_id", session_id)

            if user_id:
                query = query.eq("user_id", user_id)

            if level:
                query = query.eq("level", level)

            if minutes:
                cutoff = (datetime.now() - timedelta(minutes=minutes)).isoformat()
                query = query.gte("created_at", cutoff)

            # ソートと件数制限
            query = query.order("created_at", desc=True).limit(limit)

            result = query.execute()
            return result.data or []

        except Exception as e:
            logger.error(f"Failed to query error logs from DB: {e}")
            return []

    def get_error_summary(
        self,
        minutes: int = 60,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        エラーサマリーを取得

        Args:
            minutes: 集計対象の時間範囲（分）
            session_id: セッションIDでフィルタ

        Returns:
            エラーサマリー
        """
        errors = self.get_recent(limit=100, minutes=minutes, session_id=session_id)

        # ソース別集計
        by_source: Dict[str, int] = {}
        by_level: Dict[str, int] = {}

        for err in errors:
            source = err.get("source", "unknown")
            level = err.get("level", "ERROR")

            by_source[source] = by_source.get(source, 0) + 1
            by_level[level] = by_level.get(level, 0) + 1

        return {
            "total_count": len(errors),
            "time_range_minutes": minutes,
            "by_source": by_source,
            "by_level": by_level,
            "latest_errors": errors[:5],  # 最新5件
        }

    def clear_buffer(self) -> None:
        """インメモリバッファをクリア"""
        with self._lock:
            self._buffer.clear()


# シングルトンインスタンス
_error_tracker: Optional[ErrorTracker] = None


def get_error_tracker() -> ErrorTracker:
    """ErrorTrackerのシングルトンインスタンスを取得"""
    global _error_tracker
    if _error_tracker is None:
        _error_tracker = ErrorTracker()
    return _error_tracker


def capture_error(
    source: str,
    message: str,
    traceback: Optional[str] = None,
    level: str = "ERROR",
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
) -> LogEntry:
    """
    エラーをキャプチャ（便利関数）

    他のモジュールから簡単に呼び出せるショートカット。

    Args:
        source: エラー発生元（例: "ex_reservation.search"）
        message: エラーメッセージ
        traceback: スタックトレース
        level: ログレベル
        session_id: セッションID
        user_id: ユーザーID
        context: 追加コンテキスト

    Returns:
        作成されたLogEntry
    """
    return get_error_tracker().capture(
        source=source,
        message=message,
        traceback=traceback,
        level=level,
        session_id=session_id,
        user_id=user_id,
        context=context,
    )


def get_recent_errors(
    limit: int = 20,
    source_filter: Optional[str] = None,
    session_id: Optional[str] = None,
    minutes: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    最近のエラーを取得（便利関数）

    Args:
        limit: 取得件数
        source_filter: ソースでフィルタ
        session_id: セッションIDでフィルタ
        minutes: 直近N分以内

    Returns:
        エラーエントリのリスト
    """
    return get_error_tracker().get_recent(
        limit=limit,
        source_filter=source_filter,
        session_id=session_id,
        minutes=minutes,
    )


def format_errors_for_diagnosis(errors: List[Dict[str, Any]]) -> str:
    """
    エラーを診断用にフォーマット

    LLMが読みやすい形式に整形。

    Args:
        errors: エラーエントリのリスト

    Returns:
        フォーマット済み文字列
    """
    if not errors:
        return "エラーは記録されていません。"

    lines = [f"## 直近のエラー ({len(errors)}件)\n"]

    for i, err in enumerate(errors, 1):
        lines.append(f"### エラー {i}")
        lines.append(f"- **時刻**: {err.get('timestamp', 'N/A')}")
        lines.append(f"- **発生元**: {err.get('source', 'N/A')}")
        lines.append(f"- **レベル**: {err.get('level', 'N/A')}")
        lines.append(f"- **メッセージ**: {err.get('message', 'N/A')}")

        if err.get('session_id'):
            lines.append(f"- **セッションID**: {err['session_id']}")

        if err.get('context'):
            lines.append(f"- **コンテキスト**: ```json\n{err['context']}\n```")

        if err.get('traceback'):
            lines.append(f"- **トレースバック**:\n```\n{err['traceback']}\n```")

        lines.append("")

    return "\n".join(lines)


# ファイルベースのログ読み取り関数（後方互換性のため維持）
def read_log_file(
    filename: str,
    lines: int = 100,
    pattern: Optional[str] = None,
) -> Dict[str, Any]:
    """
    ログファイルを読み取り（後方互換性のため維持）

    Args:
        filename: ファイル名（logs/内）
        lines: 読み取る行数（末尾から）
        pattern: フィルタパターン（正規表現）

    Returns:
        読み取り結果
    """
    import re

    log_path = LOG_DIR / filename

    # セキュリティチェック
    try:
        resolved = log_path.resolve()
        if not str(resolved).startswith(str(LOG_DIR.resolve())):
            return {
                "success": False,
                "content": "",
                "lines_read": 0,
                "file_path": str(log_path),
                "error": "ログディレクトリ外へのアクセスは禁止されています",
            }
    except Exception as e:
        return {
            "success": False,
            "content": "",
            "lines_read": 0,
            "file_path": str(log_path),
            "error": str(e),
        }

    if not log_path.exists():
        return {
            "success": False,
            "content": "",
            "lines_read": 0,
            "file_path": str(log_path),
            "error": f"ファイルが存在しません: {filename}",
        }

    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()

        selected_lines = all_lines[-lines:]

        if pattern:
            try:
                regex = re.compile(pattern, re.IGNORECASE)
                selected_lines = [l for l in selected_lines if regex.search(l)]
            except re.error:
                pass

        content = "".join(selected_lines)

        return {
            "success": True,
            "content": content,
            "lines_read": len(selected_lines),
            "total_lines": len(all_lines),
            "file_path": str(log_path),
        }

    except Exception as e:
        return {
            "success": False,
            "content": "",
            "lines_read": 0,
            "file_path": str(log_path),
            "error": str(e),
        }


def list_log_files() -> List[Dict[str, Any]]:
    """
    利用可能なログファイル一覧を取得

    Returns:
        ログファイル情報のリスト
    """
    if not LOG_DIR.exists():
        return []

    files = []
    for path in LOG_DIR.glob("*.log"):
        try:
            stat = path.stat()
            files.append({
                "name": path.name,
                "size_bytes": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            })
        except Exception:
            continue

    files.sort(key=lambda f: f["modified"], reverse=True)
    return files
