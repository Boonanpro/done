"""
Meeting Room schemas - WebSocket message types for real-time presentation meetings.
"""
from pydantic import BaseModel
from typing import Optional
from enum import Enum


class MeetingPhase(str, Enum):
    """Meeting lifecycle phases."""
    PREPARING = "preparing"       # Generating slides
    PRESENTING = "presenting"     # Dan is presenting a slide
    PAUSED = "paused"             # Dan paused (user interrupted)
    QA = "qa"                     # Q&A mode
    RESEARCHING = "researching"   # Dan is researching
    ENDED = "ended"


class SlideContent(BaseModel):
    """A single slide in the presentation."""
    index: int
    total: int
    title: str
    bullets: list[str] = []
    note: str = ""                # Speaker notes / narration script
    highlight: Optional[str] = None  # Key takeaway


class MeetingState(BaseModel):
    """Full meeting state pushed to client."""
    phase: MeetingPhase
    current_slide: int = 0
    total_slides: int = 0
    topic: str = ""


# --- WebSocket message types (Server → Client) ---

class WsSlide(BaseModel):
    type: str = "slide"
    slide: SlideContent
    narration: str = ""           # Text that will be spoken


class WsAudio(BaseModel):
    """Audio chunk (sent as binary frame, not JSON)."""
    pass


class WsStateUpdate(BaseModel):
    type: str = "state"
    state: MeetingState


class WsTranscript(BaseModel):
    type: str = "transcript"
    speaker: str                  # "dan" or "user"
    text: str


class WsError(BaseModel):
    type: str = "error"
    message: str


# --- WebSocket message types (Client → Server) ---

class WsAuth(BaseModel):
    type: str = "auth"
    token: str = ""
    session_id: Optional[str] = None


class WsStart(BaseModel):
    type: str = "start"
    proposal_content: str = ""
    topic: str = ""


class WsUserMessage(BaseModel):
    type: str = "user_message"
    text: str


class WsControl(BaseModel):
    type: str = "control"
    action: str                   # "pause", "resume", "next", "prev", "end"
