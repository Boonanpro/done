'use client';

import { useCallback, useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useGeminiVoice } from '@/hooks/useGeminiVoice';
import { api } from '@/lib/api-client';
import { useAuthStore } from '@/stores/auth-store';

type CompanionState = 'loading' | 'idle' | 'connecting' | 'listening' | 'processing' | 'speaking' | 'error';

const stateConfig: Record<CompanionState, { color: string; pulse: boolean; label: string }> = {
  loading: { color: '#666', pulse: true, label: '接続中...' },
  idle: { color: '#666', pulse: false, label: 'タップで開始' },
  connecting: { color: '#f59e0b', pulse: true, label: '接続中...' },
  listening: { color: '#22c55e', pulse: true, label: '聞いています...' },
  processing: { color: '#f59e0b', pulse: true, label: '考え中...' },
  speaking: { color: '#3b82f6', pulse: false, label: 'ダンが話しています...' },
  error: { color: '#ef4444', pulse: false, label: 'エラー' },
};

export default function CompanionPage() {
  const router = useRouter();
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const isLoading = useAuthStore((state) => state.isLoading);
  const hasToken = typeof window !== 'undefined' && !!localStorage.getItem('done-token');

  const [sessionId, setSessionId] = useState<string | null>(null);
  const [lastDanMessage, setLastDanMessage] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [toolLabel, setToolLabel] = useState<string | null>(null);

  // Auth check
  useEffect(() => {
    if (!isLoading && !isAuthenticated && !hasToken) {
      router.push('/login');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isLoading, isAuthenticated, hasToken]);

  // Get session ID
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

  const voice = useGeminiVoice({
    sessionId,
    onText: useCallback((text: string) => {
      setLastDanMessage(text);
    }, []),
    onToolStart: useCallback((tool: string) => {
      setToolLabel(tool);
    }, []),
    onToolResult: useCallback(() => {
      setToolLabel(null);
    }, []),
    onTurnComplete: useCallback(() => {
      setToolLabel(null);
    }, []),
  });

  // Map Gemini voice state to companion state
  let state: CompanionState;
  if (!sessionId) {
    state = errorMessage ? 'error' : 'loading';
  } else if (voice.state === 'idle') {
    state = 'idle';
  } else if (voice.state === 'connecting') {
    state = 'connecting';
  } else if (voice.state === 'speaking') {
    state = 'speaking';
  } else if (voice.state === 'processing') {
    state = 'processing';
  } else if (voice.state === 'error') {
    state = 'error';
  } else {
    state = 'listening';
  }

  const config = stateConfig[state];
  const displayLabel = state === 'processing' && toolLabel
    ? `${toolLabel}...`
    : config.label;

  const handleToggle = () => {
    if (voice.state === 'idle' || voice.state === 'error') {
      voice.connect();
    } else {
      voice.disconnect();
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
        style={{
          width: 80,
          height: 80,
          borderRadius: '50%',
          background: config.color,
          boxShadow: config.pulse ? `0 0 40px ${config.color}, 0 0 80px ${config.color}40` : `0 0 20px ${config.color}60`,
          animation: config.pulse ? 'pulse 2s ease-in-out infinite' : 'none',
          transition: 'background 0.3s, box-shadow 0.3s',
          marginBottom: 32,
        }}
      />

      {/* State label */}
      <div style={{ fontSize: 18, color: '#999', marginBottom: 16 }}>
        {displayLabel}
      </div>

      {/* Error display */}
      {voice.error && (
        <div style={{ fontSize: 12, color: '#ef4444', marginBottom: 8, maxWidth: '80%', textAlign: 'center' }}>
          {voice.error}
        </div>
      )}

      {/* Debug info */}
      <div style={{ fontSize: 10, color: '#555', marginBottom: 8, maxWidth: '90%', textAlign: 'center', wordBreak: 'break-all' }}>
        {voice.debugUrl || `state: ${voice.state} | sid: ${sessionId?.slice(0, 8) || 'none'}`}
      </div>

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
            background: voice.state !== 'idle' && voice.state !== 'error' ? '#333' : '#fff',
            color: voice.state !== 'idle' && voice.state !== 'error' ? '#fff' : '#000',
            cursor: 'pointer',
            transition: 'background 0.2s, color 0.2s',
          }}
        >
          {voice.state !== 'idle' && voice.state !== 'error' ? '停止' : '開始'}
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
