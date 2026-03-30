"""
Document Management API Routes — Dan版Notion資料管理
"""
import uuid
import hashlib
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, UploadFile, File, Form
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.services.supabase_client import get_supabase_client

router = APIRouter(prefix="/dashboard/documents", tags=["documents"])

# ============================================================
# Storage Configuration
# ============================================================

STORAGE_ROOT = Path("D:/dan-workspace/files")
THUMBNAIL_ROOT = Path("D:/dan-workspace/files/.thumbnails")
STORAGE_ROOT.mkdir(parents=True, exist_ok=True)
THUMBNAIL_ROOT.mkdir(parents=True, exist_ok=True)

ALLOWED_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg",
    ".pdf", ".txt", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".md", ".csv", ".json", ".html", ".css", ".js", ".ts", ".tsx",
    ".py", ".sh", ".yaml", ".yml", ".toml",
    ".mp3", ".wav", ".ogg", ".m4a", ".flac",
    ".mp4", ".avi", ".mov", ".mkv", ".webm",
    ".zip", ".rar", ".7z", ".tar", ".gz",
}


# ============================================================
# Pydantic Models
# ============================================================

class DocumentCreate(BaseModel):
    title: str
    description: Optional[str] = None
    content: Optional[str] = None
    doc_type: str = "file"
    parent_id: Optional[str] = None
    category_id: Optional[str] = None
    icon: Optional[str] = None
    tags: list[str] = []
    project_id: Optional[str] = None
    business_slug: Optional[str] = None
    metadata: dict = {}


class DocumentUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    content: Optional[str] = None
    parent_id: Optional[str] = None
    category_id: Optional[str] = None
    icon: Optional[str] = None
    tags: Optional[list[str]] = None
    sort_order: Optional[int] = None
    is_starred: Optional[bool] = None
    metadata: Optional[dict] = None


class CategoryCreate(BaseModel):
    name: str
    slug: str
    icon: Optional[str] = "folder"
    parent_id: Optional[str] = None
    description: Optional[str] = None
    sort_order: int = 0


class CategoryUpdate(BaseModel):
    name: Optional[str] = None
    icon: Optional[str] = None
    description: Optional[str] = None
    sort_order: Optional[int] = None


# ============================================================
# Categories
# ============================================================

@router.get("/categories")
async def list_categories():
    """カテゴリ一覧（ツリー構造）"""
    sb = get_supabase_client().client
    result = sb.table("document_categories").select("*").order("sort_order").execute()
    return {"categories": result.data}


@router.post("/categories")
async def create_category(body: CategoryCreate):
    """カテゴリ作成"""
    sb = get_supabase_client().client
    data = body.model_dump(exclude_none=True)
    result = sb.table("document_categories").insert(data).execute()
    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to create category")
    return {"category": result.data[0]}


@router.patch("/categories/{category_id}")
async def update_category(category_id: str, body: CategoryUpdate):
    """カテゴリ更新"""
    sb = get_supabase_client().client
    data = body.model_dump(exclude_none=True)
    if not data:
        raise HTTPException(status_code=400, detail="No fields to update")
    result = sb.table("document_categories").update(data).eq("id", category_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Category not found")
    return {"category": result.data[0]}


# ============================================================
# Documents CRUD
# ============================================================

@router.get("")
async def list_documents(
    parent_id: Optional[str] = Query(None),
    category_id: Optional[str] = Query(None),
    doc_type: Optional[str] = Query(None),
    tag: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    is_starred: Optional[bool] = Query(None),
    sort_by: str = Query("updated_at"),
    sort_dir: str = Query("desc"),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
):
    """ドキュメント一覧取得（フィルター・ソート対応）"""
    sb = get_supabase_client().client
    query = sb.table("documents").select(
        "*, document_files(id, filename, original_name, file_url, mime_type, file_size, version, is_current, thumbnail_path)",
        count="exact"
    ).eq("is_deleted", False)

    # Filter by parent (root level if None)
    if parent_id:
        query = query.eq("parent_id", parent_id)
    elif parent_id is None and not search:
        query = query.is_("parent_id", "null")

    if category_id:
        query = query.eq("category_id", category_id)
    if doc_type:
        query = query.eq("doc_type", doc_type)
    if is_starred is not None:
        query = query.eq("is_starred", is_starred)
    if tag:
        query = query.contains("tags", [tag])
    if search:
        query = query.or_(f"title.ilike.%{search}%,description.ilike.%{search}%")

    # Sort
    desc = sort_dir == "desc"
    query = query.order(sort_by, desc=desc)
    query = query.range(offset, offset + limit - 1)

    result = query.execute()

    return {
        "documents": result.data,
        "total": result.count or 0,
        "limit": limit,
        "offset": offset,
    }


@router.get("/tree")
async def get_document_tree():
    """サイドバー用ツリー構造（フォルダ + カテゴリ）"""
    sb = get_supabase_client().client

    # Get categories
    cats = sb.table("document_categories").select("*").order("sort_order").execute()

    # Get folders and starred items
    folders = (
        sb.table("documents")
        .select("id, title, parent_id, icon, doc_type, category_id, is_starred, sort_order")
        .eq("is_deleted", False)
        .in_("doc_type", ["folder", "collection"])
        .order("sort_order")
        .execute()
    )

    # Get recent documents
    recent = (
        sb.table("documents")
        .select("id, title, icon, doc_type, updated_at")
        .eq("is_deleted", False)
        .eq("doc_type", "file")
        .order("updated_at", desc=True)
        .limit(10)
        .execute()
    )

    return {
        "categories": cats.data,
        "folders": folders.data,
        "recent": recent.data,
    }


@router.get("/search")
async def search_documents(
    q: str = Query(..., min_length=1),
    limit: int = Query(20, le=100),
):
    """全文検索（タイトル・タグ・説明を横断）"""
    sb = get_supabase_client().client
    result = (
        sb.table("documents")
        .select("id, title, description, icon, doc_type, tags, category_id, updated_at, document_files(id, original_name, mime_type, thumbnail_path, is_current)")
        .eq("is_deleted", False)
        .or_(f"title.ilike.%{q}%,description.ilike.%{q}%")
        .order("updated_at", desc=True)
        .limit(limit)
        .execute()
    )
    return {"results": result.data, "query": q}


@router.get("/stats")
async def get_document_stats():
    """統計情報（ダッシュボードKPI用）"""
    sb = get_supabase_client().client

    total = sb.table("documents").select("id", count="exact").eq("is_deleted", False).execute()
    files = sb.table("document_files").select("file_size").eq("is_current", True).execute()
    categories = sb.table("document_categories").select("id", count="exact").execute()
    starred = sb.table("documents").select("id", count="exact").eq("is_starred", True).eq("is_deleted", False).execute()

    total_size = sum(f.get("file_size", 0) for f in (files.data or []))

    # Category distribution
    cat_dist = (
        sb.table("documents")
        .select("category_id, document_categories(name)")
        .eq("is_deleted", False)
        .not_.is_("category_id", "null")
        .execute()
    )
    cat_counts = {}
    for d in (cat_dist.data or []):
        cat_name = d.get("document_categories", {}).get("name", "不明") if d.get("document_categories") else "不明"
        cat_counts[cat_name] = cat_counts.get(cat_name, 0) + 1

    return {
        "total_documents": total.count or 0,
        "total_size_bytes": total_size,
        "total_categories": categories.count or 0,
        "starred_count": starred.count or 0,
        "category_distribution": cat_counts,
    }


@router.get("/{document_id}")
async def get_document(document_id: str):
    """ドキュメント詳細取得"""
    sb = get_supabase_client().client
    result = (
        sb.table("documents")
        .select("*, document_files(*), document_categories(*)")
        .eq("id", document_id)
        .eq("is_deleted", False)
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"document": result.data[0]}


@router.post("")
async def create_document(body: DocumentCreate):
    """ドキュメント作成（フォルダ/コレクション/ファイルメタデータ）"""
    sb = get_supabase_client().client
    data = body.model_dump(exclude_none=True)
    result = sb.table("documents").insert(data).execute()
    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to create document")
    return {"document": result.data[0]}


@router.patch("/{document_id}")
async def update_document(document_id: str, body: DocumentUpdate):
    """ドキュメント更新"""
    sb = get_supabase_client().client
    data = body.model_dump(exclude_none=True)
    if not data:
        raise HTTPException(status_code=400, detail="No fields to update")
    result = (
        sb.table("documents")
        .update(data)
        .eq("id", document_id)
        .eq("is_deleted", False)
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"document": result.data[0]}


@router.delete("/{document_id}")
async def delete_document(document_id: str):
    """ソフトデリート"""
    sb = get_supabase_client().client
    result = (
        sb.table("documents")
        .update({
            "is_deleted": True,
            "deleted_at": datetime.now(timezone.utc).isoformat(),
        })
        .eq("id", document_id)
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"deleted": True}


# ============================================================
# File Upload & Versioning
# ============================================================

def _compute_checksum(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    document_id: Optional[str] = Form(None),
    parent_id: Optional[str] = Form(None),
    category_id: Optional[str] = Form(None),
    tags: Optional[str] = Form(None),  # comma-separated
):
    """ファイルアップロード + 自動ドキュメント作成 + バージョン管理"""
    sb = get_supabase_client().client

    # Validate extension
    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"File type {ext} not allowed")

    # Read file
    content = await file.read()
    file_size = len(content)
    checksum = _compute_checksum(content)

    # Generate storage path
    file_uuid = str(uuid.uuid4())
    storage_filename = f"{file_uuid}{ext}"
    storage_path = STORAGE_ROOT / storage_filename

    # Save to local storage
    with open(storage_path, "wb") as f:
        f.write(content)

    file_url = f"/api/dashboard/documents/file/{storage_filename}"

    # If document_id provided, add as new version
    if document_id:
        # Mark previous versions as not current
        sb.table("document_files").update({"is_current": False}).eq("document_id", document_id).eq("is_current", True).execute()

        # Get next version number
        versions = sb.table("document_files").select("version").eq("document_id", document_id).order("version", desc=True).limit(1).execute()
        next_version = (versions.data[0]["version"] + 1) if versions.data else 1

        file_record = sb.table("document_files").insert({
            "document_id": document_id,
            "filename": storage_filename,
            "original_name": file.filename,
            "storage_path": str(storage_path),
            "file_url": file_url,
            "mime_type": file.content_type,
            "file_size": file_size,
            "version": next_version,
            "is_current": True,
            "checksum": checksum,
        }).execute()

        # Update document's updated_at
        sb.table("documents").update({"updated_at": datetime.now(timezone.utc).isoformat()}).eq("id", document_id).execute()

        return {
            "document_id": document_id,
            "file": file_record.data[0] if file_record.data else None,
            "version": next_version,
        }

    # No document_id — create new document + file
    tag_list = [t.strip() for t in tags.split(",")] if tags else []

    doc_data = {
        "title": Path(file.filename).stem,
        "doc_type": "file",
        "parent_id": parent_id,
        "category_id": category_id,
        "tags": tag_list,
        "metadata": {"original_filename": file.filename},
    }
    doc_result = sb.table("documents").insert(doc_data).execute()
    if not doc_result.data:
        raise HTTPException(status_code=500, detail="Failed to create document")

    new_doc_id = doc_result.data[0]["id"]

    file_record = sb.table("document_files").insert({
        "document_id": new_doc_id,
        "filename": storage_filename,
        "original_name": file.filename,
        "storage_path": str(storage_path),
        "file_url": file_url,
        "mime_type": file.content_type,
        "file_size": file_size,
        "version": 1,
        "is_current": True,
        "checksum": checksum,
    }).execute()

    return {
        "document": doc_result.data[0],
        "file": file_record.data[0] if file_record.data else None,
    }


@router.get("/file/{filename}")
async def serve_file(filename: str):
    """ファイル配信"""
    file_path = (STORAGE_ROOT / filename).resolve()
    if not file_path.is_relative_to(STORAGE_ROOT.resolve()):
        raise HTTPException(status_code=400, detail="Invalid filename")
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(file_path)


# ============================================================
# Version History
# ============================================================

@router.get("/{document_id}/versions")
async def get_versions(document_id: str):
    """バージョン履歴取得"""
    sb = get_supabase_client().client
    result = (
        sb.table("document_files")
        .select("*")
        .eq("document_id", document_id)
        .order("version", desc=True)
        .execute()
    )
    return {"versions": result.data}


# ============================================================
# Bulk Import (既存ファイル取り込み)
# ============================================================

class ImportRequest(BaseModel):
    source_dir: str = "D:/dan-workspace"
    dry_run: bool = True


@router.post("/import")
async def import_existing_files(body: ImportRequest):
    """既存ファイルを一括スキャン・取り込み（dry_run=trueでプレビュー）"""
    source = Path(body.source_dir)
    if not source.exists():
        raise HTTPException(status_code=400, detail=f"Directory not found: {body.source_dir}")

    # Scan files (skip directories we don't want to import)
    skip_dirs = {".vercel", "__pycache__", "node_modules", ".git", "proposals", "files", ".thumbnails"}
    files_found = []

    for item in source.rglob("*"):
        if item.is_dir():
            continue
        # Skip items in skip_dirs
        if any(part in skip_dirs for part in item.parts):
            continue
        rel_path = item.relative_to(source)
        files_found.append({
            "path": str(item),
            "relative_path": str(rel_path),
            "name": item.name,
            "extension": item.suffix.lower(),
            "size": item.stat().st_size,
            "modified": datetime.fromtimestamp(item.stat().st_mtime, tz=timezone.utc).isoformat(),
        })

    if body.dry_run:
        return {
            "dry_run": True,
            "files_found": len(files_found),
            "files": files_found,
        }

    # Actual import — copy files to storage and create DB records
    sb = get_supabase_client().client
    imported = []

    for file_info in files_found:
        src_path = Path(file_info["path"])
        ext = file_info["extension"]

        # Copy to storage
        file_uuid = str(uuid.uuid4())
        storage_filename = f"{file_uuid}{ext}"
        dest_path = STORAGE_ROOT / storage_filename
        shutil.copy2(src_path, dest_path)

        # Compute checksum
        with open(src_path, "rb") as f:
            checksum = _compute_checksum(f.read())

        # Create document
        doc_data = {
            "title": src_path.stem,
            "doc_type": "file",
            "metadata": {
                "original_path": file_info["relative_path"],
                "imported_at": datetime.now(timezone.utc).isoformat(),
            },
        }
        doc_result = sb.table("documents").insert(doc_data).execute()
        if not doc_result.data:
            continue
        doc_id = doc_result.data[0]["id"]

        # Detect mime type
        import mimetypes
        mime_type = mimetypes.guess_type(src_path.name)[0] or "application/octet-stream"

        # Create file record
        sb.table("document_files").insert({
            "document_id": doc_id,
            "filename": storage_filename,
            "original_name": src_path.name,
            "storage_path": str(dest_path),
            "file_url": f"/api/dashboard/documents/file/{storage_filename}",
            "mime_type": mime_type,
            "file_size": file_info["size"],
            "version": 1,
            "is_current": True,
            "checksum": checksum,
        }).execute()

        imported.append({
            "document_id": doc_id,
            "title": src_path.stem,
            "original_path": file_info["relative_path"],
        })

    return {
        "dry_run": False,
        "imported_count": len(imported),
        "imported": imported,
    }


# ============================================================
# Relations
# ============================================================

# ============================================================
# AI Chat (Claude CLI経由)
# ============================================================

class AIChatRequest(BaseModel):
    message: str


@router.post("/ai-chat")
async def ai_chat(body: AIChatRequest):
    """AIに資料整理を指示する（Claude Code CLI経由で定額プラン利用）"""
    import asyncio

    sb = get_supabase_client().client

    # Get current state for context
    docs = sb.table("documents").select("id, title, doc_type, tags, category_id, parent_id").eq("is_deleted", False).limit(200).execute()
    cats = sb.table("document_categories").select("id, name, slug").execute()

    context = f"""あなたは資料管理AIアシスタントです。以下の操作ができます：
- カテゴリの作成・更新
- ファイルのカテゴリ変更・タグ付け・リネーム・移動
- ファイルの整理方針の提案

現在のドキュメント数: {len(docs.data or [])}
現在のカテゴリ: {[c['name'] for c in (cats.data or [])]}

ドキュメント一覧（抜粋）:
{chr(10).join(f"- {d['title']} (type={d['doc_type']}, tags={d['tags']})" for d in (docs.data or [])[:30])}

ユーザーの指示: {body.message}

JSONで応答してください:
{{"response": "ユーザーへの返答テキスト", "actions": [{{"type": "create_category|update_document|move_document", "params": {{}}}}], "actions_taken": true/false}}
"""

    try:
        # Use Claude CLI via subprocess (定額プラン)
        process = await asyncio.create_subprocess_exec(
            "claude", "-p", context, "--output-format", "json",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            process.communicate(), timeout=60
        )

        import json
        result_text = stdout.decode("utf-8").strip()

        # Parse Claude's response
        try:
            # Claude CLI JSON output has a "result" field
            cli_output = json.loads(result_text)
            response_text = cli_output.get("result", result_text)

            # Try to parse the inner JSON from Claude's response
            try:
                ai_response = json.loads(response_text)
                response_msg = ai_response.get("response", response_text)
                actions = ai_response.get("actions", [])
                actions_taken = False

                # Execute actions
                for action in actions:
                    action_type = action.get("type")
                    params = action.get("params", {})

                    if action_type == "create_category":
                        sb.table("document_categories").insert({
                            "name": params.get("name"),
                            "slug": params.get("slug", params.get("name", "").lower().replace(" ", "-")),
                            "icon": params.get("icon", "folder"),
                            "description": params.get("description"),
                        }).execute()
                        actions_taken = True

                    elif action_type == "update_document":
                        doc_id = params.get("id")
                        update_data = {k: v for k, v in params.items() if k != "id" and v is not None}
                        if doc_id and update_data:
                            sb.table("documents").update(update_data).eq("id", doc_id).execute()
                            actions_taken = True

                    elif action_type == "move_document":
                        doc_id = params.get("id")
                        new_parent = params.get("parent_id")
                        new_category = params.get("category_id")
                        update = {}
                        if new_parent is not None:
                            update["parent_id"] = new_parent
                        if new_category is not None:
                            update["category_id"] = new_category
                        if doc_id and update:
                            sb.table("documents").update(update).eq("id", doc_id).execute()
                            actions_taken = True

                return {"response": response_msg, "actions_taken": actions_taken}

            except json.JSONDecodeError:
                return {"response": response_text, "actions_taken": False}

        except json.JSONDecodeError:
            return {"response": result_text, "actions_taken": False}

    except asyncio.TimeoutError:
        return {"response": "処理がタイムアウトしました。もう少し具体的な指示をお試しください。", "actions_taken": False}
    except FileNotFoundError:
        return {"response": "Claude CLIが見つかりません。セットアップを確認してください。", "actions_taken": False}
    except Exception as e:
        return {"response": f"エラーが発生しました: {str(e)}", "actions_taken": False}


class RelationCreate(BaseModel):
    source_id: str
    target_id: str
    relation_type: str = "related"


@router.post("/relations")
async def create_relation(body: RelationCreate):
    """ドキュメント間のリレーション作成"""
    sb = get_supabase_client().client
    result = sb.table("document_relations").insert(body.model_dump()).execute()
    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to create relation")
    return {"relation": result.data[0]}


@router.get("/{document_id}/relations")
async def get_relations(document_id: str):
    """ドキュメントのリレーション取得"""
    sb = get_supabase_client().client
    outgoing = sb.table("document_relations").select("*, documents!document_relations_target_id_fkey(id, title, icon)").eq("source_id", document_id).execute()
    incoming = sb.table("document_relations").select("*, documents!document_relations_source_id_fkey(id, title, icon)").eq("target_id", document_id).execute()
    return {
        "outgoing": outgoing.data,
        "incoming": incoming.data,
    }
