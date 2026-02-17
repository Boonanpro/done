"""
File Upload API Routes
Handles file uploads for chat attachments
"""

import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.api.chat_routes import get_current_user
from app.models import User

router = APIRouter(tags=["files"])

# Upload directory - use a dedicated folder in the project
UPLOAD_DIR = Path("D:/done/uploads")
UPLOAD_DIR.mkdir(exist_ok=True, parents=True)

# Allowed file extensions
ALLOWED_EXTENSIONS = {
    "image": {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"},
    "document": {".pdf", ".txt", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx"},
    "archive": {".zip", ".rar", ".7z", ".tar", ".gz"},
    "audio": {".mp3", ".wav", ".ogg", ".m4a", ".flac"},
    "video": {".mp4", ".avi", ".mov", ".mkv", ".webm"},
}

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB


class FileUploadResponse(BaseModel):
    id: str
    filename: str
    url: str
    content_type: str
    size: int
    created_at: str


def get_file_type(filename: str) -> str:
    """Determine file type from extension"""
    ext = Path(filename).suffix.lower()
    for file_type, extensions in ALLOWED_EXTENSIONS.items():
        if ext in extensions:
            return file_type
    return "other"


def is_allowed_file(filename: str) -> bool:
    """Check if file extension is allowed"""
    ext = Path(filename).suffix.lower()
    for extensions in ALLOWED_EXTENSIONS.values():
        if ext in extensions:
            return True
    return False


@router.post("/upload", response_model=FileUploadResponse)
async def upload_file(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user)
):
    """
    Upload a file for chat attachment
    """
    # Validate file size
    file.file.seek(0, 2)
    file_size = file.file.tell()
    file.file.seek(0)
    
    if file_size > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File size exceeds 10MB limit")
    
    # Validate file extension
    if not is_allowed_file(file.filename):
        raise HTTPException(
            status_code=400, 
            detail="File type not allowed. Allowed types: images, documents, archives, audio, video"
        )
    
    # Generate unique filename
    file_ext = Path(file.filename).suffix
    unique_filename = f"{uuid.uuid4()}{file_ext}"
    file_path = UPLOAD_DIR / unique_filename
    
    # Save file
    try:
        content = await file.read()
        with open(file_path, "wb") as f:
            f.write(content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save file: {str(e)}")
    
    # Generate URL
    file_url = f"/api/v1/files/{unique_filename}"
    
    return FileUploadResponse(
        id=str(uuid.uuid4()),
        filename=file.filename,
        url=file_url,
        content_type=file.content_type,
        size=file_size,
        created_at=datetime.utcnow().isoformat()
    )


@router.get("/{filename}")
async def get_file(filename: str):
    """
    Serve uploaded files
    """
    file_path = UPLOAD_DIR / filename
    
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    
    return FileResponse(file_path)
