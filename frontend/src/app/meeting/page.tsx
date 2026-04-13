'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { useMeeting } from '@/hooks/useMeeting';
import { useAuthStore } from '@/stores/auth-store';
import { SlideRenderer } from '@/components/meeting/SlideRenderer';
import { TranscriptPanel } from '@/components/meeting/TranscriptPanel';
import { ControlBar } from '@/components/meeting/ControlBar';
import { Presentation, ArrowLeft } from 'lucide-react';

export default function MeetingPage() {
  const router = useRouter();
  const isAuthenticated = useAuthStore(s => s.isAuthenticated);
  const isLoading = useAuthStore(s => s.isLoading);

  const [topic, setTopic] = useState('');
  const [content, setContent] = useState('');
  const [ready, setReady] = useState(false);  // true after mount + sessionStorage read
  const startedRef = useRef(false);

  // Read sessionStorage after mount (avoids hydration mismatch)
  useEffect(() => {
    setTopic(sessionStorage.getItem('meeting-topic') || '');
    setContent(sessionStorage.getItem('meeting-content') || '');
    setReady(true);
  }, []);

  // Auth guard
  useEffect(() => {
    if (!isLoading && !isAuthenticated && !localStorage.getItem('done-token')) {
      router.push('/login');
    }
  }, [isLoading, isAuthenticated, router]);

  const meeting = useMeeting({
    onError: useCallback((msg: string) => {
      console.error('Meeting error:', msg);
    }, []),
  });

  // Connect + start once ready and content is available
  useEffect(() => {
    if (!ready || !content || startedRef.current) return;
    if (meeting.phase === 'idle') {
      meeting.connect();
    }
  }, [ready, content, meeting]);

  // When connected (phase=preparing), send the start command
  useEffect(() => {
    if (meeting.phase === 'preparing' && content && !startedRef.current) {
      startedRef.current = true;
      meeting.start(topic || '提案MTG', content);
    }
  }, [meeting, meeting.phase, content, topic]);

  const handleEnd = useCallback(() => {
    meeting.control('end');
    setTimeout(() => router.push('/chat'), 2000);
  }, [meeting, router]);

  const handleBack = useCallback(() => {
    meeting.disconnect();
    router.push('/chat');
  }, [meeting, router]);

  // Show nothing until client-side hydration is done
  if (!ready) {
    return (
      <div className="fixed inset-0 bg-gray-900 flex items-center justify-center">
        <div className="w-10 h-10 border-4 border-blue-500 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div className="fixed inset-0 bg-gray-900 flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-700 bg-gray-800/80 backdrop-blur">
        <div className="flex items-center gap-3">
          <button
            onClick={handleBack}
            className="p-1.5 text-gray-400 hover:text-white rounded-lg hover:bg-gray-700 transition-colors"
          >
            <ArrowLeft size={18} />
          </button>
          <Presentation size={18} className="text-blue-400" />
          <h1 className="text-white font-semibold text-sm">{topic || '提案MTG'}</h1>
        </div>

        <div className="flex items-center gap-2">
          <span className={`text-xs px-2 py-1 rounded-full ${
            meeting.phase === 'presenting'
              ? 'bg-green-500/20 text-green-400'
              : meeting.phase === 'qa'
              ? 'bg-blue-500/20 text-blue-400'
              : meeting.phase === 'preparing'
              ? 'bg-yellow-500/20 text-yellow-400'
              : meeting.phase === 'ended'
              ? 'bg-gray-500/20 text-gray-400'
              : 'bg-gray-500/20 text-gray-500'
          }`}>
            {meeting.phase === 'presenting' && 'プレゼン中'}
            {meeting.phase === 'qa' && 'Q&A'}
            {meeting.phase === 'preparing' && '準備中'}
            {meeting.phase === 'paused' && '一時停止'}
            {meeting.phase === 'ended' && '終了'}
            {meeting.phase === 'connecting' && '接続中'}
            {meeting.phase === 'idle' && '待機中'}
          </span>

          {meeting.state.totalSlides > 0 && (
            <span className="text-xs text-gray-500 font-mono">
              {meeting.state.currentSlide + 1}/{meeting.state.totalSlides}
            </span>
          )}
        </div>
      </div>

      {/* Main content */}
      <div className="flex-1 flex overflow-hidden">
        <div className="flex-1 flex flex-col p-4">
          <SlideRenderer
            slide={meeting.currentSlide}
            preparing={meeting.phase === 'preparing' || meeting.phase === 'connecting' || meeting.phase === 'idle'}
            onPrev={() => meeting.control('prev')}
            onNext={() => meeting.control('next')}
          />
        </div>

        <div className="w-80 border-l border-gray-700 bg-gray-800/50 flex flex-col">
          <TranscriptPanel
            entries={meeting.transcript}
            summary={meeting.summary}
          />
        </div>
      </div>

      {/* Control bar */}
      <ControlBar
        phase={meeting.phase}
        isSpeaking={meeting.isSpeaking}
        onSendMessage={meeting.sendMessage}
        onControl={meeting.control}
        onEnd={handleEnd}
      />

      {/* No content - manual input fallback */}
      {ready && !content && meeting.phase !== 'ended' && (
        <div className="absolute inset-0 flex items-center justify-center bg-black/60 z-10">
          <StartMeetingPrompt
            onStart={(t, c) => {
              setTopic(t);
              setContent(c);
            }}
          />
        </div>
      )}

      {/* Error overlay */}
      {meeting.error && (
        <div className="absolute bottom-20 left-1/2 -translate-x-1/2 bg-red-600/90 text-white px-4 py-2 rounded-lg text-sm z-20">
          {meeting.error}
        </div>
      )}
    </div>
  );
}

function StartMeetingPrompt({ onStart }: { onStart: (topic: string, content: string) => void }) {
  const [topic, setTopic] = useState('');
  const [content, setContent] = useState('');

  return (
    <div className="bg-gray-800 rounded-xl p-6 max-w-lg w-full mx-4 shadow-2xl">
      <h2 className="text-lg font-semibold text-white mb-4">MTGを開始</h2>
      <div className="space-y-4">
        <div>
          <label className="text-sm text-gray-400 mb-1 block">トピック</label>
          <input
            type="text"
            value={topic}
            onChange={e => setTopic(e.target.value)}
            placeholder="例: 新サービスの企画"
            className="w-full bg-gray-700 text-white rounded-lg px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
        <div>
          <label className="text-sm text-gray-400 mb-1 block">提案内容</label>
          <textarea
            value={content}
            onChange={e => setContent(e.target.value)}
            placeholder="プレゼンしたい内容を貼り付けてください..."
            rows={8}
            className="w-full bg-gray-700 text-white rounded-lg px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-blue-500 resize-none"
          />
        </div>
        <button
          onClick={() => onStart(topic || '提案', content)}
          disabled={!content.trim()}
          className="w-full py-2.5 bg-blue-600 hover:bg-blue-500 disabled:bg-gray-600 text-white rounded-lg font-medium text-sm transition-colors"
        >
          MTG開始
        </button>
      </div>
    </div>
  );
}
