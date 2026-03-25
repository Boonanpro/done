'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { KpiCard } from '@/app/dashboard/components/kpi-card';

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

const projectStatusColors: Record<string, string> = {
  planning: 'bg-yellow-500',
  in_progress: 'bg-blue-500',
  review: 'bg-violet-500',
  deployed: 'bg-emerald-500',
  maintenance: 'bg-cyan-500',
  archived: 'bg-neutral-500',
};

export default function DxHomePage() {
  const [stats, setStats] = useState<DxStats | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch(`${API_BASE}/dashboard/dx/stats`)
      .then((r) => r.json())
      .then(setStats)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="w-6 h-6 border-2 border-neutral-600 border-t-white rounded-full animate-spin" />
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
          <h1 className="text-2xl font-semibold text-white mb-1">DX事業</h1>
          <p className="text-sm text-neutral-500">HP制作・DXツール提供の統合管理</p>
        </div>
        <div className="flex gap-2">
          <Link
            href="/dashboard/dx/clients"
            className="px-4 py-2 rounded-lg text-sm bg-neutral-800 text-white hover:bg-neutral-700 transition-colors"
          >
            クライアント一覧
          </Link>
          <Link
            href="/dashboard/dx/projects"
            className="px-4 py-2 rounded-lg text-sm bg-white text-neutral-900 hover:bg-neutral-200 transition-colors"
          >
            プロジェクト一覧
          </Link>
        </div>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <KpiCard label="クライアント数" value={kpis?.client_count ?? 0} icon="🏢" />
        <KpiCard label="アクティブ" value={kpis?.active_clients ?? 0} icon="✅" />
        <KpiCard label="プロジェクト数" value={kpis?.project_count ?? 0} icon="📁" />
        <KpiCard label="公開済み" value={kpis?.deployed_projects ?? 0} icon="🚀" />
      </div>

      {/* Project Status */}
      <div className="rounded-xl border border-neutral-800 bg-neutral-900/50 p-5">
        <h2 className="text-sm font-medium text-neutral-400 mb-4">プロジェクトステータス</h2>
        <div className="space-y-3">
          {allStatuses.map((status) => {
            const count = projectStatus[status] || 0;
            const pct = (count / maxCount) * 100;
            return (
              <div key={status} className="flex items-center gap-3">
                <span className="text-xs text-neutral-400 w-20 shrink-0 text-right">
                  {projectStatusLabels[status]}
                </span>
                <div className="flex-1 h-6 bg-neutral-800 rounded-md overflow-hidden">
                  <div
                    className={`h-full rounded-md transition-all ${projectStatusColors[status] ?? 'bg-neutral-600'}`}
                    style={{ width: `${Math.max(pct, count > 0 ? 8 : 0)}%` }}
                  />
                </div>
                <span className="text-xs text-neutral-500 w-8 text-right">{count}</span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
