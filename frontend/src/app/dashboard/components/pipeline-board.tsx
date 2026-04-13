interface Deal {
  id: string;
  company_name: string;
  stage: string;
  amount: number;
  probability: 'A' | 'B' | 'C' | 'D';
}

interface PipelineBoardProps {
  stages: string[];
  deals: Deal[];
}

const probColors: Record<string, string> = {
  A: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30',
  B: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
  C: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
  D: 'bg-red-500/20 text-red-400 border-red-500/30',
};

function formatAmount(amount: number): string {
  if (amount >= 10000) {
    return `${(amount / 10000).toFixed(0)}万`;
  }
  return amount.toLocaleString();
}

export function PipelineBoard({ stages, deals }: PipelineBoardProps) {
  return (
    <div className="flex gap-3 overflow-x-auto pb-4">
      {stages.map((stage) => {
        const stageDeals = deals.filter((d) => d.stage === stage);
        return (
          <div
            key={stage}
            className="min-w-[200px] w-[200px] shrink-0"
          >
            {/* Stage header */}
            <div className="flex items-center justify-between mb-3 px-1">
              <span className="text-xs font-medium text-neutral-400">{stage}</span>
              <span className="text-xs text-neutral-600 tabular-nums">
                {stageDeals.length}
              </span>
            </div>

            {/* Cards */}
            <div className="space-y-2">
              {stageDeals.map((deal) => (
                <div
                  key={deal.id}
                  className="rounded-lg border border-neutral-800 bg-neutral-900/80 p-3 hover:border-neutral-700 transition-colors"
                >
                  <div className="flex items-start justify-between gap-2 mb-2">
                    <span className="text-sm text-white font-medium leading-tight">
                      {deal.company_name}
                    </span>
                    <span
                      className={`text-[10px] px-1.5 py-0.5 rounded border font-medium shrink-0 ${probColors[deal.probability] ?? probColors.D}`}
                    >
                      {deal.probability}
                    </span>
                  </div>
                  <span className="text-xs text-neutral-500">
                    {deal.amount > 0 ? `¥${formatAmount(deal.amount)}` : '金額未定'}
                  </span>
                </div>
              ))}
              {stageDeals.length === 0 && (
                <div className="rounded-lg border border-dashed border-neutral-800 p-4 text-center">
                  <span className="text-xs text-neutral-700">なし</span>
                </div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
