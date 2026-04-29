'use client';

import { useState, useCallback, KeyboardEvent } from 'react';
import { MeetingPhase } from '@/hooks/useMeeting';
import {
  Mic, MicOff, Hand, Play, Pause,
  ChevronLeft, ChevronRight, LogOut, Send, Volume2,
} from 'lucide-react';

interface ControlBarProps {
  phase: MeetingPhase;
  isSpeaking: boolean;
  onSendMessage: (text: string) => void;
  onControl: (action: 'pause' | 'resume' | 'next' | 'prev' | 'end') => void;
  onEnd: () => void;
}

export function ControlBar({ phase, isSpeaking, onSendMessage, onControl, onEnd }: ControlBarProps) {
  const [message, setMessage] = useState('');
  const isActive = phase !== 'idle' && phase !== 'connecting' && phase !== 'ended';

  const handleSend = useCallback(() => {
    const text = message.trim();
    if (!text) return;
    onSendMessage(text);
    setMessage('');
  }, [message, onSendMessage]);

  const handleKeyDown = useCallback((e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }, [handleSend]);

  return (
    <div className="bg-gray-800/80 backdrop-blur border-t border-gray-700 px-4 py-3">
      {/* Speaking indicator */}
      {isSpeaking && (
        <div className="flex items-center gap-2 mb-2 px-2">
          <Volume2 size={14} className="text-blue-400 animate-pulse" />
          <span className="text-xs text-blue-400">ダンが話しています...</span>
        </div>
      )}

      <div className="flex items-center gap-3">
        {/* Message input */}
        <div className="flex-1 flex items-center gap-2 bg-gray-700 rounded-full px-4 py-2">
          <input
            type="text"
            value={message}
            onChange={e => setMessage(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={
              phase === 'presenting'
                ? '質問を入力（プレゼンが一時停止します）'
                : phase === 'qa'
                ? '質問を入力...'
                : 'メッセージを入力...'
            }
            disabled={!isActive}
            className="flex-1 bg-transparent text-white text-sm placeholder-gray-400 outline-none"
          />
          <button
            onClick={handleSend}
            disabled={!message.trim() || !isActive}
            className="p-1 text-gray-400 hover:text-blue-400 disabled:opacity-30 transition-colors"
          >
            <Send size={16} />
          </button>
        </div>

        {/* Presentation controls */}
        {(phase === 'presenting' || phase === 'paused' || phase === 'qa') && (
          <div className="flex items-center gap-1">
            <button
              onClick={() => onControl('prev')}
              className="p-2 text-gray-400 hover:text-white rounded-lg hover:bg-gray-700 transition-colors"
              title="前のスライド"
            >
              <ChevronLeft size={18} />
            </button>

            {phase === 'presenting' ? (
              <button
                onClick={() => onControl('pause')}
                className="p-2 text-yellow-400 hover:text-yellow-300 rounded-lg hover:bg-gray-700 transition-colors"
                title="一時停止"
              >
                <Pause size={18} />
              </button>
            ) : (
              <button
                onClick={() => onControl('resume')}
                className="p-2 text-green-400 hover:text-green-300 rounded-lg hover:bg-gray-700 transition-colors"
                title="再開"
              >
                <Play size={18} />
              </button>
            )}

            <button
              onClick={() => onControl('next')}
              className="p-2 text-gray-400 hover:text-white rounded-lg hover:bg-gray-700 transition-colors"
              title="次のスライド"
            >
              <ChevronRight size={18} />
            </button>
          </div>
        )}

        {/* End meeting */}
        {isActive && (
          <button
            onClick={onEnd}
            className="flex items-center gap-1.5 px-3 py-2 bg-red-600/20 text-red-400 hover:bg-red-600/30 rounded-lg transition-colors text-sm"
          >
            <LogOut size={14} />
            退出
          </button>
        )}
      </div>
    </div>
  );
}
