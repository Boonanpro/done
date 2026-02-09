'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { PCMPlayer } from '@/lib/audio-playback';

export type GeminiVoiceState =
  | 'idle'
  | 'connecting'
  | 'listening'
  | 'speaking'
  | 'processing'
  | 'error';

interface UseGeminiVoiceOptions {
  sessionId: string | null;
  onText?: (text: string) => void;
  onProcessStep?: (step: string) => void;
  onToolStart?: (tool: string) => void;
  onToolResult?: (tool: string, success: boolean) => void;
  onTurnComplete?: () => void;
}

interface UseGeminiVoiceResult {
  state: GeminiVoiceState;
  error: string | null;
  lastText: string | null;
  debugUrl: string | null;
  connect: () => Promise<void>;
  disconnect: () => void;
}

function getWsBase(): string {
  if (process.env.NEXT_PUBLIC_WS_URL) {
    return process.env.NEXT_PUBLIC_WS_URL;
  }
  if (typeof window === 'undefined') return 'ws://localhost:8000';
  // Same-origin WebSocket: use the Next.js dev server which proxies /ws/* to backend
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${proto}//${window.location.host}`;
}

export function useGeminiVoice({
  sessionId,
  onText,
  onProcessStep,
  onToolStart,
  onToolResult,
  onTurnComplete,
}: UseGeminiVoiceOptions): UseGeminiVoiceResult {
  const [state, setState] = useState<GeminiVoiceState>('idle');
  const [error, setError] = useState<string | null>(null);
  const [lastText, setLastText] = useState<string | null>(null);
  const [debugUrl, setDebugUrl] = useState<string | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const playerRef = useRef<PCMPlayer | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const streamRef = useRef<MediaStream | null>(null);

  // Refs for callbacks to avoid stale closures
  const onTextRef = useRef(onText);
  const onProcessStepRef = useRef(onProcessStep);
  const onToolStartRef = useRef(onToolStart);
  const onToolResultRef = useRef(onToolResult);
  const onTurnCompleteRef = useRef(onTurnComplete);

  useEffect(() => { onTextRef.current = onText; }, [onText]);
  useEffect(() => { onProcessStepRef.current = onProcessStep; }, [onProcessStep]);
  useEffect(() => { onToolStartRef.current = onToolStart; }, [onToolStart]);
  useEffect(() => { onToolResultRef.current = onToolResult; }, [onToolResult]);
  useEffect(() => { onTurnCompleteRef.current = onTurnComplete; }, [onTurnComplete]);

  const disconnect = useCallback(() => {
    // Close WebSocket
    if (wsRef.current) {
      try { wsRef.current.close(); } catch {}
      wsRef.current = null;
    }

    // Stop microphone
    if (streamRef.current) {
      streamRef.current.getTracks().forEach(t => t.stop());
      streamRef.current = null;
    }

    // Close AudioContext (capture)
    if (audioCtxRef.current) {
      audioCtxRef.current.close().catch(() => {});
      audioCtxRef.current = null;
    }

    // Stop player
    if (playerRef.current) {
      playerRef.current.destroy();
      playerRef.current = null;
    }

    setState('idle');
  }, []);

  const connect = useCallback(async () => {
    if (!sessionId) {
      setError('No session ID');
      return;
    }

    setState('connecting');
    setError(null);

    const wsUrl = `${getWsBase()}/ws/gemini-voice`;
    setDebugUrl(wsUrl);

    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;
    ws.binaryType = 'arraybuffer';

    // Handshake phase: auth → config, then switch to streaming mode
    let phase: 'connecting' | 'auth' | 'config' | 'ready' = 'connecting';
    const timeout = setTimeout(() => {
      if (phase !== 'ready') {
        setError(`Timeout in phase: ${phase}`);
        setState('error');
        ws.close();
      }
    }, 30000);

    ws.onopen = () => {
      phase = 'auth';
      const token = localStorage.getItem('done-token');
      ws.send(JSON.stringify({
        type: 'auth',
        token: token || '',
        session_id: sessionId,
      }));
    };

    ws.onmessage = async (event: MessageEvent) => {
      // During handshake, handle JSON responses
      if (phase === 'auth' || phase === 'config') {
        const text = typeof event.data === 'string'
          ? event.data
          : new TextDecoder().decode(event.data);

        let data: Record<string, unknown>;
        try {
          data = JSON.parse(text);
        } catch {
          setDebugUrl(`Parse error in ${phase}: ${text.slice(0, 100)}`);
          return;
        }

        if (data.type === 'error') {
          clearTimeout(timeout);
          setError(data.message as string || 'Server error');
          setState('error');
          ws.close();
          return;
        }

        if (phase === 'auth' && data.type === 'auth_success') {
          phase = 'config';
          ws.send(JSON.stringify({ type: 'config', mode: 'voice' }));
          return;
        }

        if (phase === 'config' && data.type === 'ready') {
          phase = 'ready';
          clearTimeout(timeout);
          setDebugUrl(`Connected: ${wsUrl}`);

          // --- Setup audio capture ---
          try {
            const audioCtx = new AudioContext({ sampleRate: 16000 });
            audioCtxRef.current = audioCtx;

            await audioCtx.audioWorklet.addModule('/audio-worklet-processor.js');

            const stream = await navigator.mediaDevices.getUserMedia({
              audio: {
                sampleRate: 16000,
                channelCount: 1,
                echoCancellation: true,
                noiseSuppression: true,
                autoGainControl: true,
              },
            });
            streamRef.current = stream;

            const source = audioCtx.createMediaStreamSource(stream);
            const worklet = new AudioWorkletNode(audioCtx, 'pcm-capture-processor');
            worklet.port.onmessage = (e: MessageEvent) => {
              if (ws.readyState === WebSocket.OPEN) {
                ws.send(e.data);
              }
            };
            source.connect(worklet);

            // --- Setup PCM player ---
            const player = new PCMPlayer(24000);
            player.init();
            playerRef.current = player;

            setState('listening');
          } catch (audioErr) {
            const msg = audioErr instanceof Error ? audioErr.message : 'Audio setup failed';
            setError(msg);
            setState('error');
            ws.close();
          }
          return;
        }

        // Unexpected message during handshake
        setDebugUrl(`Unexpected in ${phase}: ${JSON.stringify(data).slice(0, 100)}`);
        return;
      }

      // --- Streaming mode ---
      if (event.data instanceof ArrayBuffer) {
        playerRef.current?.play(event.data);
        setState('speaking');
        return;
      }

      if (typeof event.data === 'string') {
        try {
          const data = JSON.parse(event.data);
          handleJsonMessage(data);
        } catch {
          // Ignore
        }
      }
    };

    ws.onclose = () => {
      clearTimeout(timeout);
      disconnect();
    };

    ws.onerror = () => {
      clearTimeout(timeout);
      setError('WebSocket error');
      setState('error');
    };
  }, [sessionId, disconnect]);

  const handleJsonMessage = useCallback((data: Record<string, unknown>) => {
    switch (data.type) {
      case 'assistant_text':
        setLastText(data.text as string);
        onTextRef.current?.(data.text as string);
        break;

      case 'process_step':
        onProcessStepRef.current?.(data.step as string);
        break;

      case 'tool_start':
        setState('processing');
        onToolStartRef.current?.(data.tool as string);
        break;

      case 'tool_result':
        onToolResultRef.current?.(data.tool as string, data.success as boolean);
        break;

      case 'turn_complete':
        setState('listening');
        onTurnCompleteRef.current?.();
        break;

      case 'error':
        setError(data.message as string);
        break;

      case 'pong':
        break;
    }
  }, []);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      disconnect();
    };
  }, [disconnect]);

  return {
    state,
    error,
    lastText,
    debugUrl,
    connect,
    disconnect,
  };
}
