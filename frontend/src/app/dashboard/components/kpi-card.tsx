import type { LucideIcon } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';

interface KpiCardProps {
  label: string;
  value: number | string;
  icon?: LucideIcon;
  change?: number;
}

export function KpiCard({ label, value, icon: Icon, change }: KpiCardProps) {
  return (
    <Card>
      <CardContent className="pt-6">
        <div className="flex items-center justify-between mb-2">
          <span className="text-sm text-muted-foreground">{label}</span>
          {Icon && <Icon className="h-4 w-4 text-muted-foreground" />}
        </div>
        <div className="flex items-end gap-2">
          <span className="text-2xl font-semibold tabular-nums">
            {typeof value === 'number' ? value.toLocaleString() : value}
          </span>
          {change !== undefined && (
            <span
              className={`text-xs mb-0.5 ${change >= 0 ? 'text-emerald-400' : 'text-red-400'}`}
            >
              {change >= 0 ? '+' : ''}
              {change}%
            </span>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
