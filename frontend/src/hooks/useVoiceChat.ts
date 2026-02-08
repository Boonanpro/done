'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { useSpeechRecognition } from './useSpeechRecognition';
import { api } from '@/lib/api-client';

type VoiceChatState = 'idle' | 'listening' | 'speaking';

interface UseVoiceChatOptions {
  onFinalTranscript: (text: string) => void;
}

interface UseVoiceChatResult {
  isActive: boolean;
  isListening: boolean;
  isSpeaking: boolean;
  interimTranscript: string;
  error: string | null;
  state: VoiceChatState;
  toggleVoice: () => void;
  speakResponse: (text: string) => void;
  skipSpeaking: () => void;
}

export function useVoiceChat({ onFinalTranscript }: UseVoiceChatOptions): UseVoiceChatResult {
  const [isActive, setIsActive] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const isActiveRef = useRef(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const objectUrlRef = useRef<string | null>(null);
  const shouldRestartListeningRef = useRef(false);
  const onFinalTranscriptRef = useRef(onFinalTranscript);
  const hasSentRef = useRef(false);

  useEffect(() => {
    onFinalTranscriptRef.current = onFinalTranscript;
  }, [onFinalTranscript]);

  // onFinalTranscript を直接 useSpeechRecognition に渡す
  const handleFinalTranscript = useCallback((text: string) => {
    if (!isActiveRef.current) return;
    hasSentRef.current = true;
    onFinalTranscriptRef.current(text);
  }, []);

  const speech = useSpeechRecognition({
    lang: 'ja-JP',
    interimResults: true,
    continuous: false,
    onFinalTranscript: handleFinalTranscript,
  });

  // Auto-restart listening after speech recognition ends (non-continuous mode)
  useEffect(() => {
    if (isActiveRef.current && !speech.isListening && !isSpeaking) {
      const timer = setTimeout(() => {
        if (isActiveRef.current && !isSpeaking) {
          hasSentRef.current = false;
          try {
            speech.start();
          } catch {
            // Ignore start errors
          }
        }
      }, 500);
      return () => clearTimeout(timer);
    }
  }, [speech.isListening, isSpeaking, speech]);

  const cleanupAudio = useCallback(() => {
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current.removeAttribute('src');
      audioRef.current = null;
    }
    if (objectUrlRef.current) {
      URL.revokeObjectURL(objectUrlRef.current);
      objectUrlRef.current = null;
    }
  }, []);

  const speakResponse = useCallback(async (text: string) => {
    if (!isActiveRef.current) return;

    setIsSpeaking(true);
    speech.stop();

    try {
      const audioData = await api.voice.tts(text);
      const blob = new Blob([audioData], { type: 'audio/mpeg' });
      const url = URL.createObjectURL(blob);
      objectUrlRef.current = url;

      const audio = new Audio(url);
      audioRef.current = audio;
      shouldRestartListeningRef.current = true;

      audio.onended = () => {
        setIsSpeaking(false);
        cleanupAudio();
        if (shouldRestartListeningRef.current && isActiveRef.current) {
          hasSentRef.current = false;
          speech.reset();
          try {
            speech.start();
          } catch {
            // Ignore
          }
        }
      };

      audio.onerror = () => {
        setIsSpeaking(false);
        cleanupAudio();
        if (isActiveRef.current) {
          hasSentRef.current = false;
          speech.reset();
          try {
            speech.start();
          } catch {
            // Ignore
          }
        }
      };

      await audio.play();
    } catch (error) {
      console.error('TTS playback failed:', error);
      setIsSpeaking(false);
      if (isActiveRef.current) {
        hasSentRef.current = false;
        speech.reset();
        try {
          speech.start();
        } catch {
          // Ignore
        }
      }
    }
  }, [speech, cleanupAudio]);

  const skipSpeaking = useCallback(() => {
    shouldRestartListeningRef.current = false;
    cleanupAudio();
    setIsSpeaking(false);
    if (isActiveRef.current) {
      hasSentRef.current = false;
      speech.reset();
      try {
        speech.start();
      } catch {
        // Ignore
      }
    }
  }, [speech, cleanupAudio]);

  const toggleVoice = useCallback(() => {
    if (isActiveRef.current) {
      // Turn off — stop() triggers onresult with final result if available.
      // The onFinalTranscript callback fires synchronously from onresult,
      // so the message will be sent before we reset.
      isActiveRef.current = false;
      setIsActive(false);
      speech.stop();
      // Small delay before reset to let onresult fire
      setTimeout(() => {
        speech.reset();
      }, 100);
      cleanupAudio();
      setIsSpeaking(false);
    } else {
      // Turn on
      isActiveRef.current = true;
      setIsActive(true);
      hasSentRef.current = false;
      speech.reset();
      try {
        speech.start();
      } catch {
        // Ignore
      }
    }
  }, [speech, cleanupAudio]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      isActiveRef.current = false;
      cleanupAudio();
    };
  }, [cleanupAudio]);

  const state: VoiceChatState = !isActive ? 'idle' : isSpeaking ? 'speaking' : 'listening';

  return {
    isActive,
    isListening: isActive && speech.isListening,
    isSpeaking,
    interimTranscript: speech.interimTranscript,
    error: speech.error,
    state,
    toggleVoice,
    speakResponse,
    skipSpeaking,
  };
}
