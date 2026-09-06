"""
成果物ページ本文（BlockNote ブロック）の API。

- 読み取りは public（slug を知っていれば閲覧できる。成果物の公開URLと同じ範囲）
- 書き込みは「編集の鍵 (X-Edit-Key)」か「オーナーのアクセストークン」のどちらか
- GET /markdown はダン向け（scripts/artifact_doc.py と同じ内容）
"""
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import PlainTextResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.models.artifact_documents_schemas import (
    ArtifactDocumentAccessRequest,
    ArtifactDocumentAccessResponse,
    ArtifactDocumentResponse,
    ArtifactDocumentRevisionResponse,
    ArtifactDocumentSave,
    ArtifactDocumentSaveResponse,
)
from app.services.artifact_documents_service import ArtifactDocumentsService, ConflictError
from app.services.auth_service import decode_access_token

router = APIRouter(prefix="/artifact-documents", tags=["artifact_documents"])
security = HTTPBearer(auto_error=False)
ACCESS_TOKEN_COOKIE = "done_access_token"


def get_service() -> ArtifactDocumentsService:
    return ArtifactDocumentsService()


def _optional_user_id(request: Request, credentials: Optional[HTTPAuthorizationCredentials]) -> Optional[str]:
    token = request.cookies.get(ACCESS_TOKEN_COOKIE)
    if not token and credentials:
        token = credentials.credentials
    if not token:
        return None
    td = decode_access_token(token)
    return td.user_id if td else None


def _editor_for(service: ArtifactDocumentsService, row: dict, user_id: Optional[str], edit_key: Optional[str]) -> Optional[str]:
    if service.is_owner(row, user_id):
        return "owner"
    if service.verify_key(row, edit_key):
        return "page"
    return None


@router.get("/{slug}", response_model=ArtifactDocumentResponse)
async def get_document(slug: str, service: ArtifactDocumentsService = Depends(get_service)):
    row = await service.get(slug)
    if not row:
        raise HTTPException(status_code=404, detail="見つかりません")
    return service.public_view(row)


@router.get("/{slug}/markdown", response_class=PlainTextResponse)
async def get_document_markdown(slug: str, service: ArtifactDocumentsService = Depends(get_service)):
    row = await service.get(slug)
    if not row:
        raise HTTPException(status_code=404, detail="見つかりません")
    return PlainTextResponse(service.markdown(row), media_type="text/markdown; charset=utf-8")


@router.get("/{slug}/revisions", response_model=list[ArtifactDocumentRevisionResponse])
async def list_revisions(slug: str, service: ArtifactDocumentsService = Depends(get_service)):
    return await service.revisions(slug)


@router.post("/{slug}/access", response_model=ArtifactDocumentAccessResponse)
async def check_access(
    slug: str,
    data: ArtifactDocumentAccessRequest,
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    service: ArtifactDocumentsService = Depends(get_service),
):
    row = await service.get(slug)
    if not row:
        raise HTTPException(status_code=404, detail="見つかりません")
    editor = _editor_for(service, row, _optional_user_id(request, credentials), data.edit_key)
    return {"can_edit": editor is not None, "editor": editor}


@router.put("/{slug}", response_model=ArtifactDocumentSaveResponse)
async def save_document(
    slug: str,
    data: ArtifactDocumentSave,
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    x_edit_key: Optional[str] = Header(default=None, alias="X-Edit-Key"),
    service: ArtifactDocumentsService = Depends(get_service),
):
    row = await service.get(slug)
    if not row:
        raise HTTPException(status_code=404, detail="見つかりません")
    editor = _editor_for(service, row, _optional_user_id(request, credentials), x_edit_key)
    if not editor:
        raise HTTPException(status_code=403, detail="編集の鍵が要ります")
    try:
        saved = await service.save(slug, data.blocks, title=data.title, editor=editor, base_version=data.base_version)
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail={"current_version": exc.current_version})
    return {
        "version": int(saved.get("version") or 1),
        "saved_at": saved.get("last_saved_at"),
        "changed": bool(saved.get("changed")),
        "changes": saved.get("changes") or [],
    }
