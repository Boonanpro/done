"""
Bank Account API Routes - Phase 8B: 振込先管理
"""
from fastapi import APIRouter, HTTPException, Depends
from typing import Optional
import logging

from app.models.payment_schemas import (
    SavedBankAccountCreate,
    SavedBankAccountUpdate,
    SavedBankAccountResponse,
    SavedBankAccountListResponse,
)
from app.services.bank_account_service import get_bank_account_service
from app.api.chat_routes import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/bank-accounts", tags=["bank-accounts"])


@router.post("", response_model=SavedBankAccountResponse)
async def create_bank_account(
    request: SavedBankAccountCreate,
    current_user: dict = Depends(get_current_user),
):
    """
    振込先を保存
    
    - **display_name**: 表示名（会社名など）
    - **bank_name**: 銀行名
    - **bank_code**: 銀行コード（4桁、オプション）
    - **branch_name**: 支店名
    - **branch_code**: 支店コード（3桁、オプション）
    - **account_type**: 口座種別（普通/当座）
    - **account_number**: 口座番号（最大7桁）
    - **account_holder**: 口座名義（カタカナ）
    """
    try:
        service = get_bank_account_service()
        user_id = current_user.user_id if hasattr(current_user, 'user_id') else "default"
        
        account = await service.create_bank_account(
            user_id=user_id,
            display_name=request.display_name,
            bank_name=request.bank_name,
            bank_code=request.bank_code,
            branch_name=request.branch_name,
            branch_code=request.branch_code,
            account_type=request.account_type,
            account_number=request.account_number,
            account_holder=request.account_holder,
        )
        
        # 口座番号をマスク
        account_number_masked = account["account_number"]
        if len(account_number_masked) > 3:
            account_number_masked = "*" * (len(account_number_masked) - 3) + account_number_masked[-3:]
        
        return SavedBankAccountResponse(
            id=account["id"],
            user_id=account["user_id"],
            display_name=account["display_name"],
            bank_name=account["bank_name"],
            bank_code=account.get("bank_code"),
            branch_name=account["branch_name"],
            branch_code=account.get("branch_code"),
            account_type=account["account_type"],
            account_number=account_number_masked,
            account_holder=account["account_holder"],
            is_verified=account.get("is_verified", False),
            last_used_at=account.get("last_used_at"),
            use_count=account.get("use_count", 0),
            created_at=account["created_at"],
            updated_at=account.get("updated_at"),
        )
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to create bank account: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("", response_model=SavedBankAccountListResponse)
async def list_bank_accounts(
    page: int = 1,
    page_size: int = 20,
    current_user: dict = Depends(get_current_user),
):
    """
    保存済み振込先一覧を取得
    
    - **page**: ページ番号（デフォルト: 1）
    - **page_size**: 1ページあたりの件数（デフォルト: 20）
    """
    try:
        service = get_bank_account_service()
        user_id = current_user.user_id if hasattr(current_user, 'user_id') else "default"
        
        accounts, total = await service.list_bank_accounts(
            user_id=user_id,
            page=page,
            page_size=page_size,
        )
        
        account_responses = []
        for acc in accounts:
            account_responses.append(SavedBankAccountResponse(
                id=acc["id"],
                user_id=acc["user_id"],
                display_name=acc["display_name"],
                bank_name=acc["bank_name"],
                bank_code=acc.get("bank_code"),
                branch_name=acc["branch_name"],
                branch_code=acc.get("branch_code"),
                account_type=acc["account_type"],
                account_number=acc["account_number"],  # 既にマスク済み
                account_holder=acc["account_holder"],
                is_verified=acc.get("is_verified", False),
                last_used_at=acc.get("last_used_at"),
                use_count=acc.get("use_count", 0),
                created_at=acc["created_at"],
                updated_at=acc.get("updated_at"),
            ))
        
        return SavedBankAccountListResponse(
            bank_accounts=account_responses,
            total=total,
        )
        
    except Exception as e:
        logger.error(f"Failed to list bank accounts: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{bank_account_id}", response_model=SavedBankAccountResponse)
async def get_bank_account(
    bank_account_id: str,
    current_user: dict = Depends(get_current_user),
):
    """
    振込先詳細を取得
    
    - **bank_account_id**: 振込先ID
    """
    try:
        service = get_bank_account_service()
        user_id = current_user.user_id if hasattr(current_user, 'user_id') else "default"
        
        account = await service.get_bank_account(
            bank_account_id=bank_account_id,
            user_id=user_id,
        )
        
        if not account:
            raise HTTPException(status_code=404, detail="Bank account not found")
        
        return SavedBankAccountResponse(
            id=account["id"],
            user_id=account["user_id"],
            display_name=account["display_name"],
            bank_name=account["bank_name"],
            bank_code=account.get("bank_code"),
            branch_name=account["branch_name"],
            branch_code=account.get("branch_code"),
            account_type=account["account_type"],
            account_number=account["account_number"],  # 既にマスク済み
            account_holder=account["account_holder"],
            is_verified=account.get("is_verified", False),
            last_used_at=account.get("last_used_at"),
            use_count=account.get("use_count", 0),
            created_at=account["created_at"],
            updated_at=account.get("updated_at"),
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get bank account: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{bank_account_id}")
async def delete_bank_account(
    bank_account_id: str,
    current_user: dict = Depends(get_current_user),
):
    """
    振込先を削除
    
    - **bank_account_id**: 振込先ID
    """
    try:
        service = get_bank_account_service()
        user_id = current_user.user_id if hasattr(current_user, 'user_id') else "default"
        
        success = await service.delete_bank_account(
            bank_account_id=bank_account_id,
            user_id=user_id,
        )
        
        if not success:
            raise HTTPException(status_code=404, detail="Bank account not found")
        
        return {"success": True, "message": "振込先を削除しました"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete bank account: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{bank_account_id}/verify", response_model=SavedBankAccountResponse)
async def verify_bank_account(
    bank_account_id: str,
    current_user: dict = Depends(get_current_user),
):
    """
    振込先を検証済みとしてマーク
    
    - **bank_account_id**: 振込先ID
    """
    try:
        service = get_bank_account_service()
        user_id = current_user.user_id if hasattr(current_user, 'user_id') else "default"
        
        account = await service.verify_bank_account(
            bank_account_id=bank_account_id,
            user_id=user_id,
        )
        
        if not account:
            raise HTTPException(status_code=404, detail="Bank account not found")
        
        return SavedBankAccountResponse(
            id=account["id"],
            user_id=account["user_id"],
            display_name=account["display_name"],
            bank_name=account["bank_name"],
            bank_code=account.get("bank_code"),
            branch_name=account["branch_name"],
            branch_code=account.get("branch_code"),
            account_type=account["account_type"],
            account_number=account["account_number"],
            account_holder=account["account_holder"],
            is_verified=account.get("is_verified", False),
            last_used_at=account.get("last_used_at"),
            use_count=account.get("use_count", 0),
            created_at=account["created_at"],
            updated_at=account.get("updated_at"),
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to verify bank account: {e}")
        raise HTTPException(status_code=500, detail=str(e))

