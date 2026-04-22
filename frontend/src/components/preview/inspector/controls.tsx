'use client';

import { ChangeEvent, useId } from 'react';

/** スライダー + 数値入力 + 単位表示の組み合わせ */
export function SliderInput({
  label,
  value,
  min,
  max,
  step = 1,
  unit = '',
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step?: number;
  unit?: string;
  onChange: (v: number) => void;
}) {
  const id = useId();
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center justify-between text-xs">
        <label htmlFor={id} className="text-muted-foreground">
          {label}
        </label>
        <div className="flex items-center gap-0.5">
          <input
            type="number"
            value={value}
            min={min}
            max={max}
            step={step}
            onChange={(e) => onChange(Number(e.target.value))}
            className="w-14 rounded border border-border bg-input/30 px-1 py-0.5 text-right text-xs"
          />
          {unit && <span className="w-4 text-xs text-muted-foreground">{unit}</span>}
        </div>
      </div>
      <input
        id={id}
        type="range"
        value={value}
        min={min}
        max={max}
        step={step}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full accent-primary"
      />
    </div>
  );
}

/** カラーピッカー + Hex 入力 */
export function ColorInput({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
}) {
  const hex = toHex(value) || '#000000';
  return (
    <div className="flex items-center justify-between gap-2 text-xs">
      <label className="text-muted-foreground">{label}</label>
      <div className="flex items-center gap-1">
        <input
          type="color"
          value={hex}
          onChange={(e) => onChange(e.target.value)}
          className="h-6 w-8 cursor-pointer rounded border border-border bg-transparent"
        />
        <input
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="w-20 rounded border border-border bg-input/30 px-1 py-0.5 text-xs"
          placeholder="#rrggbb"
        />
      </div>
    </div>
  );
}

/** ドロップダウン選択 */
export function SelectInput({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: { value: string; label: string }[];
  onChange: (v: string) => void;
}) {
  return (
    <div className="flex items-center justify-between gap-2 text-xs">
      <label className="text-muted-foreground">{label}</label>
      <select
        value={value}
        onChange={(e: ChangeEvent<HTMLSelectElement>) => onChange(e.target.value)}
        className="max-w-[60%] flex-1 rounded border border-border bg-input/30 px-1 py-0.5 text-xs"
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </div>
  );
}

/** トグルグループ */
export function ToggleGroup({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: { value: string; label: string }[];
  onChange: (v: string) => void;
}) {
  return (
    <div className="flex items-center justify-between gap-2 text-xs">
      <label className="text-muted-foreground">{label}</label>
      <div className="flex overflow-hidden rounded border border-border">
        {options.map((o) => (
          <button
            key={o.value}
            type="button"
            onClick={() => onChange(o.value)}
            className={`px-2 py-0.5 text-xs transition-colors ${
              value === o.value
                ? 'bg-primary text-primary-foreground'
                : 'bg-background text-muted-foreground hover:bg-muted'
            }`}
          >
            {o.label}
          </button>
        ))}
      </div>
    </div>
  );
}

/** セクション見出し */
export function SectionHeader({ title }: { title: string }) {
  return (
    <h3 className="border-b border-border pb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
      {title}
    </h3>
  );
}

/** rgba / rgb / hsl → hex（できる範囲で）*/
function toHex(color: string): string | null {
  if (!color) return null;
  if (color.startsWith('#')) return color.length === 7 ? color : null;
  const m = color.match(/rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/);
  if (m) {
    const [r, g, b] = [m[1], m[2], m[3]].map(Number);
    return (
      '#' +
      [r, g, b].map((v) => v.toString(16).padStart(2, '0')).join('')
    );
  }
  return null;
}

/** CSS value "16px" / "1rem" → 数値（単位を無視）*/
export function parseNumericValue(raw: string | undefined): number | null {
  if (!raw) return null;
  const m = String(raw).match(/-?\d+(\.\d+)?/);
  return m ? Number(m[0]) : null;
}
