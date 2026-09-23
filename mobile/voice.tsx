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

import { appendLive } from '../frontend/src/components/voice/live-backend';
// RN's global fetch resolves through a JS timer, which pauses off-screen.
// All call requests must use the native transport, including tools and polling.
import { fetch } from 'expo/fetch';
import { LiveGreeting } from '../frontend/src/components/voice/live-greeting';
import { LiveJobs, type LiveJob } from '../frontend/src/components/voice/live-jobs';
import { voiceQuality, voiceTransport } from './voice-quality';
import { startVoiceBackground, stopVoiceBackground, onVoiceEnd, onVoiceTick, markVoiceConnected, playVoiceCue, playAtomVoiceCue, setWorkWaiting, bindRemoteAudio, unbindRemoteAudio, audioEndpointStats, muteExternalAudio, connectAtomAudio } from './voice-background';
import { WorkWaiting, isWorking } from '../frontend/src/components/voice/work-waiting';

type RtEvent = { type: string; [key: string]: unknown };
type Status = 'idle' | 'connecting' | 'connected' | 'ending' | 'error';


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
  const sessionRef = useRef('');
  const cleanupRef = useRef<() => void>(() => {});
  const finishRef = useRef<() => void>(() => {});
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
  const disconnect = useCallback(() => {
    genRef.current++;
    cleanupRef.current(); cleanupRef.current = () => {};
    if (sessionRef.current) void api('live/backend/close', {session_id: sessionRef.current}); sessionRef.current = '';
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
    if (sessionRef.current) void api('live/backend/close', {session_id: sessionRef.current}); sessionRef.current = '';
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
    const buffers = {user: '', assistant: ''};
    const ends = {user: 0, assistant: 0};
    const flushTimers: Partial<Record<'user' | 'assistant', ReturnType<typeof setTimeout>>> = {};
    const flushAt = {user: 0, assistant: 0};
    let nativeTick: {remove: () => void} | undefined;
    let pollJobs: (() => Promise<void>) | undefined;
    let lastPoll = 0;
    let nextDiagnostic = 0;
    let startDeadline = 0;
    let workingJob = false, metering = false;
    let audioTimer: ReturnType<typeof setInterval> | undefined;
    const waiting = new WorkWaiting(setWorkWaiting);
    const measureWaiting = async () => {
      if (metering || !live()) return;
      metering = true;
      try {
        const stats = await pcRef.current?.getStats?.();
        if (!stats || !live()) return;
        const quality = voiceQuality(stats);
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
        if (live()) waiting.update(Date.now(), isWorking(undefined, workingJob), talking, started && !endingRef.current);
      } finally { metering = false; }
    };
    const flush = (role: 'user' | 'assistant') => {
      clearTimeout(flushTimers[role]);
      flushAt[role] = 0;
      const text = buffers[role].trim(); buffers[role] = '';
      if (!text) return;
      dialogue.push({role, text}); if (dialogue.length > 32) dialogue.shift();
      if (role === 'user') latestUserRef.current = text;
      saveTranscript(role, text);
    };
    cleanupRef.current = () => {
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
          }
          buffers[role] += String(message.delta || ''); ends[role] = Number(message.end_ms) || 0;
          if (role === 'user') latestUserRef.current = buffers.user;
          clearTimeout(flushTimers[role]); flushTimers[role] = setTimeout(() => flush(role), 2500);
          flushAt[role] = Date.now() + 2500;
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
      sessionRef.current = sessionId;
      if (!live()) { if (sessionId) void api('live/backend/close', {session_id: sessionId}); return; }
      const sdp = (session.transport as any)?.sdp;
      if (!sessionId || !sdp) throw new Error('Live接続情報がありません');
      await pc.setRemoteDescription({type: 'answer', sdp});
      if (!live()) return;
      if (!started) deadline = setTimeout(() => {
        if (live() && !started) { disconnect(); setError('Liveへの接続がタイムアウトしました'); setStatus('error'); }
      }, 30000);
      startDeadline = Date.now() + 30000;
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
              console.info('DanVoice job_poll_unavailable');
            }
            return;
          }
          if (jobPollUnavailable) {
            jobPollUnavailable = false;
            console.info('DanVoice job_poll_recovered');
          }
          workingJob = ((data.jobs || []) as LiveJob[]).some(job => ['queued','running'].includes(job.state));
          if(workingJob) setCurrentActivity('作業中');
          else setCurrentActivity(null);
          for (const {job,event} of jobs.updates((data.jobs || []) as LiveJob[])) {
            console.info('DanVoice job_event_received',JSON.stringify({job_id:job.id,state:job.state,seq:event.seq,received_at:Date.now()}));
            traceDelivery('job-received',{job_id:job.id,state:job.state,seq:event.seq,kind:event.kind});
            pushActivity(event.text);   // the call itself is fed by the server (results spoken); the screen shows the activity
          }
        } finally { polling = false; }
      };
      if (Platform.OS !== 'android') timer = setInterval(() => { void pollJobs?.(); }, 1500);
    } catch (cause) {
      if (!live()) return;
      disconnect(); setError(cause instanceof Error ? cause.message : String(cause)); setStatus('error');
    }
  }, [api, append, dcSend, disconnect, onClose, pushActivity, roomId, saveTranscript, audioEndpoint]);

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
