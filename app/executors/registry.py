"""
Executor Registry for Architecture v2
推論ファースト・Executor実行フローのためのExecutor登録・検索機能
"""
from typing import Optional, Type, Dict, List, Any
from dataclasses import dataclass


@dataclass
class ExecutorInfo:
    """Executor情報"""
    executor_class: Type
    service_type: str  # airline, train, bus, hotel, product, voice
    service_name: str  # jal, ana, ex_reservation, willer, amazon, etc.
    display_name: str  # 表示名（日本語）
    url_patterns: List[str]  # 対応するURLパターン
    capabilities: List[str]  # search, execute, validate


class ExecutorRegistry:
    """
    Executorの登録・検索を管理
    
    推論結果から最適なExecutorを探すために使用
    """
    
    _instance: Optional['ExecutorRegistry'] = None
    _executors: Dict[str, Dict[str, ExecutorInfo]] = {}
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._executors = {}
        return cls._instance
    
    @classmethod
    def register(
        cls,
        executor_class: Type,
        service_type: str,
        service_name: str,
        display_name: str,
        url_patterns: Optional[List[str]] = None,
        capabilities: Optional[List[str]] = None,
    ) -> None:
        """
        Executorを登録
        
        Args:
            executor_class: Executorクラス
            service_type: サービスタイプ（airline, train, bus, hotel, product, voice）
            service_name: サービス名（jal, ex_reservation, willer等）
            display_name: 表示名（日本語）
            url_patterns: 対応するURLパターン
            capabilities: 対応機能（search, execute, validate）
        """
        instance = cls()
        
        if service_type not in instance._executors:
            instance._executors[service_type] = {}
        
        info = ExecutorInfo(
            executor_class=executor_class,
            service_type=service_type,
            service_name=service_name,
            display_name=display_name,
            url_patterns=url_patterns or [],
            capabilities=capabilities or ["execute"],
        )
        
        instance._executors[service_type][service_name] = info
    
    @classmethod
    def find(
        cls,
        service_type: str,
        service_name: Optional[str] = None,
        capability: Optional[str] = None,
    ) -> Optional[Any]:
        """
        Executorを検索
        
        Args:
            service_type: サービスタイプ
            service_name: サービス名（省略時は汎用Executorを返す）
            capability: 必要な機能（search, execute等）
            
        Returns:
            Executorインスタンス、見つからない場合はNone
        """
        instance = cls()
        
        type_executors = instance._executors.get(service_type, {})
        
        # 特定のサービス名で検索
        if service_name and service_name in type_executors:
            info = type_executors[service_name]
            if capability is None or capability in info.capabilities:
                return info.executor_class()
        
        # 汎用Executorを検索
        if "generic" in type_executors:
            info = type_executors["generic"]
            if capability is None or capability in info.capabilities:
                return info.executor_class()
        
        # service_typeに登録されている最初のExecutorを返す
        for name, info in type_executors.items():
            if capability is None or capability in info.capabilities:
                return info.executor_class()
        
        return None
    
    @classmethod
    def find_by_url(cls, url: str) -> Optional[Any]:
        """
        URLからExecutorを検索
        
        Args:
            url: URL
            
        Returns:
            Executorインスタンス、見つからない場合はNone
        """
        instance = cls()
        
        for type_executors in instance._executors.values():
            for info in type_executors.values():
                for pattern in info.url_patterns:
                    if pattern in url:
                        return info.executor_class()
        
        return None
    
    @classmethod
    def list_available(
        cls,
        service_type: Optional[str] = None,
        capability: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        利用可能なExecutorをリスト
        
        Args:
            service_type: フィルタするサービスタイプ
            capability: フィルタする機能
            
        Returns:
            Executor情報のリスト
        """
        instance = cls()
        result = []
        
        types_to_check = (
            {service_type: instance._executors.get(service_type, {})}
            if service_type
            else instance._executors
        )
        
        for svc_type, type_executors in types_to_check.items():
            for info in type_executors.values():
                if capability is None or capability in info.capabilities:
                    result.append({
                        "service_type": info.service_type,
                        "service_name": info.service_name,
                        "display_name": info.display_name,
                        "capabilities": info.capabilities,
                    })
        
        return result
    
    @classmethod
    def get_executor_for_solution(
        cls,
        optimal_solution: Dict[str, Any],
    ) -> Optional[Any]:
        """
        推論結果の最適解からExecutorを取得
        
        Args:
            optimal_solution: 推論結果
                - service_type: サービスタイプ
                - service_name: サービス名（オプション）
                - url: URL（オプション）
                
        Returns:
            Executorインスタンス、見つからない場合はNone
        """
        # URLから探す
        if "url" in optimal_solution:
            executor = cls.find_by_url(optimal_solution["url"])
            if executor:
                return executor
        
        # service_type + service_nameから探す
        service_type = optimal_solution.get("service_type")
        service_name = optimal_solution.get("service_name")
        
        if service_type:
            return cls.find(
                service_type=service_type,
                service_name=service_name,
                capability="search",  # 探索機能が必要
            )
        
        return None


def register_all_executors():
    """
    全てのExecutorを登録
    
    アプリケーション起動時に呼び出す
    """
    # Train（新幹線）- 新しいアクション分割版
    from app.executors.ex_reservation import EXReservationExecutor
    ExecutorRegistry.register(
        executor_class=EXReservationExecutor,
        service_type="train",
        service_name="ex_reservation",
        display_name="EX予約（新幹線）",
        url_patterns=["smart-ex.jp", "jr-central.co.jp"],
        capabilities=["search", "execute", "cancel"],  # cancelを追加
    )
    
    # Bus（高速バス）
    from app.executors.highway_bus_executor import HighwayBusExecutor
    ExecutorRegistry.register(
        executor_class=HighwayBusExecutor,
        service_type="bus",
        service_name="willer",
        display_name="WILLER TRAVEL",
        url_patterns=["willer.co.jp", "travel.willer.co.jp"],
        capabilities=["search", "execute"],
    )
    
    # Product（Amazon）
    from app.executors.amazon_executor import AmazonExecutor
    ExecutorRegistry.register(
        executor_class=AmazonExecutor,
        service_type="product",
        service_name="amazon",
        display_name="Amazon",
        url_patterns=["amazon.co.jp", "amazon.com"],
        capabilities=["search", "execute"],
    )
    
    # Product（楽天）
    from app.executors.rakuten_executor import RakutenExecutor
    ExecutorRegistry.register(
        executor_class=RakutenExecutor,
        service_type="product",
        service_name="rakuten",
        display_name="楽天市場",
        url_patterns=["rakuten.co.jp"],
        capabilities=["search", "execute"],
    )
    
    # Voice（電話）
    from app.executors.voice_executor import VoiceExecutor
    ExecutorRegistry.register(
        executor_class=VoiceExecutor,
        service_type="voice",
        service_name="phone",
        display_name="電話発信",
        url_patterns=[],
        capabilities=["execute"],
    )
    
    # Bank（銀行振込）
    from app.executors.bank_transfer_executor import BankTransferExecutor
    ExecutorRegistry.register(
        executor_class=BankTransferExecutor,
        service_type="payment",
        service_name="bank_transfer",
        display_name="銀行振込",
        url_patterns=[],
        capabilities=["execute"],
    )


# 便利関数
def get_executor_registry() -> ExecutorRegistry:
    """ExecutorRegistryのインスタンスを取得"""
    return ExecutorRegistry()


def find_executor(
    service_type: str,
    service_name: Optional[str] = None,
    capability: Optional[str] = None,
) -> Optional[Any]:
    """Executorを検索（ショートカット）"""
    return ExecutorRegistry.find(
        service_type=service_type,
        service_name=service_name,
        capability=capability,
    )

