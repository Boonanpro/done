'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useVoiceChat } from '@/hooks/useVoiceChat';
import { api, type MessageResponse, type ProcessStep } from '@/lib/api-client';
import { useAuthStore } from '@/stores/auth-store';

type CompanionState = 'loading' | 'idle' | 'listening' | 'processing' | 'speaking' | 'error';

const stateConfig: Record<CompanionState, { color: string; pulse: boolean; label: string }> = {
  loading: { color: '#666', pulse: true, label: '接続中...' },
  idle: { color: '#666', pulse: false, label: 'タップで開始' },
  listening: { color: '#22c55e', pulse: true, label: '聞いています...' },
  processing: { color: '#f59e0b', pulse: true, label: '考え中...' },
  speaking: { color: '#3b82f6', pulse: false, label: 'ダンが話しています...' },
  error: { color: '#ef4444', pulse: false, label: 'エラー' },
};

export default function CompanionPage() {
  const router = useRouter();
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const isLoading = useAuthStore((state) => state.isLoading);
  const user = useAuthStore((state) => state.user);
  const hasToken = typeof window !== 'undefined' && !!localStorage.getItem('done-token');

  const [sessionId, setSessionId] = useState<string | null>(null);
  const [isProcessing, setIsProcessing] = useState(false);
  const [lastDanMessage, setLastDanMessage] = useState<string | null>(null);
  const [currentTranscript, setCurrentTranscript] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const isProcessingRef = useRef(false);

  // 認証チェック
  useEffect(() => {
    if (!isLoading && !isAuthenticated && !hasToken) {
      router.push('/login');
    }
  }, [isLoading, isAuthenticated, hasToken, router]);

  // セッションID取得
  useEffect(() => {
    if (!isAuthenticated && !hasToken) return;
    let cancelled = false;
    (async () => {
      try {
        const room = await api.dan.getRoom();
        if (!cancelled) setSessionId(room.id);
      } catch (err) {
        console.error('Failed to get room:', err);
        if (!cancelled) setErrorMessage('接続に失敗しました');
      }
    })();
    return () => { cancelled = true; };
  }, [isAuthenticated, hasToken]);

  // SSE経由でメッセージ送信（チャットページと同じフロー）
  const sendMessage = useCallback(async (text: string) => {
    if (!sessionId || isProcessingRef.current) return;
    isProcessingRef.current = true;
    setIsProcessing(true);
    setCurrentTranscript(text);

    try {
      await api.sm.sendMessageStream(
        {
          message: text,
          session_id: sessionId,
          user_id: user?.id,
        },
        {
          onAIMessage: (msg: MessageResponse) => {
            setLastDanMessage(msg.content || '');
            // Voice hookのspeakResponseはonAIMessageで呼ばれる（下のeffectで）
          },
          onComplete: () => {
            isProcessingRef.current = false;
            setIsProcessing(false);
            setCurrentTranscript(null);
          },
          onError: (error: string) => {
            console.error('SSE error:', error);
            isProcessingRef.current = false;
            setIsProcessing(false);
            setCurrentTranscript(null);
          },
        }
      );
    } catch (err) {
      console.error('Send failed:', err);
      isProcessingRef.current = false;
      setIsProcessing(false);
      setCurrentTranscript(null);
    }
  }, [sessionId, user?.id]);

  // AI応答メッセージをRefで追跡してTTS再生するため
  const lastDanMessageRef = useRef<string | null>(null);

  const voice = useVoiceChat({
    onFinalTranscript: (text: string) => {
      sendMessage(text);
    },
  });

  // AI応答が来たらTTS再生
  useEffect(() => {
    if (lastDanMessage && lastDanMessage !== lastDanMessageRef.current && voice.isActive) {
      lastDanMessageRef.current = lastDanMessage;
      voice.speakResponse(lastDanMessage);
    }
  }, [lastDanMessage, voice.isActive, voice.speakResponse]);

  // 状態の統合
  let state: CompanionState;
  if (!sessionId) {
    state = errorMessage ? 'error' : 'loading';
  } else if (!voice.isActive) {
    state = 'idle';
  } else if (voice.isSpeaking) {
    state = 'speaking';
  } else if (isProcessing) {
    state = 'processing';
  } else {
    state = 'listening';
  }

  const { color, pulse, label } = stateConfig[state];

  const handleToggle = () => {
    if (voice.isActive) {
      voice.toggleVoice();
    } else {
      voice.toggleVoice();
    }
  };

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        background: '#000',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        fontFamily: 'system-ui, sans-serif',
        color: '#fff',
        userSelect: 'none',
        WebkitUserSelect: 'none',
        touchAction: 'manipulation',
      }}
    >
      {/* Status dot */}
      <div
        onClick={state === 'speaking' ? () => voice.skipSpeaking() : undefined}
        style={{
          width: 80,
          height: 80,
          borderRadius: '50%',
          background: color,
          boxShadow: pulse ? `0 0 40px ${color}, 0 0 80px ${color}40` : `0 0 20px ${color}60`,
          animation: pulse ? 'pulse 2s ease-in-out infinite' : 'none',
          transition: 'background 0.3s, box-shadow 0.3s',
          marginBottom: 32,
          cursor: state === 'speaking' ? 'pointer' : 'default',
        }}
      />

      {/* State label */}
      <div style={{ fontSize: 18, color: '#999', marginBottom: 16 }}>
        {label}
      </div>

      {/* Error display */}
      {voice.error && (
        <div style={{ fontSize: 12, color: '#ef4444', marginBottom: 8, maxWidth: '80%', textAlign: 'center' }}>
          Error: {voice.error}
        </div>
      )}

      {/* Debug info (development only) */}
      <div style={{ fontSize: 10, color: '#555', marginBottom: 16, maxWidth: '80%', textAlign: 'center' }}>
        {voice.isActive ? (voice.isListening ? 'MIC ON' : 'MIC OFF') : ''} {isProcessing ? '| SENDING' : ''} {sessionId ? '' : '| NO SESSION'}
      </div>

      {/* Current transcript / interim */}
      {(currentTranscript || voice.interimTranscript) && (
        <div style={{ fontSize: 14, color: '#666', marginBottom: 24, maxWidth: '80%', textAlign: 'center' }}>
          {voice.interimTranscript || currentTranscript}
        </div>
      )}

      {/* Last Dan message */}
      {lastDanMessage && (
        <div
          style={{
            fontSize: 14,
            color: '#444',
            maxWidth: '80%',
            textAlign: 'center',
            lineHeight: 1.5,
            position: 'absolute',
            bottom: 120,
            left: '10%',
            right: '10%',
            overflow: 'hidden',
            display: '-webkit-box',
            WebkitLineClamp: 3,
            WebkitBoxOrient: 'vertical',
          }}
        >
          {lastDanMessage}
        </div>
      )}

      {/* Start / Stop button */}
      {sessionId && (
        <button
          onClick={handleToggle}
          style={{
            position: 'absolute',
            bottom: 48,
            padding: '14px 48px',
            fontSize: 16,
            fontWeight: 600,
            border: 'none',
            borderRadius: 28,
            background: voice.isActive ? '#333' : '#fff',
            color: voice.isActive ? '#fff' : '#000',
            cursor: 'pointer',
            transition: 'background 0.2s, color 0.2s',
          }}
        >
          {voice.isActive ? '停止' : '開始'}
        </button>
      )}

      {/* Pulse animation */}
      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; transform: scale(1); }
          50% { opacity: 0.7; transform: scale(1.1); }
        }
      `}</style>
    </div>
  );
}
