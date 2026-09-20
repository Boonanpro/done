"""Private loopback-only browser ownership API for room MCP processes."""
from typing import Literal
import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.services import browser_lifecycle

router = APIRouter()


class BrowserSessionRequest(BaseModel):
    operation: Literal["ensure", "hold", "hold_auth", "release", "release_auth", "close", "status"]
    room_id: str = Field(min_length=1, max_length=256)
    reason: str = Field(default="", max_length=500)


@router.post("/internal/browser/session")
def browser_session(body: BrowserSessionRequest, request: Request):
    if (not request.client or request.client.host not in {"127.0.0.1", "::1"}
            or request.headers.get("origin")
            or not browser_lifecycle.authorized(request.headers.get("x-dan-browser-token", ""))):
        raise HTTPException(403, "Local browser manager authentication required")
    try:
        return browser_lifecycle.manage_session(body.operation, body.room_id, body.reason)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        logging.getLogger(__name__).exception("Browser lifecycle operation failed: %s", body.operation)
        raise HTTPException(503, "Browser manager operation failed; inspect Core logs") from exc
