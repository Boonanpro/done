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

    def test_health_endpoint(self, client):
        """GET /health - 詳細ヘルスチェック"""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"


# Note: v1 API tests (TestWishAPI, TestReviseAPI, TestTaskAPI) were removed
# as those endpoints were deleted in the v1 to v2 migration.
# v2 uses /api/v1/chat/dan/messages/stream for the new streaming API.
