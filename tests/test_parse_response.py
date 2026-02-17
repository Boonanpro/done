"""
_parse_response のユニットテスト

ダン出力問題の根本解決 - フィルタリング検証
"""

import pytest
import sys
from pathlib import Path

# プロジェクトルートをパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.agent.v2.runner import AgentRunner
from app.agent.v2.session import Session, State


class TestParseResponse:
    """_parse_response のテスト"""

    def setup_method(self):
        """各テストの前にセットアップ"""
        # ダミーセッション
        self.session = Session(
            session_id="test",
            user_id="test_user",
        )
        self.runner = AgentRunner(session=self.session)

    def test_state_detection(self):
        """[STATE:] が検出され、ユーザー応答から除外される"""
        response = "[STATE: RESEARCH]\n検索しています..."
        result = self.runner._parse_response(response)

        assert result["new_state"] == State.RESEARCH
        assert "[STATE:" not in result["user_response"]
        assert "検索しています..." in result["user_response"]

    def test_step_detection(self):
        """[STEP] が検出され、ユーザー応答から除外される"""
        response = "[STEP] ログイン中\n[STEP] 検索実行中\n結果を表示します"
        result = self.runner._parse_response(response)

        assert len(result["steps"]) == 2
        assert "ログイン中" in result["steps"]
        assert "[STEP]" not in result["user_response"]
        assert "結果を表示します" in result["user_response"]

    def test_tool_call_filtered(self):
        """[TOOL:] とパラメータがフィルタリングされる"""
        response = """検索します。

[TOOL: ex-reservation search]
departure: 東京
arrival: 新大阪
date: 2026-01-20
time: 19:00

結果をお待ちください。"""

        result = self.runner._parse_response(response)

        assert "[TOOL:" not in result["user_response"]
        assert "departure:" not in result["user_response"]
        assert "arrival:" not in result["user_response"]
        assert "検索します。" in result["user_response"]
        assert "結果をお待ちください。" in result["user_response"]

    def test_tool_call_in_code_block_filtered(self):
        """コードブロック内の[TOOL:]もフィルタリングされる（プロンプト例コピー対策）"""
        response = """検索を実行します。

```
[TOOL: ex-reservation search]
departure: 東京
arrival: 新大阪
```

お待ちください。"""

        result = self.runner._parse_response(response)

        assert "[TOOL:" not in result["user_response"]
        assert "departure:" not in result["user_response"]
        assert "検索を実行します。" in result["user_response"]
        assert "お待ちください。" in result["user_response"]

    def test_normal_code_block_preserved(self):
        """通常のコードブロック（Pythonコード等）は維持される"""
        response = """Pythonでhello worldを表示するコードです：

```python
print("Hello, World!")
```

これで完了です。"""

        result = self.runner._parse_response(response)

        assert "```python" in result["user_response"]
        assert 'print("Hello, World!")' in result["user_response"]
        assert "```" in result["user_response"]

    def test_mixed_content(self):
        """STATE, STEP, TOOL が混在した複雑なレスポンス"""
        response = """[STATE: RESEARCH]
[STEP] EX予約にログイン中
[STEP] 新幹線を検索中

検索しています...

[TOOL: ex-reservation search]
departure: 東京
arrival: 新大阪

結果が見つかりました！

【列車】のぞみ263号
【区間】東京 → 新大阪
【時刻】19:00発 → 21:29着"""

        result = self.runner._parse_response(response)

        assert result["new_state"] == State.RESEARCH
        assert len(result["steps"]) == 2
        assert "[STATE:" not in result["user_response"]
        assert "[STEP]" not in result["user_response"]
        assert "[TOOL:" not in result["user_response"]
        assert "departure:" not in result["user_response"]
        assert "検索しています..." in result["user_response"]
        assert "結果が見つかりました！" in result["user_response"]
        assert "【列車】のぞみ263号" in result["user_response"]

    def test_consecutive_blank_lines_normalized(self):
        """フィルタリング後の連続空行が1つにまとめられる"""
        response = """こんにちは

[TOOL: test action]
param: value



さようなら"""

        result = self.runner._parse_response(response)

        # 3つ以上の連続空行は2つにまとめられる
        assert "\n\n\n" not in result["user_response"]

    def test_tool_without_params(self):
        """パラメータなしのツール呼び出し"""
        response = """キャンセルします。

[TOOL: ex-reservation cancel]

処理中です。"""

        result = self.runner._parse_response(response)

        assert "[TOOL:" not in result["user_response"]
        assert "キャンセルします。" in result["user_response"]
        assert "処理中です。" in result["user_response"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
