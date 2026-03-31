'use client';

import { useEffect, useState } from 'react';
import { PipelineBoard } from '@/app/dashboard/components/pipeline-board';

const API_BASE = 'http://127.0.0.1:8000/api';

export interface Deal {
  id: string;
  company_name: string;
  stage: string;
  amount: number;
  probability: 'A' | 'B' | 'C' | 'D';
}

const stages = [
  '初回連絡',
  'アポ取得',
  '商談実施',
  '見積提出',
  '交渉中',
  '成約',
  '失注',
];

export default function DealsPage() {
  const [deals, setDeals] = useState<Deal[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchDeals = async () => {
      try {
        const res = await fetch(`${API_BASE}/dashboard/ai-b2b-sales/deals`, { credentials: 'include' });
        if (res.ok) {
          const data = await res.json();
          setDeals(data.deals ?? data);
        }
      } catch {
        // keep empty
      } finally {
        setLoading(false);
      }
    };
    fetchDeals();
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="w-6 h-6 border-2 border-neutral-600 border-t-white rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-white mb-1">商談管理</h1>
        <p className="text-sm text-neutral-500">
          {deals.length}件の商談
        </p>
      </div>

      <PipelineBoard stages={stages} deals={deals} />

      {deals.length === 0 && (
        <div className="text-center py-16 text-neutral-500">
          <p className="text-lg mb-2">商談がまだありません</p>
          <p className="text-sm">企業への提案を開始すると、ここに表示されます</p>
        </div>
      )}
    </div>
  );
}
