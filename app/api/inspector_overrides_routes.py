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


@router.post("/publish")
async def publish_overrides(
    slug: str = Query(..., min_length=1),
    user: TokenData = Depends(get_current_user),
    service: InspectorOverridesService = Depends(get_service),
):
    """slug の全 override を JSX に焼き込み、done-artifacts へ自動公開する。

    Inspector のライブ編集を「公開ボタンを押さずに」本番反映するための自動公開トリガ。
    フロントが編集保存後にデバウンスして叩く。焼き込み(DB→JSX)後に
    schedule_artifact_git_publish で done-artifacts へ push し、Vercel 再ビルドで
    公開URL/クライアントに反映される（〜1〜2分）。DB の override は消さない
    （ライブプレビューの継続適用のため。JSX と内容一致で無害）。
    """
    overrides = await service.list_by_slug(slug, user.user_id)
    applied = 0
    skipped: list[str] = []
    for ov in overrides:
        try:
            r = apply_override_for_slug(
                slug=slug,
                element_key=ov.get("element_key", ""),
                styles=ov.get("styles") or {},
                attrs=ov.get("attrs") or {},
            )
            if r.get("applied"):
                applied += 1
            elif r.get("reason"):
                skipped.append(f"{ov.get('element_key')}: {r['reason']}")
        except Exception as e:  # noqa: BLE001 - 1件の失敗で全体を止めない
            skipped.append(f"{ov.get('element_key')}: {e}")

    publish_scheduled = False
    try:
        from app.services.artifact_git_publish import schedule_artifact_git_publish
        schedule_artifact_git_publish([slug])
        publish_scheduled = True
    except Exception as e:  # noqa: BLE001
        skipped.append(f"publish schedule failed: {e}")

    return {
        "slug": slug,
        "overrides": len(overrides),
        "applied": applied,
        "publish_scheduled": publish_scheduled,
        "skipped": skipped,
    }


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
    """`data-edit-id` を持つ JSX 要素を **非破壊的に隠す**（display:none を注入）。

    旧仕様 (2026-05-21 以前) は JSX から要素ごと物理削除していた。これが
    Inspector 経由で `<MultiStepInquiry />` 等のコンポーネント呼び出しを
    JSX から消し、後の「sync」commit でその削除がそのまま git に流れる
    事故を起こした（2026-05-10 commit d9e49be / 2026-05-20 stash@{0}）。

    新仕様:
    - 物理削除ではなく `style.display = "none"` の override を DB に upsert
    - 直書き (apply_override_for_slug) も走らせて JSX に `style={{...}}` を注入
    - JSX の構造（import / コンポーネント呼び出し）は保たれる
    - 後から「やっぱり戻したい」時は override を消すかインスペクタで unhide
    - 本当に物理削除したい場合は、開発者がエディタで JSX を編集する

    制約: レガシー DOM パスキー (`@` なし) は非対応。
    """
    hide_styles = {"display": "none"}
    saved = await service.upsert(
        artifact_slug=data.artifact_slug,
        element_key=data.element_key,
        styles=hide_styles,
        attrs=None,
        user_id=user.user_id,
        replace_attrs=False,
    )
    write_result = apply_override_for_slug(
        slug=data.artifact_slug,
        element_key=data.element_key,
        styles=hide_styles,
        attrs=None,
    )
    if not write_result["applied"] and write_result.get("reason") and "not found" in write_result["reason"]:
        raise HTTPException(status_code=404, detail=write_result["reason"])
    return {
        "hidden": True,
        "removed": True,  # 既存クライアント互換: UI 上は「削除」表示
        "file": write_result.get("file"),
        "override_id": saved.get("id"),
        "reason": write_result.get("reason"),
        "mode": "hide_via_display_none",
    }


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
