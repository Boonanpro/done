"""
Pytest configuration and fixtures
"""
import pytest
from fastapi.testclient import TestClient

from main import app


@pytest.fixture
def client():
    """テスト用のHTTPクライアント"""
    return TestClient(app)
