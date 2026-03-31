'use client';

import { useEffect, useState, useMemo } from 'react';
import { DataTable } from '@/app/dashboard/components/data-table';

const API_BASE = 'http://127.0.0.1:8000/api';

interface Company {
  id: string;
  name: string;
  industry: string;
  area: string;
  status: string;
  score: number;
  updated_at: string;
}

const statusConfig: Record<string, { label: string; className: string }> = {
  new: { label: '新規', className: 'bg-neutral-500/20 text-neutral-400 border-neutral-500/30' },
  researched: { label: '調査済', className: 'bg-blue-500/20 text-blue-400 border-blue-500/30' },
  email_sent: { label: 'メール済', className: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30' },
  replied: { label: '返信あり', className: 'bg-green-500/20 text-green-400 border-green-500/30' },
  contracted: { label: '契約済', className: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30' },
  excluded: { label: '除外', className: 'bg-red-500/20 text-red-400 border-red-500/30' },
};

const allStatuses = Object.keys(statusConfig);

export default function CompaniesPage() {
  const [companies, setCompanies] = useState<Company[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('all');

  useEffect(() => {
    const fetchCompanies = async () => {
      try {
        const res = await fetch(`${API_BASE}/dashboard/ai-b2b-sales/companies`, { credentials: 'include' });
        if (res.ok) {
          const data = await res.json();
          setCompanies(data.companies ?? data);
        }
      } catch {
        // keep empty
      } finally {
        setLoading(false);
      }
    };
    fetchCompanies();
  }, []);

  const filtered = useMemo(() => {
    return companies.filter((c) => {
      const matchesSearch = !search || c.name.toLowerCase().includes(search.toLowerCase());
      const matchesStatus = statusFilter === 'all' || c.status === statusFilter;
      return matchesSearch && matchesStatus;
    });
  }, [companies, search, statusFilter]);

  const columns = [
    {
      key: 'name' as const,
      label: '企業名',
      render: (c: Company) => (
        <span className="text-white font-medium">{c.name}</span>
      ),
    },
    { key: 'industry' as const, label: '業種' },
    { key: 'area' as const, label: 'エリア' },
    {
      key: 'status' as const,
      label: 'ステータス',
      render: (c: Company) => {
        const cfg = statusConfig[c.status] ?? statusConfig.new;
        return (
          <span className={`text-xs px-2 py-0.5 rounded-full border ${cfg.className}`}>
            {cfg.label}
          </span>
        );
      },
    },
    {
      key: 'score' as const,
      label: 'スコア',
      render: (c: Company) => (
        <span className={`text-sm font-mono ${c.score >= 70 ? 'text-emerald-400' : c.score >= 40 ? 'text-yellow-400' : 'text-neutral-500'}`}>
          {c.score}
        </span>
      ),
    },
    {
      key: 'updated_at' as const,
      label: '更新日',
      render: (c: Company) => (
        <span className="text-neutral-500 text-xs">
          {new Date(c.updated_at).toLocaleDateString('ja-JP')}
        </span>
      ),
    },
  ];

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="w-6 h-6 border-2 border-neutral-600 border-t-white rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-white mb-1">企業リスト</h1>
        <p className="text-sm text-neutral-500">
          {companies.length}件の企業
        </p>
      </div>

      {/* Filters */}
      <div className="flex flex-col sm:flex-row gap-3">
        <input
          type="text"
          placeholder="企業名で検索..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="flex-1 px-3 py-2 text-sm bg-neutral-900 border border-neutral-800 rounded-lg text-white placeholder-neutral-600 focus:outline-none focus:border-neutral-600"
        />
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="px-3 py-2 text-sm bg-neutral-900 border border-neutral-800 rounded-lg text-neutral-300 focus:outline-none focus:border-neutral-600"
        >
          <option value="all">全ステータス</option>
          {allStatuses.map((s) => (
            <option key={s} value={s}>
              {statusConfig[s].label}
            </option>
          ))}
        </select>
      </div>

      {/* Table */}
      <DataTable columns={columns} data={filtered} emptyMessage="企業が見つかりません" />
    </div>
  );
}
