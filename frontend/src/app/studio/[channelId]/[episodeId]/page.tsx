'use client';

import { useEffect, useRef, useState, useCallback } from 'react';
import { useRouter, useParams } from 'next/navigation';
import { api, ApiError, StudioEpisode, StudioVoiceTrack, StudioVideoClip } from '@/lib/api-client';
import {
  ChevronLeft, Send, Play, Pause, SkipBack, SkipForward,
  Film, Mic, Video, RefreshCw, Volume2, X, AlertCircle, CheckCircle,
} from 'lucide-react';

// ─── Toast System ───
type Toast = { id: number; message: string; type: 'error' | 'success' | 'info' };
let toastId = 0;

function useToast() {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const add = useCallback((message: string, type: Toast['type'] = 'error') => {
    const id = ++toastId;
    setToasts(t => [...t, { id, message, type }]);
    setTimeout(() => setToasts(t => t.filter(x => x.id !== id)), type === 'error' ? 8000 : 4000);
  }, []);
  const remove = useCallback((id: number) => setToasts(t => t.filter(x => x.id !== id)), []);
  return { toasts, add, remove };
}

function extractErrorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    const d = err.data as Record<string, unknown> | undefined;
    if (d?.detail && typeof d.detail === 'string') return d.detail;
    if (d?.detail && typeof d.detail === 'object') return JSON.stringify(d.detail);
    return `API Error ${err.status}: ${err.statusText}`;
  }
  if (err instanceof Error) return err.message;
  return String(err);
}

// ─── Timeline Clip Type ───
type TimelineClip = {
  id: string;
  track: 'v1' | 'v2' | 'audio' | 'bgm' | 'text';
  label: string;
  startPct: number;
  widthPct: number;
  color: string;
  sourceId?: string;
  type: 'video' | 'voice' | 'text';
};

// ─── Main Component ───
export default function EpisodeEditorPage() {
  const router = useRouter();
  const { channelId, episodeId } = useParams<{ channelId: string; episodeId: string }>();
  const { toasts, add: toast, remove: removeToast } = useToast();

  // Data
  const [episode, setEpisode] = useState<StudioEpisode | null>(null);
  const [voiceTracks, setVoiceTracks] = useState<StudioVoiceTrack[]>([]);
  const [videoClips, setVideoClips] = useState<StudioVideoClip[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  // UI State
  const [selectedClipId, setSelectedClipId] = useState<string | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [previewType, setPreviewType] = useState<'video' | 'audio' | null>(null);
  const [isPlaying, setIsPlaying] = useState(false);

  // Chat
  const [messages, setMessages] = useState<Array<{ role: string; content: string }>>([]);
  const [chatInput, setChatInput] = useState('');
  const [chatSending, setChatSending] = useState(false);
  const [chatError, setChatError] = useState<string | null>(null);
  const chatEndRef = useRef<HTMLDivElement>(null);

  // Generate forms
  const [activePanel, setActivePanel] = useState<'none' | 'video' | 'voice'>('none');
  const [videoPrompt, setVideoPrompt] = useState('');
  const [videoLabel, setVideoLabel] = useState('');
  const [videoDuration, setVideoDuration] = useState(5);
  const [generatingVideo, setGeneratingVideo] = useState(false);
  const [voiceText, setVoiceText] = useState('');
  const [voiceLabel, setVoiceLabel] = useState('');
  const [generatingVoice, setGeneratingVoice] = useState(false);

  // Refs
  const previewRef = useRef<HTMLVideoElement>(null);
  const audioRef = useRef<HTMLAudioElement>(null);

  // ─── Load Data ───
  useEffect(() => {
    Promise.all([
      api.studio.getEpisode(episodeId),
      api.studio.listVoiceTracks(episodeId),
      api.studio.listVideoClips(episodeId),
    ]).then(([ep, vt, vc]) => {
      setEpisode(ep);
      setMessages(ep.script_messages || []);
      setVoiceTracks(vt);
      setVideoClips(vc);
      if (vc.length > 0 && vc[0].file_url) {
        setPreviewUrl(vc[0].file_url);
        setPreviewType('video');
        setSelectedClipId(vc[0].id);
      }
    }).catch(err => {
      setLoadError(extractErrorMessage(err));
    }).finally(() => setLoading(false));
  }, [episodeId]);

  // ─── Auto-scroll chat ───
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // ─── Auto-poll video status ───
  useEffect(() => {
    const processing = videoClips.filter(c => c.kling_status === 'processing');
    if (processing.length === 0) return;
    const timer = setInterval(async () => {
      for (const clip of processing) {
        try {
          const updated = await api.studio.checkVideoStatus(clip.id);
          setVideoClips(clips => clips.map(c => c.id === clip.id ? updated : c));
          if (updated.kling_status === 'done') {
            toast(`映像「${updated.label || 'clip'}」の生成が完了しました`, 'success');
          } else if (updated.kling_status === 'error') {
            toast(`映像「${updated.label || 'clip'}」の生成に失敗しました`, 'error');
          }
        } catch {
          // polling error is non-critical, skip
        }
      }
    }, 10000);
    return () => clearInterval(timer);
  }, [videoClips, toast]);

  // ─── Chat ───
  const sendMessage = useCallback(async (e: React.FormEvent) => {
    e.preventDefault();
    const msg = chatInput.trim();
    if (!msg || chatSending) return;
    setChatInput('');
    setChatSending(true);
    setChatError(null);
    const updated = [...messages, { role: 'user', content: msg }];
    setMessages(updated);
    try {
      const res = await api.studio.chatScript(episodeId, msg);
      setMessages([...updated, { role: 'assistant', content: res.response }]);
    } catch (err) {
      const errMsg = extractErrorMessage(err);
      setChatError(errMsg);
      // Keep the user message but show error instead of fake assistant message
      setMessages([...updated, { role: 'assistant', content: `⚠ エラー: ${errMsg}` }]);
    } finally {
      setChatSending(false);
    }
  }, [chatInput, chatSending, messages, episodeId]);

  // ─── Video Generation ───
  const handleGenerateVideo = useCallback(async (e: React.FormEvent) => {
    e.preventDefault();
    if (!videoPrompt.trim() || generatingVideo) return;
    setGeneratingVideo(true);
    try {
      const clip = await api.studio.generateVideo(episodeId, videoPrompt, videoDuration, 'std', videoLabel);
      setVideoClips(c => [clip, ...c]);
      setVideoPrompt('');
      setVideoLabel('');
      setActivePanel('none');
      toast('映像生成リクエストを送信しました。完了まで数分かかります。', 'info');
    } catch (err) {
      toast(extractErrorMessage(err));
    } finally {
      setGeneratingVideo(false);
    }
  }, [episodeId, videoPrompt, videoDuration, videoLabel, generatingVideo, toast]);

  // ─── Voice Generation ───
  const handleGenerateVoice = useCallback(async (e: React.FormEvent) => {
    e.preventDefault();
    if (!voiceText.trim() || generatingVoice) return;
    setGeneratingVoice(true);
    try {
      const track = await api.studio.generateVoice(episodeId, voiceText, voiceLabel);
      setVoiceTracks(t => [...t, track]);
      setVoiceText('');
      setVoiceLabel('');
      setActivePanel('none');
      toast('音声を生成しました', 'success');
    } catch (err) {
      toast(extractErrorMessage(err));
    } finally {
      setGeneratingVoice(false);
    }
  }, [episodeId, voiceText, voiceLabel, generatingVoice, toast]);

  // ─── Preview Controls ───
  const selectMedia = useCallback((url: string, type: 'video' | 'audio', id: string) => {
    setPreviewUrl(url);
    setPreviewType(type);
    setSelectedClipId(id);
    setIsPlaying(false);
  }, []);

  const togglePlay = useCallback(() => {
    const el = previewType === 'video' ? previewRef.current : audioRef.current;
    if (!el) return;
    if (isPlaying) { el.pause(); } else { el.play(); }
    setIsPlaying(!isPlaying);
  }, [isPlaying, previewType]);

  // ─── Build Timeline Data ───
  const timelineClips: TimelineClip[] = [];
  let vOffset = 0;
  videoClips.filter(c => c.file_url).forEach((c) => {
    const w = 20;
    timelineClips.push({
      id: c.id, track: 'v1', label: c.label || c.prompt.slice(0, 20),
      startPct: vOffset, widthPct: w, color: 'bg-blue-600', sourceId: c.id, type: 'video',
    });
    vOffset += w + 2;
  });
  let aOffset = 0;
  voiceTracks.filter(t => t.file_url).forEach((t) => {
    const w = 18;
    timelineClips.push({
      id: t.id, track: 'audio', label: t.label || t.text_content.slice(0, 20),
      startPct: aOffset, widthPct: w, color: 'bg-green-600', sourceId: t.id, type: 'voice',
    });
    aOffset += w + 2;
  });

  // ─── Loading / Error States ───
  if (loading) {
    return (
      <div className="h-screen bg-[#06060a] text-zinc-500 flex items-center justify-center text-sm">
        読み込み中...
      </div>
    );
  }

  if (loadError) {
    return (
      <div className="h-screen bg-[#06060a] text-zinc-300 flex flex-col items-center justify-center gap-4">
        <AlertCircle size={32} className="text-red-500" />
        <p className="text-sm">データの読み込みに失敗しました</p>
        <p className="text-xs text-zinc-500 max-w-md text-center">{loadError}</p>
        <button
          onClick={() => window.location.reload()}
          className="text-xs text-indigo-400 hover:text-indigo-300 underline mt-2"
        >
          再読み込み
        </button>
      </div>
    );
  }

  return (
    <div className="h-screen bg-[#06060a] text-zinc-200 flex flex-col overflow-hidden select-none">
      {/* ═══ Toast Notifications ═══ */}
      <div className="fixed top-3 right-3 z-[100] flex flex-col gap-2 max-w-sm">
        {toasts.map(t => (
          <div
            key={t.id}
            className={`flex items-start gap-2 px-3 py-2.5 rounded-lg text-xs shadow-lg border animate-in slide-in-from-right ${
              t.type === 'error' ? 'bg-red-950/90 border-red-800/60 text-red-200' :
              t.type === 'success' ? 'bg-green-950/90 border-green-800/60 text-green-200' :
              'bg-zinc-900/90 border-zinc-700/60 text-zinc-200'
            }`}
          >
            {t.type === 'error' ? <AlertCircle size={14} className="shrink-0 mt-0.5 text-red-400" /> :
             t.type === 'success' ? <CheckCircle size={14} className="shrink-0 mt-0.5 text-green-400" /> :
             <RefreshCw size={14} className="shrink-0 mt-0.5 text-zinc-400" />}
            <span className="flex-1 leading-relaxed">{t.message}</span>
            <button onClick={() => removeToast(t.id)} className="shrink-0 text-zinc-500 hover:text-zinc-300">
              <X size={12} />
            </button>
          </div>
        ))}
      </div>

      {/* ═══ Title Bar ═══ */}
      <div className="h-9 bg-[#08080e] border-b border-zinc-800/60 flex items-center px-3 gap-2 shrink-0">
        <button onClick={() => router.push(`/studio/${channelId}`)} className="text-zinc-500 hover:text-white">
          <ChevronLeft size={16} />
        </button>
        <div className="flex gap-1.5 mr-2">
          <div className="w-3 h-3 rounded-full bg-red-500" />
          <div className="w-3 h-3 rounded-full bg-yellow-500" />
          <div className="w-3 h-3 rounded-full bg-green-500" />
        </div>
        <span className="text-xs text-zinc-500 font-medium truncate">
          Dan Studio — {episode?.title || 'Untitled'}
        </span>
        <div className="ml-auto flex items-center gap-1.5 text-xs text-zinc-600">
          <div className="w-1.5 h-1.5 rounded-full bg-green-500" />
          AI Connected
        </div>
      </div>

      {/* ═══ Main Body ═══ */}
      <div className="flex-1 flex min-h-0">

        {/* ─── Center: Preview + Media + Timeline ─── */}
        <div className="flex-1 flex flex-col min-w-0">
          {/* Preview */}
          <div className="flex-1 bg-black flex items-center justify-center relative min-h-0">
            <div className="w-[96%] h-[92%] bg-[#0a0a12] rounded relative overflow-hidden flex items-center justify-center">
              {previewUrl && previewType === 'video' ? (
                <video
                  ref={previewRef}
                  src={previewUrl}
                  className="max-w-full max-h-full object-contain"
                  onEnded={() => setIsPlaying(false)}
                />
              ) : previewUrl && previewType === 'audio' ? (
                <div className="flex flex-col items-center gap-3">
                  <Volume2 size={48} className="text-zinc-600" />
                  <p className="text-xs text-zinc-500">音声プレビュー</p>
                  <audio ref={audioRef} src={previewUrl} onEnded={() => setIsPlaying(false)} />
                </div>
              ) : (
                <div className="text-zinc-700 text-sm flex flex-col items-center gap-2">
                  <Film size={32} className="opacity-30" />
                  <span>メディアを選択してプレビュー</span>
                </div>
              )}

              {/* Controls overlay */}
              {previewUrl && (
                <div className="absolute bottom-3 left-1/2 -translate-x-1/2 flex items-center gap-4 bg-black/60 rounded-full px-4 py-1.5">
                  <button className="text-zinc-400 hover:text-white"><SkipBack size={14} /></button>
                  <button onClick={togglePlay} className="text-white hover:text-zinc-300">
                    {isPlaying ? <Pause size={18} /> : <Play size={18} />}
                  </button>
                  <button className="text-zinc-400 hover:text-white"><SkipForward size={14} /></button>
                </div>
              )}
            </div>
          </div>

          {/* Media Browser */}
          <div className="h-24 bg-[#0e0e18] border-t border-zinc-800/60 flex items-center px-3 gap-2 overflow-x-auto shrink-0">
            {videoClips.length === 0 && voiceTracks.length === 0 && (
              <span className="text-xs text-zinc-700 mr-2">メディアがありません</span>
            )}

            {/* Video Clips */}
            {videoClips.map(clip => (
              <button
                key={clip.id}
                onClick={() => clip.file_url && selectMedia(clip.file_url, 'video', clip.id)}
                className={`w-28 h-16 rounded shrink-0 border-2 transition-all relative overflow-hidden ${
                  selectedClipId === clip.id ? 'border-indigo-500 shadow-lg shadow-indigo-500/20' : 'border-transparent hover:border-zinc-600'
                }`}
              >
                {clip.thumbnail_url ? (
                  <img src={clip.thumbnail_url} className="w-full h-full object-cover" alt="" />
                ) : (
                  <div className="w-full h-full bg-zinc-800 flex flex-col items-center justify-center gap-1">
                    {clip.kling_status === 'processing' ? (
                      <>
                        <RefreshCw size={14} className="text-yellow-500 animate-spin" />
                        <span className="text-[8px] text-yellow-500">生成中...</span>
                      </>
                    ) : clip.kling_status === 'error' ? (
                      <>
                        <AlertCircle size={14} className="text-red-400" />
                        <span className="text-[8px] text-red-400">失敗</span>
                      </>
                    ) : clip.file_url ? (
                      <Video size={14} className="text-blue-400" />
                    ) : (
                      <Video size={14} className="text-zinc-600" />
                    )}
                  </div>
                )}
                <span className="absolute bottom-0.5 left-1 text-[8px] text-white/80 bg-black/70 px-1 rounded truncate max-w-[90%]">
                  {clip.label || clip.prompt.slice(0, 10)}
                </span>
              </button>
            ))}

            {/* Voice Tracks */}
            {voiceTracks.map(track => (
              <button
                key={track.id}
                onClick={() => track.file_url && selectMedia(track.file_url, 'audio', track.id)}
                className={`w-28 h-16 rounded shrink-0 border-2 transition-all bg-zinc-800 flex flex-col items-center justify-center gap-1 ${
                  selectedClipId === track.id ? 'border-green-500' : 'border-transparent hover:border-zinc-600'
                }`}
              >
                <Mic size={12} className="text-green-500/70" />
                <span className="text-[9px] text-zinc-400 truncate max-w-[90%]">
                  {track.label || track.text_content.slice(0, 12)}
                </span>
                {track.status === 'done' && <span className="text-[7px] text-green-500">完了</span>}
                {track.status === 'error' && <span className="text-[7px] text-red-400">失敗</span>}
              </button>
            ))}

            {/* Add buttons */}
            <button
              onClick={() => setActivePanel(activePanel === 'video' ? 'none' : 'video')}
              className={`w-16 h-16 rounded border-2 border-dashed shrink-0 flex flex-col items-center justify-center gap-1 transition-colors ${
                activePanel === 'video' ? 'border-indigo-500 text-indigo-400' : 'border-zinc-700 text-zinc-600 hover:text-zinc-400 hover:border-zinc-500'
              }`}
            >
              <Video size={14} />
              <span className="text-[8px]">映像</span>
            </button>
            <button
              onClick={() => setActivePanel(activePanel === 'voice' ? 'none' : 'voice')}
              className={`w-16 h-16 rounded border-2 border-dashed shrink-0 flex flex-col items-center justify-center gap-1 transition-colors ${
                activePanel === 'voice' ? 'border-green-500 text-green-400' : 'border-zinc-700 text-zinc-600 hover:text-zinc-400 hover:border-zinc-500'
              }`}
            >
              <Mic size={14} />
              <span className="text-[8px]">音声</span>
            </button>
          </div>

          {/* Generation Panel (slides in below media browser) */}
          {activePanel !== 'none' && (
            <div className="bg-[#0e0e18] border-t border-zinc-800/60 px-4 py-3 shrink-0">
              {activePanel === 'video' && (
                <form onSubmit={handleGenerateVideo} className="flex gap-3 items-end">
                  <div className="flex-1 space-y-2">
                    <div className="flex gap-2">
                      <input
                        className="flex-1 bg-zinc-900 border border-zinc-700 rounded-lg px-3 py-1.5 text-xs focus:outline-none focus:border-indigo-500"
                        placeholder="ラベル（例: 冒頭シーン）"
                        value={videoLabel}
                        onChange={e => setVideoLabel(e.target.value)}
                      />
                      <select
                        className="bg-zinc-900 border border-zinc-700 rounded-lg px-2 py-1.5 text-xs focus:outline-none"
                        value={videoDuration}
                        onChange={e => setVideoDuration(Number(e.target.value))}
                      >
                        <option value={5}>5秒</option>
                        <option value={10}>10秒</option>
                      </select>
                    </div>
                    <textarea
                      className="w-full bg-zinc-900 border border-zinc-700 rounded-lg px-3 py-1.5 text-xs focus:outline-none focus:border-indigo-500 resize-none"
                      rows={2}
                      placeholder="映像プロンプト（英語推奨）"
                      value={videoPrompt}
                      onChange={e => setVideoPrompt(e.target.value)}
                      required
                      autoFocus
                    />
                  </div>
                  <div className="flex flex-col gap-1.5">
                    <button
                      type="submit"
                      disabled={generatingVideo || !videoPrompt.trim()}
                      className="bg-indigo-500 text-white px-4 py-2 rounded-lg text-xs font-medium hover:bg-indigo-400 disabled:opacity-40 transition-colors whitespace-nowrap"
                    >
                      {generatingVideo ? '送信中...' : '生成'}
                    </button>
                    <button type="button" onClick={() => setActivePanel('none')} className="text-zinc-500 text-xs hover:text-zinc-300">
                      閉じる
                    </button>
                  </div>
                </form>
              )}
              {activePanel === 'voice' && (
                <form onSubmit={handleGenerateVoice} className="flex gap-3 items-end">
                  <div className="flex-1 space-y-2">
                    <input
                      className="w-full bg-zinc-900 border border-zinc-700 rounded-lg px-3 py-1.5 text-xs focus:outline-none focus:border-green-500"
                      placeholder="ラベル（例: 冒頭ナレーション）"
                      value={voiceLabel}
                      onChange={e => setVoiceLabel(e.target.value)}
                    />
                    <textarea
                      className="w-full bg-zinc-900 border border-zinc-700 rounded-lg px-3 py-1.5 text-xs focus:outline-none focus:border-green-500 resize-none"
                      rows={2}
                      placeholder="読み上げるテキスト..."
                      value={voiceText}
                      onChange={e => setVoiceText(e.target.value)}
                      required
                      autoFocus
                    />
                  </div>
                  <div className="flex flex-col gap-1.5">
                    <button
                      type="submit"
                      disabled={generatingVoice || !voiceText.trim()}
                      className="bg-green-600 text-white px-4 py-2 rounded-lg text-xs font-medium hover:bg-green-500 disabled:opacity-40 transition-colors whitespace-nowrap"
                    >
                      {generatingVoice ? '生成中...' : '生成'}
                    </button>
                    <button type="button" onClick={() => setActivePanel('none')} className="text-zinc-500 text-xs hover:text-zinc-300">
                      閉じる
                    </button>
                  </div>
                </form>
              )}
            </div>
          )}

          {/* Timeline */}
          <div className="h-[160px] bg-[#0a0a12] border-t border-zinc-800/60 flex flex-col shrink-0">
            {/* Timeline header */}
            <div className="h-7 bg-[#0e0e18] border-b border-zinc-800/40 flex items-center px-3 gap-4 text-[11px]">
              <span className="text-indigo-400 font-medium">タイムライン</span>
              <span className="text-zinc-600 ml-auto">
                映像: {videoClips.filter(c => c.file_url).length} / 音声: {voiceTracks.filter(t => t.file_url).length}
              </span>
            </div>

            {/* Ruler */}
            <div className="h-5 bg-[#08080e] border-b border-zinc-800/40 relative">
              {['0:00', '0:05', '0:10', '0:15', '0:20', '0:25', '0:30'].map((t, i) => (
                <span key={t} className="absolute bottom-0.5 text-[9px] text-zinc-700 font-mono" style={{ left: `${60 + i * 140}px` }}>
                  {t}
                </span>
              ))}
              <div className="absolute top-0 bottom-0 w-0.5 bg-red-500 left-[60px]">
                <div className="absolute -top-0.5 -left-[5px] w-0 h-0 border-l-[5px] border-r-[5px] border-t-[5px] border-l-transparent border-r-transparent border-t-red-500" />
              </div>
            </div>

            {/* Tracks */}
            <div className="flex-1 overflow-hidden">
              {[
                { id: 'v1', label: 'V1 映像', trackKey: 'v1' as const },
                { id: 'v2', label: 'V2 B-Roll', trackKey: 'v2' as const },
                { id: 'text', label: 'テロップ', trackKey: 'text' as const },
                { id: 'audio', label: 'A1 音声', trackKey: 'audio' as const },
                { id: 'bgm', label: 'BGM', trackKey: 'bgm' as const },
              ].map(track => (
                <div key={track.id} className="h-[24px] flex items-center border-b border-zinc-900/50">
                  <div className="w-16 shrink-0 text-[9px] text-zinc-600 font-semibold text-right pr-2 border-r border-zinc-800/40 h-full flex items-center justify-end">
                    {track.label}
                  </div>
                  <div className="flex-1 h-full relative px-0.5">
                    {timelineClips
                      .filter(c => c.track === track.trackKey)
                      .map(clip => (
                        <div
                          key={clip.id}
                          className={`absolute top-[3px] bottom-[3px] rounded text-[8px] font-semibold text-white/90 flex items-center px-1.5 overflow-hidden whitespace-nowrap cursor-pointer transition-all ${clip.color} ${
                            selectedClipId === clip.sourceId ? 'ring-1 ring-white/50' : ''
                          }`}
                          style={{ left: `${clip.startPct}%`, width: `${clip.widthPct}%` }}
                          onClick={() => {
                            const src = clip.type === 'video'
                              ? videoClips.find(v => v.id === clip.sourceId)
                              : voiceTracks.find(v => v.id === clip.sourceId);
                            if (src && 'file_url' in src && src.file_url) {
                              selectMedia(src.file_url, clip.type === 'video' ? 'video' : 'audio', clip.sourceId!);
                            }
                          }}
                        >
                          {clip.label}
                        </div>
                      ))}
                    {timelineClips.filter(c => c.track === track.trackKey).length === 0 && (
                      <div className="h-full flex items-center pl-2 text-[9px] text-zinc-800">
                        ドラッグして配置
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* ─── Right: AI Chat Panel ─── */}
        <div className="w-80 bg-[#0f0f1a] border-l border-zinc-800/60 flex flex-col shrink-0">
          {/* AI Header */}
          <div className="h-10 border-b border-zinc-800/60 flex items-center px-3 gap-2 text-sm font-semibold shrink-0">
            <div className="w-2 h-2 rounded-full bg-green-500" />
            Dan AI
            <span className="text-[10px] bg-indigo-500/10 text-indigo-400 px-2 py-0.5 rounded-full ml-auto border border-indigo-500/20">
              脚本アシスタント
            </span>
          </div>

          {/* Messages */}
          <div className="flex-1 overflow-y-auto p-3 space-y-2.5 min-h-0">
            {messages.length === 0 && (
              <div className="text-zinc-700 text-xs text-center py-8">
                AIと脚本を壁打ちする<br />
                <span className="text-zinc-600 mt-2 block">例:「第1話の構成を考えて」</span>
                <span className="text-zinc-600 block">「冒頭の掴みを3パターン出して」</span>
              </div>
            )}
            {messages.map((m, i) => (
              <div
                key={i}
                className={`px-3 py-2 rounded-xl text-xs leading-relaxed max-w-[94%] ${
                  m.role === 'user'
                    ? 'ml-auto bg-indigo-900/40 text-indigo-100 rounded-br-sm'
                    : 'bg-[#141420] text-zinc-300 border border-zinc-800/60 rounded-bl-sm'
                }`}
              >
                {m.role !== 'user' && (
                  <span className="text-[10px] font-bold text-indigo-400 block mb-1">DAN</span>
                )}
                <span className="whitespace-pre-wrap">{m.content}</span>
              </div>
            ))}
            {chatSending && (
              <div className="bg-[#141420] border border-zinc-800/60 rounded-xl px-3 py-2 text-xs text-zinc-500 rounded-bl-sm">
                <span className="text-[10px] font-bold text-indigo-400 block mb-1">DAN</span>
                <span className="animate-pulse">考え中...</span>
              </div>
            )}
            <div ref={chatEndRef} />
          </div>

          {/* Chat error banner */}
          {chatError && (
            <div className="mx-2 mb-1 px-3 py-1.5 bg-red-950/50 border border-red-800/40 rounded-lg text-[10px] text-red-300 flex items-center gap-1.5">
              <AlertCircle size={10} className="shrink-0" />
              <span className="truncate">{chatError}</span>
              <button onClick={() => setChatError(null)} className="ml-auto shrink-0"><X size={10} /></button>
            </div>
          )}

          {/* Input */}
          <form onSubmit={sendMessage} className="p-2.5 border-t border-zinc-800/60 shrink-0">
            <div className="flex items-center gap-2 bg-[#0a0a15] border border-zinc-800/60 rounded-xl px-3 py-2">
              <input
                className="flex-1 bg-transparent text-xs text-zinc-200 placeholder:text-zinc-700 focus:outline-none"
                placeholder="脚本について相談..."
                value={chatInput}
                onChange={e => setChatInput(e.target.value)}
              />
              <button
                type="submit"
                disabled={chatSending || !chatInput.trim()}
                className="w-7 h-7 rounded-lg bg-indigo-500 flex items-center justify-center text-white disabled:opacity-30 hover:bg-indigo-400 transition-colors"
              >
                <Send size={12} />
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  );
}
