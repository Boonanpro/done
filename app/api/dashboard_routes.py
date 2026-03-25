"""
Dashboard API Routes - ダッシュボード管理画面
"""
from fastapi import APIRouter, HTTPException, Query
from typing import Optional
from app.services.supabase_client import get_supabase_client

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


# ============================================================
# Hub: ビジネス一覧
# ============================================================

@router.get("/businesses")
async def list_businesses():
    sb = get_supabase_client().client
    result = sb.table("dashboard_businesses").select("*").order("created_at").execute()
    return {"businesses": result.data}


# ============================================================
# AI B2B Sales: Stats
# ============================================================

@router.get("/ai-b2b-sales/stats")
async def get_b2b_stats():
    sb = get_supabase_client().client

    companies = sb.table("b2b_companies").select("id, status", count="exact").execute()
    deals = sb.table("b2b_deals").select("id, stage, estimated_amount", count="exact").execute()
    contracts = sb.table("b2b_contracts").select("id, amount, status").eq("status", "active").execute()
    emails = sb.table("b2b_emails").select("id, status", count="exact").execute()

    company_count = companies.count or 0
    deal_count = deals.count or 0
    active_contracts = len(contracts.data) if contracts.data else 0
    email_count = emails.count or 0

    # Stage distribution for pipeline
    stage_counts = {}
    if deals.data:
        for d in deals.data:
            stage = d.get("stage", "unknown")
            stage_counts[stage] = stage_counts.get(stage, 0) + 1

    # Company status distribution
    status_counts = {}
    if companies.data:
        for c in companies.data:
            s = c.get("status", "unknown")
            status_counts[s] = status_counts.get(s, 0) + 1

    # Monthly revenue from active contracts
    monthly_revenue = sum(c.get("amount", 0) for c in (contracts.data or []))

    return {
        "kpis": {
            "company_count": company_count,
            "email_count": email_count,
            "deal_count": deal_count,
            "contract_count": active_contracts,
            "monthly_revenue": monthly_revenue,
        },
        "pipeline": stage_counts,
        "company_status": status_counts,
    }


# ============================================================
# AI B2B Sales: Companies
# ============================================================

@router.get("/ai-b2b-sales/companies")
async def list_companies(
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
):
    sb = get_supabase_client().client
    query = sb.table("b2b_companies").select(
        "*, b2b_areas(prefecture, city)", count="exact"
    )

    if status:
        query = query.eq("status", status)
    if search:
        query = query.ilike("name", f"%{search}%")

    result = query.order("created_at", desc=True).range(offset, offset + limit - 1).execute()
    return {
        "companies": result.data,
        "total": result.count or 0,
    }


@router.post("/ai-b2b-sales/companies")
async def create_company(body: dict):
    sb = get_supabase_client().client
    result = sb.table("b2b_companies").insert(body).execute()
    if not result.data:
        raise HTTPException(status_code=400, detail="Failed to create company")
    return result.data[0]


@router.patch("/ai-b2b-sales/companies/{company_id}")
async def update_company(company_id: str, body: dict):
    sb = get_supabase_client().client
    result = sb.table("b2b_companies").update(body).eq("id", company_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Company not found")
    return result.data[0]


# ============================================================
# AI B2B Sales: Deals
# ============================================================

@router.get("/ai-b2b-sales/deals")
async def list_deals(
    stage: Optional[str] = Query(None),
    limit: int = Query(100, le=500),
):
    sb = get_supabase_client().client
    query = sb.table("b2b_deals").select(
        "*, b2b_companies(name)"
    )
    if stage:
        query = query.eq("stage", stage)

    result = query.order("created_at", desc=True).range(0, limit - 1).execute()
    return {"deals": result.data}


@router.post("/ai-b2b-sales/deals")
async def create_deal(body: dict):
    sb = get_supabase_client().client
    result = sb.table("b2b_deals").insert(body).execute()
    if not result.data:
        raise HTTPException(status_code=400, detail="Failed to create deal")
    return result.data[0]


@router.patch("/ai-b2b-sales/deals/{deal_id}")
async def update_deal(deal_id: str, body: dict):
    sb = get_supabase_client().client
    result = sb.table("b2b_deals").update(body).eq("id", deal_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Deal not found")
    return result.data[0]


# ============================================================
# DX事業: Stats
# ============================================================

@router.get("/dx/stats")
async def get_dx_stats():
    sb = get_supabase_client().client

    clients = sb.table("dx_clients").select("id, status", count="exact").execute()
    projects = sb.table("dx_projects").select("id, status, estimated_amount", count="exact").execute()

    client_count = clients.count or 0
    project_count = projects.count or 0

    # Status distributions
    client_status = {}
    if clients.data:
        for c in clients.data:
            s = c.get("status", "unknown")
            client_status[s] = client_status.get(s, 0) + 1

    project_status = {}
    total_revenue = 0
    if projects.data:
        for p in projects.data:
            s = p.get("status", "unknown")
            project_status[s] = project_status.get(s, 0) + 1
            total_revenue += p.get("estimated_amount", 0) or 0

    return {
        "kpis": {
            "client_count": client_count,
            "project_count": project_count,
            "active_clients": client_status.get("active", 0),
            "deployed_projects": project_status.get("deployed", 0),
            "total_revenue": total_revenue,
        },
        "client_status": client_status,
        "project_status": project_status,
    }


# ============================================================
# DX事業: Clients
# ============================================================

@router.get("/dx/clients")
async def list_dx_clients(
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
):
    sb = get_supabase_client().client
    query = sb.table("dx_clients").select("*", count="exact")

    if status:
        query = query.eq("status", status)
    if search:
        query = query.ilike("name", f"%{search}%")

    result = query.order("created_at", desc=True).range(offset, offset + limit - 1).execute()
    return {"clients": result.data, "total": result.count or 0}


@router.get("/dx/clients/{client_id}")
async def get_dx_client(client_id: str):
    sb = get_supabase_client().client
    result = sb.table("dx_clients").select("*").eq("id", client_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Client not found")
    # Also fetch projects for this client
    projects = sb.table("dx_projects").select("*").eq("client_id", client_id).order("created_at", desc=True).execute()
    client = result.data[0]
    client["projects"] = projects.data or []
    return client


@router.post("/dx/clients")
async def create_dx_client(body: dict):
    sb = get_supabase_client().client
    result = sb.table("dx_clients").insert(body).execute()
    if not result.data:
        raise HTTPException(status_code=400, detail="Failed to create client")
    return result.data[0]


@router.patch("/dx/clients/{client_id}")
async def update_dx_client(client_id: str, body: dict):
    sb = get_supabase_client().client
    result = sb.table("dx_clients").update(body).eq("id", client_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Client not found")
    return result.data[0]


@router.delete("/dx/clients/{client_id}")
async def delete_dx_client(client_id: str):
    sb = get_supabase_client().client
    result = sb.table("dx_clients").delete().eq("id", client_id).execute()
    return {"deleted": True}


# ============================================================
# DX事業: Projects
# ============================================================

@router.get("/dx/projects")
async def list_dx_projects(
    status: Optional[str] = Query(None),
    client_id: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
):
    sb = get_supabase_client().client
    query = sb.table("dx_projects").select("*, dx_clients(name)", count="exact")

    if status:
        query = query.eq("status", status)
    if client_id:
        query = query.eq("client_id", client_id)

    result = query.order("created_at", desc=True).range(offset, offset + limit - 1).execute()
    return {"projects": result.data, "total": result.count or 0}


@router.post("/dx/projects")
async def create_dx_project(body: dict):
    sb = get_supabase_client().client
    result = sb.table("dx_projects").insert(body).execute()
    if not result.data:
        raise HTTPException(status_code=400, detail="Failed to create project")
    return result.data[0]


@router.patch("/dx/projects/{project_id}")
async def update_dx_project(project_id: str, body: dict):
    sb = get_supabase_client().client
    result = sb.table("dx_projects").update(body).eq("id", project_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Project not found")
    return result.data[0]


@router.delete("/dx/projects/{project_id}")
async def delete_dx_project(project_id: str):
    sb = get_supabase_client().client
    result = sb.table("dx_projects").delete().eq("id", project_id).execute()
    return {"deleted": True}
