"""
VoiceExecutor - 電話によるタスク実行
Phase 10: エージェントからの自動架電
"""
import re
import logging
from typing import Optional, Dict, Any

from app.executors.base import BaseExecutor, ExecutionResult
from app.models.schemas import SearchResult
from app.models.voice_schemas import CallPurpose

logger = logging.getLogger(__name__)


def extract_phone_number(text: str) -> Optional[str]:
    """
    テキストから電話番号を抽出
    
    Args:
        text: 解析対象のテキスト
        
    Returns:
        抽出された電話番号（E.164形式に正規化）
    """
    patterns = [
        r'\+81[-\s]?\d[-\s]?\d{1,4}[-\s]?\d{1,4}[-\s]?\d{3,4}',  # +81-3-1234-5678
        r'\+81\d{9,10}',                 # +81312345678
        r'0\d{1,4}[-\s]?\d{1,4}[-\s]?\d{4}',  # 03-1234-5678 or 03 1234 5678
        r'0\d{9,10}',                    # 0312345678
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            phone = match.group()
            # 正規化（ハイフンとスペースを除去）
            phone = re.sub(r'[-\s]', '', phone)
            # 国内番号を国際形式に変換
            if phone.startswith('0'):
                phone = '+81' + phone[1:]
            return phone
    
    return None


class VoiceExecutor(BaseExecutor):
    """
    電話によるタスク実行
    
    ユーザーの代わりにAIが電話をかけて、
    予約や問い合わせなどのタスクを実行します。
    """
    
    service_name = "voice"
    
    async def _do_execute(
        self,
        task_id: str,
        search_result: SearchResult,
        credentials: Optional[Dict[str, str]] = None,
    ) -> ExecutionResult:
        """
        電話でタスクを実行
        
        Args:
            task_id: タスクID
            search_result: 実行対象（電話番号、目的、コンテキスト）
            
        Returns:
            実行結果
        """
        from app.services.voice_service import get_voice_service
        
        voice_service = get_voice_service()
        
        # 電話番号と目的を取得
        details = search_result.details or {}
        phone_number = details.get("phone_number")
        user_id = details.get("user_id", "00000000-0000-0000-0000-000000000001")
        purpose_str = details.get("purpose", "other")
        context = details.get("context", {})
        
        # 電話番号が直接指定されていない場合、説明文から抽出を試みる
        if not phone_number and search_result.description:
            phone_number = extract_phone_number(search_result.description)
        
        if not phone_number:
            return ExecutionResult(
                success=False,
                message="Phone number not specified. Please include a phone number and try again.",
            )
        
        # 電話番号を正規化
        phone_number = re.sub(r'[-\s]', '', phone_number)
        if phone_number.startswith('0'):
            phone_number = '+81' + phone_number[1:]
        
        # 目的を解析
        try:
            purpose = CallPurpose(purpose_str)
        except ValueError:
            purpose = CallPurpose.OTHER
        
        # コンテキストにタスク情報を追加
        context.update({
            "task_id": task_id,
            "task_description": search_result.title,  # Use title instead of description
            "source_url": search_result.url,
        })
        
        try:
            # 電話発信
            call = await voice_service.initiate_call(
                user_id=user_id,
                to_number=phone_number,
                purpose=purpose,
                context=context,
                task_id=task_id,
            )
            
            logger.info(f"VoiceExecutor: Initiated call {call.call_sid} to {phone_number}")
            
            await self._update_progress(
                task_id=task_id,
                message=f"Initiating call: {phone_number}",
                progress=50,
            )
            
            return ExecutionResult(
                success=True,
                message=f"Call initiated. Call ID: {call.call_sid}",
                details={
                    "call_id": call.id,
                    "call_sid": call.call_sid,
                    "to_number": phone_number,
                    "purpose": purpose.value,
                },
            )
            
        except Exception as e:
            logger.error(f"VoiceExecutor: Failed to initiate call: {e}")
            return ExecutionResult(
                success=False,
                message=f"Failed to initiate call: {str(e)}",
            )
    
    def _requires_login(self) -> bool:
        """電話タスクはログイン不要"""
        return False
    
    async def _login(self, page, credentials: dict) -> bool:
        """ログイン処理（不要）"""
        return True
    
    async def _execute_steps(
        self,
        page,
        task_id: str,
        search_result: SearchResult,
    ) -> ExecutionResult:
        """
        ブラウザ操作は不要
        電話発信は_do_executeで完了している
        """
        return ExecutionResult(
            success=True,
            message="Browser operations not required for phone tasks",
        )

