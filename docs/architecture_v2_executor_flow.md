# アーキテクチャ v2: 推論ファースト・Executor実行フロー

## 概要

従来の「検索ツール先行」アーキテクチャから、「推論ファースト」アーキテクチャへ移行する。

### 従来の問題点

```
検索ツール（スカイスキャナー等）→ 提案 → 承認 → Executor（別サイト）
         ↑ 手段に縛られる              ↑ 不整合の可能性
```

- 検索と実行で異なるサイトを使用 → 在庫・価格の不整合
- Executorの範囲内に手段が縛られる
- 予約できない便を提案してしまう可能性

### 新アーキテクチャ

```
推論+Web検索（自由）→ Executor探す → Executor.search() → 提案 → 承認 → Executor.execute()
         ↑ 縛られない                    ↑ 同じサイトで一貫
```

---

## フロー詳細

### Step 1: 推論 + Web検索（手段に縛られない）

ユーザーの要望に対して、AIの推論とWeb検索で**最適な手段そのもの**を導き出す。

```python
# 入力
user_wish = "明日大阪から韓国に安く行きたい"

# AI推論 + Web検索
research_result = await agent.research(user_wish)
# {
#     "optimal_solution": "ピーチ航空の関空→仁川便",
#     "reasoning": "LCCが最安。ピーチは直近¥12,000〜",
#     "service_type": "airline",
#     "service_name": "peach",
#     "params": {
#         "departure": "関西国際空港",
#         "arrival": "仁川国際空港",
#         "date": "2026-01-06",
#         "time_preference": "18:00以降"
#     }
# }
```

### Step 2: 最適解を実現するExecutorを探す

導き出された最適解を実現できるExecutorをシステム内から探す。

```python
# Executor検索
executor = ExecutorRegistry.find(
    service_type="airline",
    service_name="peach"  # 特定のサービス
)

# 見つからない場合は汎用Executorを試す
if not executor:
    executor = ExecutorRegistry.find(
        service_type="airline",
        service_name="generic"  # 汎用航空券Executor
    )

# それでも見つからない場合
if not executor:
    return {
        "status": "no_executor",
        "message": "自動予約機能はまだありませんが、こちらから手動で予約できます",
        "url": "https://www.flypeach.com/..."
    }
```

### Step 3: Executor実行（探索モード）

Executorを使って実際のサイトで予約可能かを確認する。

```python
# 探索モード
search_result = await executor.search(params)
# {
#     "success": True,
#     "available_options": [
#         {
#             "flight": "MM123",
#             "departure_time": "18:30",
#             "arrival_time": "20:30",
#             "price": 12000,
#             "seats_available": 5,
#             "booking_url": "https://..."
#         },
#         ...
#     ]
# }

# 予約不可の場合はStep 1に戻る
if not search_result.success or not search_result.available_options:
    return await agent.research(user_wish, exclude=["peach"])
```

### Step 4: 提案（予約可能確認済み + 承認ボタン）

予約可能を確認した上で、承認ボタン付きの提案を返す。

```
[ACTION]
ピーチ航空で関空→仁川を予約します

[DETAILS]
• MM123便 18:30発 → 20:30着
• エコノミー ¥12,000
• 空席5席（確認済み）

[NOTES]
実際の予約サイトで空席を確認済みです。

[✓ 承認して予約]  [✏️ 条件を変更]
```

### Step 5: Executor実行（実行モード）

ユーザーが承認したら、実際に予約を確定する。

```python
# 実行モード
execution_result = await executor.execute(
    selection=selected_option,
    credentials=user_credentials
)
# {
#     "success": True,
#     "confirmation_number": "PEACH-12345678",
#     "details": {...}
# }
```

---

## コンポーネント設計

### 1. ExecutorRegistry

Executorを登録・検索する仕組み。

```python
class ExecutorRegistry:
    """Executorの登録・検索"""
    
    _executors: dict[str, dict[str, type[BaseExecutor]]] = {}
    
    @classmethod
    def register(cls, service_type: str, service_name: str, executor_class: type):
        """Executorを登録"""
        if service_type not in cls._executors:
            cls._executors[service_type] = {}
        cls._executors[service_type][service_name] = executor_class
    
    @classmethod
    def find(cls, service_type: str, service_name: str = None) -> Optional[BaseExecutor]:
        """Executorを検索"""
        type_executors = cls._executors.get(service_type, {})
        
        # 特定のサービス名で検索
        if service_name and service_name in type_executors:
            return type_executors[service_name]()
        
        # 汎用Executorを検索
        if "generic" in type_executors:
            return type_executors["generic"]()
        
        return None
    
    @classmethod
    def list_available(cls, service_type: str = None) -> list[str]:
        """利用可能なExecutorをリスト"""
        if service_type:
            return list(cls._executors.get(service_type, {}).keys())
        return [f"{t}/{s}" for t, svc in cls._executors.items() for s in svc.keys()]
```

### 2. BaseExecutor（拡張版）

```python
class BaseExecutor(ABC):
    """Executor基底クラス"""
    
    service_type: str = "generic"  # airline, train, bus, hotel, product, etc.
    service_name: str = "generic"  # peach, jal, ex_reservation, amazon, etc.
    
    @abstractmethod
    async def search(self, params: dict) -> SearchResult:
        """
        探索モード: 予約可能な選択肢を検索
        
        - 実際のサイトにPlaywrightでアクセス
        - 空席・在庫・価格を確認
        - 予約可能なものだけ返す
        """
        pass
    
    async def validate(self, selection: dict) -> ValidationResult:
        """
        検証モード: 選択した便/商品がまだ予約可能か再確認
        
        - 提案から時間が経っている場合に使用
        - デフォルトはsearch()を再実行
        """
        return await self.search(selection)
    
    @abstractmethod
    async def execute(self, selection: dict, credentials: dict) -> ExecutionResult:
        """
        実行モード: 実際に予約/購入を確定
        
        - ユーザー承認後に呼び出し
        """
        pass
```

### 3. Agent（新フロー対応）

```python
class AISecretaryAgent:
    
    async def process_wish_v2(self, wish: str, user_id: str) -> dict:
        """新フロー: 推論ファースト"""
        
        # Step 1: 推論 + Web検索
        research = await self._research_optimal_solution(wish)
        
        # Step 2: Executor検索
        executor = ExecutorRegistry.find(
            service_type=research["service_type"],
            service_name=research.get("service_name")
        )
        
        if not executor:
            return self._no_executor_response(research)
        
        # Step 3: Executor探索モード
        search_result = await executor.search(research["params"])
        
        if not search_result.success:
            # 別の手段を探す
            return await self.process_wish_v2(
                wish, 
                user_id, 
                exclude=[research["service_name"]]
            )
        
        # Step 4: 提案生成
        return await self._generate_proposal(
            research=research,
            search_result=search_result,
            executor=executor
        )
```

---

## 実装優先順位

1. **ExecutorRegistry作成** - Executorを登録・検索する仕組み
2. **BaseExecutor拡張** - search()メソッド追加
3. **既存Executor改修** - EXReservation, HighwayBus等にsearch()を実装
4. **Agent新フロー** - process_wish_v2()を実装
5. **chat_routes.py対応** - 新フローに対応
6. **フロントエンド** - 承認ボタン対応

---

## プロセス表示の設計原則

### ❌ ダメな例（当たり前すぎる・根拠がない）

```
リクエストを分析しています...
最適な手段を検索中...
EX予約から3件取得しました
提案を作成しました
```

### ✅ 良い例（根拠を見せる・実況中継）

```
考え中...
新幹線で新大阪→博多に行きたいようなので、EX予約で検索します
時間の指定がないので17時台で探します
指定席・普通車で検索します（指定がない場合のデフォルト）
EX予約にアクセス中...
検索条件を入力中... 新大阪→博多 1/20 17:00頃
17時台で予約可能な列車が3つ見つかりました
最も乗車時間が短い「のぞみ41号 17:03発」を選択します
座席を選択中... 窓側E席を確保
予約内容を確認中...
```

### 設計ルール

1. **「分析中」「作成中」は不要** - 当たり前すぎる内容は表示しない
2. **根拠を見せる** - なぜその選択をしたのかを説明する
   - 「時間の指定がないので17時台で探します」
   - 「普通車を使われることが多いので今回も普通車で」
3. **具体的な実況中継** - 操作の詳細を伝える
   - 「のぞみ41号 17:03発を選択します」
   - 「窓側E席を確保」
4. **仮定した内容を明示** - ユーザーが修正しやすいように
   - 「指定がないので○○と仮定しました」

### 今後の実装TODO

- [ ] 時間が指定されていない場合のデフォルトロジック（17時台等）
- [ ] 座席クラスのデフォルトロジック（普通車指定席）
- [ ] 窓側/通路側の好みを学習する仕組み
- [ ] 「最も乗車時間が短い」等の選択ロジックと表示

---

## 将来の拡張

- **Executor自動生成**: AIが新しいサービスのExecutorを自動生成
- **学習機能**: 実行結果からExecutorを改善
- **マルチExecutor**: 複数のExecutorを組み合わせて複雑なタスクを実行

