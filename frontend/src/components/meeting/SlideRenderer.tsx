'use client';

import { SlideContent } from '@/hooks/useMeeting';
import { ChevronLeft, ChevronRight } from 'lucide-react';

interface SlideRendererProps {
  slide: SlideContent | null;
  onPrev?: () => void;
  onNext?: () => void;
  preparing?: boolean;
}

export function SlideRenderer({ slide, onPrev, onNext, preparing }: SlideRendererProps) {
  if (preparing) {
    return (
      <div className="flex-1 flex items-center justify-center bg-gradient-to-br from-gray-900 to-gray-800 rounded-xl">
        <div className="text-center">
          <div className="w-12 h-12 border-4 border-blue-500 border-t-transparent rounded-full animate-spin mx-auto mb-4" />
          <p className="text-gray-400 text-lg">スライドを準備中...</p>
        </div>
      </div>
    );
  }

  if (!slide) {
    return (
      <div className="flex-1 flex items-center justify-center bg-gradient-to-br from-gray-900 to-gray-800 rounded-xl">
        <p className="text-gray-500">MTGを開始してください</p>
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col bg-gradient-to-br from-gray-900 to-gray-800 rounded-xl overflow-hidden">
      {/* Slide content */}
      <div className="flex-1 p-8 flex flex-col justify-center">
        <h2 className="text-2xl font-bold text-white mb-6">{slide.title}</h2>

        <ul className="space-y-3 mb-6">
          {slide.bullets.map((bullet, i) => (
            <li key={i} className="flex items-start gap-3 text-gray-200 text-lg">
              <span className="w-2 h-2 rounded-full bg-blue-400 mt-2.5 shrink-0" />
              <span>{bullet}</span>
            </li>
          ))}
        </ul>

        {slide.highlight && (
          <div className="mt-4 p-4 bg-blue-500/10 border border-blue-500/30 rounded-lg">
            <p className="text-blue-300 font-medium">{slide.highlight}</p>
          </div>
        )}
      </div>

      {/* Navigation bar */}
      <div className="flex items-center justify-between px-6 py-3 bg-black/30">
        <button
          onClick={onPrev}
          disabled={slide.index === 0}
          className="p-2 text-gray-400 hover:text-white disabled:opacity-30 transition-colors"
        >
          <ChevronLeft size={20} />
        </button>

        <span className="text-gray-400 text-sm font-mono">
          {slide.index + 1} / {slide.total}
        </span>

        <button
          onClick={onNext}
          disabled={slide.index === slide.total - 1}
          className="p-2 text-gray-400 hover:text-white disabled:opacity-30 transition-colors"
        >
          <ChevronRight size={20} />
        </button>
      </div>
    </div>
  );
}
