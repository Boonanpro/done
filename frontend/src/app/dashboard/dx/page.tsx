'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { Building2, CheckCircle, FolderKanban, Rocket } from 'lucide-react';
import { KpiCard } from '@/app/dashboard/components/kpi-card';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Progress } from '@/components/ui/progress';
import { Skeleton } from '@/components/ui/skeleton';

const API_BASE = 'http://127.0.0.1:8000/api';

interface DxStats {
  kpis: {
    client_count: number;
    project_count: number;
    active_clients: number;
    deployed_projects: number;
    total_revenue: number;
  };
  client_status: Record<string, number>;
  project_status: Record<string, number>;
}

const projectStatusLabels: Record<string, string> = {
  planning: '計画中',
  in_progress: '制作中',
  review: 'レビュー中',
  deployed: '公開済み',
  maintenance: '保守中',
  archived: 'アーカイブ',
};

export default function DxHomePage() {
  const [stats, setStats] = useState<DxStats | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch(`${API_BASE}/dashboard/dx/stats`, { credentials: 'include' })
      .then((r) => r.json())
      .then(setStats)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="max-w-5xl mx-auto space-y-8">
        <div>
          <Skeleton className="h-8 w-32 mb-2" />
          <Skeleton className="h-4 w-64" />
        </div>
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Card key={i}>
              <CardContent className="pt-6 space-y-3">
                <Skeleton className="h-4 w-24" />
                <Skeleton className="h-8 w-16" />
              </CardContent>
            </Card>
          ))}
        </div>
      </div>
    );
  }

  const kpis = stats?.kpis;
  const projectStatus = stats?.project_status || {};
  const allStatuses = Object.keys(projectStatusLabels);
  const maxCount = Math.max(...allStatuses.map((s) => projectStatus[s] || 0), 1);

  return (
    <div className="max-w-5xl mx-auto space-y-8">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-foreground mb-1">DX事業</h1>
          <p className="text-sm text-muted-foreground">HP制作・DXツール提供の統合管理</p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" asChild>
            <Link href="/dashboard/dx/clients">クライアント一覧</Link>
          </Button>
          <Button asChild>
            <Link href="/dashboard/dx/projects">プロジェクト一覧</Link>
          </Button>
        </div>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <KpiCard label="クライアント数" value={kpis?.client_count ?? 0} icon={Building2} />
        <KpiCard label="アクティブ" value={kpis?.active_clients ?? 0} icon={CheckCircle} />
        <KpiCard label="プロジェクト数" value={kpis?.project_count ?? 0} icon={FolderKanban} />
        <KpiCard label="公開済み" value={kpis?.deployed_projects ?? 0} icon={Rocket} />
      </div>

      {/* Project Status */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-medium text-muted-foreground">プロジェクトステータス</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {allStatuses.map((status) => {
            const count = projectStatus[status] || 0;
            const pct = (count / maxCount) * 100;
            return (
              <div key={status} className="flex items-center gap-3">
                <span className="text-sm text-muted-foreground w-20 shrink-0 text-right">
                  {projectStatusLabels[status]}
                </span>
                <Progress value={count > 0 ? Math.max(pct, 8) : 0} className="flex-1" />
                <span className="text-sm text-muted-foreground w-8 text-right tabular-nums">{count}</span>
              </div>
            );
          })}
        </CardContent>
      </Card>
    </div>
  );
}
