"""
LINE Desktop API Routes

API endpoints for controlling LINE PC application via pywinauto.
⚠️ WARNING: This may violate LINE's Terms of Service. Use at your own risk.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Any

router = APIRouter(prefix="/line", tags=["LINE"])


class SendMessageRequest(BaseModel):
    """Request to send a message"""
    recipient: str  # Friend name or chat name
    message: str


class SearchFriendRequest(BaseModel):
    """Request to search for a friend"""
    search_term: str


class ConnectRequest(BaseModel):
    """Request to connect to LINE"""
    start_if_not_running: bool = False


@router.get("/status")
async def get_line_status() -> Dict[str, Any]:
    """
    Get LINE connection status.
    
    Returns information about:
    - Whether connected to LINE
    - Whether LINE is running
    - Whether LINE is installed
    """
    try:
        from app.tools.line_desktop import get_line_controller
        controller = get_line_controller()
        return controller.get_status()
    except RuntimeError as e:
        return {
            "connected": False,
            "line_running": False,
            "line_installed": False,
            "error": str(e),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/connect")
async def connect_to_line(request: ConnectRequest) -> Dict[str, Any]:
    """
    Connect to LINE PC application.
    
    Prerequisites:
    - LINE PC must be installed
    - User must be logged in to LINE
    - LINE should be running (or set start_if_not_running=True)
    """
    try:
        from app.tools.line_desktop import get_line_controller
        controller = get_line_controller()
        
        success = controller.connect(start_if_not_running=request.start_if_not_running)
        
        if success:
            return {
                "status": "connected",
                "message": "Successfully connected to LINE",
            }
        else:
            raise HTTPException(
                status_code=400,
                detail="Failed to connect to LINE. Make sure LINE is running and logged in.",
            )
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/disconnect")
async def disconnect_from_line() -> Dict[str, Any]:
    """
    Disconnect from LINE (does not close LINE application).
    """
    try:
        from app.tools.line_desktop import get_line_controller
        controller = get_line_controller()
        controller.disconnect()
        return {"status": "disconnected", "message": "Disconnected from LINE"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/search")
async def search_friend(request: SearchFriendRequest) -> Dict[str, Any]:
    """
    Search for a friend in LINE.
    
    Args:
        search_term: Name or ID to search for
    """
    try:
        from app.tools.line_desktop import get_line_controller
        controller = get_line_controller()
        
        if not controller.is_connected():
            raise HTTPException(
                status_code=400,
                detail="Not connected to LINE. Call /connect first.",
            )
        
        success = controller.search_friend(request.search_term)
        
        if success:
            return {
                "status": "success",
                "message": f"Searched for: {request.search_term}",
            }
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Failed to search for: {request.search_term}",
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/send")
async def send_message(request: SendMessageRequest) -> Dict[str, Any]:
    """
    Send a message to a recipient via LINE.
    
    This will:
    1. Search for the recipient
    2. Select the chat
    3. Send the message
    
    ⚠️ WARNING: This action may violate LINE's Terms of Service.
    """
    try:
        from app.tools.line_desktop import get_line_controller
        controller = get_line_controller()
        
        if not controller.is_connected():
            raise HTTPException(
                status_code=400,
                detail="Not connected to LINE. Call /connect first.",
            )
        
        success = controller.send_message_to(request.recipient, request.message)
        
        if success:
            return {
                "status": "sent",
                "message": f"Message sent to {request.recipient}",
                "content": request.message[:100] + "..." if len(request.message) > 100 else request.message,
            }
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Failed to send message to: {request.recipient}",
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/debug/window-info")
async def get_window_info() -> Dict[str, Any]:
    """
    Get LINE window structure information.
    
    This is useful for debugging and understanding the UI controls.
    """
    try:
        from app.tools.line_desktop import get_line_controller
        controller = get_line_controller()
        
        if not controller.is_connected():
            raise HTTPException(
                status_code=400,
                detail="Not connected to LINE. Call /connect first.",
            )
        
        return controller.get_window_info()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
