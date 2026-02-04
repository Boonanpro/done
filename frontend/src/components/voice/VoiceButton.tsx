'use client';

import { Mic, MicOff } from 'lucide-react';

interface VoiceButtonProps {
  isListening: boolean;
  isSupported: boolean;
  onStart: () => void;
  onStop: () => void;
  disabled?: boolean;
}

export function VoiceButton({
  isListening,
  isSupported,
  onStart,
  onStop,
  disabled = false,
}: VoiceButtonProps) {
  const isDisabled = disabled || !isSupported;

  return (
    <button
      type="button"
      onClick={isListening ? onStop : onStart}
      disabled={isDisabled}
      className={`relative flex h-24 w-24 items-center justify-center rounded-full border text-white transition-all duration-200 ${
        isListening
          ? 'border-white/40 bg-white/10 shadow-[0_0_24px_rgba(255,255,255,0.35)]'
          : 'border-white/20 bg-white/5 hover:border-white/40 hover:bg-white/10'
      } ${isDisabled ? 'cursor-not-allowed opacity-40' : ''}`}
      aria-pressed={isListening}
      aria-label={isListening ? 'Stop listening' : 'Start listening'}
    >
      {isListening && (
        <span className="absolute inset-0 rounded-full border border-white/30 animate-ping" />
      )}
      {isListening ? <Mic className="h-8 w-8" /> : <MicOff className="h-8 w-8" />}
    </button>
  );
}
