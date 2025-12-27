# ADR-001: タスクをSupabase DBに永続化

## ステータス
採用（2024-12-27）

## 関連
- **Commits**: `163bb92`
- **CHANGELOG**: [v1.3.0](../../CHANGELOG.md#130---2024-12-27)

## 背景・問題

タスクがPythonのメモリ（`_tasks: dict`）に保存されていたため：

```python
# 以前の実装
class AISecretaryAgent:
    _tasks: dict[str, dict] = {}  # サーバー再起動で全て消える
```

**問題点**：
1. サーバー再起動でタスクが全て消失
2. 本番運用に適さない
3. 複数サーバーインスタンスでタスク共有不可

## 決定

タスクをSupabase DB（`tasks`テーブル）に永続化し、メモリはキャッシュとして併用する。

```
リクエスト
    ↓
メモリキャッシュ (_tasks_cache) ← 高速アクセス
    ↓ 同期
Supabase DB (tasks テーブル) ← 永続化
```

## 検討した代替案

| 案 | メリット | デメリット | 結論 |
|----|---------|-----------|------|
| メモリのみ（現状維持） | 実装簡単 | 再起動で消失 | ❌ |
| DBのみ | シンプル | 毎回DB問い合わせで遅い | ❌ |
| **キャッシュ + DB** | 高速 + 永続 | 実装やや複雑 | ✅ 採用 |
| Redis + DB | 分散キャッシュ可能 | 過剰な複雑さ | ❌ |

## 実装詳細

```python
# 新しい実装
class AISecretaryAgent:
    _tasks_cache: dict[str, dict] = {}  # キャッシュ
    
    async def _get_task(self, task_id: str) -> Optional[dict]:
        # 1. キャッシュ確認
        if task_id in self._tasks_cache:
            return self._tasks_cache[task_id]
        # 2. DBから取得
        task = await db.get_task(task_id)
        if task:
            self._tasks_cache[task_id] = task
        return task
```

## 結果

- ✅ サーバー再起動後もタスク保持
- ✅ 高速アクセス（キャッシュヒット時）
- ✅ DB障害時はキャッシュのみで動作（フォールバック）

## 今後の課題

- キャッシュの有効期限（TTL）設定
- 複数サーバー時のキャッシュ整合性

