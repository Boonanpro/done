"""
Payment Tasks - Phase 7D: 支払いスケジューラ
"""
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="app.tasks.payment_tasks.check_scheduled_payments")
def check_scheduled_payments():
    """
    スケジュールされた支払いをチェックして実行
    
    5分毎に実行され、scheduled_payment_time <= now() かつ status = 'approved' の請求書を検索し、
    支払いを実行する。
    """
    import asyncio
    from app.services.supabase_client import get_supabase_client
    from app.executors.bank_transfer_executor import get_bank_transfer_executor
    
    try:
        now = datetime.now(ZoneInfo("Asia/Tokyo"))
        logger.info(f"Checking scheduled payments at {now.isoformat()}")
        
        # Supabaseクライアントを取得
        supabase_client = get_supabase_client()
        db = supabase_client.client
        
        # scheduled_payment_time <= now() かつ status = 'approved' の請求書を検索
        result = db.table("invoices").select("*").eq(
            "status", "approved"
        ).lte(
            "scheduled_payment_time", now.isoformat()
        ).execute()
        
        if not result.data or len(result.data) == 0:
            logger.info("No scheduled payments to process")
            return {"processed": 0, "success": 0, "failed": 0}
        
        invoices = result.data
        logger.info(f"Found {len(invoices)} scheduled payments to process")
        
        # 各請求書を処理
        processed = 0
        success = 0
        failed = 0
        
        executor = get_bank_transfer_executor()
        
        for invoice in invoices:
            invoice_id = invoice["id"]
            user_id = invoice.get("user_id", "default")
            
            try:
                logger.info(f"Processing payment for invoice {invoice_id}")
                
                # ステータスを executing に更新
                db.table("invoices").update({
                    "status": "executing",
                    "payment_started_at": now.isoformat(),
                    "updated_at": now.isoformat(),
                }).eq("id", invoice_id).execute()
                
                # 振込を実行（シミュレーションモード）
                bank_type = invoice.get("bank_type", "simulation")
                
                # 非同期関数を同期的に実行
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    transfer_result = loop.run_until_complete(
                        executor.execute(
                            invoice_id=invoice_id,
                            user_id=user_id,
                            bank_type=bank_type,
                        )
                    )
                finally:
                    loop.close()
                
                if transfer_result.success:
                    success += 1
                    logger.info(f"Payment successful for invoice {invoice_id}: {transfer_result.transaction_id}")
                else:
                    failed += 1
                    logger.error(f"Payment failed for invoice {invoice_id}: {transfer_result.message}")
                
                processed += 1
                
            except Exception as e:
                failed += 1
                processed += 1
                logger.error(f"Error processing payment for invoice {invoice_id}: {e}")
                
                # エラーを記録
                db.table("invoices").update({
                    "status": "failed",
                    "error_message": str(e),
                    "updated_at": datetime.now(ZoneInfo("Asia/Tokyo")).isoformat(),
                }).eq("id", invoice_id).execute()
        
        result_summary = {
            "processed": processed,
            "success": success,
            "failed": failed,
            "checked_at": now.isoformat(),
        }
        logger.info(f"Payment check completed: {result_summary}")
        return result_summary
        
    except Exception as e:
        logger.error(f"Error in check_scheduled_payments: {e}")
        return {"error": str(e)}


@shared_task(name="app.tasks.payment_tasks.execute_single_payment")
def execute_single_payment(invoice_id: str, user_id: str, bank_type: str = "simulation"):
    """
    単一の支払いを実行
    
    Args:
        invoice_id: 請求書ID
        user_id: ユーザーID
        bank_type: 銀行タイプ
    """
    import asyncio
    from app.executors.bank_transfer_executor import get_bank_transfer_executor
    
    try:
        logger.info(f"Executing single payment for invoice {invoice_id}")
        
        executor = get_bank_transfer_executor()
        
        # 非同期関数を同期的に実行
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(
                executor.execute(
                    invoice_id=invoice_id,
                    user_id=user_id,
                    bank_type=bank_type,
                )
            )
        finally:
            loop.close()
        
        return {
            "invoice_id": invoice_id,
            "success": result.success,
            "message": result.message,
            "transaction_id": result.transaction_id,
        }
        
    except Exception as e:
        logger.error(f"Error executing payment for invoice {invoice_id}: {e}")
        return {
            "invoice_id": invoice_id,
            "success": False,
            "message": str(e),
        }


