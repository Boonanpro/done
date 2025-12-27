"""
E2E Test Configuration

Loads .env.test for test environment settings.
Uses real services (Supabase, Claude, Playwright).
"""
import pytest
import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def pytest_configure(config):
    """Configure pytest for E2E tests"""
    # Load test environment variables
    from dotenv import load_dotenv
    
    env_test_path = project_root / ".env.test"
    if env_test_path.exists():
        load_dotenv(env_test_path, override=True)
        print(f"\n✅ Loaded test environment from {env_test_path}")
    else:
        print(f"\n⚠️ Warning: {env_test_path} not found!")
        print("   Copy env_test_example.txt to .env.test and configure it.")
        print("   E2E tests require a separate Supabase test project.\n")


@pytest.fixture(scope="session")
def app():
    """Create FastAPI test application"""
    from main import app
    return app


@pytest.fixture(scope="session")
def client(app):
    """Create test client"""
    from fastapi.testclient import TestClient
    return TestClient(app)


@pytest.fixture(scope="session")
def auth_headers(client):
    """Get authenticated headers for API calls"""
    # Register a test user
    import uuid
    test_email = f"e2e_test_{uuid.uuid4().hex[:8]}@test.com"
    
    register_response = client.post(
        "/api/v1/chat/register",
        json={
            "email": test_email,
            "password": "TestPassword123!",
            "display_name": "E2E Test User"
        }
    )
    
    if register_response.status_code == 200:
        token = register_response.json().get("token")
        return {"Authorization": f"Bearer {token}"}
    
    # If registration fails, try login
    login_response = client.post(
        "/api/v1/chat/login",
        json={
            "email": test_email,
            "password": "TestPassword123!"
        }
    )
    
    if login_response.status_code == 200:
        token = login_response.json().get("token")
        return {"Authorization": f"Bearer {token}"}
    
    # Return empty headers if auth fails
    return {}


@pytest.fixture(scope="function")
def browser_page():
    """Create Playwright browser page for E2E tests"""
    from playwright.sync_api import sync_playwright
    
    playwright = sync_playwright().start()
    browser = playwright.chromium.launch(headless=False)  # --headed mode
    context = browser.new_context(
        viewport={"width": 1280, "height": 720},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    )
    page = context.new_page()
    
    yield page
    
    # Cleanup
    context.close()
    browser.close()
    playwright.stop()

