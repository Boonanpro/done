'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Building2, FolderOpen } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';

const API_BASE = 'http://127.0.0.1:8000/api';

interface Business {
  slug: string;
  name: string;
  description: string;
  icon: string;
  status: 'active' | 'paused' | 'setup' | 'planning' | 'archived';
}

const statusConfig: Record<string, { label: string; className: string }> = {
  active: { label: '稼働中', className: 'text-emerald-400 border-emerald-400/30' },
  paused: { label: '一時停止', className: 'text-yellow-400 border-yellow-400/30' },
  setup: { label: 'セットアップ中', className: 'text-muted-foreground border-border' },
  planning: { label: '計画中', className: 'text-yellow-400 border-yellow-400/30' },
  archived: { label: 'アーカイブ', className: 'text-muted-foreground border-border' },
};

const fallbackBusinesses: Business[] = [
  {
    slug: 'documents',
    name: 'Dan Docs',
    description: 'ドキュメント・ファイル管理（Notion風エディタ）',
    icon: 'file-text',
    status: 'active',
  },
  {
    slug: 'ai-b2b-sales',
    name: 'AI B2B自動営業',
    description: 'AIを活用したB2B企業向け自動営業パイプライン管理',
    icon: 'building-2',
    status: 'active',
  },
];

export default function DashboardHubPage() {
  const router = useRouter();
  const [businesses, setBusinesses] = useState<Business[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchBusinesses = async () => {
      try {
        const res = await fetch(`${API_BASE}/dashboard/businesses`, { credentials: 'include' });
        if (res.ok) {
          const data = await res.json();
          setBusinesses(data.businesses ?? data);
        } else {
          setBusinesses(fallbackBusinesses);
        }
      } catch {
        setBusinesses(fallbackBusinesses);
      } finally {
        setLoading(false);
      }
    };
    fetchBusinesses();
  }, []);

  if (loading) {
    return (
      <div className="max-w-4xl mx-auto">
        <Skeleton className="h-8 w-48 mb-2" />
        <Skeleton className="h-4 w-64 mb-8" />
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {Array.from({ length: 3 }).map((_, i) => (
            <Card key={i}>
              <CardContent className="pt-6 space-y-3">
                <Skeleton className="h-6 w-6" />
                <Skeleton className="h-5 w-32" />
                <Skeleton className="h-4 w-full" />
              </CardContent>
            </Card>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-4xl mx-auto">
      <h1 className="text-2xl font-semibold text-foreground mb-1">ダッシュボード</h1>
      <p className="text-sm text-muted-foreground mb-8">ビジネスを選択してください</p>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {businesses.map((biz) => {
          const st = statusConfig[biz.status] || statusConfig.setup;
          return (
            <Card
              key={biz.slug}
              className="cursor-pointer hover:bg-secondary/30 transition-colors"
              onClick={() => router.push(`/dashboard/${biz.slug}`)}
            >
              <CardContent className="pt-6">
                <div className="flex items-start justify-between mb-3">
                  <Building2 className="h-6 w-6 text-muted-foreground" />
                  <Badge variant="outline" className={st.className}>
                    {st.label}
                  </Badge>
                </div>
                <h2 className="text-base font-medium text-foreground mb-1">
                  {biz.name}
                </h2>
                <p className="text-sm text-muted-foreground leading-relaxed">
                  {biz.description}
                </p>
              </CardContent>
            </Card>
          );
        })}
      </div>

      {businesses.length === 0 && (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-16">
            <FolderOpen className="h-10 w-10 text-muted-foreground mb-3" />
            <p className="text-lg text-muted-foreground mb-2">ビジネスが登録されていません</p>
            <p className="text-sm text-muted-foreground">チャットから新しいビジネスを作成してください</p>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
