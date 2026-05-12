'use client';

/**
 * publish ページ
 * create_feature で自動生成。中身を実装してください。
 * build スキルのデザイントークンが適用済み。
 */
import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Plus, Search, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

const API_BASE = '/api/v1/publish';

export default function PublishPage() {
  const queryClient = useQueryClient();
  const [searchQuery, setSearchQuery] = useState('');

  // データ取得
  const { data, isLoading } = useQuery({
    queryKey: ['publish'],
    queryFn: async () => {
      const res = await fetch(API_BASE);
      if (!res.ok) throw new Error('取得に失敗');
      return res.json();
    },
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6">
      {/* ヘッダー */}
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-foreground">publish</h1>
        <Button>
          <Plus className="h-4 w-4 mr-2" />
          新規作成
        </Button>
      </div>

      {/* 検索 */}
      <div className="flex items-center gap-4">
        <div className="relative flex-1 max-w-md">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="検索..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="pl-10"
          />
        </div>
      </div>

      {/* コンテンツ — TODO: 実装してください */}
      <div className="text-muted-foreground">
        {/* ここにリスト、グリッド、テーブル等を実装 */}
        <p>データ: {JSON.stringify(data, null, 2)}</p>
      </div>
    </div>
  );
}
