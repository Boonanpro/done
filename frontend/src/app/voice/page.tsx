'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { VoiceButton } from '@/components/voice/VoiceButton';
import { useSpeechRecognition } from '@/hooks/useSpeechRecognition';
import { useSpeechSynthesis } from '@/hooks/useSpeechSynthesis';
import { useVoiceWebSocket, VoiceSocketMessage } from '@/hooks/useVoiceWebSocket';

type VoiceMessage = {
  id: string;
  role: 'user' | 'dan' | 'system';
  text: string;
};

const SESSION_STORAGE_KEY = 'voice-session-id';
const TOKEN_STORAGE_KEY = 'done-token';

export default function VoicePage() {
  const [token, setToken] = useState<string | null>(null);
  const [storedSessionId, setStoredSessionId] = useState<string | null>(null);
  const [isReady, setIsReady] = useState(false);
  const [messages, setMessages] = useState<VoiceMessage[]>([]);
  const [progressSteps, setProgressSteps] = useState<string[]>([]);
  const [processing, setProcessing] = useState(false);
  const [uiError, setUiError] = useState<string | null>(null);

  const lastSentRef = useRef<string | null>(null);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    setToken(localStorage.getItem(TOKEN_STORAGE_KEY));
    setStoredSessionId(localStorage.getItem(SESSION_STORAGE_KEY));
    setIsReady(true);
  }, []);

  const {
    speak,
    cancel,
    isSpeaking,
    error: ttsError,
  } = useSpeechSynthesis();

  const handleSocketMessage = useCallback(
    (message: VoiceSocketMessage) => {
      if (!message || typeof message !== 'object') return;

      if ('type' in message) {
        switch (message.type) {
          case 'progress':
            setProgressSteps((prev) => [...prev.slice(-4), String(message.step)]);
            return;
          case 'assistant_message': {
            const text = String((message as { text?: unknown }).text ?? '');
            if (text.trim()) {
              setMessages((prev) => [
                ...prev,
                {
                  id: `${Date.now()}-dan`,
                  role: 'dan',
                  text,
                },
              ]);
              speak(text, { lang: 'ja-JP' });
            }
            return;
          }
          case 'processing':
            setProcessing(String((message as { status?: unknown }).status) === 'start');
            return;
          case 'notify': {
            const notifyMsg = String((message as { message?: unknown }).message ?? '');
            setMessages((prev) => [
              ...prev,
              {
                id: `${Date.now()}-notify`,
                role: 'system',
                text: notifyMsg,
              },
            ]);
            return;
          }
          case 'error':
            setUiError(String((message as { message?: unknown }).message ?? ''));
            return;
          default:
            return;
        }
      }
    },
    [speak]
  );

  const { status, sessionId, error: socketError, sendText } = useVoiceWebSocket({
    token,
    sessionId: storedSessionId,
    autoConnect: isReady,
    onMessage: handleSocketMessage,
  });

  useEffect(() => {
    if (!sessionId || typeof window === 'undefined') return;
    localStorage.setItem(SESSION_STORAGE_KEY, sessionId);
  }, [sessionId]);

  const {
    isSupported: isSpeechSupported,
    isListening,
    transcript,
    interimTranscript,
    finalTranscript,
    error: speechError,
    start,
    stop,
    reset,
  } = useSpeechRecognition({
    lang: 'ja-JP',
    interimResults: true,
    continuous: false,
  });

  useEffect(() => {
    const cleaned = finalTranscript.trim();
    if (!cleaned) return;
    if (lastSentRef.current === cleaned) return;
    if (status !== 'connected') return;

    lastSentRef.current = cleaned;
    sendText(cleaned);
    setProgressSteps([]);
    setMessages((prev) => [
      ...prev,
      { id: `${Date.now()}-user`, role: 'user', text: cleaned },
    ]);
  }, [finalTranscript, sendText, status]);

  const statusLabel = useMemo(() => {
    if (!isSpeechSupported) return '音声入力は未対応です';
    if (socketError) return 'サーバーに接続できません';
    if (processing) return 'ダンが考え中...';
    if (isListening) return '聴き取り中';
    if (status === 'connected') return '待機中';
    if (status === 'connecting') return '接続中...';
    return '未接続';
  }, [isSpeechSupported, socketError, processing, isListening, status]);

  const handleStart = useCallback(() => {
    lastSentRef.current = null;
    reset();
    start();
  }, [reset, start]);

  const currentTranscript = interimTranscript || transcript || 'ここに認識結果が表示されます。';

  return (
    <div className="min-h-screen bg-[radial-gradient(circle_at_top,_rgba(255,255,255,0.08),_transparent_55%)] text-foreground">
      <div className="mx-auto flex min-h-screen w-full max-w-4xl flex-col items-center justify-center px-6 py-12">
        <div className="w-full rounded-3xl border border-white/10 bg-white/5 p-8 backdrop-blur">
          <header className="mb-8 flex flex-col items-center gap-2 text-center">
            <p className="text-xs uppercase tracking-[0.3em] text-white/60">Dan Voice Companion</p>
            <h1 className="text-3xl font-semibold text-white">声でダンとつながる</h1>
            <p className="text-sm text-white/60">
              マイクを押して話しかけると、ダンが返答を読み上げます。
            </p>
          </header>

          <div className="flex flex-col items-center gap-6">
            <div className="flex flex-col items-center gap-3">
              <VoiceButton
                isListening={isListening}
                isSupported={isSpeechSupported}
                onStart={handleStart}
                onStop={stop}
                disabled={status !== 'connected'}
              />
              <div className="flex items-center gap-2 text-xs text-white/60">
                <span className="h-2 w-2 rounded-full bg-white/60" />
                {statusLabel}
              </div>
            </div>

            <div className="grid w-full gap-4 md:grid-cols-2">
              <section className="rounded-2xl border border-white/10 bg-black/30 p-4">
                <p className="text-xs uppercase tracking-[0.2em] text-white/50">Transcript</p>
                <p className="mt-3 text-base text-white/90">
                  {currentTranscript}
                </p>
                {interimTranscript && (
                  <p className="mt-2 text-sm text-white/50">…{interimTranscript}</p>
                )}
                {speechError && (
                  <p className="mt-2 text-xs text-red-300">音声エラー: {speechError}</p>
                )}
              </section>

              <section className="rounded-2xl border border-white/10 bg-black/30 p-4">
                <div className="flex items-center justify-between">
                  <p className="text-xs uppercase tracking-[0.2em] text-white/50">Dan Reply</p>
                  <button
                    type="button"
                    onClick={cancel}
                    className="text-xs text-white/50 hover:text-white"
                  >
                    読み上げ停止
                  </button>
                </div>
                <div className="mt-3 space-y-3 text-sm text-white/90">
                  {messages.length === 0 && (
                    <p className="text-white/50">まだ会話がありません。</p>
                  )}
                  {messages.slice(-4).map((message) => (
                    <div key={message.id} className="flex flex-col gap-1">
                      <span className="text-xs text-white/40">
                        {message.role === 'user' ? 'あなた' : message.role === 'dan' ? 'ダン' : '通知'}
                      </span>
                      <span>{message.text}</span>
                    </div>
                  ))}
                </div>
                {(uiError || socketError || ttsError) && (
                  <p className="mt-3 text-xs text-red-300">
                    {uiError || socketError || ttsError}
                  </p>
                )}
                {isSpeaking && (
                  <p className="mt-3 text-xs text-white/40">読み上げ中...</p>
                )}
              </section>
            </div>

            <section className="w-full rounded-2xl border border-white/10 bg-black/20 p-4">
              <p className="text-xs uppercase tracking-[0.2em] text-white/50">Process</p>
              <div className="mt-3 flex flex-wrap gap-2">
                {progressSteps.length === 0 ? (
                  <span className="text-xs text-white/40">進捗はここに表示されます。</span>
                ) : (
                  progressSteps.map((step, index) => (
                    <span
                      key={`${step}-${index}`}
                      className="rounded-full border border-white/10 px-3 py-1 text-xs text-white/70"
                    >
                      {step}
                    </span>
                  ))
                )}
              </div>
            </section>
          </div>
        </div>
      </div>
    </div>
  );
}
