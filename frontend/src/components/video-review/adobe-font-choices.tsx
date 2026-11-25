'use client';

import { useEffect, useId, useState } from 'react';
import { ADOBE_FONTS, HEADING_FONTS, isRetiredFont, loadHeadingKit } from './adobe-fonts';

export function AdobeFontChoices({ text, selected, headingsOnly, onSelect }: {
  text: string;
  selected: string;
  headingsOnly?: boolean;
  onSelect: (id: keyof typeof ADOBE_FONTS) => void;
}) {
  const group = useId();
  const [error, setError] = useState(false);
  useEffect(() => { void loadHeadingKit().catch(() => setError(true)); }, []);
  const ids = Object.keys(headingsOnly ? HEADING_FONTS : ADOBE_FONTS) as (keyof typeof ADOBE_FONTS)[];
  return <>
    {error && <p role="alert" className="text-sm">Adobe Fonts の見本を読み込めませんでした。</p>}
    <div className="grid grid-cols-2 gap-2">
      {ids.filter(id => !isRetiredFont(id)).map(id => {
        const f = ADOBE_FONTS[id];
        return <label key={id} className={`min-w-0 cursor-pointer rounded border p-2 ${selected === id ? 'border-primary' : ''}`}>
          <span className="flex items-center gap-2 text-xs"><input type="radio" name={group} aria-label={f.label}
            checked={selected === id} onChange={() => onSelect(id)}/>{f.label}</span>
          <span aria-hidden="true" className="mt-1 block truncate text-2xl"
            style={{fontFamily: 'web' in f ? f.web : f.face, fontWeight: f.weight}}>{text || '旅の記録 2026'}</span>
        </label>;
      })}
    </div>
  </>;
}
