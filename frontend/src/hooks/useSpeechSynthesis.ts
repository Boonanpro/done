'use client';

import { useCallback, useEffect, useState } from 'react';

interface SpeakOptions {
  lang?: string;
  voiceName?: string;
  rate?: number;
  pitch?: number;
  volume?: number;
  interrupt?: boolean;
}

interface UseSpeechSynthesisResult {
  isSupported: boolean;
  isSpeaking: boolean;
  voices: SpeechSynthesisVoice[];
  error: string | null;
  speak: (text: string, options?: SpeakOptions) => void;
  cancel: () => void;
}

export function useSpeechSynthesis(): UseSpeechSynthesisResult {
  const [isSupported, setIsSupported] = useState(true);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [voices, setVoices] = useState<SpeechSynthesisVoice[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (typeof window === 'undefined' || !window.speechSynthesis) {
      setIsSupported(false);
      return;
    }

    const loadVoices = () => {
      const available = window.speechSynthesis.getVoices();
      setVoices(available);
    };

    loadVoices();
    window.speechSynthesis.onvoiceschanged = loadVoices;

    return () => {
      if (window.speechSynthesis) {
        window.speechSynthesis.onvoiceschanged = null;
      }
    };
  }, []);

  const cancel = useCallback(() => {
    if (!window.speechSynthesis) return;
    window.speechSynthesis.cancel();
    setIsSpeaking(false);
  }, []);

  const speak = useCallback(
    (text: string, options: SpeakOptions = {}) => {
      if (!window.speechSynthesis || !text.trim()) return;

      const {
        lang = 'ja-JP',
        voiceName,
        rate = 1,
        pitch = 1,
        volume = 1,
        interrupt = true,
      } = options;

      if (interrupt) {
        window.speechSynthesis.cancel();
      }

      const utterance = new SpeechSynthesisUtterance(text);
      utterance.lang = lang;
      utterance.rate = rate;
      utterance.pitch = pitch;
      utterance.volume = volume;

      if (voiceName) {
        const match = voices.find((voice) => voice.name === voiceName);
        if (match) utterance.voice = match;
      } else {
        const byLang = voices.find((voice) => voice.lang?.startsWith(lang));
        if (byLang) utterance.voice = byLang;
      }

      utterance.onstart = () => {
        setIsSpeaking(true);
        setError(null);
      };
      utterance.onend = () => {
        setIsSpeaking(false);
      };
      utterance.onerror = (event) => {
        setIsSpeaking(false);
        setError(event.error || 'speech-synthesis-error');
      };

      window.speechSynthesis.speak(utterance);
    },
    [voices]
  );

  return {
    isSupported,
    isSpeaking,
    voices,
    error,
    speak,
    cancel,
  };
}
