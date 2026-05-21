"""
inspector_overrides の API エンドポイント
"""
import os
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.services.auth_service import TokenData, decode_access_token
from app.services.inspector_overrides_service import InspectorOverridesService
from app.services.inspector_writeback_core import (
    apply_override_for_slug,
    remove_element_for_slug,
    restore_file_content,
)
from app.models.inspector_overrides_schemas import (
    OverrideUpsert,
    OverrideResponse,
    DeleteElementRequest,
    RestoreFileRequest,
)

router = APIRouter(prefix="/inspector-overrides", tags=["inspector-overrides"])
security = HTTPBearer(auto_error=False)
ACCESS_TOKEN_COOKIE = "done_access_token"

# DAN_DEV_NO_AUTH=1 が立っていれば、Playwright 等の自動テストから認証なしで叩ける。
# 本番では絶対に立てない（test-edit artifact 以外も無制限に書き換え可能になる）。
_DEV_NO_AUTH = os.environ.get("DAN_DEV_NO_AUTH") == "1"
_DEV_TEST_USER_ID = "00000000-0000-0000-0000-000000000000"


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> TokenData:
    if _DEV_NO_AUTH:
        # dev test 用の fake user。実 DB には影響しない（direct-write は file 操作のみ）。
        from datetime import datetime, timedelta, timezone
        return TokenData(
            user_id=_DEV_TEST_USER_ID,
            email="dev-test@local",
            exp=datetime.now(timezone.utc) + timedelta(hours=24),
        )
    token = request.cookies.get(ACCESS_TOKEN_COOKIE)
    if not token and credentials:
        token = credentials.credentials
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    td = decode_access_token(token)
    if not td:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return td


def get_service() -> InspectorOverridesService:
    return InspectorOverridesService()


@router.post("", response_model=OverrideResponse)
async def upsert_override(
    data: OverrideUpsert,
    user: TokenData = Depends(get_current_user),
    service: InspectorOverridesService = Depends(get_service),
):
    result = await service.upsert(
        artifact_slug=data.artifact_slug,
        element_key=data.element_key,
        styles=data.styles,
        attrs=data.attrs,
        user_id=user.user_id,
        project_id=str(data.project_id) if data.project_id else None,
        replace_attrs=data.replace_attrs,
    )
    return result


@router.post("/direct-write")
async def direct_write_override(
    data: OverrideUpsert,
    user: TokenData = Depends(get_current_user),
):
    """Inspector の編集を DB ではなく直接 JSX ファイルに書き込む。

    ローカル dev 環境専用。Vercel など read-only FS では使えない。
    成功時は HMR で即時反映、ユーザーが git commit & push するまで本番には届かない。
    """
    result = apply_override_for_slug(
        slug=data.artifact_slug,
        element_key=data.element_key,
        styles=data.styles or {},
        attrs=data.attrs or {},
    )
    if not result["applied"] and result["reason"] and "not found" in result["reason"]:
        raise HTTPException(status_code=404, detail=result["reason"])
    return result


@router.post("/restore-file")
async def restore_file(
    data: RestoreFileRequest,
    user: TokenData = Depends(get_current_user),
):
    """Undo 用: artifact 配下のファイルを指定内容で完全置換する。

    安全策: `frontend/src/app/artifacts/<slug>/` 配下に限定、.tsx/.ts/.css/.js/.jsx のみ。
    """
    result = restore_file_content(
        slug=data.artifact_slug,
        file_path_rel=data.file_path,
        content=data.content,
    )
    if not result["restored"]:
        if result["reason"] and ("outside" in result["reason"] or "unsupported" in result["reason"]):
            raise HTTPException(status_code=400, detail=result["reason"])
        # no diff の場合は 200 を返す（既に目的の状態）
    return result


@router.post("/delete-element")
async def delete_element(
    data: DeleteElementRequest,
    user: TokenData = Depends(get_current_user),
    service: InspectorOverridesService = Depends(get_service),
):
    """`data-edit-id` を持つ JSX 要素をブロックごと完全削除する（ハード削除）。

    動作:
    - JSX ファイルから開きタグ〜閉じタグまでを物理削除（self-closing は単体削除）
    - 削除後、その element_key に紐づく inspector_overrides 行も DB から消す
    - HMR でローカルに即時反映、本番は git commit & push 後の再ビルドで反映

    制約:
    - html/body/head/main など page 全体を壊すタグは拒否
    - レガシー DOM パスキー (`@` なし) は非対応
    """
    result = remove_element_for_slug(
        slug=data.artifact_slug,
        element_key=data.element_key,
    )
    if not result["removed"]:
        if result["reason"] and "not found" in result["reason"]:
            raise HTTPException(status_code=404, detail=result["reason"])
        if result["reason"]:
            raise HTTPException(status_code=400, detail=result["reason"])
    # JSX 削除に成功したら、対応する override 行もクリーンアップ
    try:
        await service.delete_one(data.artifact_slug, data.element_key, user.user_id)
    except Exception:
        # 残骸 override は害がないので失敗しても OK
        pass
    return result


@router.get("", response_model=List[OverrideResponse])
async def list_overrides(
    slug: str = Query(..., min_length=1),
    user: TokenData = Depends(get_current_user),
    service: InspectorOverridesService = Depends(get_service),
):
    return await service.list_by_slug(slug, user.user_id)


@router.get("/public", response_model=List[OverrideResponse])
async def list_public_overrides(
    slug: str = Query(..., min_length=1),
    service: InspectorOverridesService = Depends(get_service),
):
    return await service.list_public_by_slug(slug)


@router.delete("")
async def clear_overrides(
    slug: str = Query(..., min_length=1),
    element_key: Optional[str] = Query(None),
    user: TokenData = Depends(get_current_user),
    service: InspectorOverridesService = Depends(get_service),
):
    if element_key:
        ok = await service.delete_one(slug, element_key, user.user_id)
        return {"deleted": 1 if ok else 0}
    count = await service.delete_by_slug(slug, user.user_id)
    return {"deleted": count}
