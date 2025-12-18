"""
API自動テスト
動作確認済みのAPIを自動テスト化

テスト実行: pytest tests/test_api.py -v
"""
import pytest


class TestHealthCheck:
    """ヘルスチェックAPI"""
    
    def test_root_endpoint(self, client):
        """GET / - ヘルスチェック"""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"


class TestWishAPI:
    """お願いを送るAPI"""
    
    def test_wish_simple(self, client):
        """POST /api/v1/wish - 簡単なお願い（確認不要）"""
        response = client.post(
            "/api/v1/wish",
            json={"wish": "What is the weather today?"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "task_id" in data
        assert "message" in data
        assert "proposed_actions" in data
        assert "requires_confirmation" in data
    
    def test_wish_requires_confirmation(self, client):
        """POST /api/v1/wish - 購入系のお願い（確認必要）"""
        response = client.post(
            "/api/v1/wish",
            json={"wish": "I want to buy a book"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["requires_confirmation"] == True
    
    def test_wish_japanese_action_first(self, client):
        """POST /api/v1/wish - 日本語の願望でアクションファースト提案"""
        response = client.post(
            "/api/v1/wish",
            json={"wish": "PCを新調したい"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "task_id" in data
        assert "proposal_detail" in data
        # アクションファーストで提案が返ってくることを確認
        assert data["requires_confirmation"] == True
        # 提案詳細に【アクション】が含まれることを確認
        if data["proposal_detail"]:
            assert "【アクション】" in data["proposal_detail"]


class TestTaskAPI:
    """タスク関連API"""
    
    def test_task_list(self, client):
        """GET /api/v1/tasks - タスク一覧"""
        response = client.get("/api/v1/tasks")
        assert response.status_code == 200
        data = response.json()
        assert "tasks" in data
    
    def test_task_get_not_found(self, client):
        """GET /api/v1/task/{id} - 存在しないタスク"""
        response = client.get("/api/v1/task/nonexistent-id")
        assert response.status_code == 404
    
    def test_task_workflow(self, client):
        """タスクの一連の流れをテスト"""
        # 1. お願いを送る
        wish_response = client.post(
            "/api/v1/wish",
            json={"wish": "I want to buy a laptop"}
        )
        assert wish_response.status_code == 200
        task_id = wish_response.json()["task_id"]
        
        # 2. タスク状態を確認
        task_response = client.get(f"/api/v1/task/{task_id}")
        assert task_response.status_code == 200
        task_data = task_response.json()
        assert task_data["id"] == task_id
        assert task_data["original_wish"] == "I want to buy a laptop"
        
        # 3. タスクを承認
        confirm_response = client.post(f"/api/v1/task/{task_id}/confirm")
        assert confirm_response.status_code == 200
        confirm_data = confirm_response.json()
        assert confirm_data["status"] == "executing"
        
        # 4. 完了を確認
        final_response = client.get(f"/api/v1/task/{task_id}")
        assert final_response.status_code == 200
        final_data = final_response.json()
        assert final_data["status"] == "completed"
