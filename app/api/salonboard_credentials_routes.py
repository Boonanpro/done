"""
salonboard_credentials のAPIエンドポイント。

アプリ自身にログイン機能を持たない設計のため、識別はブラウザが生成する
device_id (UUID) を使う。平文の login_id / password は GET レスポンスに
決して含めない。復号は自動投稿処理 (将来実装) からのみ呼ぶ。
"""
from fastapi import APIRouter, HTTPException, Query

from app.models.salonboard_credentials_schemas import (
    SalonboardCredentialsSet,
    SalonboardCredentialsStatus,
)
from app.services.salonboard_credentials_service import (
    SalonboardCredentialsService,
)

router = APIRouter(
    prefix="/salonboard-credentials",
    tags=["salonboard-credentials"],
)


def _get_service() -> SalonboardCredentialsService:
    return SalonboardCredentialsService()


@router.get("/status", response_model=SalonboardCredentialsStatus)
async def get_status(device_id: str = Query(..., min_length=8, max_length=128)):
    """device_id に紐づく設定状態を返す。平文は含まない。"""
    return await _get_service().get_status(device_id)


@router.post("", response_model=SalonboardCredentialsStatus)
async def set_credentials(payload: SalonboardCredentialsSet):
    """サロンボードのログイン情報を暗号化して保存する。
    同じ device_id があれば上書き。"""
    if not payload.consent:
        raise HTTPException(
            status_code=400, detail="秘密保持と取扱いへの同意が必要です"
        )
    svc = _get_service()
    saved = await svc.save(
        device_id=payload.device_id,
        stylist_name=payload.stylist_name,
        login_id=payload.login_id,
        password=payload.password,
        email=payload.email,
    )
    if not saved:
        raise HTTPException(status_code=500, detail="保存に失敗しました")
    return await svc.get_status(payload.device_id)


@router.delete("")
async def delete_credentials(
    device_id: str = Query(..., min_length=8, max_length=128),
):
    """設定を削除する。"""
    svc = _get_service()
    deleted = await svc.delete(device_id)
    return {"deleted": deleted}
