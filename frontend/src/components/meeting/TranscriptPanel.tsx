'use client';

import { useEffect, useRef } from 'react';
import { TranscriptEntry } from '@/hooks/useMeeting';

interface TranscriptPanelProps {
  entries: TranscriptEntry[];
  summary?: string | null;
}

export function TranscriptPanel({ entries, summary }: TranscriptPanelProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [entries.length]);

  return (
    <div className="flex flex-col h-full">
      <div className="px-4 py-3 border-b border-gray-700">
        <h3 className="text-sm font-semibold text-gray-300">トランスクリプト</h3>
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
        {entries.map((entry, i) => (
          <div key={i} className={`flex gap-2 ${entry.speaker === 'user' ? 'justify-end' : ''}`}>
            {entry.speaker === 'dan' && (
              <div className="w-6 h-6 rounded-full bg-blue-600 flex items-center justify-center shrink-0 mt-0.5">
                <span className="text-[10px] font-bold text-white">D</span>
              </div>
            )}
            <div
              className={`max-w-[85%] rounded-lg px-3 py-2 text-sm leading-relaxed ${
                entry.speaker === 'dan'
                  ? 'bg-gray-700 text-gray-200'
                  : 'bg-blue-600 text-white'
              }`}
            >
              {entry.text}
            </div>
          </div>
        ))}

        {summary && (
          <div className="mt-4 p-3 bg-green-500/10 border border-green-500/30 rounded-lg">
            <h4 className="text-xs font-semibold text-green-400 mb-2">MTGサマリー</h4>
            <p className="text-sm text-gray-300 whitespace-pre-wrap">{summary}</p>
          </div>
        )}

        <div ref={bottomRef} />
      </div>
    </div>
  );
}
