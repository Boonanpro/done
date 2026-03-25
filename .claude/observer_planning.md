# 観察チェックリスト: 計画の記録

会話の一区切り後に自動で呼ばれる。直前の会話で計画や方針の合意・進捗変化があれば記録せよ。
該当なしなら何もせず終了。

---

## チェック内容

### 1. 計画の記録

- この会話で計画や方針が合意されたか？（ユーザーが「それでいこう」「OK」「進めて」等で承認した場面）
- 既存の計画に対して進捗があったか？（ステップの完了、新しいタスクの追加など）
- 合意や進捗が検出された場合:
  1. 合意内容（計画のタイトル、ステップ、方針）を抽出する
  2. **プロンプトで渡された `ROOM_ID` を使って** 以下のパスに書き出す:
     `~/.dan/workspace/plans/{ROOM_ID}.md`
  3. フォーマット:

```markdown
## 承認済み計画

プロジェクト: {プロジェクト名}

以下はユーザーと合意済みの計画です。この計画に従って作業してください。
計画から逸脱する必要がある場合は、必ず理由を説明してユーザーの承認を得てください。

### 完了済み
- [x] 完了したステップ

### 残タスク
- [ ] 未完了のステップ
```

  4. 既にそのROOM_IDの計画ファイルが存在する場合は、内容を読んで更新する（完了/未完了の反映）
- 合意ではなく単なる議論・検討中の場合は書き出さない。明確な承認があった場合のみ記録する。
- → 記録先: `~/.dan/workspace/plans/{ROOM_ID}.md`

### 2. プロジェクトステータスの更新

会話の状況に応じて、プロジェクトのステータスをDBで更新する。
以下のPythonスクリプトをBashで実行すること:

```python
import json
from supabase import create_client
import os
sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
# ROOM_IDからプロジェクトを検索
result = sb.table("projects").select("id,status").eq("room_id", "{ROOM_ID}").execute()
if result.data:
    project = result.data[0]
    # 新しいステータスに更新
    sb.table("projects").update({"status": "{NEW_STATUS}"}).eq("id", project["id"]).execute()
```

ステータスの判断基準:
- **in_progress**: ユーザーが計画を承認し、作業が開始された/進行中
- **completed**: 全ステップが完了した
- **paused**: ユーザーが「一旦止めて」等で中断を指示した

ステータスを変更する明確な根拠がない場合は変更しない。
