"""

Skill API Routes - スキル生成・管理



Claude Code CLIを使って高品質なスキルを生成する。

"""

from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks

from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from pydantic import BaseModel

from typing import Optional, List, Dict, Any

from pathlib import Path
from datetime import datetime

import asyncio
import re

import yaml



from app.services.skill_generator_claude import (

    analyze_session_for_skill,

    generate_skill,

    extend_skill,

    SkillProposal,

    SkillGenerationResult,

    _format_events_as_session_log,

    _filter_successful_events,

)

from app.services.supabase_client import get_supabase_client

from app.services.auth_service import decode_access_token

from app.services import learning_service

from app.agent.v2.tools import SkillRegistry



router = APIRouter(prefix="/skills", tags=["skills"])

security = HTTPBearer(auto_error=False)



# YAMLログディレクトリ

BROWSER_LOGS_DIR = Path("D:/done/app/logs/browser")





def _yaml_is_successful(yaml_path: Path) -> Optional[bool]:

    """YAMLログのsession.successを判定"""

    try:

        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))

    except Exception:

        return None

    if not isinstance(data, dict):

        return None

    session = data.get("session", {})

    if isinstance(session, dict) and "success" in session:

        return bool(session.get("success"))

    return None





class SkillAnalyzeRequest(BaseModel):

    """スキル分析リクエスト"""

    session_id: str

    instruction: Optional[str] = None





class SkillProposalDetail(BaseModel):
    """単一のスキル提案詳細"""
    proposal_id: str
    skill_name: str
    description: str
    site: str
    actions: List[str] = []
    parameters: List[Dict[str, Any]] = []
    decision: str  # create / extend / skip
    target_skill: Optional[str] = None
    new_actions: Optional[List[str]] = None


class SkillAnalyzeResponse(BaseModel):

    """スキル分析レスポンス（複数提案対応）"""

    success: bool

    # 複数提案対応（新規）
    proposals: List[SkillProposalDetail] = []

    message: str

    # 後方互換（deprecated - 単一提案の場合のみ使用）
    proposal_id: Optional[str] = None

    status: Optional[str] = None

    skill_name: Optional[str] = None

    description: Optional[str] = None

    site: Optional[str] = None

    actions: List[str] = []

    parameters: List[Dict[str, Any]] = []

    analysis: Optional[Dict[str, Any]] = None

    steps: Optional[List[str]] = None

    # Phase 1: LLM judgment result
    decision: Optional[str] = None  # create / extend / skip
    decision_reason: Optional[str] = None
    skip_reason: Optional[str] = None  # Human-readable reason when skipped





class SkillGenerateRequest(BaseModel):

    """Skill generate request."""

    proposal_id: str



class SkillGenerateResponse(BaseModel):

    """スキル生成レスポンス"""

    success: bool

    proposal_id: Optional[str] = None

    status: Optional[str] = None

    skill_name: str

    skill_path: Optional[str] = None

    files_created: Optional[List[str]] = None

    message: str





class SkillProposalResponse(BaseModel):

    """Skill proposal detail"""

    id: str

    session_id: str

    instruction: Optional[str] = None

    status: str

    skill_name: Optional[str] = None

    description: Optional[str] = None

    site: Optional[str] = None

    actions: List[str] = []

    parameters: List[Dict[str, Any]] = []

    analysis: Optional[Dict[str, Any]] = None

    steps: Optional[List[str]] = None

    created_at: Optional[str] = None

    updated_at: Optional[str] = None





class SkillProposalsListResponse(BaseModel):

    """Skill proposals list"""

    proposals: List[SkillProposalResponse]


class SkillProposalDismissRequest(BaseModel):

    """Dismiss a skill proposal."""

    status: Optional[str] = "dismissed"





class SkillListResponse(BaseModel):

    """スキル一覧レスポンス"""

    skills: list[dict]





async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):

    """認証ユーザーを取得"""

    if not credentials:

        raise HTTPException(status_code=401, detail="認証が必要です")



    token_data = decode_access_token(credentials.credentials)

    if not token_data:

        raise HTTPException(status_code=401, detail="無効なトークンです")



    return token_data





def find_yaml_by_session_id(session_id: str) -> Optional[Path]:

    """セッションIDからYAMLファイルを検索"""

    # セッションIDでディレクトリを検索

    session_dir = BROWSER_LOGS_DIR / session_id

    if session_dir.exists():

        yaml_files = list(session_dir.glob("*.yaml"))

        if yaml_files:

            success_files = [f for f in yaml_files if _yaml_is_successful(f) is True]

            if success_files:

                return max(success_files, key=lambda f: f.stat().st_mtime)

            # 最新のファイルを返す（成功ログなし）

            return max(yaml_files, key=lambda f: f.stat().st_mtime)



    # 見つからない場合は全ディレクトリを検索（フォールバック）

    candidates = []

    for yaml_file in BROWSER_LOGS_DIR.glob("*/*.yaml"):

        if session_id in yaml_file.parent.name:

            candidates.append(yaml_file)

    if candidates:

        success_files = [f for f in candidates if _yaml_is_successful(f) is True]

        if success_files:

            return max(success_files, key=lambda f: f.stat().st_mtime)

        return max(candidates, key=lambda f: f.stat().st_mtime)



    return None



# ============================================

# Skill proposal persistence

# ============================================





def _get_supabase():

    return get_supabase_client().client





def _format_skill_proposal(row: dict) -> dict:

    return {

        "id": row.get("id"),

        "session_id": row.get("session_id"),

        "instruction": row.get("instruction"),

        "status": row.get("status"),

        "skill_name": row.get("skill_name"),

        "description": row.get("description"),

        "site": row.get("site"),

        "actions": row.get("actions") or [],

        "parameters": row.get("parameters") or [],

        "analysis": row.get("analysis"),

        "steps": row.get("steps"),

        "created_at": row.get("created_at"),

        "updated_at": row.get("updated_at"),

    }





def _get_latest_skill_proposal(

    user_id: str,

    session_id: str,

    instruction: Optional[str] = None,

    status: Optional[str] = None,

) -> Optional[dict]:

    supabase = _get_supabase()

    query = supabase.table("skill_proposals").select("*")

    query = query.eq("user_id", user_id).eq("session_id", session_id)

    if instruction is not None:

        query = query.eq("instruction", instruction)

    if status is not None:

        query = query.eq("status", status)

    result = query.order("created_at", desc=True).limit(1).execute()

    if result.data:

        return result.data[0]

    return None





def _get_skill_proposal_by_id(user_id: str, proposal_id: str) -> Optional[dict]:

    supabase = _get_supabase()

    result = supabase.table("skill_proposals").select("*").eq("id", proposal_id).eq("user_id", user_id).execute()

    if result.data:

        return result.data[0]

    return None





def _create_skill_proposal(user_id: str, session_id: str, proposal: SkillProposal, instruction: Optional[str], status: str = "pending") -> dict:

    supabase = _get_supabase()

    payload = {

        "user_id": user_id,

        "session_id": session_id,

        "instruction": instruction,

        "status": status,

        "skill_name": proposal.skill_name,

        "description": proposal.description,

        "site": proposal.site,

        "actions": proposal.actions,

        "parameters": proposal.parameters,

        "analysis": proposal.analysis or {},

        "steps": proposal.steps or [],

        # Phase 2: extend機能用フィールド

        "decision": proposal.decision,

        "target_skill": proposal.target_skill,

        "new_actions": proposal.new_actions or [],

    }

    result = supabase.table("skill_proposals").insert(payload).execute()

    return result.data[0]





def _update_skill_proposal(proposal_id: str, updates: dict) -> dict:

    supabase = _get_supabase()

    result = supabase.table("skill_proposals").update(updates).eq("id", proposal_id).execute()

    return result.data[0] if result.data else updates







@router.post("/analyze", response_model=SkillAnalyzeResponse)

async def analyze_skill(

    request: SkillAnalyzeRequest,

    current_user = Depends(get_current_user)

):

    """

    セッションを分析してスキル提案を取得



    ユーザーに「このスキルを作りますか？」と表示するための情報を取得。

    Claude Code CLIでログを分析するため、数十秒かかる場合がある。



    - session_id: ブラウザセッションID（YAMLログのディレクトリ名）

    """

    # デバッグ用ファイルログ

    from datetime import datetime

    debug_log = Path("D:/done/skill_analyze_debug.log")

    with open(debug_log, "a", encoding="utf-8") as f:

        f.write(f"\n=== {datetime.now().isoformat()} ===\n")

        f.write(f"[SKILL_ANALYZE] Request received: session_id={request.session_id}\n")



    # learning_eventsからイベントを取得（新方式）
    events_list = await learning_service.get_events_for_session(request.session_id)
    events_data = [
        {
            "action_name": e.action_name,
            "action_params": e.action_params,
            "technical_success": e.technical_success,
            "context": e.context,
            "site": e.site,
            "skill_name": e.skill_name,
        }
        for e in events_list
    ] if events_list else []

    with open(debug_log, "a", encoding="utf-8") as f:
        f.write(f"[SKILL_ANALYZE] Found {len(events_data)} learning events\n")

    # YAMLファイルも検索（フォールバック）
    yaml_path = find_yaml_by_session_id(request.session_id)

    with open(debug_log, "a", encoding="utf-8") as f:

        f.write(f"[SKILL_ANALYZE] YAML path: {yaml_path}\n")

    if not events_data and not yaml_path:

        raise HTTPException(

            status_code=404,

            detail=f"セッション {request.session_id} のログが見つかりません"

        )

    # セッション成功判定
    if yaml_path:
        session_success = _yaml_is_successful(yaml_path)
    elif events_data:
        # events の場合は全て成功していれば成功とみなす
        session_success = any(e["technical_success"] for e in events_data)
    else:
        session_success = None



    # Reuse existing proposal (same instruction)

    existing = _get_latest_skill_proposal(

        current_user.user_id,

        request.session_id,

        instruction=request.instruction,

        status="pending",

    )

    if existing:

        formatted = _format_skill_proposal(existing)

        return SkillAnalyzeResponse(

            success=True,

            proposal_id=formatted["id"],

            status=formatted["status"],

            skill_name=formatted.get("skill_name"),

            description=formatted.get("description"),

            site=formatted.get("site"),

            actions=formatted.get("actions", []),

            parameters=formatted.get("parameters", []),

            analysis=formatted.get("analysis"),

            steps=formatted.get("steps"),

            message="Reusing existing pending proposal.",

        )



    # Claude Code CLIで分析

    with open(debug_log, "a", encoding="utf-8") as f:

        f.write(f"[SKILL_ANALYZE] Calling analyze_session_for_skill...\n")



    try:

        proposals = await analyze_session_for_skill(

            yaml_log_path=str(yaml_path) if yaml_path and not events_data else None,

            instruction=request.instruction,

            events=events_data if events_data else None,

        )

        with open(debug_log, "a", encoding="utf-8") as f:

            f.write(f"[SKILL_ANALYZE] Result: {len(proposals)} proposals\n")

    except Exception as e:

        with open(debug_log, "a", encoding="utf-8") as f:

            f.write(f"[SKILL_ANALYZE] ERROR: {e}\n")

        raise



    if not proposals:

        with open(debug_log, "a", encoding="utf-8") as f:

            f.write(f"[SKILL_ANALYZE] No proposals, returning failure\n")

        return SkillAnalyzeResponse(

            success=False,

            message="Failed to analyze session.",

        )

    # 全てskipの場合はskip情報を返す
    non_skip_proposals = [p for p in proposals if p.decision != "skip"]
    if not non_skip_proposals:
        first_skip = proposals[0]
        skip_message = first_skip.skip_reason or first_skip.decision_reason or "既存スキルで対応可能です"
        with open(debug_log, "a", encoding="utf-8") as f:
            f.write(f"[SKILL_ANALYZE] All skipped: {skip_message}\n")
        return SkillAnalyzeResponse(
            success=True,
            message=skip_message,
            decision=first_skip.decision,
            decision_reason=first_skip.decision_reason,
            skip_reason=first_skip.skip_reason,
        )

    # 各提案をDBに保存
    stored_proposals: List[SkillProposalDetail] = []
    status_value = "pending" if session_success is not False else "draft"

    for proposal in non_skip_proposals:
        with open(debug_log, "a", encoding="utf-8") as f:
            f.write(f"[SKILL_ANALYZE] Storing proposal: skill_name={proposal.skill_name}, decision={proposal.decision}\n")

        if session_success is False and proposal.analysis is not None:
            note = proposal.analysis.get("notes", "")
            extra_note = "成功ログが見つからないため暫定分析"
            if extra_note not in note:
                proposal.analysis["notes"] = f"{note} / {extra_note}".strip(" /")

        stored = _create_skill_proposal(
            current_user.user_id,
            request.session_id,
            proposal,
            request.instruction,
            status=status_value,
        )

        stored_proposals.append(SkillProposalDetail(
            proposal_id=stored["id"],
            skill_name=proposal.skill_name,
            description=proposal.description,
            site=proposal.site or "",
            actions=proposal.actions,
            parameters=proposal.parameters,
            decision=proposal.decision,
            target_skill=proposal.target_skill,
            new_actions=proposal.new_actions,
        ))

    # メッセージ生成
    if len(stored_proposals) == 1:
        message = f"「{stored_proposals[0].skill_name}」スキルを作成できます"
    else:
        skill_names = ", ".join([p.skill_name for p in stored_proposals])
        message = f"{len(stored_proposals)}個のスキルを作成できます: {skill_names}"

    if session_success is False:
        message += "（成功ログが見つからないため暫定）"

    # 後方互換: 最初の提案を従来フィールドにも設定
    first_proposal = non_skip_proposals[0]
    first_stored = stored_proposals[0]

    return SkillAnalyzeResponse(
        success=True,
        proposals=stored_proposals,
        message=message,
        # 後方互換フィールド
        proposal_id=first_stored.proposal_id,
        status=status_value,
        skill_name=first_proposal.skill_name,
        description=first_proposal.description,
        site=first_proposal.site,
        actions=first_proposal.actions,
        parameters=first_proposal.parameters,
        analysis=first_proposal.analysis,
        steps=first_proposal.steps,
        decision=first_proposal.decision,
        decision_reason=first_proposal.decision_reason,
    )





@router.post("/generate", response_model=SkillGenerateResponse)

async def generate_skill_endpoint(

    request: SkillGenerateRequest,

    current_user = Depends(get_current_user)

):

    """
    Generate a skill from a proposal ID.

    - proposal_id: proposal ID returned by /skills/analyze
    """

    # Reuse existing proposal (same instruction)

    proposal_row = _get_skill_proposal_by_id(current_user.user_id, request.proposal_id)

    if not proposal_row:

        raise HTTPException(

            status_code=404,

            detail=f"Proposal {request.proposal_id} not found"

        )



    if proposal_row.get("status") != "pending":

        raise HTTPException(

            status_code=409,

            detail=f"Proposal cannot be generated (status={proposal_row.get('status')})"

        )



    session_id = proposal_row.get("session_id")

    # learning_eventsからイベントを取得（新方式）
    events_list = await learning_service.get_events_for_session(session_id)
    session_log_text = None
    if events_list:
        events_data = [
            {
                "action_name": e.action_name,
                "action_params": e.action_params,
                "technical_success": e.technical_success,
                "context": e.context,
                "site": e.site,
            }
            for e in events_list
        ]
        filtered = _filter_successful_events(events_data)
        session_log_text = _format_events_as_session_log(filtered)

    # YAMLもフォールバックとして検索
    yaml_path = find_yaml_by_session_id(session_id)

    if not session_log_text and not yaml_path:

        raise HTTPException(

            status_code=404,

            detail=f"Session {session_id} log not found"

        )

    # 成功判定
    if yaml_path and not session_log_text:
        session_success = _yaml_is_successful(yaml_path)
        if session_success is False:
            raise HTTPException(
                status_code=409,
                detail="Success log not found; re-run a successful session."
            )



    skill_name = proposal_row.get("skill_name") or "generated_skill"

    decision = proposal_row.get("decision") or "create"



    # Phase 2: decision に応じて処理を分岐

    if decision == "extend":

        # 既存スキルにアクション追加

        target_skill = proposal_row.get("target_skill")

        new_actions = proposal_row.get("new_actions") or []



        if not target_skill:

            raise HTTPException(

                status_code=400,

                detail="target_skill is required for extend"

            )



        result = await extend_skill(

            yaml_log_path=str(yaml_path) if yaml_path and not session_log_text else None,

            target_skill=target_skill,

            new_actions=new_actions,

            description=proposal_row.get("description"),

            analysis=proposal_row.get("analysis") or {},

            steps=proposal_row.get("steps") or [],

            instruction=proposal_row.get("instruction"),

            session_log_text=session_log_text,

        )

    else:

        # 新規スキル作成（create または未指定）

        result = await generate_skill(

            yaml_log_path=str(yaml_path) if yaml_path and not session_log_text else None,

            skill_name=skill_name,

            description=proposal_row.get("description"),

            analysis=proposal_row.get("analysis") or {},

            steps=proposal_row.get("steps") or [],

            instruction=proposal_row.get("instruction"),

            session_log_text=session_log_text,

        )



    if not result.success:

        raise HTTPException(

            status_code=500,

            detail=f"Skill generation failed: {result.error}"

        )



    _update_skill_proposal(

        request.proposal_id,

        {

            "status": "generated",

            "generated_at": datetime.utcnow().isoformat(),

            "generated_skill_name": result.skill_name,

            "generated_skill_path": result.skill_path,

        },

    )



    return SkillGenerateResponse(

        success=True,

        proposal_id=request.proposal_id,

        status="generated",

        skill_name=result.skill_name,

        skill_path=result.skill_path,

        files_created=result.files_created,

        message=f"Generated skill '{result.skill_name}'",

    )



@router.get("/proposals", response_model=SkillProposalsListResponse)
async def list_skill_proposals(
    session_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 10,
    current_user = Depends(get_current_user),
):
    """List skill proposals for the current user."""
    supabase = _get_supabase()
    query = supabase.table("skill_proposals").select("*").eq("user_id", current_user.user_id)
    if session_id:
        query = query.eq("session_id", session_id)
    if status:
        query = query.eq("status", status)
    result = query.order("created_at", desc=True).limit(limit).execute()
    proposals = [_format_skill_proposal(row) for row in (result.data or [])]
    return SkillProposalsListResponse(
        proposals=[SkillProposalResponse(**p) for p in proposals]
    )


@router.get("/proposals/{proposal_id}", response_model=SkillProposalResponse)
async def get_skill_proposal(
    proposal_id: str,
    current_user = Depends(get_current_user),
):
    """Get a single skill proposal by ID."""
    proposal = _get_skill_proposal_by_id(current_user.user_id, proposal_id)
    if not proposal:
        raise HTTPException(status_code=404, detail="Skill proposal not found")
    return SkillProposalResponse(**_format_skill_proposal(proposal))


@router.post("/proposals/{proposal_id}/dismiss", response_model=SkillProposalResponse)
async def dismiss_skill_proposal(
    proposal_id: str,
    request: SkillProposalDismissRequest,
    current_user = Depends(get_current_user),
):
    """Dismiss a skill proposal so it doesn't resurface."""
    proposal = _get_skill_proposal_by_id(current_user.user_id, proposal_id)
    if not proposal:
        raise HTTPException(status_code=404, detail="Skill proposal not found")

    status_value = request.status or "dismissed"
    updated = _update_skill_proposal(
        proposal_id,
        {"status": status_value},
    )
    return SkillProposalResponse(**_format_skill_proposal(updated))

@router.get("/list", response_model=SkillListResponse)

async def list_skills(current_user = Depends(get_current_user)):

    """

    生成されたスキル一覧を取得

    """

    skills_dir = Path("D:/done/.claude/skills")

    skills = []



    for skill_dir in skills_dir.iterdir():

        if not skill_dir.is_dir():

            continue

        if skill_dir.name.startswith("_"):  # テスト用ディレクトリをスキップ

            continue



        skill_md_path = skill_dir / "SKILL.md"

        if skill_md_path.exists():

            # SKILL.mdから情報を抽出

            content = skill_md_path.read_text(encoding="utf-8")



            # タイトルを抽出

            title_match = content.split("\n")[0] if content else ""

            title = title_match.replace("# ", "").replace(" Skill", "").strip()



            # 生成日時を抽出（あれば）

            generated_at = None

            for line in content.split("\n"):

                if "生成日時:" in line:

                    generated_at = line.split("生成日時:")[1].strip()

                    break



            parent_skill = None
            parent_match = re.search(r'^\s*(parent_skill|parent)\s*:\s*(.+)$', content, re.MULTILINE | re.IGNORECASE)
            if parent_match:
                parent_skill = parent_match.group(2).strip()

            domain = None
            domain_match = re.search(r'^\s*(domain|site)\s*:\s*(.+)$', content, re.MULTILINE | re.IGNORECASE)
            if domain_match:
                domain = domain_match.group(2).strip().lower()
                domain = domain.replace('https://', '').replace('http://', '').split('/')[0]
            else:
                url_match = re.search(r'https?://([^/\s]+)', content)
                if url_match:
                    domain = url_match.group(1).strip().lower()

            group = parent_skill or domain or skill_dir.name

            try:
                skill = SkillRegistry.get(skill_dir.name)
                if skill:
                    title = skill.display_name
                    domain = skill.domain or domain
                    parent_skill = skill.parent_skill or parent_skill
                    group = skill.get_group()
            except Exception:
                pass


            skills.append({

                "name": skill_dir.name,

                "title": title,

                "path": str(skill_dir),

                "generated_at": generated_at,
                "domain": domain,
                "parent_skill": parent_skill,
                "group": group,

                "has_actions": (skill_dir / "actions").exists(),

            })



    return SkillListResponse(skills=skills)





@router.get("/{skill_name}")

async def get_skill(skill_name: str, current_user = Depends(get_current_user)):

    """

    スキルの詳細を取得

    """

    skills_dir = Path("D:/done/.claude/skills")

    skill_dir = skills_dir / skill_name



    if not skill_dir.exists():

        raise HTTPException(status_code=404, detail="スキルが見つかりません")



    skill_md_path = skill_dir / "SKILL.md"

    if not skill_md_path.exists():

        raise HTTPException(status_code=404, detail="SKILL.mdが見つかりません")



    skill_md = skill_md_path.read_text(encoding="utf-8")



    # アクション一覧

    actions = {}

    actions_dir = skill_dir / "actions"

    if actions_dir.exists():

        for action_file in actions_dir.glob("*.md"):

            actions[action_file.stem] = action_file.read_text(encoding="utf-8")



    # セレクタヒント

    selectors = None

    selectors_path = skill_dir / "selectors_hints.txt"

    if selectors_path.exists():

        selectors = selectors_path.read_text(encoding="utf-8")



    return {

        "name": skill_name,

        "skill_md": skill_md,

        "actions": actions,

        "selectors": selectors,

    }





@router.delete("/{skill_name}")

async def delete_skill(skill_name: str, current_user = Depends(get_current_user)):

    """

    スキルを削除

    """

    import shutil



    skills_dir = Path("D:/done/.claude/skills")

    skill_dir = skills_dir / skill_name



    if not skill_dir.exists():

        raise HTTPException(status_code=404, detail="スキルが見つかりません")



    # テスト用ディレクトリは削除不可

    if skill_name.startswith("_"):

        raise HTTPException(status_code=400, detail="テスト用スキルは削除できません")



    try:

        shutil.rmtree(skill_dir)

    except Exception as e:

        raise HTTPException(status_code=500, detail=f"削除に失敗しました: {str(e)}")



    return {"success": True, "message": f"スキル '{skill_name}' を削除しました"}
