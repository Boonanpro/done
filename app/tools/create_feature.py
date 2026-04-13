"""
create_feature — 新機能の雛形ファイルを自動生成するツール

機能名を受け取り、DB migration + schemas + service + routes + frontend page + seed script を生成。
ダンが機能実装を開始する際に必ず通る関門。
"""
import os
import re
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).parent.parent.parent  # D:/done
SUPABASE_MIGRATIONS = PROJECT_ROOT / "supabase" / "migrations"
BACKEND_MODELS = PROJECT_ROOT / "app" / "models"
BACKEND_SERVICES = PROJECT_ROOT / "app" / "services"
BACKEND_API = PROJECT_ROOT / "app" / "api"
FRONTEND_DASHBOARD = PROJECT_ROOT / "frontend" / "src" / "app" / "dashboard"
SCRIPTS = PROJECT_ROOT / "scripts"

# 実行済みfeatureを追跡するファイル
FEATURE_REGISTRY = PROJECT_ROOT / ".claude" / "feature_registry.json"


def to_snake(name: str) -> str:
    """CamelCase or 日本語 → snake_case"""
    # 日本語はそのままハイフン区切り
    if re.search(r'[a-zA-Z]', name):
        s = re.sub(r'(?<!^)(?=[A-Z])', '_', name).lower()
        return re.sub(r'[^a-z0-9_]', '_', s).strip('_')
    return re.sub(r'[^a-z0-9_]', '_', name.lower()).strip('_')


def to_kebab(name: str) -> str:
    return to_snake(name).replace('_', '-')


def get_next_migration_number() -> str:
    """次のマイグレーション番号を取得"""
    existing = sorted(SUPABASE_MIGRATIONS.glob("*.sql"))
    if existing:
        last = existing[-1].name.split("_")[0]
        return str(int(last) + 1).zfill(3)
    return "001"


def create_feature(feature_name: str, description: str = "") -> dict:
    """
    機能の雛形ファイル一式を生成する。

    Args:
        feature_name: 機能名（英語推奨、例: "notebook", "invoice_manager"）
        description: 機能の説明

    Returns:
        生成されたファイルのリスト
    """
    snake = to_snake(feature_name)
    kebab = to_kebab(feature_name)
    migration_num = get_next_migration_number()

    created_files = []

    # ==========================================
    # 1. DB Migration
    # ==========================================
    migration_path = SUPABASE_MIGRATIONS / f"{migration_num}_{snake}.sql"
    migration_path.write_text(f"""-- {feature_name} のテーブル定義
-- create_feature で自動生成。中身を実装してください。
--
-- 説明: {description}
-- 生成日時: {datetime.now().isoformat()}

-- メインテーブル
CREATE TABLE IF NOT EXISTS {snake} (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    -- TODO: カラムを定義してください
    -- 例:
    -- title TEXT NOT NULL,
    -- content JSONB DEFAULT '{{}}',
    -- status TEXT DEFAULT 'active',
    -- user_id UUID REFERENCES auth.users(id),

    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    created_by UUID REFERENCES auth.users(id)
);

-- RLS有効化
ALTER TABLE {snake} ENABLE ROW LEVEL SECURITY;

-- RLSポリシー
CREATE POLICY "{snake}_owner" ON {snake}
    FOR ALL USING (created_by = auth.uid());

-- updated_atの自動更新
CREATE OR REPLACE FUNCTION update_{snake}_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER {snake}_updated_at
    BEFORE UPDATE ON {snake}
    FOR EACH ROW EXECUTE FUNCTION update_{snake}_updated_at();
""", encoding="utf-8")
    created_files.append(str(migration_path))

    # ==========================================
    # 2. Pydantic Schemas
    # ==========================================
    schemas_path = BACKEND_MODELS / f"{snake}_schemas.py"
    schemas_path.write_text(f'''"""
{feature_name} のデータスキーマ
create_feature で自動生成。中身を実装してください。
"""
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from uuid import UUID


class {snake.title().replace("_", "")}Create(BaseModel):
    """新規作成リクエスト"""
    # TODO: フィールドを定義してください
    # 例:
    # title: str = Field(..., min_length=1)
    # content: Optional[dict] = None
    pass


class {snake.title().replace("_", "")}Update(BaseModel):
    """更新リクエスト"""
    # TODO: 更新可能なフィールドを定義してください
    pass


class {snake.title().replace("_", "")}Response(BaseModel):
    """レスポンス"""
    id: UUID
    created_at: datetime
    updated_at: datetime
    # TODO: レスポンスフィールドを定義してください

    class Config:
        from_attributes = True
''', encoding="utf-8")
    created_files.append(str(schemas_path))

    # ==========================================
    # 3. Service Layer
    # ==========================================
    service_path = BACKEND_SERVICES / f"{snake}_service.py"
    service_path.write_text(f'''"""
{feature_name} のビジネスロジック
create_feature で自動生成。中身を実装してください。
"""
from typing import Optional, List
from app.services.supabase_client import get_supabase_client


class {snake.title().replace("_", "")}Service:
    def __init__(self):
        self.supabase = get_supabase_client().client
        self.table = "{snake}"

    async def create(self, data: dict, user_id: str) -> dict:
        """新規作成"""
        result = self.supabase.table(self.table).insert({{
            **data,
            "created_by": user_id,
        }}).execute()
        return result.data[0] if result.data else None

    async def get(self, id: str, user_id: str) -> Optional[dict]:
        """1件取得"""
        result = self.supabase.table(self.table).select("*").eq("id", id).eq("created_by", user_id).execute()
        return result.data[0] if result.data else None

    async def list(self, user_id: str, limit: int = 50) -> List[dict]:
        """一覧取得"""
        result = self.supabase.table(self.table).select("*").eq("created_by", user_id).order("created_at", desc=True).limit(limit).execute()
        return result.data or []

    async def update(self, id: str, data: dict, user_id: str) -> Optional[dict]:
        """更新"""
        result = self.supabase.table(self.table).update(data).eq("id", id).eq("created_by", user_id).execute()
        return result.data[0] if result.data else None

    async def delete(self, id: str, user_id: str) -> bool:
        """削除"""
        result = self.supabase.table(self.table).delete().eq("id", id).eq("created_by", user_id).execute()
        return bool(result.data)
''', encoding="utf-8")
    created_files.append(str(service_path))

    # ==========================================
    # 4. API Routes
    # ==========================================
    routes_path = BACKEND_API / f"{snake}_routes.py"
    routes_path.write_text(f'''"""
{feature_name} のAPIエンドポイント
create_feature で自動生成。中身を実装してください。
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import List
from app.services.auth_service import get_current_user, TokenData
from app.services.{snake}_service import {snake.title().replace("_", "")}Service
from app.models.{snake}_schemas import (
    {snake.title().replace("_", "")}Create,
    {snake.title().replace("_", "")}Update,
    {snake.title().replace("_", "")}Response,
)

router = APIRouter(prefix="/api/v1/{kebab}", tags=["{feature_name}"])


def get_service():
    return {snake.title().replace("_", "")}Service()


@router.get("", response_model=List[{snake.title().replace("_", "")}Response])
async def list_{snake}(
    current_user: TokenData = Depends(get_current_user),
    service: {snake.title().replace("_", "")}Service = Depends(get_service),
):
    return await service.list(current_user.user_id)


@router.post("", response_model={snake.title().replace("_", "")}Response)
async def create_{snake}(
    data: {snake.title().replace("_", "")}Create,
    current_user: TokenData = Depends(get_current_user),
    service: {snake.title().replace("_", "")}Service = Depends(get_service),
):
    result = await service.create(data.model_dump(), current_user.user_id)
    if not result:
        raise HTTPException(status_code=400, detail="作成に失敗しました")
    return result


@router.get("/{{id}}", response_model={snake.title().replace("_", "")}Response)
async def get_{snake}(
    id: str,
    current_user: TokenData = Depends(get_current_user),
    service: {snake.title().replace("_", "")}Service = Depends(get_service),
):
    result = await service.get(id, current_user.user_id)
    if not result:
        raise HTTPException(status_code=404, detail="見つかりません")
    return result


@router.patch("/{{id}}", response_model={snake.title().replace("_", "")}Response)
async def update_{snake}(
    id: str,
    data: {snake.title().replace("_", "")}Update,
    current_user: TokenData = Depends(get_current_user),
    service: {snake.title().replace("_", "")}Service = Depends(get_service),
):
    result = await service.update(id, data.model_dump(exclude_unset=True), current_user.user_id)
    if not result:
        raise HTTPException(status_code=404, detail="見つかりません")
    return result


@router.delete("/{{id}}")
async def delete_{snake}(
    id: str,
    current_user: TokenData = Depends(get_current_user),
    service: {snake.title().replace("_", "")}Service = Depends(get_service),
):
    if not await service.delete(id, current_user.user_id):
        raise HTTPException(status_code=404, detail="見つかりません")
    return {{"ok": True}}
''', encoding="utf-8")
    created_files.append(str(routes_path))

    # ==========================================
    # 5. Frontend Page
    # ==========================================
    page_dir = FRONTEND_DASHBOARD / kebab
    page_dir.mkdir(parents=True, exist_ok=True)

    page_path = page_dir / "page.tsx"
    page_path.write_text(f"""'use client';

/**
 * {feature_name} ページ
 * create_feature で自動生成。中身を実装してください。
 * designスキルのデザイントークンが適用済み。
 */
import {{ useState }} from 'react';
import {{ useQuery, useMutation, useQueryClient }} from '@tanstack/react-query';
import {{ Plus, Search, Loader2 }} from 'lucide-react';
import {{ Button }} from '@/components/ui/button';
import {{ Input }} from '@/components/ui/input';

const API_BASE = '/api/v1/{kebab}';

export default function {snake.title().replace("_", "")}Page() {{
  const queryClient = useQueryClient();
  const [searchQuery, setSearchQuery] = useState('');

  // データ取得
  const {{ data, isLoading }} = useQuery({{
    queryKey: ['{snake}'],
    queryFn: async () => {{
      const res = await fetch(API_BASE);
      if (!res.ok) throw new Error('取得に失敗');
      return res.json();
    }},
  }});

  if (isLoading) {{
    return (
      <div className="flex items-center justify-center h-full">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }}

  return (
    <div className="p-6 space-y-6">
      {{/* ヘッダー */}}
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-foreground">{feature_name}</h1>
        <Button>
          <Plus className="h-4 w-4 mr-2" />
          新規作成
        </Button>
      </div>

      {{/* 検索 */}}
      <div className="flex items-center gap-4">
        <div className="relative flex-1 max-w-md">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="検索..."
            value={{searchQuery}}
            onChange={{(e) => setSearchQuery(e.target.value)}}
            className="pl-10"
          />
        </div>
      </div>

      {{/* コンテンツ — TODO: 実装してください */}}
      <div className="text-muted-foreground">
        {{/* ここにリスト、グリッド、テーブル等を実装 */}}
        <p>データ: {{JSON.stringify(data, null, 2)}}</p>
      </div>
    </div>
  );
}}
""", encoding="utf-8")
    created_files.append(str(page_path))

    # ==========================================
    # 6. Seed Script
    # ==========================================
    seed_path = SCRIPTS / f"seed_{snake}.py"
    seed_path.write_text(f'''"""
{feature_name} のサンプルデータ投入スクリプト
create_feature で自動生成。中身を実装してください。
完了報告前に必ず実行すること。
"""
import sys
sys.path.insert(0, "D:/done")

from app.services.supabase_client import get_supabase_client


def seed():
    sb = get_supabase_client().client

    # オーナーのuser_idを取得
    users = sb.table("users").select("id").limit(1).execute()
    if not users.data:
        print("ユーザーが見つかりません")
        return
    user_id = users.data[0]["id"]

    # TODO: サンプルデータを定義してください
    samples = [
        # {{"title": "サンプル1", "created_by": user_id}},
        # {{"title": "サンプル2", "created_by": user_id}},
    ]

    for sample in samples:
        result = sb.table("{snake}").insert(sample).execute()
        if result.data:
            print(f"  作成: {{result.data[0].get('id', '?')}}")
        else:
            print(f"  失敗: {{sample}}")

    print(f"サンプルデータ {{len(samples)}} 件を投入しました")


if __name__ == "__main__":
    seed()
''', encoding="utf-8")
    created_files.append(str(seed_path))

    # ==========================================
    # 7. Feature Registry に記録
    # ==========================================
    import json
    registry = {}
    if FEATURE_REGISTRY.exists():
        registry = json.loads(FEATURE_REGISTRY.read_text(encoding="utf-8"))

    registry[snake] = {
        "name": feature_name,
        "description": description,
        "created_at": datetime.now().isoformat(),
        "files": created_files,
    }

    FEATURE_REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    FEATURE_REGISTRY.write_text(json.dumps(registry, indent=2, ensure_ascii=False), encoding="utf-8")

    return {
        "feature": snake,
        "files": created_files,
        "next_steps": [
            f"1. {migration_path.name} のカラム定義を実装",
            f"2. Supabase で SQL を適用",
            f"3. {schemas_path.name} のフィールドを定義",
            f"4. {service_path.name} のビジネスロジックを実装",
            f"5. {routes_path.name} のエンドポイントをカスタマイズ",
            f"6. main.py にルーターを登録",
            f"7. {page_path.name} のUIを実装",
            f"8. {seed_path.name} のサンプルデータを実装・実行",
        ],
    }


if __name__ == "__main__":
    import sys
    name = sys.argv[1] if len(sys.argv) > 1 else "test_feature"
    desc = sys.argv[2] if len(sys.argv) > 2 else ""
    result = create_feature(name, desc)
    print(f"Created {len(result['files'])} files for '{result['feature']}':")
    for f in result['files']:
        print(f"  {f}")
    print("\nNext steps:")
    for s in result['next_steps']:
        print(f"  {s}")
