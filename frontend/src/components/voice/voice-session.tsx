'use client';

/** Live 1 owns conversation; the Responses backend uses the room's tools. */
import { useCallback, useEffect, useRef, useState } from 'react';
import { X } from 'lucide-react';

import { usePreviewStore } from '@/stores/preview-store';

import { VoiceOrb } from './voice-orb';
import { connectAtomWifi, type AtomWifiTransport } from './atom-wifi-transport';
import { waitForStandbyDrain } from './standby-drain';

import { LiveBackend, appendLive, readLiveBackendStream } from './live-backend';
import { LiveJobs, liveJobObservation, type LiveJob } from './live-jobs';
import { LiveGreeting } from './live-greeting';
import { WorkWaiting, isWorking } from './work-waiting';
import { WaitingAudio } from './waiting-audio';
import { GeminiTransport } from './gemini-transport';

type Status = 'idle' | 'connecting' | 'connected' | 'error';
type RtEvent = { type: string; [key: string]: unknown };

const TOOL_LABELS: Record<string, string> = {
  delegate_to_dan: 'ダンへ委譲',
  check_dan_status: '進行確認',
  look_at_screen: '画面確認',
  web_search: 'Web検索',
  read_room_history: '履歴読込',
  get_artifact_state: '状態取得',
  set_text: '文言変更',
  set_style: 'スタイル変更',
  list_source_files: 'ファイル一覧',
  read_source: 'ソース読込',
  edit_source: 'ソース編集',
  write_source: 'ソース書換',
  generate_image: '画像生成',
  look_at_page: '全体確認',
  look_at_section: '細部確認',
  check_contrast: 'コントラスト検査',
  read_skill: 'スキル参照',
  timeline_state: '動画の状態',
  timeline_edit: '動画を編集',
  timeline_frame: '動画の画面確認',
};

interface VoiceSessionProps {
  roomId: string;
  chatTitle?: string;
  onClose: () => void;
}

export function VoiceSession({ roomId, chatTitle, onClose }: VoiceSessionProps) {
  const [status, setStatus] = useState<Status>('idle');
  const pendingCenterReportsRef = useRef(new Map<string, string | null>());
  const [error, setError] = useState<string | null>(null);
  const [speaking, setSpeaking] = useState(false);
  const [currentActivity, setCurrentActivity] = useState<string | null>(null);
  /** オーブ下に出す活動フィード（ツール実行・委譲の進行を1行ずつ）。文字起こしは出さない。 */
  const [activity, setActivity] = useState<string[]>([]);
  const liveBackendRef = useRef<LiveBackend | null>(null);
  const hasActiveVoiceJobsRef = useRef(false);
  const workingJobsRef = useRef(false);
  const waitingAudioRef = useRef<WaitingAudio | null>(null);
  const jobObservationsRef = useRef(new Map<string,string>());
  const jobDelegationsRef = useRef(new Map<string,string>());
  const latestUserSpeechRef = useRef('');
  const flushTranscriptsRef = useRef<(() => void) | null>(null);

  // ---- 開発CLI監視用のファイルログ（scratch実験ページと同じ受け口に流す） ----
  const [logSession] = useState(() => `chat-${new Date().toISOString().slice(0, 19).replace(/:/g, '-')}`);
  const logBufferRef = useRef<Array<{ time: string; tag: string; text: string }>>([]);
  const pushLog = useCallback((tag: string, text: string) => {
    logBufferRef.current.push({
      time: new Date().toLocaleTimeString('ja-JP', { hour12: false }),
      tag,
      text,
    });
  }, []);
  useEffect(() => {
    const flush = () => {
      const batch = logBufferRef.current.splice(0);
      if (!batch.length) return;
      void fetch('/scratch/realtime-voice/api/log', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: logSession, entries: batch }),
      }).catch(() => {});
    };
    const t = setInterval(flush, 3000);
    return () => {
      clearInterval(t);
      flush();
    };
  }, [logSession]);

  const pushActivity = useCallback((line: string) => {
    setActivity((a) => [...a, line].slice(-5));
  }, []);

  const pcRef = useRef<RTCPeerConnection | null>(null);
  const geminiRef = useRef<GeminiTransport | null>(null);
  const dcRef = useRef<RTCDataChannel | null>(null);
  const micRef = useRef<MediaStream | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const atomWifiRef = useRef<AtomWifiTransport | null>(null);
  const displayStreamRef = useRef<MediaStream | null>(null);
  const genRef = useRef(0);

  const guardianTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // ---- オーブ駆動用の音量計測 ----
  const audioCtxRef = useRef<AudioContext | null>(null);
  const micAnalyserRef = useRef<AnalyserNode | null>(null);
  const aiAnalyserRef = useRef<AnalyserNode | null>(null);
  const levelBufRef = useRef<Uint8Array<ArrayBuffer>>(new Uint8Array(new ArrayBuffer(512)));

  const readLevel = useCallback((analyser: AnalyserNode | null): number => {
    if (!analyser) return 0;
    const buf = levelBufRef.current;
    analyser.getByteTimeDomainData(buf);
    let sum = 0;
    for (let i = 0; i < buf.length; i += 1) {
      const v = (buf[i] - 128) / 128;
      sum += v * v;
    }
    // RMS を体感リニアに寄せる（小声でも反応するよう平方根で持ち上げ）
    return Math.min(1, Math.sqrt(Math.sqrt(sum / buf.length)) * 1.6);
  }, []);
  const getUserLevel = useCallback(() => readLevel(micAnalyserRef.current), [readLevel]);
  const getAiLevel = useCallback(() => readLevel(aiAnalyserRef.current), [readLevel]);

  const authHeaders = useCallback((): Record<string, string> => {
    const token = typeof localStorage !== 'undefined' ? localStorage.getItem('done-token') || '' : '';
    return { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) };
  }, []);

  /** 文字起こしを部屋の履歴へ保存（失敗しても会話は止めない） */
  const saveTranscript = useCallback(
    (role: 'user' | 'assistant', content: string, createdAt?: string) => {
      void fetch(`/api/v1/voicelog/${encodeURIComponent(roomId)}`, {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify({ role, content: content.slice(0, 7500), created_at: createdAt }),
        keepalive: true,
      }).catch(() => {});
    },
    [authHeaders, roomId],
  );

  const dcSend = useCallback((obj: unknown) => {
    if (geminiRef.current) { geminiRef.current.append(obj as RtEvent); return; }
    const dc = dcRef.current;
    if (dc && dc.readyState === 'open') dc.send(JSON.stringify(obj));
  }, []);

  const injectItem = useCallback((event: unknown) => {
    const item = event as { type: string; item?: Record<string, unknown> };
    if (item.type === 'conversation.item.create') {
      if (item.item) liveBackendRef.current?.addInput(item.item);
    }
  }, []);

  const injectSystemAndRespond = useCallback((text: string, delegationId: string | null = null) => {
    appendLive(dcSend, 'commentary', text, delegationId);
  }, [dcSend]);

  useEffect(() => {
    if (status !== 'connected') return;
    const jobs = new LiveJobs();
    let polling = false;
    let disposed = false;
    const poll = async () => {
      if (polling || disposed) return;
      polling = true;
      try {
        const response = await fetch('/api/v1/voicelog/command-center', {
          method:'POST', headers:authHeaders(), body:JSON.stringify({room_id:roomId,args:{action:'jobs'}}),
        });
        if (!response.ok || disposed) return;
        const data = await response.json();
        const rows: LiveJob[] = data.jobs || [];
        hasActiveVoiceJobsRef.current = rows.some(job => !['completed','failed','cancelled'].includes(job.state));
        workingJobsRef.current = rows.some(job => ['queued','running'].includes(job.state));
        for (const job of rows) {
          if (job.report_message_id) pendingCenterReportsRef.current.delete(job.report_message_id);
        }
        for (const {job,event} of jobs.updates(rows)) {
          const text = `[作業 ${job.id} / ${job.task} / ${job.state}${job.confirmation ? ' / confirmation_id='+job.confirmation.id : ''}]\n${event.text}`;
          liveBackendRef.current?.addInput({type:'message',role:'user',content:[{type:'input_text',text}]});
          const observation = liveJobObservation(job,event);
          if(observation.kind==='commentary') {jobObservationsRef.current.delete(job.id);appendLive(dcSend,'commentary',observation.text,jobDelegationsRef.current.get(job.id) || null);}
          else jobObservationsRef.current.set(job.id,observation.text);
        }
      } catch (error) { pushLog('⚠', '作業状況の同期に失敗しました'); }
      finally { polling = false; }
    };
    void poll();
    const timer = window.setInterval(() => { void poll(); }, 1500);
    return () => { disposed = true; window.clearInterval(timer); };
  }, [status,roomId,authHeaders,dcSend,pushLog]);

  useEffect(() => {
    if (status !== 'connected') return;
    let closed = false;
    let running = false;
    let restored = false;
    const checkReports = async () => {
      if (running || (restored && !pendingCenterReportsRef.current.size)) return;
      running = true;
      try {
        if (!restored) {
          const jobsResponse = await fetch('/api/v1/voicelog/command-center', {
            method: 'POST', headers: authHeaders(), body: JSON.stringify({ room_id: roomId, args: { action: 'requests' } }),
          });
          if (!jobsResponse.ok || closed) return;
          const jobs = await jobsResponse.json();
          if (closed) return;
          for (const job of jobs.requests || []) {
            if (['pending', 'firing'].includes(job.status) && !pendingCenterReportsRef.current.has(job.report_message_id)) pendingCenterReportsRef.current.set(job.report_message_id, null);
          }
          restored = true;
        }
        if (!pendingCenterReportsRef.current.size || closed) return;
        const response = await fetch(`/api/v1/chat/rooms/${encodeURIComponent(roomId)}/messages?limit=50`, { headers: authHeaders() });
        if (!response.ok || closed) return;
        const data = await response.json();
        if (closed) return;
        for (const message of data.messages || []) {
          if (!pendingCenterReportsRef.current.has(message.id)) continue;
          const delegationId = pendingCenterReportsRef.current.get(message.id) ?? null;
          pendingCenterReportsRef.current.delete(message.id);
          liveBackendRef.current?.addInput({ type: 'message', role: 'user', content: [{ type: 'input_text', text: message.content }] });
          injectSystemAndRespond(`[作業報告が司令塔に届きました。記録として読み、要点を短く伝える]\n${message.content}`, delegationId);
        }
      } finally { running = false; }
    };
    const timer = window.setInterval(() => { void checkReports().catch(() => {}); }, 3000);
    return () => { closed = true; window.clearInterval(timer); };
  }, [status, roomId, authHeaders, injectSystemAndRespond]);

  /** look_at_screen 用の画面共有キャプチャ（初回のみ許可ダイアログ） */
  const captureScreenshot = useCallback(async (): Promise<string | null> => {
    let stream = displayStreamRef.current;
    if (!stream || !stream.active) {
      const constraints: MediaStreamConstraints & { video: Record<string, unknown> } = {
        video: { preferCurrentTab: false },
        audio: false,
      };
      stream = await navigator.mediaDevices.getDisplayMedia(constraints);
      displayStreamRef.current = stream;
    }
    const video = document.createElement('video');
    video.srcObject = stream;
    video.muted = true;
    await video.play();
    await new Promise((r) => setTimeout(r, 200));
    const scale = Math.min(1, 1280 / (video.videoWidth || 1280));
    const canvas = document.createElement('canvas');
    canvas.width = Math.round((video.videoWidth || 1280) * scale);
    canvas.height = Math.round((video.videoHeight || 720) * scale);
    canvas.getContext('2d')!.drawImage(video, 0, 0, canvas.width, canvas.height);
    video.pause();
    video.srcObject = null;
    return canvas.toDataURL('image/jpeg', 0.7);
  }, []);

  const executeTool = useCallback(
    async (name: string, args: Record<string, unknown>, delegationId: string | null = null): Promise<Record<string, unknown>> => {
      if (name === 'delegate_to_dan') {
        const task = String(args.task ?? '').trim();
        if (!task) return { error: 'task が空です' };
        const response = await fetch('/api/v1/voicelog/command-center', {
          method: 'POST', headers: authHeaders(),
          body: JSON.stringify({ room_id: roomId, args: { action: 'work', task } }),
        });
        const result = await response.json();
        if (!response.ok || !result.accepted) return { error: result.detail || '作業を受け付けられませんでした。' };
        if (result.engine !== 'steerable_cli') pendingCenterReportsRef.current.set(result.report_message_id, delegationId);
        pushLog('📋', `委譲: ${task.slice(0, 200)}`);
        return { ...result, status: 'delegated', note: 'この部屋のDanが実行します。進捗と結果は保存され、通話終了後も作業は続きます。' };
      }

      if (name === 'control_dan_task') {
        const response = await fetch('/api/v1/voicelog/command-center', {
          method:'POST', headers:authHeaders(), body:JSON.stringify({room_id:roomId,
            args:{...args,action:'control_job',approval_text:latestUserSpeechRef.current}}),
        });
        const data = await response.json();
        return response.ok ? data : {error:data.detail || '作業への指示を届けられませんでした'};
      }
      if (name === 'command_center') {
        const response = await fetch('/api/v1/voicelog/command-center', {
          method: 'POST', headers: authHeaders(),
          body: JSON.stringify({ room_id: roomId, args }),
        });
        const result = await response.json();
        if (response.ok && result.accepted && result.report_message_id && result.engine !== 'steerable_cli') {
          pendingCenterReportsRef.current.set(result.report_message_id, delegationId);
        }
        return response.ok ? result : { error: result.detail || '司令塔の操作に失敗しました。' };
      }

      if (name === 'read_room_history') {
        const limit = Math.min(50, Math.max(1, Number(args.limit) || 4));
        try {
          const res = await fetch(`/api/v1/chat/rooms/${encodeURIComponent(roomId)}/messages?limit=${limit}`, {
            headers: authHeaders(),
          });
          if (!res.ok) return { error: `履歴の取得に失敗 (HTTP ${res.status})` };
          const data = (await res.json()) as { messages?: Array<{ sender_type?: string; content?: string; created_at?: string }> };
          const msgs = (data.messages || []).map((m) => ({
            from: m.sender_type === 'ai' ? 'dan' : 'user',
            at: String(m.created_at || '').slice(5, 16),
            text: String(m.content || ''),
          }));
          return { count: msgs.length, messages: msgs };
        } catch (e) {
          return { error: `履歴の取得に失敗: ${String(e).slice(0, 120)}` };
        }
      }

      if (name === 'web_search') {
        const query = String(args.query ?? '').trim();
        if (!query) return { error: 'query が空です' };
        try {
          const res = await fetch('/api/v1/voicelog/search', {
            method: 'POST',
            headers: authHeaders(),
            body: JSON.stringify({ query }),
          });
          const data = (await res.json()) as Record<string, unknown>;
          if (!res.ok) return { error: String(data.detail || `検索に失敗 (${res.status})`) };
          return data;
        } catch (e) {
          return { error: `検索に失敗: ${String(e).slice(0, 120)}` };
        }
      }

      if (name === 'check_dan_status') {
        const response = await fetch('/api/v1/voicelog/command-center', {
          method: 'POST', headers: authHeaders(), body: JSON.stringify({ room_id: roomId, args: { action: 'requests' } }),
        });
        const crossRoom = await response.json();
        return {
          cross_room: response.ok ? crossRoom : { error: crossRoom.detail || '進行状況を取得できませんでした' },
          note: 'cross_roomにこの部屋と別室への依頼、実行状態、プロセスモニターが含まれます。',
        };
      }

      if (name === 'look_at_screen') {
        try {
          const dataUrl = await captureScreenshot();
          if (!dataUrl) return { error: 'スクリーンショットを取得できませんでした' };
          const id = `item_img_${Date.now()}`;
          injectItem({
            type: 'conversation.item.create',
            item: { id, type: 'message', role: 'user', content: [{ type: 'input_image', image_url: dataUrl }] },
          });
          return { ok: true, note: 'ユーザーの画面のスクリーンショットを会話に添付しました。' };
        } catch (e) {
          return { error: `画面キャプチャに失敗（共有が許可されなかった可能性）: ${String(e).slice(0, 120)}` };
        }
      }

      // ---- 成果物編集ツール群（V2）: 対象=成果物タブで開いている成果物。実行は全部サーバー側 ----
      const previewSlug = () => {
        const s = usePreviewStore.getState();
        return s.iframeSlug || s.artifact?.slug || null;
      };
      const refreshPreview = () => usePreviewStore.getState().bumpContentVersion();
      const needSlug = (): string | { error: string } => {
        const slug = previewSlug();
        return slug || { error: '成果物タブで対象の成果物を開いてください（プレビューが開いていません）' };
      };
      const api = async (path: string, payload: Record<string, unknown>): Promise<Record<string, unknown>> => {
        const res = await fetch(`/api/v1/voicelog/${path}`, {
          method: 'POST',
          headers: authHeaders(),
          body: JSON.stringify(payload),
        });
        const data = (await res.json().catch(() => ({}))) as Record<string, unknown>;
        if (!res.ok) return { error: String(data.detail || `失敗 (HTTP ${res.status})`) };
        return data;
      };
      const injectImages = (images: string[]) => {
        images.forEach((img, i) => {
          const id = `item_img_${Date.now()}_${i}`;
          injectItem({
            type: 'conversation.item.create',
            item: { id, type: 'message', role: 'user', content: [{ type: 'input_image', image_url: img }] },
          });
        });
      };

      if (name === 'get_artifact_state' || name === 'check_contrast') {
        const slug = needSlug();
        if (typeof slug !== 'string') return slug;
        const data = await api('capture', { slug, mode: name === 'check_contrast' ? 'contrast' : 'state' });
        return data;
      }

      if (name === 'look_at_page') {
        const slug = needSlug();
        if (typeof slug !== 'string') return slug;
        const data = await api('capture', { slug, mode: 'tiles' });
        if (data.error) return data;
        const tiles = (data.tiles as string[]) || [];
        if (!tiles.length) return { error: 'タイルが取得できませんでした' };
        injectImages(tiles);
        return {
          ok: true,
          tiles: tiles.length,
          note: `成果物の全体を上から順に${tiles.length}枚の高解像度タイルで添付しました。draft反映済みの実際の見た目です。悪いところに自分の目で気付いてください。`,
        };
      }

      if (name === 'look_at_section') {
        const slug = needSlug();
        if (typeof slug !== 'string') return slug;
        const data = await api('capture', { slug, mode: 'section', element_id: String(args.id ?? '') });
        if (data.error) return data;
        if (!data.image) return { error: '撮影できませんでした' };
        injectImages([data.image as string]);
        return { ok: true, note: `要素 ${String(args.id)} の原寸スクリーンショットを添付しました。` };
      }

      if (name === 'set_text' || name === 'set_style') {
        const slug = needSlug();
        if (typeof slug !== 'string') return slug;
        const payload: Record<string, unknown> = { slug, element_id: String(args.id ?? '') };
        if (name === 'set_text') payload.text = String(args.text ?? '');
        else payload.styles = args.styles ?? {};
        const data = await api('edit', payload);
        if (!data.error) refreshPreview();
        return data.error ? data : { ok: true, id: args.id, note: 'draftとして保存しました。プレビューを再読込して反映します。' };
      }

      if (name === 'list_source_files' || name === 'read_source' || name === 'edit_source' || name === 'write_source') {
        const slug = needSlug();
        if (typeof slug !== 'string') return slug;
        const action =
          name === 'list_source_files' ? 'list' : name === 'read_source' ? 'read' : name === 'edit_source' ? 'edit' : 'write';
        const data = await api('source', {
          action,
          slug,
          file: args.file,
          old_string: args.old_string,
          new_string: args.new_string,
          content: args.content,
        });
        if (!data.error && (action === 'edit' || action === 'write')) refreshPreview();
        return data;
      }

      if (name === 'generate_image') {
        const prompt = String(args.prompt ?? '').trim();
        if (!prompt) return { error: 'prompt が空です' };
        pushLog('🖼', `画像生成開始: ${prompt.slice(0, 80)}`);
        void (async () => {
          const data = await api('generate-image', { prompt, size: args.size });
          if (data.error) {
            injectSystemAndRespond(`[システム通知] 画像生成に失敗しました（${String(data.error).slice(0, 150)}）。ユーザーに伝えてください。`);
            return;
          }
          pushLog('🖼', `画像生成完了: ${String(data.url)}`);
          injectSystemAndRespond(
            `[システム通知] 画像が完成しました: ${String(data.url)}\n` +
              'set_style の background-image、または edit_source で <img> の src にこのURLを自分で適用してください。',
          );
        })();
        return { status: 'generating', note: '20〜60秒で完成の通知が届きます。届いたら自分で適用してください。' };
      }

      if (name === 'read_skill') {
        return api('skill', { name: args.name });
      }

      // 動画エディタ（制作ルーム）: 速い車線＝1操作即時コミット / 目＝合成後フレーム
      if (name === 'timeline_state') {
        if (!roomId) return { error: '部屋が特定できません（チャットの部屋から音声を開いてください）' };
        return api('timeline', { room_id: roomId, action: 'state', outline: args.outline !== false });
      }
      if (name === 'timeline_edit') {
        if (!roomId) return { error: '部屋が特定できません' };
        const data = await api('timeline', {
          room_id: roomId, action: 'edit', op: String(args.op ?? ''), args: (args.args as Record<string, unknown>) ?? {},
          content_id: args.content_id ? String(args.content_id) : undefined,
        });
        pushLog('🎬', `編集 ${String(args.op ?? '')}: ${data.error ? String(data.error) : 'OK'}`);
        return data;
      }
      if (name === 'timeline_frame') {
        if (!roomId) return { error: '部屋が特定できません' };
        const data = await api('timeline', {
          room_id: roomId, action: 'frame', t: typeof args.t === 'number' ? args.t : undefined,
          content_id: args.content_id ? String(args.content_id) : undefined,
        });
        if (data.error || !data.image) return data.error ? data : { error: 'フレームを取得できませんでした' };
        injectImages([data.image as string]);
        return { ok: true, t: data.t, note: `${Number(data.t).toFixed(1)}秒の合成後フレームを添付しました（字幕・ぼかし・枠込み）。` };
      }

      return { error: `未知のツール: ${name}` };
    },
    [authHeaders, captureScreenshot, injectItem, injectSystemAndRespond, pushLog, roomId],
  );

  const disconnect = useCallback(() => {
    waitingAudioRef.current?.close(); waitingAudioRef.current = null;
    workingJobsRef.current = false;
    genRef.current += 1;
    flushTranscriptsRef.current?.(); flushTranscriptsRef.current = null;
    liveBackendRef.current?.close(); liveBackendRef.current = null;
    geminiRef.current?.close(); geminiRef.current = null;
    for (const id of pendingCenterReportsRef.current.keys()) pendingCenterReportsRef.current.set(id, null);
    const channel = dcRef.current, peer = pcRef.current;
    dcRef.current = null; pcRef.current = null;
    if (channel?.readyState === 'open') {
      let closed = false;
      const finish = () => { if (closed) return; closed = true; channel.close(); peer?.close(); };
      channel.addEventListener('message', event => { try { if (JSON.parse(event.data).type === 'session.closed') finish(); } catch {} });
      channel.send(JSON.stringify({ type: 'session.close' }));
      setTimeout(finish, 3000);
    } else { channel?.close(); peer?.close(); }
    if (guardianTimerRef.current) {
      clearInterval(guardianTimerRef.current);
      guardianTimerRef.current = null;
    }
    displayStreamRef.current?.getTracks().forEach((t) => t.stop());
    displayStreamRef.current = null;
    micRef.current?.getTracks().forEach((t) => t.stop());
    micRef.current = null;
    atomWifiRef.current?.close();
    atomWifiRef.current = null;
    if (audioRef.current) {
      audioRef.current.srcObject = null;
      audioRef.current.remove();
      audioRef.current = null;
    }
    void audioCtxRef.current?.close().catch(() => {});
    audioCtxRef.current = null;
    micAnalyserRef.current = null;
    aiAnalyserRef.current = null;
    setSpeaking(false);
    setCurrentActivity(null);
    setStatus((s) => (s === 'error' ? 'error' : 'idle'));
  }, []);

  const connect = useCallback(async () => {
    disconnect();
    genRef.current += 1;
    const myGen = genRef.current;
    const live = () => genRef.current === myGen;
    const provider = new URLSearchParams(location.search).get('voice') === 'gemini' ? 'gemini' : 'openai';

    setStatus('connecting');
    setError(null);
    setActivity([]);
    let outputPlaying = false;
    let lastOutput = 0;
    let speechEpoch = 0;
    let started = false;
    let liveSessionId = '';
    let userTurn = 0, userLength = 0, followupEligible = false;
    let currentWork: Record<string,unknown> | null = null;
    const waiting = new WorkWaiting(active => waitingAudioRef.current?.set(active));
    jobObservationsRef.current.clear();jobDelegationsRef.current.clear();hasActiveVoiceJobsRef.current=false;
    const dialogue: Array<{ role: string; text: string }> = [];
    const recentDialogue = () => [...dialogue, ...Object.entries(transcripts).map(([role, row]) => ({ role, text: row!.text }))].slice(-32);
    type Transcript = { text: string; end: number; at: string; timer?: ReturnType<typeof setTimeout> };
    const transcripts: Partial<Record<'user' | 'assistant', Transcript>> = {};
    const flush = (role: 'user' | 'assistant') => {
      const row = transcripts[role];
      if (!row) return;
      clearTimeout(row.timer); delete transcripts[role];
      if (row.text.trim()) { dialogue.push({ role, text: row.text.trim() }); saveTranscript(role, row.text.trim(), row.at); pushLog(role === 'user' ? '🎤' : '🗣', row.text.trim()); }
      if (role === 'user' && live() && provider === 'openai' && followupEligible) liveBackendRef.current?.followupSpeech(userTurn,userLength,
        () => [{role:'user',content:JSON.stringify({dialogue:recentDialogue(),utterance_final:!transcripts.user})}]);
    };
    flushTranscriptsRef.current = () => { flush('user'); flush('assistant'); };
    let ending = false;
    const endCall = async () => {
      if (ending || !live()) return;
      ending = true;
      waiting.close();
      liveBackendRef.current?.close();
      micRef.current?.getAudioTracks().forEach(track => { track.enabled = false; });
      (window as Window & { atomEvent?: (event: Record<string, unknown>) => void }).atomEvent?.({ type: 'standby_requested' });
      // A completed end-call request wins over further model speech. Allow a
      // short audible tail, but never wait indefinitely for Live to stop talking.
      await waitForStandbyDrain(() => ({ active: live(), generating: false, playing: outputPlaying, epoch: 0 }),
        { tailMs: 150, timeoutMs: 700 });
      if (!live()) return;
      flush('user'); flush('assistant');
      try {
        await atomWifiRef.current?.standby();
        disconnect();
      } catch (error) {
        setError('待機への切り替えに失敗しました'); setStatus('error'); disconnect();
        throw error;
      }
    };
    const backend = new LiveBackend(async (input,onText) => {
      const response = await fetch('/api/v1/voicelog/live/backend/stream', {
        method: 'POST', headers: authHeaders(), body: JSON.stringify({ session_id: liveSessionId, input }),
      });
      // Backend failure must not close the independent Live audio connection.
      return readLiveBackendStream(response,geminiRef.current ? undefined : onText);
    }, async (name, args, delegationId) => {
      if (!live()) throw new Error('Session closed');
      pushLog('🔧', `${name}(${JSON.stringify(args).slice(0, 140)})`);
      setCurrentActivity(TOOL_LABELS[name] || name);
      pushActivity(`🔧 ${TOOL_LABELS[name] || name}`);
      let result: Record<string, unknown>;
      if (name === 'enter_voice_standby' && atomWifiRef.current) {
        await endCall();
        return { ok: true, state: 'standby' };
      } else result = await executeTool(name, args, delegationId.startsWith('test_') ? null : delegationId);
      const receipt=result.receipt as {id?:string} | undefined;
      if(result.accepted && receipt?.id && !delegationId.startsWith('followup-') && !delegationId.startsWith('test_'))
        jobDelegationsRef.current.set(receipt.id,delegationId);
      if (live()) setCurrentActivity(null);
      (window as Window & { atomEvent?: (event: Record<string, unknown>) => void }).atomEvent?.({
        type: 'tool_result', name, action: args.action, project_id: args.project_id,
        status: result.error ? 'error' : result.status || 'ok',
      });
      return result;
    }, (text, id) => {
      pushLog('📄', text);
      if (live()) {
        if (geminiRef.current) geminiRef.current.complete(id, text);
        else appendLive(dcSend, 'commentary', text, id.startsWith('test_') || id.startsWith('followup-') ? null : id);
      }
    }, message => {
      pushLog('⚠', message);
      if (live()) {
        if (geminiRef.current) geminiRef.current.error(message);
        else appendLive(dcSend, 'commentary', message);
      }
    }, () => {
      if (liveSessionId) void fetch('/api/v1/voicelog/live/backend/close', {
        method:'POST',headers:authHeaders(),body:JSON.stringify({session_id:liveSessionId}),keepalive:true,
      }).catch(() => {});
    }, async input => {
      const response = await fetch('/api/v1/voicelog/live/backend/steer', {
        method: 'POST', headers: authHeaders(), body: JSON.stringify({session_id: liveSessionId, input}),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || '追加指示の受信を確認できませんでした');
      return data;
    }, state => {
      currentWork=state;
    });
    liveBackendRef.current = backend;
    (window as Window & { __atomTestText?: (text: string) => void }).__atomTestText = text => {
      if (!live() || !started) return;
      if (geminiRef.current) { geminiRef.current.sendText(text); return; }
      dialogue.push({ role: 'user', text }); saveTranscript('user', text);
      appendLive(dcSend, 'thinking', text);
      backend.delegate(`test_${crypto.randomUUID()}`, () => [{ type: 'message', role: 'user', content: [{ type: 'input_text', text }] }]);
    };
    const greeting = new LiveGreeting(dcSend, type => {
      (window as Window & { atomEvent?: (event: { type: string }) => void }).atomEvent?.({ type });
    });
    (window as Window & { __atomGreet?: () => boolean }).__atomGreet = () => {
      if (!live() || !started || ending || !atomWifiRef.current) return false;
      if (geminiRef.current) return geminiRef.current.greet();
      if (dcRef.current?.readyState !== 'open') return false;
      greeting.start(crypto.randomUUID());
      return true;
    };
    let ready: () => void = () => {};
    let failed: (error: Error) => void = () => {};
    const opened = new Promise<void>((resolve, reject) => { ready = resolve; failed = reject; });
    void opened.catch(() => {});
    const handleLiveEvent = (msg: RtEvent) => {
      if (!live()) return;
      greeting.observe(msg);
      if (msg.type === 'session.started') {
        liveSessionId = String((msg.session as { id: string }).id); started = true; ready();
        (window as Window & { __atomConfig?: unknown }).__atomConfig = { model: provider === 'gemini' ? 'gemini-3.8-live-extended-thinking' : 'gpt-live-1', backend: 'gpt-6-astra' };
        pushLog('✅', provider === 'gemini' ? 'Gemini Extended Thinking connected' : 'Live 1 connected');
      } else if (msg.type === 'session.closed') {
        flush('user'); flush('assistant');
        if (started) { setError('音声の接続が終了しました'); setStatus('error'); }
        else failed(new Error('音声モデルへの接続が終了しました'));
      } else if (msg.type === 'error') {
        const message = String((msg.error as { message?: string })?.message || 'Live 1 error');
        pushLog('⚠', message);
        if (!started) failed(new Error(message));
      } else if (msg.type === 'session.input_transcript.delta' || msg.type === 'session.output_transcript.delta') {
        waiting.speech(performance.now());
        const role = msg.type === 'session.input_transcript.delta' ? 'user' : 'assistant';
        const delta = String(msg.delta || '');
        if (!delta) return;
        let row = transcripts[role];
        if (row && Number(msg.start_ms) - row.end > 1600) { flush(role); row = undefined; }
        if (!row) {
          if (role === 'user') {
            userTurn++;userLength=0;followupEligible=hasActiveVoiceJobsRef.current;
            if(provider==='openai') {
              if(currentWork && currentWork.state!=='complete' && (currentWork.state!=='executing' || hasActiveVoiceJobsRef.current)) appendLive(dcSend,'thinking',JSON.stringify({current_work:currentWork}));
              for(const observation of jobObservationsRef.current.values()) appendLive(dcSend,'thinking',observation);
            }
          }
          row = { text: '', end: Number(msg.end_ms), at: new Date().toISOString() };
          transcripts[role] = row;
        }
        row.text += delta; row.end = Number(msg.end_ms);
        if (role === 'user') {
          userLength += delta.length;
          speechEpoch += 1; latestUserSpeechRef.current = row.text;
          if (provider === 'gemini') (window as Window & { atomEvent?: (event: Record<string, unknown>) => void }).atomEvent?.({ type: 'user_speech' });
        }
        clearTimeout(row.timer); row.timer = setTimeout(() => flush(role), 2500);
        if (role === 'assistant') lastOutput = performance.now();
      } else if (msg.type === 'session.delegation.created') {
        const id = String((msg.delegation as { id: string }).id);
        backend.delegateSpeech(id,userTurn,userLength, () => [{ type: 'message', role: 'user', content: [{ type: 'input_text', text: JSON.stringify({ dialogue: recentDialogue(), utterance_final:!transcripts.user, ...(msg.request ? { request: msg.request } : {}) }) }] }]);
      }

    };

    let pc: RTCPeerConnection | null = null;
    let mic: MediaStream | null = null;
    let audioEl: HTMLAudioElement | null = null;
    let atomWifi: AtomWifiTransport | null = null;
    const cleanupLocal = () => {
      if (provider === 'gemini') { geminiRef.current?.close(); geminiRef.current = null; }
      atomWifi?.close();
      if (atomWifiRef.current === atomWifi) atomWifiRef.current = null;
      try {
        pc?.close();
      } catch {
        /* noop */
      }
      mic?.getTracks().forEach((t) => t.stop());
      if (audioEl) {
        audioEl.srcObject = null;
        audioEl.remove();
      }
    };

    try {
      if (typeof window !== 'undefined' && !window.isSecureContext) {
        throw new Error('音声にはHTTPSかlocalhostが必要です');
      }
      const token = localStorage.getItem('done-token') || '';

      if (!live()) return;

      if (provider === 'gemini') {
        const audioCtx = new AudioContext({ sampleRate: 48000 });
        audioCtxRef.current = audioCtx;
        atomWifi = await connectAtomWifi(roomId, audioCtx);
        if (!live()) { cleanupLocal(); return; }
        atomWifiRef.current = atomWifi;
        mic = atomWifi?.stream ?? await navigator.mediaDevices.getUserMedia({ audio: true });
        micRef.current = mic;
        const response = await fetch('/api/v1/voicelog/live/session', {
          method: 'POST', headers: authHeaders(),
          body: JSON.stringify({ room_id: roomId, device: !!atomWifi, provider: 'gemini', thinking: 'high' }),
        });
        const session = await response.json();
        if (!response.ok) throw new Error(session.detail || 'Geminiの接続を準備できませんでした');
        liveSessionId = session.session.id;
        if (!live()) {
          void fetch('/api/v1/voicelog/live/backend/close', { method: 'POST', headers: authHeaders(), body: JSON.stringify({ session_id: liveSessionId }) });
          cleanupLocal(); return;
        }
        const transport = new GeminiTransport(audioCtx, session, handleLiveEvent,
          () => atomWifi?.interrupt(), () => atomWifi?.resume());
        geminiRef.current = transport;
        (window as Window & { __atomConnection?: () => unknown }).__atomConnection = () => ({
          room: roomId, connection: transport.connectionState,
          channel: transport.connectionState === 'connected' ? 'open' : 'closed',
          config: { model: transport.model, backend: 'gpt-6-astra', thinking: 'high' },
          interactionStatus: transport.interactionStatus,
        });
        if (atomWifi) atomWifi.play(transport.output.stream);
        else {
          audioEl = document.createElement('audio'); audioEl.autoplay = true;
          audioEl.srcObject = transport.output.stream; audioRef.current = audioEl;
          document.body.appendChild(audioEl); void audioEl.play().catch(() => {});
        }
        const analyser = audioCtx.createAnalyser(); analyser.fftSize = 1024;
        audioCtx.createMediaStreamSource(transport.output.stream).connect(analyser);
        aiAnalyserRef.current = analyser;
        const micAnalyser = audioCtx.createAnalyser(); micAnalyser.fftSize = 1024;
        audioCtx.createMediaStreamSource(mic).connect(micAnalyser); micAnalyserRef.current = micAnalyser;
        await audioCtx.resume();
        await transport.start(mic);
        if (!live()) { cleanupLocal(); return; }
        setStatus('connected');
        const samples = new Float32Array(1024);
        guardianTimerRef.current = setInterval(() => {
          if (!live() || ending) return;
          analyser.getFloatTimeDomainData(samples);
          const rms = Math.sqrt(samples.reduce((sum, x) => sum + x * x, 0) / samples.length);
          if (rms > .004) { lastOutput = performance.now(); outputPlaying = true; }
          else if (performance.now() - lastOutput > 500) outputPlaying = false;
          setSpeaking(outputPlaying);
        }, 100);
        return;
      }

      pc = new RTCPeerConnection();
      audioEl = document.createElement('audio');
      audioEl.autoplay = true;
      audioEl.style.display = 'none';
      document.body.appendChild(audioEl);

      const audioCtx = new AudioContext({ sampleRate: 48000 });
      audioCtxRef.current = audioCtx;
      atomWifi = await connectAtomWifi(roomId, audioCtx);
      waitingAudioRef.current = new WaitingAudio(audioCtx, atomWifi?.cueOutput ?? audioCtx.destination);
      if (!live()) { cleanupLocal(); return; }
      atomWifiRef.current = atomWifi;
      if (atomWifi) audioEl.volume = 0;

      pc.ontrack = (e) => {
        const stream = e.streams[0] || new MediaStream([e.track]);
        if (audioEl) { audioEl.srcObject = stream; void audioEl.play().catch(() => {}); }
        atomWifi?.play(stream);
        // AI音声の音量 → オーブの雲の揺らめき
        try {
          const src = audioCtx.createMediaStreamSource(stream);
          const analyser = audioCtx.createAnalyser();
          analyser.fftSize = 1024;
          src.connect(analyser);
          aiAnalyserRef.current = analyser;
        } catch {
          /* noop */
        }
      };

      try {
        mic = atomWifi?.stream ?? await navigator.mediaDevices.getUserMedia({ audio: true });
      } catch {
        throw new Error('マイクの使用が許可されませんでした');
      }
      if (!live()) {
        cleanupLocal();
        return;
      }
      for (const track of mic.getAudioTracks()) pc.addTrack(track, mic);
      // マイク音量 → オーブ全体の揺れ
      try {
        const src = audioCtx.createMediaStreamSource(mic);
        const analyser = audioCtx.createAnalyser();
        analyser.fftSize = 1024;
        src.connect(analyser);
        micAnalyserRef.current = analyser;
      } catch {
        /* noop */
      }

      const dc = pc.createDataChannel('oai-events');
      pcRef.current = pc; dcRef.current = dc; micRef.current = mic; audioRef.current = audioEl;
      dc.onmessage = event => { try { handleLiveEvent(JSON.parse(event.data)); } catch (error) { pushLog('⚠', String(error)); } };
      dc.onclose = () => { failed(new Error('Live 1の接続が閉じました')); if (live()) setStatus('error'); };
      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);
      const peer = pc;
      if (peer.iceGatheringState !== 'complete') await new Promise<void>((resolve, reject) => {
        const timer = setTimeout(() => { peer.removeEventListener('icegatheringstatechange', check); reject(new Error('音声接続の準備がタイムアウトしました')); }, 10000);
        function check() { if (peer.iceGatheringState === 'complete') { clearTimeout(timer); peer.removeEventListener('icegatheringstatechange', check); resolve(); } }
        peer.addEventListener('icegatheringstatechange', check); check();
      });
      if (!live()) { cleanupLocal(); return; }
      const response = await fetch('/api/v1/voicelog/live/session', {
        method: 'POST', headers: authHeaders(),
        body: JSON.stringify({ room_id: roomId, sdp: peer.localDescription?.sdp, device: !!atomWifi, timezone: Intl.DateTimeFormat().resolvedOptions().timeZone }),
      });
      const session = await response.json();
      if (!response.ok) throw new Error(session.detail || 'Live 1への接続に失敗しました');
      if (!live()) { cleanupLocal(); return; }
      await peer.setRemoteDescription({ type: 'answer', sdp: session.transport.sdp });
      let timeout: ReturnType<typeof setTimeout> | undefined;
      try { await Promise.race([opened, new Promise<void>((_, reject) => { timeout = setTimeout(() => reject(new Error('Live 1の開始がタイムアウトしました')), 30000); })]); }
      finally { clearTimeout(timeout); }
      if (!live()) { cleanupLocal(); return; }
      setStatus('connected');
      // Live is full duplex. Observe actual audio instead of guessing from backend turns.
      const samples = new Float32Array(1024);
      guardianTimerRef.current = setInterval(() => {
        if (!live() || ending) return;
        greeting.tick();
        const analyser = aiAnalyserRef.current;
        if (!analyser) return;
        analyser.getFloatTimeDomainData(samples);
        const rms = Math.sqrt(samples.reduce((sum, x) => sum + x * x, 0) / samples.length);
        if (rms > .004) { lastOutput = performance.now(); outputPlaying = true; greeting.audio(); }
        else if (performance.now() - lastOutput > 500) outputPlaying = false;
        waiting.update(performance.now(), isWorking(currentWork?.state, workingJobsRef.current),
          outputPlaying || readLevel(micAnalyserRef.current) > .025, started && !ending);
        setSpeaking(outputPlaying);
      }, 100);
    } catch (e) {
      cleanupLocal();
      backend.close();
      if (!live()) return;
      setError(e instanceof Error ? e.message : '接続に失敗しました');
      setStatus('error');
    }
  }, [authHeaders, chatTitle, dcSend, disconnect, executeTool, injectItem, injectSystemAndRespond, roomId, saveTranscript, pushActivity, pushLog]);

  useEffect(() => {
    void connect();
    return () => disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="flex flex-col items-center gap-3 p-4">
      <div className="flex w-full items-center justify-between">
        <span className="text-xs text-muted-foreground">
          音声モード
        </span>
        <button
          type="button"
          onClick={() => {
            disconnect();
            onClose();
          }}
          className="rounded-md p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
          aria-label="音声モードを閉じる"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      <VoiceOrb size={150} getUserLevel={getUserLevel} getAiLevel={getAiLevel} active={status === 'connected'} />

      <div className="min-h-5 text-center text-xs text-muted-foreground">
        {status === 'connecting' && '接続中…'}
        {status === 'error' && <span className="text-destructive">{error}</span>}
        {status === 'connected' && currentActivity && `（${currentActivity}）`}
        {status === 'connected' && !currentActivity && (speaking ? '' : '')}
      </div>

      {activity.length > 0 && (
        <div className="w-full space-y-1 border-t border-border pt-2">
          {activity.map((line, i) => (
            <p key={i} className="truncate text-center text-xs text-muted-foreground">
              {line}
            </p>
          ))}
        </div>
      )}

      {status === 'error' && (
        <button
          type="button"
          onClick={() => void connect()}
          className="rounded-md border border-border px-3 py-1 text-xs text-foreground hover:bg-accent"
        >
          再接続
        </button>
      )}
    </div>
  );
}
