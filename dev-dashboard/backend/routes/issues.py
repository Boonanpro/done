"""
Issues Router - イシュー関連のAPI
"""
from typing import Optional
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from services.issue_service import get_issue_service
from config import BROWSER_LOGS_DIR

router = APIRouter(tags=["issues"])


class IssueUpdateRequest(BaseModel):
    """イシュー更新リクエスト"""
    status: Optional[str] = None


@router.get("/issues")
async def get_issues(
    status: Optional[str] = Query(None, description="ステータスでフィルタ"),
    site: Optional[str] = Query(None, description="サイトでフィルタ"),
    issue_type: Optional[str] = Query(None, description="タイプでフィルタ"),
    limit: int = Query(50, ge=1, le=100, description="取得件数"),
    offset: int = Query(0, ge=0, description="オフセット"),
    sort_by: str = Query("created_at", description="ソートカラム"),
    sort_order: str = Query("desc", description="ソート順序"),
):
    """イシュー一覧を取得"""
    try:
        print(f"[DEBUG] get_issues called: limit={limit}, offset={offset}")
        service = get_issue_service()
        result = await service.get_issues(
            status=status,
            site=site,
            issue_type=issue_type,
            limit=limit,
            offset=offset,
            sort_by=sort_by,
            sort_order=sort_order,
        )
        print(f"[DEBUG] get_issues success: {len(result.get('issues', []))} issues")
        return result
    except Exception as e:
        print(f"[ERROR] get_issues failed: {e}")
        import traceback
        traceback.print_exc()
        raise


@router.get("/issues/filters")
async def get_filter_options():
    """フィルタ用の選択肢を取得"""
    try:
        print("[DEBUG] get_filter_options called")
        service = get_issue_service()
        sites = await service.get_unique_sites()
        types = await service.get_unique_types()
        print(f"[DEBUG] get_filter_options success: sites={sites}, types={types}")
        return {
            "statuses": ["open", "in_progress", "resolved", "wont_fix"],
            "sites": sites,
            "types": types,
        }
    except Exception as e:
        print(f"[ERROR] get_filter_options failed: {e}")
        import traceback
        traceback.print_exc()
        raise


@router.get("/stats")
async def get_stats():
    """統計情報を取得"""
    try:
        print("[DEBUG] get_stats called")
        service = get_issue_service()
        result = await service.get_stats()
        print(f"[DEBUG] get_stats success: total={result.get('total', 0)}")
        return result
    except Exception as e:
        print(f"[ERROR] get_stats failed: {e}")
        import traceback
        traceback.print_exc()
        raise


@router.get("/issues/{issue_id}")
async def get_issue(issue_id: str):
    """イシュー詳細を取得"""
    service = get_issue_service()
    issue = await service.get_issue(issue_id)

    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")

    return issue


@router.patch("/issues/{issue_id}")
async def update_issue(issue_id: str, request: IssueUpdateRequest):
    """イシューを更新"""
    service = get_issue_service()
    issue = await service.update_issue(
        issue_id=issue_id,
        status=request.status,
    )

    if not issue:
        raise HTTPException(status_code=404, detail="Issue not found")

    return {"success": True, "issue": issue}


@router.get("/issues/{issue_id}/screenshot/{filename:path}")
async def get_screenshot(issue_id: str, filename: str):
    """スクリーンショットを取得"""
    # セキュリティ: パストラバーサル防止
    if ".." in filename or filename.startswith("/"):
        raise HTTPException(status_code=400, detail="Invalid filename")

    filepath = BROWSER_LOGS_DIR / filename

    if not filepath.exists():
        raise HTTPException(status_code=404, detail="Screenshot not found")

    # BROWSER_LOGS_DIR外へのアクセス防止
    try:
        filepath.resolve().relative_to(BROWSER_LOGS_DIR.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied")

    return FileResponse(
        filepath,
        media_type="image/png",
        filename=filepath.name,
    )


@router.get("/issues/{issue_id}/html/{filename:path}")
async def get_html_snapshot(issue_id: str, filename: str):
    """HTMLスナップショットを取得"""
    # セキュリティ: パストラバーサル防止
    if ".." in filename or filename.startswith("/"):
        raise HTTPException(status_code=400, detail="Invalid filename")

    filepath = BROWSER_LOGS_DIR / filename

    if not filepath.exists():
        raise HTTPException(status_code=404, detail="HTML snapshot not found")

    # BROWSER_LOGS_DIR外へのアクセス防止
    try:
        filepath.resolve().relative_to(BROWSER_LOGS_DIR.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied")

    return FileResponse(
        filepath,
        media_type="text/html",
        filename=filepath.name,
    )
