'use client';

import { useEffect, useState } from 'react';
import { Building2, FileText, Handshake, CheckCircle } from 'lucide-react';
import { KpiCard } from '@/app/dashboard/components/kpi-card';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Progress } from '@/components/ui/progress';
import { Skeleton } from '@/components/ui/skeleton';

const API_BASE = 'http://127.0.0.1:8000/api';

interface Stats {
  companies: number;
  proposals: number;
  deals: number;
  contracts: number;
  pipeline: { stage: string; count: number }[];
  recentActivity: { id: string; text: string; time: string }[];
}

const defaultStats: Stats = {
  companies: 0,
  proposals: 0,
  deals: 0,
  contracts: 0,
  pipeline: [],
  recentActivity: [],
};

const pipelineStages = [
  '初回連絡',
  'アポ取得',
  '商談実施',
  '見積提出',
  '交渉中',
  '成約',
  '失注',
];

const stageColors: Record<string, string> = {
  '初回連絡': 'bg-blue-500',
  'アポ取得': 'bg-cyan-500',
  '商談実施': 'bg-violet-500',
  '見積提出': 'bg-amber-500',
  '交渉中': 'bg-orange-500',
  '成約': 'bg-emerald-500',
  '失注': 'bg-red-500',
};

export default function AiB2bSalesHomePage() {
  const [stats, setStats] = useState<Stats>(defaultStats);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchStats = async () => {
      try {
        const res = await fetch(`${API_BASE}/dashboard/ai-b2b-sales/stats`);
        if (res.ok) {
          const data = await res.json();
          setStats({ ...defaultStats, ...data });
        }
      } catch {
        // keep defaults
      } finally {
        setLoading(false);
      }
    };
    fetchStats();
  }, []);

  if (loading) {
    return (
      <div className="max-w-5xl mx-auto space-y-8">
        <div>
          <Skeleton className="h-8 w-40 mb-2" />
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

  const maxPipelineCount = Math.max(
    ...pipelineStages.map(
      (s) => stats.pipeline.find((p) => p.stage === s)?.count ?? 0
    ),
    1
  );

  return (
    <div className="max-w-5xl mx-auto space-y-8">
      <div>
        <h1 className="text-2xl font-semibold text-foreground mb-1">AI B2B自動営業</h1>
        <p className="text-sm text-muted-foreground">営業パイプラインの概要</p>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <KpiCard label="企業数" value={stats.companies} icon={Building2} />
        <KpiCard label="提案数" value={stats.proposals} icon={FileText} />
        <KpiCard label="商談数" value={stats.deals} icon={Handshake} />
        <KpiCard label="契約数" value={stats.contracts} icon={CheckCircle} />
      </div>

      {/* Pipeline Summary */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-medium text-muted-foreground">パイプライン概要</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {pipelineStages.map((stage) => {
            const count = stats.pipeline.find((p) => p.stage === stage)?.count ?? 0;
            const pct = (count / maxPipelineCount) * 100;
            return (
              <div key={stage} className="flex items-center gap-3">
                <span className="text-sm text-muted-foreground w-20 shrink-0 text-right">
                  {stage}
                </span>
                <Progress value={count > 0 ? Math.max(pct, 8) : 0} className="flex-1" />
                <span className="text-sm text-muted-foreground w-8 text-right tabular-nums">{count}</span>
              </div>
            );
          })}
        </CardContent>
      </Card>

      {/* Recent Activity */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-medium text-muted-foreground">最近のアクティビティ</CardTitle>
        </CardHeader>
        <CardContent>
          {stats.recentActivity.length > 0 ? (
            <ul className="space-y-3">
              {stats.recentActivity.map((activity) => (
                <li
                  key={activity.id}
                  className="flex items-start gap-3 text-sm"
                >
                  <span className="w-1.5 h-1.5 mt-1.5 rounded-full bg-muted-foreground/40 shrink-0" />
                  <span className="text-foreground flex-1">{activity.text}</span>
                  <span className="text-xs text-muted-foreground shrink-0">{activity.time}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted-foreground">アクティビティはまだありません</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
