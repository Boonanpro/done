interface DataPoint {
  label: string;
  value: number;
}

interface TimeSeriesChartProps {
  title: string;
  data: DataPoint[];
  color?: string;
}

export function TimeSeriesChart({
  title,
  data,
  color = 'bg-blue-500',
}: TimeSeriesChartProps) {
  const maxValue = Math.max(...data.map((d) => d.value), 1);

  return (
    <div className="rounded-xl border border-neutral-800 bg-neutral-900/50 p-5">
      <h3 className="text-sm font-medium text-neutral-400 mb-4">{title}</h3>
      {data.length > 0 ? (
        <div className="flex items-end gap-1 h-32">
          {data.map((point, i) => {
            const pct = (point.value / maxValue) * 100;
            return (
              <div
                key={i}
                className="flex-1 flex flex-col items-center gap-1"
              >
                <span className="text-[10px] text-neutral-600 tabular-nums">
                  {point.value}
                </span>
                <div className="w-full flex items-end justify-center" style={{ height: '80px' }}>
                  <div
                    className={`w-full max-w-[24px] rounded-t ${color} transition-all`}
                    style={{ height: `${Math.max(pct, 2)}%` }}
                  />
                </div>
                <span className="text-[10px] text-neutral-600 truncate w-full text-center">
                  {point.label}
                </span>
              </div>
            );
          })}
        </div>
      ) : (
        <div className="h-32 flex items-center justify-center">
          <span className="text-sm text-neutral-600">データがありません</span>
        </div>
      )}
    </div>
  );
}
