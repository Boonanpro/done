"""
Memory Service - OpenClaw-style memory with hybrid search

Features:
- Markdown files as source of truth (~/.dan/workspace/memory/)
- SQLite + sqlite-vec for vector search
- OpenAI embeddings (text-embedding-3-small)
- Hybrid search: vector similarity (70%) + BM25 keyword (30%)
"""

import sqlite3
import logging
import hashlib
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional
import json

import sqlite_vec
from openai import OpenAI

from app.config import settings

logger = logging.getLogger(__name__)

# Paths
WORKSPACE_DIR = Path.home() / ".dan" / "workspace"
MEMORY_DIR = WORKSPACE_DIR / "memory"
MEMORY_DB_PATH = Path.home() / ".dan" / "memory.sqlite"

# Embedding settings
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSIONS = 1536

# Search settings
CHUNK_SIZE = 400  # tokens (approx)
CHUNK_OVERLAP = 80
MIN_SCORE = 0.35
MAX_RESULTS = 6
VECTOR_WEIGHT = 0.7
KEYWORD_WEIGHT = 0.3


class MemoryService:
    """Memory service with hybrid search"""

    def __init__(self):
        self._openai_client: Optional[OpenAI] = None
        self._db_conn: Optional[sqlite3.Connection] = None
        self._ensure_directories()

    def _ensure_directories(self):
        """Ensure memory directories exist"""
        WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
        MEMORY_DIR.mkdir(parents=True, exist_ok=True)

    @property
    def openai_client(self) -> OpenAI:
        """Lazy-load OpenAI client"""
        if self._openai_client is None:
            if not settings.OPENAI_API_KEY:
                raise RuntimeError("OPENAI_API_KEY not set")
            self._openai_client = OpenAI(api_key=settings.OPENAI_API_KEY)
        return self._openai_client

    def _get_db(self) -> sqlite3.Connection:
        """Get or create database connection"""
        if self._db_conn is None:
            MEMORY_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
            self._db_conn = sqlite3.connect(str(MEMORY_DB_PATH))
            self._db_conn.enable_load_extension(True)
            sqlite_vec.load(self._db_conn)
            self._db_conn.enable_load_extension(False)
            self._init_db()
        return self._db_conn

    def _init_db(self):
        """Initialize database schema"""
        conn = self._db_conn

        # Chunks table (source of truth metadata)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS chunks (
                id INTEGER PRIMARY KEY,
                file_path TEXT NOT NULL,
                content TEXT NOT NULL,
                start_line INTEGER,
                end_line INTEGER,
                content_hash TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(file_path, start_line)
            )
        """)

        # Vector table for semantic search
        conn.execute(f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS chunks_vec USING vec0(
                chunk_id INTEGER PRIMARY KEY,
                embedding FLOAT[{EMBEDDING_DIMENSIONS}]
            )
        """)

        # FTS table for keyword search
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
                content,
                content='chunks',
                content_rowid='id'
            )
        """)

        # Triggers to keep FTS in sync
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
                INSERT INTO chunks_fts(rowid, content) VALUES (new.id, new.content);
            END
        """)

        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
                INSERT INTO chunks_fts(chunks_fts, rowid, content) VALUES('delete', old.id, old.content);
            END
        """)

        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON chunks BEGIN
                INSERT INTO chunks_fts(chunks_fts, rowid, content) VALUES('delete', old.id, old.content);
                INSERT INTO chunks_fts(rowid, content) VALUES (new.id, new.content);
            END
        """)

        # File tracking table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS indexed_files (
                file_path TEXT PRIMARY KEY,
                file_hash TEXT NOT NULL,
                indexed_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Embedding cache: content_hash → embedding (OpenClaw方式)
        # 同じ内容のチャンクは1回だけAPIを呼び、キャッシュから再利用する
        conn.execute("""
            CREATE TABLE IF NOT EXISTS embedding_cache (
                content_hash TEXT PRIMARY KEY,
                embedding TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.commit()

    def _compute_file_hash(self, content: str) -> str:
        """Compute hash of file content"""
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def _chunk_text(self, text: str, file_path: str) -> List[Dict[str, Any]]:
        """Split text into chunks with metadata"""
        lines = text.split('\n')
        chunks = []
        current_chunk = []
        current_start = 0
        char_count = 0

        # Approximate: 1 token ≈ 4 chars for English, 1-2 for Japanese
        chars_per_chunk = CHUNK_SIZE * 3  # Conservative estimate
        overlap_chars = CHUNK_OVERLAP * 3

        for i, line in enumerate(lines):
            current_chunk.append(line)
            char_count += len(line) + 1  # +1 for newline

            if char_count >= chars_per_chunk:
                chunk_content = '\n'.join(current_chunk)
                chunks.append({
                    'file_path': file_path,
                    'content': chunk_content,
                    'start_line': current_start,
                    'end_line': i,
                    'content_hash': self._compute_file_hash(chunk_content),
                })

                # Overlap: keep some lines for context
                overlap_lines = []
                overlap_count = 0
                for line in reversed(current_chunk):
                    overlap_lines.insert(0, line)
                    overlap_count += len(line) + 1
                    if overlap_count >= overlap_chars:
                        break

                current_chunk = overlap_lines
                current_start = max(0, i - len(overlap_lines) + 1)
                char_count = overlap_count

        # Don't forget the last chunk
        if current_chunk:
            chunk_content = '\n'.join(current_chunk)
            chunks.append({
                'file_path': file_path,
                'content': chunk_content,
                'start_line': current_start,
                'end_line': len(lines) - 1,
                'content_hash': self._compute_file_hash(chunk_content),
            })

        return chunks

    def _get_embedding(self, text: str) -> List[float]:
        """Get embedding from OpenAI"""
        response = self.openai_client.embeddings.create(
            model=EMBEDDING_MODEL,
            input=text,
        )
        return response.data[0].embedding

    def _get_cached_embedding(self, content_hash: str) -> Optional[List[float]]:
        """embedding_cacheからキャッシュ済みのembeddingを取得"""
        conn = self._get_db()
        row = conn.execute(
            "SELECT embedding FROM embedding_cache WHERE content_hash = ?",
            (content_hash,)
        ).fetchone()
        if row:
            return json.loads(row[0])
        return None

    def _save_cached_embedding(self, content_hash: str, embedding: List[float]):
        """embeddingをキャッシュに保存"""
        conn = self._get_db()
        conn.execute(
            "INSERT OR REPLACE INTO embedding_cache (content_hash, embedding) VALUES (?, ?)",
            (content_hash, json.dumps(embedding))
        )

    def index_file(self, file_path: Path) -> int:
        """
        Index a single file with chunk-level deduplication.

        OpenClaw方式: チャンクごとにcontent_hashを比較し、
        変更があったチャンクだけembedding APIを呼ぶ。
        """
        if not file_path.exists():
            logger.warning(f"File not found: {file_path}")
            return 0

        content = file_path.read_text(encoding='utf-8')
        file_hash = self._compute_file_hash(content)
        relative_path = str(file_path.relative_to(WORKSPACE_DIR))

        conn = self._get_db()

        # Check if already indexed with same hash
        row = conn.execute(
            "SELECT file_hash FROM indexed_files WHERE file_path = ?",
            (relative_path,)
        ).fetchone()

        if row and row[0] == file_hash:
            logger.debug(f"File unchanged, skipping: {relative_path}")
            return 0

        # 新しいチャンクを生成
        new_chunks = self._chunk_text(content, relative_path)
        new_hashes = {chunk['content_hash'] for chunk in new_chunks}

        # 既存チャンクのハッシュ→ID+embeddingの有無を取得
        existing_rows = conn.execute(
            """SELECT c.id, c.content_hash, (cv.chunk_id IS NOT NULL) as has_vec
               FROM chunks c
               LEFT JOIN chunks_vec cv ON cv.chunk_id = c.id
               WHERE c.file_path = ?""",
            (relative_path,)
        ).fetchall()
        existing_by_hash = {}
        for row_id, row_hash, has_vec in existing_rows:
            existing_by_hash[row_hash] = {"id": row_id, "has_vec": bool(has_vec)}

        # 不要になったチャンクを削除（新しいチャンク群に含まれないもの）
        for old_hash, info in existing_by_hash.items():
            if old_hash not in new_hashes:
                conn.execute("DELETE FROM chunks WHERE id = ?", (info["id"],))
                conn.execute("DELETE FROM chunks_vec WHERE chunk_id = ?", (info["id"],))

        # 新しいチャンクを処理
        api_calls = 0
        cache_hits = 0
        skipped = 0

        for chunk in new_chunks:
            c_hash = chunk['content_hash']

            # 既存チャンクにハッシュが一致 + embeddingもある → スキップ
            if c_hash in existing_by_hash and existing_by_hash[c_hash]["has_vec"]:
                skipped += 1
                continue

            # 既存チャンクにハッシュが一致するがembeddingがない → embeddingだけ追加
            if c_hash in existing_by_hash:
                chunk_id = existing_by_hash[c_hash]["id"]
            else:
                # 新規チャンク → INSERT
                cursor = conn.execute(
                    """INSERT OR REPLACE INTO chunks (file_path, content, start_line, end_line, content_hash)
                       VALUES (?, ?, ?, ?, ?)""",
                    (chunk['file_path'], chunk['content'], chunk['start_line'],
                     chunk['end_line'], c_hash)
                )
                chunk_id = cursor.lastrowid

            # embedding: キャッシュ優先 → なければAPI呼び出し
            try:
                cached = self._get_cached_embedding(c_hash)
                if cached:
                    embedding = cached
                    cache_hits += 1
                else:
                    embedding = self._get_embedding(chunk['content'])
                    self._save_cached_embedding(c_hash, embedding)
                    api_calls += 1

                # chunks_vecに挿入（既存があれば置換）
                conn.execute("DELETE FROM chunks_vec WHERE chunk_id = ?", (chunk_id,))
                conn.execute(
                    "INSERT INTO chunks_vec (chunk_id, embedding) VALUES (?, ?)",
                    (chunk_id, json.dumps(embedding))
                )
            except Exception as e:
                logger.error(f"Failed to get embedding for chunk: {e}")
                continue

        # Update file tracking
        conn.execute(
            """INSERT OR REPLACE INTO indexed_files (file_path, file_hash, indexed_at)
               VALUES (?, ?, ?)""",
            (relative_path, file_hash, datetime.now().isoformat())
        )

        conn.commit()
        total = api_calls + cache_hits + skipped
        logger.info(
            f"Indexed {relative_path}: {total} chunks "
            f"(api={api_calls}, cache={cache_hits}, skipped={skipped})"
        )
        return api_calls + cache_hits

    def index_all(self) -> Dict[str, int]:
        """Index all memory files"""
        results = {}

        # Index bootstrap files
        for filename in ['MEMORY.md', 'USER.md', 'RULES.md']:
            file_path = WORKSPACE_DIR / filename
            if file_path.exists():
                results[filename] = self.index_file(file_path)

        # Index daily memory files
        if MEMORY_DIR.exists():
            for file_path in MEMORY_DIR.glob('*.md'):
                results[file_path.name] = self.index_file(file_path)

        return results

    def search(self, query: str, max_results: int = MAX_RESULTS) -> List[Dict[str, Any]]:
        """
        Hybrid search: vector similarity + BM25 keyword

        Returns list of {file_path, content, start_line, end_line, score}
        """
        conn = self._get_db()

        # Get query embedding
        try:
            query_embedding = self._get_embedding(query)
        except Exception as e:
            logger.error(f"Failed to get query embedding: {e}")
            # Fallback to keyword-only search
            return self._keyword_search(query, max_results)

        # Vector search (sqlite-vec requires k=? syntax)
        vector_results = conn.execute(
            """
            SELECT chunk_id, distance
            FROM chunks_vec
            WHERE embedding MATCH ? AND k = ?
            """,
            (json.dumps(query_embedding), max_results * 4)
        ).fetchall()

        # Convert L2 distance to similarity score: similarity = 1 / (1 + distance)
        # This gives values between 0 and 1, where closer = higher score
        vector_scores = {row[0]: 1 / (1 + row[1]) for row in vector_results}

        # Keyword search (BM25)
        keyword_results = conn.execute(
            """
            SELECT rowid, bm25(chunks_fts) as score
            FROM chunks_fts
            WHERE chunks_fts MATCH ?
            ORDER BY score
            LIMIT ?
            """,
            (query, max_results * 4)
        ).fetchall()

        # Normalize keyword scores
        if keyword_results:
            max_kw_score = max(abs(r[1]) for r in keyword_results) or 1
            keyword_scores = {row[0]: abs(row[1]) / max_kw_score for row in keyword_results}
        else:
            keyword_scores = {}

        # Combine scores
        all_chunk_ids = set(vector_scores.keys()) | set(keyword_scores.keys())
        combined = []

        for chunk_id in all_chunk_ids:
            vec_score = vector_scores.get(chunk_id, 0)
            kw_score = keyword_scores.get(chunk_id, 0)
            final_score = (vec_score * VECTOR_WEIGHT) + (kw_score * KEYWORD_WEIGHT)

            if final_score >= MIN_SCORE:
                combined.append((chunk_id, final_score))

        # Sort by score and get top results
        combined.sort(key=lambda x: x[1], reverse=True)
        top_chunks = combined[:max_results]

        # Fetch chunk details
        results = []
        for chunk_id, score in top_chunks:
            row = conn.execute(
                """SELECT file_path, content, start_line, end_line
                   FROM chunks WHERE id = ?""",
                (chunk_id,)
            ).fetchone()

            if row:
                results.append({
                    'file_path': row[0],
                    'content': row[1][:700],  # Cap at ~700 chars like OpenClaw
                    'start_line': row[2],
                    'end_line': row[3],
                    'score': round(score, 3),
                })

        return results

    def _keyword_search(self, query: str, max_results: int) -> List[Dict[str, Any]]:
        """Fallback keyword-only search"""
        conn = self._get_db()

        results = conn.execute(
            """
            SELECT c.file_path, c.content, c.start_line, c.end_line, bm25(chunks_fts) as score
            FROM chunks_fts f
            JOIN chunks c ON f.rowid = c.id
            WHERE chunks_fts MATCH ?
            ORDER BY score
            LIMIT ?
            """,
            (query, max_results)
        ).fetchall()

        return [{
            'file_path': row[0],
            'content': row[1][:700],
            'start_line': row[2],
            'end_line': row[3],
            'score': round(abs(row[4]), 3),
        } for row in results]

    def save_memory(self, content: str, filename: Optional[str] = None) -> str:
        """
        Save content to memory file

        Args:
            content: Content to save
            filename: Optional filename. If None, uses today's date.

        Returns:
            Path to saved file (relative to workspace)
        """
        if filename is None:
            filename = f"{datetime.now().strftime('%Y-%m-%d')}.md"

        file_path = MEMORY_DIR / filename

        # Append to existing file or create new
        if file_path.exists():
            existing = file_path.read_text(encoding='utf-8')
            content = existing + "\n\n" + content

        file_path.write_text(content, encoding='utf-8')

        # Re-index the file
        self.index_file(file_path)

        return f"memory/{filename}"

    def get_memory_file(self, filename: str) -> Optional[str]:
        """Read a memory file"""
        # Try memory directory first
        file_path = MEMORY_DIR / filename
        if not file_path.exists():
            # Try workspace root
            file_path = WORKSPACE_DIR / filename

        if file_path.exists():
            return file_path.read_text(encoding='utf-8')
        return None


# Singleton instance
_memory_service: Optional[MemoryService] = None


def get_memory_service() -> MemoryService:
    """Get singleton memory service instance"""
    global _memory_service
    if _memory_service is None:
        _memory_service = MemoryService()
    return _memory_service
