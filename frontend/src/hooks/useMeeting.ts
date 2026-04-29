'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

// --- Types ---

export type MeetingPhase =
  | 'idle'
  | 'connecting'
  | 'preparing'
  | 'presenting'
  | 'paused'
  | 'qa'
  | 'researching'
  | 'ended';

export interface SlideContent {
  index: number;
  total: number;
  title: string;
  bullets: string[];
  note: string;
  highlight?: string;
}

export interface TranscriptEntry {
  speaker: 'dan' | 'user';
  text: string;
  timestamp: number;
}

export interface MeetingState {
  phase: MeetingPhase;
  currentSlide: number;
  totalSlides: number;
  topic: string;
}

interface UseMeetingOptions {
  onSlide?: (slide: SlideContent, narration: string) => void;
  onTranscript?: (entry: TranscriptEntry) => void;
  onSummary?: (text: string) => void;
  onError?: (message: string) => void;
}

interface UseMeetingResult {
  state: MeetingState;
  phase: MeetingPhase;
  currentSlide: SlideContent | null;
  transcript: TranscriptEntry[];
  summary: string | null;
  error: string | null;
  isSpeaking: boolean;
  connect: () => void;
  disconnect: () => void;
  start: (topic: string, proposalContent: string) => void;
  sendMessage: (text: string) => void;
  control: (action: 'pause' | 'resume' | 'next' | 'prev' | 'end') => void;
}

function getWsBase(): string {
  if (process.env.NEXT_PUBLIC_WS_URL) {
    return process.env.NEXT_PUBLIC_WS_URL;
  }
  // Connect directly to backend to avoid Next.js dev server WebSocket issues
  return 'ws://127.0.0.1:8000';
}

export function useMeeting(options: UseMeetingOptions = {}): UseMeetingResult {
  const [state, setState] = useState<MeetingState>({
    phase: 'idle',
    currentSlide: 0,
    totalSlides: 0,
    topic: '',
  });
  const [currentSlide, setCurrentSlide] = useState<SlideContent | null>(null);
  const [transcript, setTranscript] = useState<TranscriptEntry[]>([]);
  const [summary, setSummary] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isSpeaking, setIsSpeaking] = useState(false);

  const wsRef = useRef<WebSocket | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const audioQueueRef = useRef<ArrayBuffer[]>([]);
  const isPlayingRef = useRef(false);

  // Stable callback refs
  const optionsRef = useRef(options);
  useEffect(() => { optionsRef.current = options; }, [options]);

  // --- Audio playback (MP3 chunks) ---
  // Collects all chunks until audio_end, then plays as one piece.
  // When playback finishes, sends "audio_played" to server so it can advance.

  const playCollectedAudio = useCallback(async () => {
    const chunks = audioQueueRef.current.splice(0);
    if (chunks.length === 0) {
      // No audio data (TTS not configured) - still notify server
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({ type: 'audio_played' }));
      }
      setIsSpeaking(false);
      return;
    }

    isPlayingRef.current = true;
    setIsSpeaking(true);

    // Merge all chunks into one buffer
    const totalLength = chunks.reduce((sum, c) => sum + c.byteLength, 0);
    const merged = new Uint8Array(totalLength);
    let offset = 0;
    for (const chunk of chunks) {
      merged.set(new Uint8Array(chunk), offset);
      offset += chunk.byteLength;
    }

    try {
      if (!audioCtxRef.current) {
        audioCtxRef.current = new AudioContext();
      }
      const ctx = audioCtxRef.current;
      if (ctx.state === 'suspended') await ctx.resume();

      const audioBuffer = await ctx.decodeAudioData(merged.buffer.slice(0));
      const source = ctx.createBufferSource();
      source.buffer = audioBuffer;
      source.connect(ctx.destination);
      source.onended = () => {
        isPlayingRef.current = false;
        setIsSpeaking(false);
        // Tell server we finished playing - it can advance to next slide
        if (wsRef.current?.readyState === WebSocket.OPEN) {
          wsRef.current.send(JSON.stringify({ type: 'audio_played' }));
        }
      };
      source.start();
    } catch (e) {
      console.warn('Audio decode/play error:', e);
      isPlayingRef.current = false;
      setIsSpeaking(false);
      // Still notify server even on error
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({ type: 'audio_played' }));
      }
    }
  }, []);

  // --- WebSocket ---

  const disconnect = useCallback(() => {
    if (wsRef.current) {
      try { wsRef.current.close(); } catch {}
      wsRef.current = null;
    }
    if (audioCtxRef.current) {
      audioCtxRef.current.close().catch(() => {});
      audioCtxRef.current = null;
    }
    audioQueueRef.current = [];
    isPlayingRef.current = false;
    setState(s => ({ ...s, phase: 'idle' }));
    setIsSpeaking(false);
  }, []);

  const connect = useCallback(() => {
    if (wsRef.current) return;

    setState(s => ({ ...s, phase: 'connecting' }));
    setError(null);
    setTranscript([]);
    setSummary(null);
    setCurrentSlide(null);

    const wsUrl = `${getWsBase()}/ws/meeting`;
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;
    ws.binaryType = 'arraybuffer';

    let phase: 'auth' | 'ready' | 'active' = 'auth';

    ws.onopen = () => {
      const token = localStorage.getItem('done-token');
      ws.send(JSON.stringify({
        type: 'auth',
        token: token || '',
        session_id: crypto.randomUUID(),
      }));
    };

    ws.onmessage = (event: MessageEvent) => {
      // Binary = audio chunk
      if (event.data instanceof ArrayBuffer) {
        audioQueueRef.current.push(event.data);
        // Don't play immediately - wait for audio_end signal for smoother playback
        return;
      }

      if (typeof event.data !== 'string') return;

      let data: Record<string, unknown>;
      try {
        data = JSON.parse(event.data);
      } catch {
        return;
      }

      const type = data.type as string;

      // Handshake
      if (phase === 'auth' && type === 'auth_success') {
        phase = 'ready';
        return;
      }
      if (phase === 'ready' && type === 'ready') {
        phase = 'active';
        setState(s => ({ ...s, phase: 'preparing' }));
        return;
      }

      // Error
      if (type === 'error') {
        setError(data.message as string);
        optionsRef.current.onError?.(data.message as string);
        return;
      }

      // State update
      if (type === 'state') {
        const serverState = data.state as Record<string, unknown>;
        setState({
          phase: serverState.phase as MeetingPhase,
          currentSlide: serverState.current_slide as number,
          totalSlides: serverState.total_slides as number,
          topic: serverState.topic as string,
        });
        return;
      }

      // Slide
      if (type === 'slide') {
        const slideData = data.slide as Record<string, unknown>;
        const slide: SlideContent = {
          index: slideData.index as number,
          total: slideData.total as number,
          title: slideData.title as string,
          bullets: slideData.bullets as string[],
          note: slideData.note as string,
          highlight: slideData.highlight as string | undefined,
        };
        setCurrentSlide(slide);
        optionsRef.current.onSlide?.(slide, data.narration as string);
        return;
      }

      // Transcript
      if (type === 'transcript') {
        const entry: TranscriptEntry = {
          speaker: data.speaker as 'dan' | 'user',
          text: data.text as string,
          timestamp: Date.now(),
        };
        setTranscript(prev => [...prev, entry]);
        optionsRef.current.onTranscript?.(entry);
        return;
      }

      // Audio end - now play the buffered audio for this slide
      if (type === 'audio_end') {
        playCollectedAudio();
        return;
      }

      // Summary
      if (type === 'summary') {
        setSummary(data.text as string);
        optionsRef.current.onSummary?.(data.text as string);
        return;
      }

      // Pong
      if (type === 'pong') return;
    };

    ws.onclose = () => {
      disconnect();
    };

    ws.onerror = () => {
      setError('WebSocket接続エラー');
      disconnect();
    };
  }, [disconnect, playCollectedAudio]);

  const sendWs = useCallback((data: Record<string, unknown>) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(data));
    }
  }, []);

  const start = useCallback((topic: string, proposalContent: string) => {
    sendWs({ type: 'start', topic, proposal_content: proposalContent });
  }, [sendWs]);

  const sendMessage = useCallback((text: string) => {
    sendWs({ type: 'user_message', text });
  }, [sendWs]);

  const control = useCallback((action: 'pause' | 'resume' | 'next' | 'prev' | 'end') => {
    sendWs({ type: 'control', action });
  }, [sendWs]);

  // Cleanup on unmount
  useEffect(() => () => disconnect(), [disconnect]);

  // Ping keepalive
  useEffect(() => {
    const interval = setInterval(() => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({ type: 'ping' }));
      }
    }, 30000);
    return () => clearInterval(interval);
  }, []);

  return {
    state,
    phase: state.phase,
    currentSlide,
    transcript,
    summary,
    error,
    isSpeaking,
    connect,
    disconnect,
    start,
    sendMessage,
    control,
  };
}
