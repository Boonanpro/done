import {VoiceOrb} from './voice-orb';
import * as Updates from 'expo-updates';
import {voiceCallStyles as vstyles} from './voice-call-styles';
import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  Animated,
  AppState,
  ActivityIndicator,
  DeviceEventEmitter,
  Easing,
  Modal,
  PermissionsAndroid,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { RTCPeerConnection, mediaDevices } from 'react-native-webrtc';
import { withAudioRecovery } from './voice-sdp';
import { reportLocation } from './location-report';
import InCallManager from 'react-native-incall-manager';
import {useSafeAreaInsets} from 'react-native-safe-area-context';

import { LiveBackend, appendLive, readLiveBackendStream } from '../frontend/src/components/voice/live-backend';
// RN's global fetch resolves through a JS timer, which pauses off-screen.
// All call requests must use the native transport, including tools and polling.
import { fetch } from 'expo/fetch';
import { LiveGreeting } from '../frontend/src/components/voice/live-greeting';
import { LiveJobs, liveJobObservation, type LiveJob } from '../frontend/src/components/voice/live-jobs';
import { explicitCallEnd, needsCallControlReview } from './call-intent';
import { voiceQuality, voiceTransport } from './voice-quality';
import { CallEndGate } from './call-end-gate';
import { startVoiceBackground, stopVoiceBackground, onVoiceEnd, onVoiceTick, markVoiceConnected, playVoiceCue, playAtomVoiceCue, setWorkWaiting, bindRemoteAudio, unbindRemoteAudio, audioEndpointStats, muteExternalAudio, connectAtomAudio } from './voice-background';
import { WorkWaiting, isWorking } from '../frontend/src/components/voice/work-waiting';

type RtEvent = { type: string; [key: string]: unknown };
type Status = 'idle' | 'connecting' | 'connected' | 'ending' | 'error';

const TOOL_LABELS: Record<string, string> = {
  delegate_to_dan: '作業中',
  check_dan_status: '進行確認',
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
};

interface VoiceOverlayProps {
  visible: boolean;
  onClose: () => void;
  roomId: string;
  chatTitle?: string;
  apiBase: string;
  token: string | null;
  expanded?: boolean;
  onMinimize?: () => void;
  onExpand?: () => void;
  audioEndpoint?: 'phone' | 'atom';
}

export function VoiceOverlay({ visible, onClose, roomId, chatTitle, apiBase, token, expanded = true, onMinimize, onExpand, audioEndpoint = 'phone' }: VoiceOverlayProps) {
  const insets = useSafeAreaInsets();
  const [status, setStatus] = useState<Status>('idle');
  const [error, setError] = useState<string | null>(null);
  const [currentActivity, setCurrentActivity] = useState<string | null>(null);
  const [activity, setActivity] = useState<string[]>([]);
  const [elapsed, setElapsed] = useState(0);
  const [muted, setMuted] = useState(false);
  const [audioRoute, setAudioRoute] = useState('');
  const availableRoutes = useRef<string[]>([]);
  const routeBusy = useRef(false);
  const observeRoute = useCallback((event: {selectedAudioDevice?: string; availableAudioDeviceList?: string}) => {
    if (event?.selectedAudioDevice) setAudioRoute(event.selectedAudioDevice);
    try { availableRoutes.current = JSON.parse(event.availableAudioDeviceList || '[]'); } catch {}
  }, []);
  useEffect(() => {
    const listener = DeviceEventEmitter.addListener('onAudioDeviceChanged', observeRoute);
    return () => listener.remove();
  }, [observeRoute]);
  const connectedAtRef = useRef(0);
  const endingRef = useRef(false);

  const pcRef = useRef<any>(null);
  const dcRef = useRef<any>(null);
  const micRef = useRef<any>(null);
  const backgroundLeaseRef = useRef<string | null>(null);
  const mutedRef = useRef(false);
  const genRef = useRef(0);
  const backendRef = useRef<LiveBackend | null>(null);
  const cleanupRef = useRef<() => void>(() => {});
  const finishRef = useRef<() => void>(() => {});
  const roomSlugRef = useRef<string | null>(null);
  const latestUserRef = useRef('');
  // ---- オーブ駆動 ----
  const userLevelRef = useRef(0);
  const aiLevelRef = useRef(0);
  const orbScale = useRef(new Animated.Value(1)).current;
  const cloudOpacity = useRef(new Animated.Value(0.45)).current;
  const cloudSpin = useRef(new Animated.Value(0)).current;

  const pushActivity = useCallback((line: string) => {
    setActivity((a) => [...a, line].slice(-5));
  }, []);

  const authHeaders = useCallback(
    (): Record<string, string> => ({
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    }),
    [token],
  );

  const api = useCallback(
    async (path: string, payload: Record<string, unknown>, timeoutMs?: number): Promise<Record<string, unknown>> => {
      const controller = timeoutMs ? new AbortController() : undefined;
      const deadline = timeoutMs ? setTimeout(() => controller!.abort(), timeoutMs) : undefined;
      try {
        const res = await fetch(`${apiBase}/api/v1/voicelog/${path}`, {
          method: 'POST',
          headers: authHeaders(),
          body: JSON.stringify(payload),
          ...(controller ? {signal: controller.signal} : {}),
        });
        const data = (await res.json().catch(() => ({}))) as Record<string, unknown>;
        if (!res.ok) return { error: String(data.detail || `失敗 (HTTP ${res.status})`) };
        return data;
      } catch (e) {
        return { error: `通信に失敗: ${String(e).slice(0, 120)}` };
      } finally {
        if (deadline) clearTimeout(deadline);
      }
    },
    [apiBase, authHeaders],
  );

  const saveTranscript = useCallback(
    (role: 'user' | 'assistant', content: string) => {
      void api(encodeURIComponent(roomId), { role, content: content.slice(0, 7500) });
    },
    [api, roomId],
  );

  const traceDelivery = useCallback((event: string, extra: Record<string, unknown>) => {
    // Metadata only; keep delivery evidence after Android's log buffer rotates.
    void fetch(`${apiBase}/api/v1/chat/perf`, {method:'POST',headers:authHeaders(),
      body:JSON.stringify({surface:'mobile',event:`voice-${event}`,ms:0,room_id:roomId,
        at:new Date().toISOString(),ua:`updates:${Updates.updateId??'embedded'}`,
        extra:{...extra,muted:mutedRef.current,app_state:AppState?.currentState}})}).catch(()=>undefined);
  },[apiBase,authHeaders,roomId]);
  const dcSend = useCallback((obj: unknown) => {
    const dc = dcRef.current;
    if (dc && dc.readyState === 'open') {
      const event = obj as Record<string, unknown>;
      console.info('DanVoice control_sent', JSON.stringify({at:Date.now(),type:event.type,event_id:event.event_id,
        delegation_id:event.delegation_id,chars:typeof event.content==='string' ? event.content.length : undefined}));
      dc.send(JSON.stringify(obj));
      if(event.type==='session.commentary.append') traceDelivery('result-sent',{
        event_id:event.event_id,delegation_id:event.delegation_id,
        chars:typeof event.content==='string' ? event.content.length : 0});
    }
  }, [traceDelivery]);

  // Live appends are small; full tool records remain with Astra.
  const append = useCallback((kind: 'commentary' | 'thinking', text: string, id: string | null = null) => {
    appendLive(dcSend, kind, text, id);
  }, [dcSend]);
  const injectSystemAndRespond = useCallback((text: string) => append('commentary', text), [append]);
  const injectImages = useCallback((images: string[]) => {
    backendRef.current?.addInput({type: 'message', role: 'user',
      content: images.map(image_url => ({type: 'input_image', image_url}))});
  }, []);

  const needSlug = useCallback((): string | { error: string } => {
    return (
      roomSlugRef.current || {
        error: 'この部屋に紐づく成果物が見つかりません（成果物を作ってから編集を頼んでください）',
      }
    );
  }, []);

  const executeTool = useCallback(
    async (name: string, args: Record<string, unknown>): Promise<Record<string, unknown>> => {
      if (name === 'look_at_screen') {
        return { error: 'モバイル版では画面共有に未対応です。見てほしいものは言葉で説明してもらってください。' };
      }
      if (name === 'enter_voice_standby') {
        finishRef.current();
        return {ok: true};
      }
      if (name === 'delegate_to_dan') {
        return api('command-center', {room_id: roomId, args: {action: 'work', task: args.task}});
      }
      if (name === 'control_dan_task') {
        return api('command-center', {room_id: roomId, args: {...args, action: 'control_job', approval_text: latestUserRef.current}});
      }
      if (name === 'command_center') return api('command-center', {room_id: roomId, args});
      if (name === 'check_dan_status') {
        return api('command-center', {room_id: roomId, args: {action: 'requests'}});
      }
      if (name === 'web_search') {
        const query = String(args.query ?? '').trim();
        if (!query) return { error: 'query が空です' };
        return api('search', { query });
      }
      if (name === 'read_room_history') {
        const limit = Math.min(50, Math.max(1, Number(args.limit) || 30));
        try {
          const res = await fetch(`${apiBase}/api/v1/chat/rooms/${encodeURIComponent(roomId)}/messages?limit=${limit}`, {
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
      if (name === 'get_artifact_state' || name === 'check_contrast') {
        const slug = needSlug();
        if (typeof slug !== 'string') return slug;
        return api('capture', { slug, mode: name === 'check_contrast' ? 'contrast' : 'state' });
      }
      if (name === 'look_at_page') {
        const slug = needSlug();
        if (typeof slug !== 'string') return slug;
        const data = await api('capture', { slug, mode: 'tiles' });
        if (data.error) return data;
        const tiles = (data.tiles as string[]) || [];
        if (!tiles.length) return { error: 'タイルが取得できませんでした' };
        injectImages(tiles);
        return { ok: true, tiles: tiles.length, note: `成果物の全体を${tiles.length}枚の高解像度タイルで添付しました。` };
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
        return data.error ? data : { ok: true, id: args.id, note: 'draftとして保存しました。' };
      }
      if (name === 'list_source_files' || name === 'read_source' || name === 'edit_source' || name === 'write_source') {
        const slug = needSlug();
        if (typeof slug !== 'string') return slug;
        const action =
          name === 'list_source_files' ? 'list' : name === 'read_source' ? 'read' : name === 'edit_source' ? 'edit' : 'write';
        return api('source', {
          action,
          slug,
          file: args.file,
          old_string: args.old_string,
          new_string: args.new_string,
          content: args.content,
        });
      }
      if (name === 'generate_image') {
        const prompt = String(args.prompt ?? '').trim();
        if (!prompt) return { error: 'prompt が空です' };
        void (async () => {
          const data = await api('generate-image', { prompt, size: args.size });
          if (data.error) {
            injectSystemAndRespond(`[システム通知] 画像生成に失敗しました（${String(data.error).slice(0, 150)}）。`);
            return;
          }
          injectSystemAndRespond(
            `[システム通知] 画像が完成しました: ${String(data.url)}\nset_style や edit_source でこのURLを自分で適用してください。`,
          );
        })();
        return { status: 'generating', note: '20〜60秒で完成の通知が届きます。' };
      }
      if (name === 'read_skill') {
        return api('skill', { name: args.name });
      }
      // 動画エディタ（制作ルーム）: 速い車線＝1操作即時コミット / 目＝合成後フレーム
      if (name === 'timeline_state') {
        if (!roomId) return { error: '部屋が特定できません' };
        return api('timeline', { room_id: roomId, action: 'state', outline: args.outline !== false });
      }
      if (name === 'timeline_edit') {
        if (!roomId) return { error: '部屋が特定できません' };
        return api('timeline', {
          room_id: roomId, action: 'edit', op: String(args.op ?? ''), args: (args.args as Record<string, unknown>) ?? {},
          content_id: args.content_id ? String(args.content_id) : undefined,
        });
      }
      if (name === 'timeline_frame') {
        if (!roomId) return { error: '部屋が特定できません' };
        const data = await api('timeline', {
          room_id: roomId, action: 'frame', t: typeof args.t === 'number' ? args.t : undefined,
          content_id: args.content_id ? String(args.content_id) : undefined,
        });
        if (data.error || !data.image) return data.error ? data : { error: 'フレームを取得できませんでした' };
        injectImages([data.image as string]);
        return { ok: true, t: data.t, note: `${Number(data.t).toFixed(1)}秒の合成後フレームを添付しました。` };
      }
      return { error: `未知のツール: ${name}` };
    },
    [api, apiBase, authHeaders, injectImages, injectSystemAndRespond, needSlug, roomId],
  );

  const disconnect = useCallback(() => {
    genRef.current++;
    cleanupRef.current(); cleanupRef.current = () => {};
    backendRef.current?.close(); backendRef.current = null;
    micRef.current?.getTracks().forEach((track: any) => track.stop()); micRef.current = null;
    dcRef.current?.close(); dcRef.current = null;
    pcRef.current?.close(); pcRef.current = null;
    const lease = backgroundLeaseRef.current;
    backgroundLeaseRef.current = null;
    if (lease !== null) { InCallManager.stop(); stopVoiceBackground(lease); }
    setStatus('idle'); setCurrentActivity(null);
  }, []);
  finishRef.current = () => {
    if (endingRef.current) return;
    endingRef.current = true;
    // Capture the native destination before unbind removes the call's route.
    // Do not wait for this query/cue before closing microphone and paid transport.
    const atomEndCue = audioEndpoint === 'atom' ? playAtomVoiceCue('standby', pcRef.current?._pcId) : null;
    genRef.current++;
    setStatus('ending');
    cleanupRef.current(); cleanupRef.current = () => {};
    backendRef.current?.close(); backendRef.current = null;
    micRef.current?.getTracks().forEach((track: any) => track.stop());
    dcRef.current?.close(); pcRef.current?.close();
    // Close network/microphone first; retain the headset route for the end cue.
    let finished = false;
    let cueDeadline: ReturnType<typeof setTimeout>;
    const finish = () => {
      if (finished) return;
      finished = true; clearTimeout(cueDeadline); disconnect(); onClose();
    };
    cueDeadline = setTimeout(finish, 2500);
    void (atomEndCue ?? playVoiceCue('standby')).catch(() => {}).finally(finish);
  };
  useEffect(() => {
    const listener = onVoiceEnd(() => finishRef.current());
    return () => listener.remove();
  }, []);

  const connect = useCallback(async () => {
    disconnect();
    endingRef.current = false; latestUserRef.current = ''; connectedAtRef.current = 0; setElapsed(0); setMuted(false);
    mutedRef.current = false;
    const generation = genRef.current;
    const live = () => generation === genRef.current;
    setStatus('connecting'); setError(null); setActivity([]);
    let sessionId = '';
    // The server may answer this call's delegations itself (its own connection to the Live session): then the phone
    // carries audio only, and a network change no longer loses a request. Decided by the server's reply.
    let serverDelegation = false;
    // The remote audio is always played. Muting it while the server answered a delegation (to hide the speech model's
    // 「確認します」) removed the real-time feel of the call (2026-09-22); a short, varied acknowledgement is wanted instead.
    let remoteTrack: any = null;
    let started = false;
    let atomSettings: {host: string; key: string} | null = null;
    let atomAttached = false;
    let resolveAtom: () => void = () => {};
    let rejectAtom: (error: Error) => void = () => {};
    const atomReady = audioEndpoint === 'atom' ? new Promise<void>((resolve,reject) => {resolveAtom=resolve;rejectAtom=reject;}) : Promise.resolve();
    void atomReady.catch(() => {});
    let atomDeadline: ReturnType<typeof setTimeout> | undefined;
    let polling = false;
    let jobPollUnavailable = false;
    let nextQualityReport = 0;
    let endpointReportPending = false;
    let timer: ReturnType<typeof setInterval> | undefined;
    let deadline: ReturnType<typeof setTimeout> | undefined;
    const dialogue: Array<{role: string; text: string}> = [];
    const jobDelegations = new Map<string,string>();
    const buffers = {user: '', assistant: ''};
    const ends = {user: 0, assistant: 0};
    const flushTimers: Partial<Record<'user' | 'assistant', ReturnType<typeof setTimeout>>> = {};
    const flushAt = {user: 0, assistant: 0};
    let nativeTick: {remove: () => void} | undefined;
    let pollJobs: (() => Promise<void>) | undefined;
    let lastPoll = 0;
    let nextDiagnostic = 0;
    let startDeadline = 0;
    let hasActiveJobs = false, followupEligible = false, userTurn = 0, userLength = 0;
    let currentWork: Record<string,unknown> | null = null;
    let workingJob = false, metering = false;
    let audioTimer: ReturnType<typeof setInterval> | undefined;
    const waiting = new WorkWaiting(setWorkWaiting);
    const callEndGate = new CallEndGate();
    let controlRequest: AbortController | undefined;
    let controlDeadline: ReturnType<typeof setTimeout> | undefined;
    const reviewCallControl = () => {
      if (controlRequest || !sessionId || !live()) return;
      const candidate = callEndGate.takeReview(Date.now());
      if (!candidate || candidate.text.length > 2000) return;
      const controller = new AbortController(); controlRequest = controller;
      controlDeadline = setTimeout(() => controller.abort(), 1200);
      const history = [...dialogue];
      // flush() may already have saved the current utterance. Do not duplicate it.
      if (buffers.user) history.push({role:'user',text:candidate.text});
      void fetch(`${apiBase}/api/v1/voicelog/live/call-control`, {
        method:'POST', headers:authHeaders(), signal:controller.signal,
        body:JSON.stringify({session_id:sessionId,dialogue:history.slice(-8).map(row=>({...row,text:row.text.slice(0,2000)}))}),
      }).then(async response => {
        if (!response.ok) return;
        const result = await response.json();
        if (!live() || controller.signal.aborted) return;
        console.info('DanVoice call_control',JSON.stringify({action:result.action,elapsed_ms:result.elapsed_ms}));
        if (result.action === 'end' && callEndGate.acceptReview(candidate.revision,Date.now())) finishRef.current();
      }).catch(() => {
        // The existing Live/Astra path remains available; no retry or spoken API error.
      }).finally(() => {
        clearTimeout(controlDeadline);
        if (controlRequest === controller) controlRequest = undefined;
      });
    };
    const measureWaiting = async () => {
      if (metering || !live()) return;
      metering = true;
      try {
        const stats = await pcRef.current?.getStats?.();
        if (!stats || !live()) return;
        const quality = voiceQuality(stats);
        const observedAt = Date.now();
        callEndGate.microphone(quality.inputAvailable ? quality.inputLevel : null, observedAt);
        if (callEndGate.shouldEnd(observedAt)) {
          console.info('DanVoice call_end', JSON.stringify({source:'microphone_and_explicit_request',at:observedAt}));
          finishRef.current();
          return;
        }
        reviewCallControl();
        userLevelRef.current = Math.min(1, Math.sqrt(quality.inputLevel) * 1.8);
        aiLevelRef.current = quality.outputLevel < .01 ? 0 : Math.min(1, Math.sqrt(quality.outputLevel) * 1.8);
        const talking = quality.inputLevel > .01 || quality.outputLevel > .01;
        if (Date.now() >= nextQualityReport) {
          console.info('DanVoice transport_quality', JSON.stringify({at:Date.now(), ...quality}));
          nextQualityReport = Date.now() + 5000;
          const peerId = pcRef.current?._pcId;
          if (!endpointReportPending && Number.isInteger(peerId)) {
            endpointReportPending = true;
            // Diagnostics must never hold up mic sampling, barge-in or end detection.
            void audioEndpointStats(peerId).then(endpoint => {
              if (live()) console.info('DanVoice endpoint_quality', JSON.stringify({at:Date.now(), endpoint}));
            }).catch(() => {
              if (live()) console.info('DanVoice endpoint_quality', JSON.stringify({at:Date.now(), endpoint:null}));
            }).finally(() => { endpointReportPending = false; });
          }
        }
        if (live()) waiting.update(Date.now(), isWorking(currentWork?.state, workingJob), talking, started && !endingRef.current);
      } finally { metering = false; }
    };
    const jobObservations = new Map<string,string>();
    const conversation = () => [{type:'message',role:'user',content:[{type:'input_text',text:JSON.stringify({
      current_time:new Date().toISOString(),timezone:Intl.DateTimeFormat().resolvedOptions().timeZone,utterance_final:!buffers.user,
      dialogue:[...dialogue,...Object.entries(buffers).filter(([,text])=>text).map(([role,text])=>({role,text}))]})}]}];
    const flush = (role: 'user' | 'assistant') => {
      clearTimeout(flushTimers[role]);
      flushAt[role] = 0;
      const text = buffers[role].trim(); buffers[role] = '';
      if (!text) return;
      dialogue.push({role, text}); if (dialogue.length > 32) dialogue.shift();
      if (role === 'user') latestUserRef.current = text;
      saveTranscript(role, text);
      if (role === 'user' && live() && explicitCallEnd(text)) {
        console.info('DanVoice explicit_call_end');
        finishRef.current();
        return;
      }
      // When the server owns the delegations it sees the transcript itself (hang-up by the words, follow-ups to the running job);
      // these two app-side requests then only produce a second, identical answer (the postcode was spoken twice on 2026-09-22).
      if (role === 'user' && live() && !serverDelegation) {
        if (needsCallControlReview(text)) {
          backend.delegateSpeech(`call-control-${userTurn}-${userLength}`,userTurn,userLength,() => [
            ...conversation(), {role:'user',content:'直近の発言が今の音声通話を終える依頼か、会話の文脈から確認してください。終了の依頼なら enter_voice_standby を実行してください。引用・否定・作業の停止と区別してください。意図が不明な場合だけ短く確認し、それ以外の判定説明や内部の道具名は発話に返さないでください。この確認のために新しい仕事を開始しないでください。'},
          ]);
        } else if (followupEligible) backend.followupSpeech(userTurn,userLength,conversation);
      }
    };
    cleanupRef.current = () => {
      clearTimeout(controlDeadline); controlRequest?.abort();
      clearTimeout(atomDeadline); rejectAtom(new Error('通話を終了しました'));
      if (pcRef.current?._pcId != null) unbindRemoteAudio(pcRef.current._pcId);
      clearInterval(audioTimer); waiting.close();
      clearInterval(timer); clearTimeout(deadline); flush('user'); flush('assistant');
      nativeTick?.remove();
    };
    const request = async (path: string, payload: Record<string, unknown>) => {
      const result = await api(path, payload);
      if (result.error) throw new Error(String(result.error));
      return result;
    };
    const backend = new LiveBackend(
      async (input,onText) => {
        const startedAt=Date.now();
        const abort=new AbortController();
        const timeout=setTimeout(()=>abort.abort(),40000);
        console.info('DanVoice backend_request',JSON.stringify({at:startedAt,input_chars:JSON.stringify(input).length}));
        try {
          const response=await fetch(`${apiBase}/api/v1/voicelog/live/backend/stream`, {
            method:'POST',headers:authHeaders(),signal:abort.signal,body:JSON.stringify({session_id:sessionId,input}),
          }) as unknown as Response;
          console.info('DanVoice backend_headers',JSON.stringify({at:Date.now(),elapsed_ms:Date.now()-startedAt,status:response.status}));
          if (response.status === 409 && live()) {
            // A lost backend session cannot be repaired by spoken instructions.
            // Close the remaining media connection instead of trapping the user
            // in a call that can talk but cannot perform actions or hang up.
            disconnect();
            setError('作業用の接続が失われたため通話を終了しました。もう一度通話を開始してください。');
            setStatus('error');
            throw new Error('Voice backend session unavailable');
          }
          const result=await readLiveBackendStream(response,onText);
          console.info('DanVoice backend_completed',JSON.stringify({at:Date.now(),elapsed_ms:Date.now()-startedAt}));
          return result;
        } catch(error) {
          console.info('DanVoice backend_failed',JSON.stringify({at:Date.now(),elapsed_ms:Date.now()-startedAt}));
          traceDelivery('backend-failed',{elapsed_ms:Date.now()-startedAt,kind:abort.signal.aborted?'timeout':'request_error'});
          throw error;
        } finally { clearTimeout(timeout); }
      },
      async (name, args, delegationId) => {
        console.info('DanVoice tool', name);
        if (!live()) return {error: 'Call ended'};
        if (name === 'enter_voice_standby' && delegationId.startsWith('call-control-')
            && delegationId !== `call-control-${userTurn}-${userLength}`)
          return {error:'終了確認の後に新しい発言がありました。古い依頼では通話を終了しません。'};
        setCurrentActivity(TOOL_LABELS[name] || null);
        try {
          const result=await executeTool(name, args);
          const receipt=(result as any).receipt;
          if((result as any).accepted && receipt?.id && !delegationId.startsWith('followup-'))
            jobDelegations.set(receipt.id,delegationId);
          return result;
        }
        finally { if (live()) setCurrentActivity(null); }
      },
      (text, id) => { if (live() && (!id.startsWith('call-control-') || id === `call-control-${userTurn}-${userLength}`)) append('commentary', text,
        id.startsWith('followup-') || id.startsWith('call-control-') ? null : id); },
      message => { if (live()) { pushActivity(message); append('commentary', `確認に失敗しました: ${message}`); } },
      () => { if (sessionId) void api('live/backend/close', {session_id: sessionId}); },
      async input => await request('live/backend/steer', {session_id: sessionId, input}) as {accepted: boolean},
      state => {
        currentWork=state;
        traceDelivery('work-state',{state:state.state,tool:state.tool,action:state.action});
        if(live()) setCurrentActivity(state.state==='reasoning' ? '確認中' :
          state.state==='reading' ? (state.tool==='web_search' ? '検索中' : '読み取り中') :
          state.state==='executing' ? '作業中' : null);
      },
    );
    backendRef.current = backend;
    const greeting = new LiveGreeting(dcSend, type => console.info('DanVoice greeting',type));
    const jobs = new LiveJobs();
    try {
      if (Platform.OS === 'android') {
        const permission = PermissionsAndroid.PERMISSIONS.RECORD_AUDIO;
        if (!(await PermissionsAndroid.check(permission))) {
          const result = await PermissionsAndroid.request(permission);
          if (result !== PermissionsAndroid.RESULTS.GRANTED) throw new Error('マイクの使用を許可してください');
        }
      }
      if (Platform.OS === 'android' && Number(Platform.Version) >= 31) {
        const permission = PermissionsAndroid.PERMISSIONS.BLUETOOTH_CONNECT;
        if (!(await PermissionsAndroid.check(permission))) await PermissionsAndroid.request(permission);
      }
      if (!live()) return;
      const lease = await startVoiceBackground();
      if (!live()) { stopVoiceBackground(lease); return; }
      backgroundLeaseRef.current = lease;
      if (audioEndpoint === 'atom') {
        atomSettings = await request('atom-direct', {}) as {host: string; key: string};
        if (!live()) return;
      }
      InCallManager.start({media: 'audio', auto: true});
      (InCallManager.setForceSpeakerphoneOn as (value: boolean | null) => void)(null);
      void InCallManager.chooseAudioRoute('').then(observeRoute).catch(() => {});
      InCallManager.setKeepScreenOn(false);
      const pc: any = new RTCPeerConnection({iceServers: [{urls: 'stun:stun.l.google.com:19302'}]});
      pcRef.current = pc;
      pc.addEventListener('track', (event: any) => {
        if (!live() || event.track?.kind !== 'audio') return;
        remoteTrack = event.track;
        const peerId = event.track._peerConnectionId;
        if (!Number.isInteger(peerId)) return;
        void bindRemoteAudio(peerId, event.track.id).then(bound => {
          if (!live()) unbindRemoteAudio(peerId);
          else {
            console.info('DanVoice remote_audio_bound', bound);
            if (atomSettings && !atomAttached) {
              atomAttached = true;
              if (!bound) throw new Error('Atomの音声処理を準備できませんでした');
              void connectAtomAudio(peerId,atomSettings.host,atomSettings.key).then(() => {
                if (live()) resolveAtom(); else unbindRemoteAudio(peerId);
              }).catch(rejectAtom);
            }
          }
        }).catch(error => {rejectAtom(error);console.warn('DanVoice remote_audio_bind_failed', String(error));});
      });
      // The pinned Android SDK resolves these per-source modes. Atom PCM enters
      // after platform effects, so keep its processing in software. Phone calls
      // can use platform effects with a software fallback when unavailable.
      const captureMode = audioEndpoint === 'atom' ? 'software' : 'automatic';
      const stream = await mediaDevices.getUserMedia({audio: Platform.OS === 'android' ? {
        googEchoCancellation: true, googNoiseSuppression: true,
        echoCancellationMode: captureMode, noiseSuppressionMode: captureMode,
      } as any : true, video: false});
      if (!live()) { stream.getTracks().forEach(track => track.stop()); return; }
      micRef.current = stream;
      nativeTick = onVoiceTick(() => {
        if (!live()) return;
        const now = Date.now();
        void measureWaiting().catch(() => waiting.close());
        if (connectedAtRef.current) setElapsed(Math.floor((now - connectedAtRef.current) / 1000));
        if (now >= nextDiagnostic) {
          console.info('DanVoice background_tick', started); nextDiagnostic = now + 15000;
          void pc.getStats().then((stats: any) => {
            const audio: Record<string,unknown>[]=[];
            stats.forEach((r:any)=>{if(['inbound-rtp','outbound-rtp','media-source'].includes(r.type) && (r.kind==='audio'||r.mediaType==='audio')) {
              const row:Record<string,unknown>={};
              for(const key of ['type','packetsSent','packetsReceived','packetsLost','bytesSent','bytesReceived','audioLevel','totalAudioEnergy','totalSamplesDuration','jitter']) if(r[key]!==undefined) row[key]=r[key];
              audio.push(row);
            }});
            return fetch(`${apiBase}/api/v1/chat/perf`,{method:'POST',headers:authHeaders(),body:JSON.stringify({surface:'mobile',event:'voice-health',ms:now-(connectedAtRef.current||now),room_id:roomId,at:new Date().toISOString(),ua:`updates:${Updates.updateId??'embedded'}`,extra:{connection:pc.connectionState,ice:pc.iceConnectionState,channel:dcRef.current?.readyState,started,audio,transport:voiceTransport(stats)}})});
          }).catch(()=>undefined);
        }
        for (const role of ['user','assistant'] as const) if (flushAt[role] && now >= flushAt[role]) flush(role);
        if (!live()) return;
        if (startDeadline && !started && now >= startDeadline) {
          disconnect(); setError('Liveへの接続がタイムアウトしました'); setStatus('error'); return;
        }
        if (now - lastPoll >= 1500) { lastPoll = now; void pollJobs?.(); }
      });
      stream.getTracks().forEach(track => {if (audioEndpoint === 'atom') track.enabled = false; pc.addTrack(track, stream);});
      if (Platform.OS !== 'android') audioTimer = setInterval(() => { void measureWaiting().catch(() => waiting.close()); }, 200);
      const dc = pc.createDataChannel('oai-events'); dcRef.current = dc;
      dc.addEventListener('message', (event: any) => {
        if (!live()) return;
        let message: any; try { message = JSON.parse(event.data); } catch { return; }
        if (!message.type?.includes('transcript.delta')) console.info('DanVoice event', JSON.stringify({at:Date.now(),
          type:message.type,client_event_id:message.client_event_id,start_ms:message.start_ms,end_ms:message.end_ms,
          error:message.error ? {type:message.error.type,code:message.error.code,event_id:message.error.event_id} : undefined}));
        greeting.observe(message);
        // responses delegation: the backend model's final message is what gets spoken; release the hold when it is done
        if(message.type==='session.commentary.appended') { traceDelivery('result-ack',{
          event_id:message.client_event_id,start_ms:message.start_ms,end_ms:message.end_ms}); }
        if (message.type === 'session.started') {
          sessionId = message.session?.id || sessionId; started = true;
          clearTimeout(deadline);
          atomDeadline = setTimeout(() => rejectAtom(new Error('Atomへの音声接続がタイムアウトしました')), 10000);
          dcSend({type:'session.instructions.append',event_id:`mobile-clock-${Date.now()}`,delegation_id:null,
            content:`端末の現在日時は ${new Date().toLocaleString('ja-JP')} (${Intl.DateTimeFormat().resolvedOptions().timeZone})。この日時は既知の情報として答えられます。`});
          void atomReady.then(async () => {
            clearTimeout(atomDeadline);
            if (!live()) return;
            if (audioEndpoint === 'atom') {
              micRef.current?.getAudioTracks().forEach((track: any) => { track.enabled = !mutedRef.current; });
              if (pcRef.current?._pcId != null) muteExternalAudio(pcRef.current._pcId, mutedRef.current);
            }
            setStatus('connected'); connectedAtRef.current = Date.now(); markVoiceConnected();
            await (audioEndpoint === 'atom' ? playAtomVoiceCue('ready', pcRef.current?._pcId) : playVoiceCue('ready')).catch(() => {});
            if (live() && !latestUserRef.current) greeting.start(`mobile-greeting-${Date.now()}`);
          }).catch(error => {
            if (!live()) return;
            disconnect(); setError(error instanceof Error ? error.message : 'Atomに接続できませんでした'); setStatus('error');
          });
        } else if (message.type === 'session.closed') {
          finishRef.current();
        } else if (message.type === 'error') {
          const detail = String(message.error?.message || '音声接続エラー');
          if (!started) { disconnect(); setError(detail); setStatus('error'); }
          else pushActivity(detail);
        } else if (['session.input_transcript.delta', 'session.output_transcript.delta'].includes(message.type)) {
          waiting.speech(Date.now());
          const role = message.type.includes('input_') ? 'user' : 'assistant';
          if (!buffers[role]) {
            console.info('DanVoice speech',JSON.stringify({at:Date.now(),role,start_ms:message.start_ms}));
            traceDelivery('speech-start',{role,start_ms:message.start_ms});
          }
          if (buffers[role] && Number(message.start_ms) - ends[role] > 1600) flush(role);
          if (role === 'user') {
            if (!buffers.user) {
              userTurn++;userLength=0;followupEligible=hasActiveJobs;
              if(currentWork && currentWork.state!=='complete' && (currentWork.state!=='executing' || hasActiveJobs)) append('thinking',JSON.stringify({current_work:currentWork}));
              for(const observation of jobObservations.values()) append('thinking',observation);
            }
            userLength += String(message.delta || '').length;
          }
          buffers[role] += String(message.delta || ''); ends[role] = Number(message.end_ms) || 0;
          if (role === 'user') callEndGate.transcript(buffers.user, Date.now());
          if (role === 'user') latestUserRef.current = buffers.user;
          clearTimeout(flushTimers[role]); flushTimers[role] = setTimeout(() => flush(role), 2500);
          flushAt[role] = Date.now() + 2500;
        } else if (message.type === 'session.delegation.created') {
          const id = message.delegation?.id;
          if (id && !serverDelegation) backend.delegateSpeech(id,userTurn,userLength, () => [{type: 'message', role: 'user', content: [{type: 'input_text',
            text: JSON.stringify({current_time:new Date().toISOString(),timezone:Intl.DateTimeFormat().resolvedOptions().timeZone,utterance_final:!buffers.user,dialogue: [...dialogue, ...Object.entries(buffers).filter(([,text]) => text).map(([role,text]) => ({role,text}))], request: message.request})}]}]);
        }
      });
      pc.addEventListener('connectionstatechange', () => {
        void fetch(`${apiBase}/api/v1/chat/perf`,{method:'POST',headers:authHeaders(),body:JSON.stringify({surface:'mobile',event:'voice-connection',ms:0,room_id:roomId,at:new Date().toISOString(),ua:`updates:${Updates.updateId??'embedded'}`,extra:{connection:pc.connectionState,ice:pc.iceConnectionState}})}).catch(()=>undefined);
        if (live() && pc.connectionState === 'failed') {
          disconnect(); setError('音声接続が切れました。再接続してください。'); setStatus('error');
        }
      });
      const offer = await pc.createOffer({});
      offer.sdp = withAudioRecovery(offer.sdp);
      await pc.setLocalDescription(offer);
      await new Promise<void>(resolve => {
        if (pc.iceGatheringState === 'complete') return resolve();
        const timeout = setTimeout(resolve, 10000);
        pc.addEventListener('icegatheringstatechange', () => {
          if (pc.iceGatheringState === 'complete') { clearTimeout(timeout); resolve(); }
        });
      });
      if (!live()) return;
      const session = await request('live/session', {room_id: roomId, sdp: pc.localDescription?.sdp, provider: 'openai', device: true, timezone: Intl.DateTimeFormat().resolvedOptions().timeZone, server_delegation: true});
      sessionId = String((session.session as any)?.id || '');
      serverDelegation = (session as any).server_delegation === true;
      if (!live()) { if (sessionId) void api('live/backend/close', {session_id: sessionId}); return; }
      const sdp = (session.transport as any)?.sdp;
      if (!sessionId || !sdp) throw new Error('Live接続情報がありません');
      await pc.setRemoteDescription({type: 'answer', sdp});
      if (!live()) return;
      if (!started) deadline = setTimeout(() => {
        if (live() && !started) { disconnect(); setError('Liveへの接続がタイムアウトしました'); setStatus('error'); }
      }, 30000);
      startDeadline = Date.now() + 30000;
      void api('room-artifact', {room_id: roomId}).then(data => { if (live()) roomSlugRef.current = (data.slug as string) || null; });
      pollJobs = async () => {
        if (!live() || !started) return;
        greeting.tick();
        if (polling) return;
        polling = true;
        try {
          const data = await api('command-center', {room_id: roomId, args: {action: 'jobs'}}, 5000);
          if (!live()) return;
          if (data.error || !Array.isArray(data.jobs)) {
            if (!jobPollUnavailable) {
              jobPollUnavailable = true;
              pushActivity('仕事の状況を取得できません。再接続を試しています');
              backend.addInput({type: 'message', role: 'user', content: [{type: 'input_text', text: JSON.stringify({type:'job_status_connection',available:false})}]});
              console.info('DanVoice job_poll_unavailable');
            }
            return;
          }
          if (jobPollUnavailable) {
            jobPollUnavailable = false;
            backend.addInput({type: 'message', role: 'user', content: [{type: 'input_text', text: JSON.stringify({type:'job_status_connection',available:true})}]});
            console.info('DanVoice job_poll_recovered');
          }
          hasActiveJobs = ((data.jobs || []) as LiveJob[]).some(job => !['completed','failed','cancelled'].includes(job.state));
          workingJob = ((data.jobs || []) as LiveJob[]).some(job => ['queued','running'].includes(job.state));
          if(workingJob) setCurrentActivity('作業中');
          else if(currentWork?.state==='complete' || currentWork?.state==='executing') setCurrentActivity(null);
          for (const {job,event} of jobs.updates((data.jobs || []) as LiveJob[])) {
            console.info('DanVoice job_event_received',JSON.stringify({job_id:job.id,state:job.state,seq:event.seq,received_at:Date.now()}));
            traceDelivery('job-received',{job_id:job.id,state:job.state,seq:event.seq,kind:event.kind});
            pushActivity(event.text);
            if (serverDelegation) continue;   // the server's sideband feeds the call itself (progress silent, results spoken)
            const text = JSON.stringify({job_id: job.id, task: job.task, state: job.state, confirmation: job.confirmation, event});
            backend.addInput({type: 'message', role: 'user', content: [{type: 'input_text', text}]});
              const observation = liveJobObservation(job,event);
              if(observation.kind==='commentary') {jobObservations.delete(job.id);append('commentary',observation.text,jobDelegations.get(job.id) || null);}
              else jobObservations.set(job.id,observation.text);
          }
        } finally { polling = false; }
      };
      if (Platform.OS !== 'android') timer = setInterval(() => { void pollJobs?.(); }, 1500);
    } catch (cause) {
      if (!live()) return;
      disconnect(); setError(cause instanceof Error ? cause.message : String(cause)); setStatus('error');
    }
  }, [api, append, dcSend, disconnect, executeTool, onClose, pushActivity, roomId, saveTranscript, audioEndpoint]);

  // ---- 音量ポーリング（getStats の audioLevel）→ オーブ駆動 ----
  useEffect(() => {
    if (status !== 'connected') return;
    const timer = setInterval(() => {
      Animated.timing(orbScale, {
        toValue: 1 + userLevelRef.current * 0.22,
        duration: 120,
        easing: Easing.out(Easing.quad),
        useNativeDriver: true,
      }).start();
      Animated.timing(cloudOpacity, {
        toValue: 0.45 + aiLevelRef.current * 0.45,
        duration: 150,
        useNativeDriver: true,
      }).start();
    }, 150);
    return () => clearInterval(timer);
  }, [status, orbScale, cloudOpacity]);

  // 雲のゆっくりした周回（常時）
  useEffect(() => {
    const loop = Animated.loop(
      Animated.timing(cloudSpin, { toValue: 1, duration: 9000, easing: Easing.linear, useNativeDriver: true }),
    );
    loop.start();
    return () => loop.stop();
  }, [cloudSpin]);

  useEffect(() => {
    if (visible) { if (token) void reportLocation(apiBase, token, true); void connect(); }
    else disconnect();
    return () => disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible]);

  const spin = cloudSpin.interpolate({ inputRange: [0, 1], outputRange: ['0deg', '360deg'] });
  const spinRev = cloudSpin.interpolate({ inputRange: [0, 1], outputRange: ['360deg', '0deg'] });

  const duration = `${Math.floor(elapsed / 60)}:${String(elapsed % 60).padStart(2, '0')}`;
  const label = status === 'connecting' ? '接続中…' : status === 'ending' ? '通話を終了しています' : status === 'error' ? '接続できませんでした' : '通話中';
  const toggleMute = () => {
    if (status !== 'connected') return;
    const next = !muted; setMuted(next);
    mutedRef.current = next;
    if (pcRef.current?._pcId != null) muteExternalAudio(pcRef.current._pcId, next);
    micRef.current?.getAudioTracks().forEach((track: any) => {track.enabled = !next;});
  };
  const speakerOn = audioRoute === 'SPEAKER_PHONE';
  const toggleSpeaker = async () => {
    if (routeBusy.current || status !== 'connected') return;
    const target = speakerOn
      ? ['BLUETOOTH','WIRED_HEADSET','EARPIECE'].find(route => availableRoutes.current.includes(route))
      : 'SPEAKER_PHONE';
    if (!target) { pushActivity('切り替え先のイヤホン・受話口が見つかりません'); return; }
    routeBusy.current = true;
    try {
      observeRoute(await InCallManager.chooseAudioRoute(target));
      console.info('DanVoice route_requested',target);
    } catch { pushActivity('音声の出力先を切り替えられませんでした'); }
    finally { routeBusy.current = false; }
  };
  if (!visible) return null;
  if (!expanded) return <View style={[vstyles.mini, {paddingTop:insets.top+8}]}>
    <Pressable accessibilityRole="button" accessibilityLabel="通話画面を開く" onPress={onExpand} style={vstyles.miniMain}>
      <Ionicons name="call" size={20} color="#9de5ca" />
      <View style={{flex:1}}><Text style={vstyles.miniTitle} numberOfLines={1}>{chatTitle || 'Dan'}</Text></View>
      <Text style={vstyles.timer}>{duration}</Text>
    </Pressable>
    <Pressable accessibilityRole="button" accessibilityLabel="通話を終了" onPress={() => finishRef.current()} style={vstyles.miniEnd}>
      <Ionicons name="call" size={20} color="#ffaaaa" style={{transform:[{rotate:'135deg'}]}} />
    </Pressable>
  </View>;
  return (
    <Modal visible={visible} animationType="fade" onRequestClose={onMinimize || (() => finishRef.current())} statusBarTranslucent>
      <View style={vstyles.backdrop}>
        <View style={[vstyles.panel,{paddingTop:insets.top+12,paddingBottom:insets.bottom+24}]}>
          <View style={vstyles.header}>
            <Pressable accessibilityRole="button" accessibilityLabel="通話を続けたまま小さくする" onPress={onMinimize} style={vstyles.headerButton}>
              <Ionicons name="chevron-down" size={26} color="#d9d2c8" />
            </Pressable>
            <View accessibilityLabel={label} accessibilityRole="text">
              {status === 'connecting' || status === 'ending' ? <ActivityIndicator size="small" color="#c7d1cc"/> :
                <Ionicons name={status === 'error' ? 'alert-circle-outline' : 'call'} size={16} color={status === 'error' ? '#ffaaaa' : '#9de5ca'}/>}
            </View>
            <Text style={vstyles.timer}>{status === 'connected' || status === 'ending' ? duration : '—:—'}</Text>
          </View>
          <View style={vstyles.centerArea}>
            <Text style={vstyles.callTitle}>Dan</Text>
            {!!chatTitle && chatTitle !== 'Done' && <Text style={vstyles.roomTitle} numberOfLines={2}>{chatTitle}</Text>}
            <VoiceOrb muted={muted} scale={orbScale} opacity={cloudOpacity} spin={spin} spinRev={spinRev}/>
            {status === 'connected' && !!currentActivity && <Text accessibilityLiveRegion="polite" style={vstyles.statusText} numberOfLines={1}>{currentActivity}</Text>}
            {status === 'error' && <Text style={vstyles.statusText}>{error}</Text>}
            {status === 'error' && <Pressable accessibilityRole="button" style={vstyles.retryButton} onPress={() => void connect()}><Text style={vstyles.retryText}>再接続</Text></Pressable>}
          </View>
          <View style={vstyles.controls}>
            {audioEndpoint !== 'atom' && <View style={vstyles.controlItem}><Pressable accessibilityRole="button" accessibilityLabel={speakerOn ? 'スピーカーをオフ' : 'スピーカーをオン'} accessibilityState={{selected:speakerOn,disabled:status !== 'connected'}} disabled={status !== 'connected'} onPress={() => void toggleSpeaker()} style={[vstyles.controlButton,speakerOn && {backgroundColor:'#e4e9e5'},status !== 'connected' && {opacity:0.4}]}>
              <Ionicons name={speakerOn ? 'volume-high' : ['BLUETOOTH','WIRED_HEADSET'].includes(audioRoute) ? 'headset-outline' : 'ear-outline'} size={26} color={speakerOn ? '#15251f' : '#e4e9e5'} />
            </Pressable></View>}
            <View style={vstyles.controlItem}><Pressable accessibilityRole="button" accessibilityLabel={muted ? 'ミュート解除' : 'マイクをミュート'} accessibilityState={{selected:muted}} onPress={toggleMute} style={[vstyles.controlButton,muted && {backgroundColor:'#e4e9e5'}]}>
              <Ionicons name={muted ? 'mic-off' : 'mic'} size={26} color={muted ? '#15251f' : '#e4e9e5'} />
            </Pressable></View>
            <View style={vstyles.controlItem}><Pressable accessibilityRole="button" accessibilityLabel="通話を終了" onPress={() => finishRef.current()} disabled={status === 'ending'} style={[vstyles.controlButton,{backgroundColor:'#b74d4d'}]}>
              <Ionicons name="call" size={27} color="#fff" style={{transform:[{rotate:'135deg'}]}} />
            </Pressable></View>
          </View>
        </View>
      </View>
    </Modal>
  );
}
