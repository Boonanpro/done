/**
 * チャット統合音声モード — モバイル版（正規ルート移植）。
 *
 * Web版 voice-session.tsx で実測検証済みの機構を React Native に移植:
 *   - OpenAI Realtime へ WebRTC 直結（react-native-webrtc）
 *   - 応答スケジューラ + guardian（沈黙の自動復旧）+ レート制限バックオフ
 *   - 会話ダイエット（古いツール結果の自動削除）/ コストメーター
 *   - 文字起こしを部屋の履歴へ保存（部屋=共有記憶）
 *   - 委譲はコアのトンネルへ wss 直結（Vercel は WS を通さないため /voicelog/config で取得）
 *   - 成果物編集ツールはサーバー実行のまま流用。対象slugは /voicelog/room-artifact で解決
 *   - look_at_screen（画面共有）のみモバイル未対応
 *
 * オーブ: 中心固定・ユーザー声=音量メーターで膨張収縮・AI声=内部の雲の揺らめき。
 * 音量は RTCPeerConnection.getStats() の audioLevel（media-source=マイク / inbound-rtp=AI）。
 */
import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  Animated,
  Easing,
  Modal,
  Pressable,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { RTCPeerConnection, mediaDevices } from 'react-native-webrtc';
import InCallManager from 'react-native-incall-manager';

const OPENAI_CALLS_URL = 'https://api.openai.com/v1/realtime/calls';

type RtEvent = { type: string; [key: string]: unknown };
type Status = 'idle' | 'connecting' | 'connected' | 'error';

const TOOL_LABELS: Record<string, string> = {
  delegate_to_dan: 'ダンモードで作業中',
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
}

export function VoiceOverlay({ visible, onClose, roomId, chatTitle, apiBase, token }: VoiceOverlayProps) {
  const [status, setStatus] = useState<Status>('idle');
  const [error, setError] = useState<string | null>(null);
  const [currentActivity, setCurrentActivity] = useState<string | null>(null);
  const [activity, setActivity] = useState<string[]>([]);
  const [sessionCost, setSessionCost] = useState(0);

  const pcRef = useRef<any>(null);
  const dcRef = useRef<any>(null);
  const micRef = useRef<any>(null);
  const delegateWsRef = useRef<WebSocket | null>(null);
  const genRef = useRef(0);

  const responseActiveRef = useRef(false);
  const pendingResponseRef = useRef(false);
  const responseTickRef = useRef(0);
  const pendingItemsRef = useRef<unknown[]>([]);
  const lastDcEventAtRef = useRef(0);
  const guardianTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const cooldownUntilRef = useRef(0);
  const lastImageItemIdsRef = useRef<string[]>([]);
  const toolOutputItemsRef = useRef<Array<{ id: string; size: number }>>([]);
  const delegatingRef = useRef(false);
  const danActivityRef = useRef<string[]>([]);
  const earlyTextRef = useRef('');
  const earlyInjectedRef = useRef(false);
  const roomSlugRef = useRef<string | null>(null);

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
    async (path: string, payload: Record<string, unknown>): Promise<Record<string, unknown>> => {
      try {
        const res = await fetch(`${apiBase}/api/v1/voicelog/${path}`, {
          method: 'POST',
          headers: authHeaders(),
          body: JSON.stringify(payload),
        });
        const data = (await res.json().catch(() => ({}))) as Record<string, unknown>;
        if (!res.ok) return { error: String(data.detail || `失敗 (HTTP ${res.status})`) };
        return data;
      } catch (e) {
        return { error: `通信に失敗: ${String(e).slice(0, 120)}` };
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

  const dcSend = useCallback((obj: unknown) => {
    const dc = dcRef.current;
    if (dc && dc.readyState === 'open') dc.send(JSON.stringify(obj));
  }, []);

  const flushPendingItems = useCallback(() => {
    const items = pendingItemsRef.current.splice(0);
    for (const item of items) dcSend(item);
  }, [dcSend]);

  const injectItem = useCallback(
    (item: unknown) => {
      if (responseActiveRef.current) pendingItemsRef.current.push(item);
      else dcSend(item);
    },
    [dcSend],
  );

  const scheduleResponse = useCallback(() => {
    if (responseActiveRef.current || Date.now() < cooldownUntilRef.current) {
      pendingResponseRef.current = true;
      return;
    }
    flushPendingItems();
    responseActiveRef.current = true;
    dcSend({ type: 'response.create' });
    const tick = responseTickRef.current;
    setTimeout(() => {
      if (responseTickRef.current !== tick) return;
      if (!dcRef.current || dcRef.current.readyState !== 'open') return;
      responseActiveRef.current = true;
      dcSend({ type: 'response.create' });
    }, 6000);
  }, [dcSend, flushPendingItems]);

  const injectSystemAndRespond = useCallback(
    (text: string) => {
      injectItem({
        type: 'conversation.item.create',
        item: { type: 'message', role: 'user', content: [{ type: 'input_text', text }] },
      });
      scheduleResponse();
    },
    [injectItem, scheduleResponse],
  );

  const injectImages = useCallback(
    (images: string[]) => {
      for (const oldId of lastImageItemIdsRef.current) {
        injectItem({ type: 'conversation.item.delete', item_id: oldId });
      }
      const ids: string[] = [];
      images.forEach((img, i) => {
        const id = `item_img_${Date.now()}_${i}`;
        ids.push(id);
        injectItem({
          type: 'conversation.item.create',
          item: { id, type: 'message', role: 'user', content: [{ type: 'input_image', image_url: img }] },
        });
      });
      lastImageItemIdsRef.current = ids;
    },
    [injectItem],
  );

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
      if (name === 'delegate_to_dan') {
        const task = String(args.task ?? '').trim();
        if (!task) return { error: 'task が空です' };
        const ws = delegateWsRef.current;
        if (!ws || ws.readyState !== WebSocket.OPEN) {
          return { error: '深い作業モードへの接続がありません（トンネル未接続）。' };
        }
        if (delegatingRef.current) return { error: '別の作業が進行中です。完了を待ってください。' };
        ws.send(JSON.stringify({ type: 'delegate', task, room_id: roomId }));
        delegatingRef.current = true;
        danActivityRef.current = [];
        earlyTextRef.current = '';
        earlyInjectedRef.current = false;
        return { status: 'delegated', note: '深い作業モードで実行を始めました。数分かかることがあります。' };
      }
      if (name === 'check_dan_status') {
        return {
          running: delegatingRef.current,
          recent_activity: danActivityRef.current.slice(-6),
          note: delegatingRef.current ? '作業中です。完了すると通知が届きます。' : '進行中の作業はありません。',
        };
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
            text: String(m.content || '').slice(0, 200),
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
      return { error: `未知のツール: ${name}` };
    },
    [api, apiBase, authHeaders, injectImages, injectSystemAndRespond, needSlug, roomId],
  );

  const disconnect = useCallback(() => {
    genRef.current += 1;
    try {
      dcRef.current?.close();
    } catch {}
    dcRef.current = null;
    try {
      pcRef.current?.close();
    } catch {}
    pcRef.current = null;
    try {
      delegateWsRef.current?.close();
    } catch {}
    delegateWsRef.current = null;
    if (guardianTimerRef.current) {
      clearInterval(guardianTimerRef.current);
      guardianTimerRef.current = null;
    }
    pendingItemsRef.current = [];
    try {
      micRef.current?.getTracks().forEach((t: any) => t.stop());
    } catch {}
    micRef.current = null;
    try {
      InCallManager.stop();
    } catch {}
    setCurrentActivity(null);
    setStatus((s) => (s === 'error' ? 'error' : 'idle'));
  }, []);

  const connect = useCallback(async () => {
    disconnect();
    genRef.current += 1;
    const myGen = genRef.current;
    const live = () => genRef.current === myGen;

    setStatus('connecting');
    setError(null);
    setActivity([]);
    responseActiveRef.current = false;
    pendingResponseRef.current = false;
    pendingItemsRef.current = [];
    lastImageItemIdsRef.current = [];
    toolOutputItemsRef.current = [];
    cooldownUntilRef.current = 0;
    delegatingRef.current = false;

    const handledCalls = new Set<string>();

    const handleFunctionCall = async (item: { name?: string; call_id?: string; arguments?: string }) => {
      if (!item.name || !item.call_id || handledCalls.has(item.call_id)) return;
      handledCalls.add(item.call_id);
      let args: Record<string, unknown> = {};
      try {
        args = JSON.parse(item.arguments || '{}');
      } catch {}
      setCurrentActivity(TOOL_LABELS[item.name] || item.name);
      pushActivity(`🔧 ${TOOL_LABELS[item.name] || item.name}`);
      const result = await executeTool(item.name, args);
      setCurrentActivity(null);
      const output = JSON.stringify(result);
      const outputItemId = `item_out_${Date.now()}_${Math.floor(Math.random() * 1e4)}`;
      dcSend({
        type: 'conversation.item.create',
        item: { id: outputItemId, type: 'function_call_output', call_id: item.call_id, output },
      });
      toolOutputItemsRef.current.push({ id: outputItemId, size: output.length });
      const items = toolOutputItemsRef.current;
      let total = items.reduce((a, x) => a + x.size, 0);
      while (items.length > 3 && (total > 24_000 || items.length > 8)) {
        const oldest = items.shift()!;
        total -= oldest.size;
        injectItem({ type: 'conversation.item.delete', item_id: oldest.id });
      }
      scheduleResponse();
    };

    const handleRtEvent = (msg: RtEvent) => {
      switch (msg.type) {
        case 'response.created':
          responseActiveRef.current = true;
          responseTickRef.current += 1;
          break;
        case 'conversation.item.input_audio_transcription.completed': {
          const t = ((msg.transcript as string) || '').trim();
          if (t) saveTranscript('user', t);
          break;
        }
        case 'response.output_audio_transcript.done':
        case 'response.audio_transcript.done': {
          const t = ((msg.transcript as string) || '').trim();
          if (t) saveTranscript('assistant', t);
          break;
        }
        case 'response.output_item.done': {
          const item = msg.item as { type?: string; name?: string; call_id?: string; arguments?: string };
          if (item?.type === 'function_call') void handleFunctionCall(item);
          break;
        }
        case 'response.done': {
          responseActiveRef.current = false;
          const response =
            (msg.response as { output?: unknown[]; status?: string; status_details?: unknown; usage?: Record<string, unknown> }) || {};
          if (response.status && response.status !== 'completed') {
            const details = JSON.stringify(response.status_details ?? {});
            if (details.includes('rate_limit_exceeded')) {
              const m = details.match(/try again in ([\d.]+)s/);
              const waitMs = m ? Math.ceil(parseFloat(m[1]) * 1000) + 800 : 8000;
              cooldownUntilRef.current = Date.now() + waitMs;
              setTimeout(() => {
                if (dcRef.current?.readyState === 'open') scheduleResponse();
              }, waitMs + 200);
            }
          }
          const u = response.usage as
            | {
                input_token_details?: { text_tokens?: number; audio_tokens?: number; image_tokens?: number; cached_tokens?: number };
                output_token_details?: { text_tokens?: number; audio_tokens?: number };
              }
            | undefined;
          if (u) {
            const i = u.input_token_details || {};
            const o = u.output_token_details || {};
            const cached = i.cached_tokens || 0;
            const freshText = Math.max(0, (i.text_tokens || 0) + (i.image_tokens || 0) - cached);
            const usd =
              (freshText * 4 + cached * 0.4 + (i.audio_tokens || 0) * 32 + (o.text_tokens || 0) * 16 + (o.audio_tokens || 0) * 64) /
              1_000_000;
            if (usd > 0) setSessionCost((c) => c + usd);
          }
          for (const raw of response.output || []) {
            const item = raw as { type?: string; name?: string; call_id?: string; arguments?: string };
            if (item.type === 'function_call') void handleFunctionCall(item);
          }
          if (pendingResponseRef.current) {
            pendingResponseRef.current = false;
            scheduleResponse();
          }
          break;
        }
      }
    };

    const danActivity = (line: string) => {
      danActivityRef.current = [...danActivityRef.current, line].slice(-6);
    };
    const handleDelegateMsg = (data: RtEvent) => {
      switch (data.type) {
        case 'delegate_started':
          delegatingRef.current = true;
          earlyTextRef.current = '';
          earlyInjectedRef.current = false;
          setCurrentActivity('深い作業モードで実行中');
          pushActivity('📋 深い作業モードを開始');
          break;
        case 'reasoning':
          danActivity(`思考: ${String(data.text || '').slice(0, 60)}`);
          break;
        case 'tool_use':
          danActivity(`ツール: ${String(data.name || 'tool')}`);
          pushActivity(`⚙ ${String(data.name || 'tool')}`);
          break;
        case 'text': {
          const chunk = String(data.text || '');
          danActivity(`発言: ${chunk.slice(0, 60)}`);
          earlyTextRef.current = `${earlyTextRef.current}${chunk}\n`;
          if (!earlyInjectedRef.current && earlyTextRef.current.trim().length >= 60) {
            earlyInjectedRef.current = true;
            injectSystemAndRespond(
              `[途中経過] 深い作業モードからの報告（まだ完了ではない）:\n${earlyTextRef.current.slice(0, 1500)}\n\n役立つ内容なら要点を短く伝えてよい。`,
            );
          }
          break;
        }
        case 'result': {
          delegatingRef.current = false;
          setCurrentActivity(null);
          pushActivity('✅ 作業完了');
          injectSystemAndRespond(
            `[システム通知] 作業が完了しました。完了報告:\n${String(data.text || '').slice(0, 4000)}\n\n要点を短く報告してください。`,
          );
          break;
        }
        case 'error':
          delegatingRef.current = false;
          setCurrentActivity(null);
          injectSystemAndRespond(`[システム通知] 作業でエラー: ${String(data.message || '').slice(0, 200)}`);
          break;
      }
    };

    try {
      // 0) 部屋の成果物slug + 委譲WSの接続先を解決
      void api('room-artifact', { room_id: roomId }).then((d) => {
        if (typeof d.slug === 'string') roomSlugRef.current = d.slug;
      });
      const cfg = await api('config', {});

      // 1) セッション発行
      const sess = await api('session', { chat_title: chatTitle ?? null, room_id: roomId });
      if (!live()) return;
      if (sess.error || !sess.value) throw new Error(String(sess.error || 'セッション発行に失敗'));

      // 2) 委譲WS（トンネル直結・非致命）
      if (typeof cfg.delegate_ws === 'string' && cfg.delegate_ws) {
        try {
          const ws = new WebSocket(cfg.delegate_ws);
          await new Promise<void>((resolve, reject) => {
            const to = setTimeout(() => reject(new Error('timeout')), 12000);
            ws.onopen = () => ws.send(JSON.stringify({ type: 'auth', token: token || '' }));
            ws.onmessage = (e) => {
              let data: RtEvent;
              try {
                data = JSON.parse(String(e.data));
              } catch {
                return;
              }
              if (data.type === 'auth_success') {
                clearTimeout(to);
                resolve();
                return;
              }
              handleDelegateMsg(data);
            };
            ws.onerror = () => {
              clearTimeout(to);
              reject(new Error('ws error'));
            };
          });
          delegateWsRef.current = ws;
        } catch {
          pushActivity('⚠ 深い作業モードに接続できません');
        }
      }
      if (!live()) return;

      // 3) WebRTC
      InCallManager.start({ media: 'audio' });
      InCallManager.setForceSpeakerphoneOn(true);
      const pc = new RTCPeerConnection({});
      // Android の WebRTC は通話ストリーム扱いで音が小さい。受信トラックの
      // 出力ゲインを引き上げる（_setVolume は react-native-webrtc の拡張。1.0=等倍）。
      (pc as any).ontrack = (e: any) => {
        try {
          e.streams?.[0]?.getAudioTracks?.().forEach((t: any) => {
            if (typeof t._setVolume === 'function') t._setVolume(8.0);
          });
        } catch {}
      };
      const mic = await mediaDevices.getUserMedia({ audio: true });
      if (!live()) {
        mic.getTracks().forEach((t: any) => t.stop());
        pc.close();
        return;
      }
      mic.getTracks().forEach((t: any) => pc.addTrack(t, mic));
      // 受信音声は react-native-webrtc が自動再生する（InCallManager がスピーカーへ）

      const dc = pc.createDataChannel('oai-events');
      (dc as any).onmessage = (e: any) => {
        lastDcEventAtRef.current = Date.now();
        try {
          handleRtEvent(JSON.parse(String(e.data)));
        } catch {}
      };

      const offer = await pc.createOffer({});
      await pc.setLocalDescription(offer);
      if (!live()) {
        pc.close();
        return;
      }
      const sdpRes = await fetch(`${OPENAI_CALLS_URL}?model=${encodeURIComponent(String(sess.model))}`, {
        method: 'POST',
        body: (pc.localDescription as any)?.sdp ?? '',
        headers: { Authorization: `Bearer ${String(sess.value)}`, 'Content-Type': 'application/sdp' },
      });
      if (!sdpRes.ok) throw new Error(`接続に失敗 (${sdpRes.status})`);
      const answer = await sdpRes.text();
      await pc.setRemoteDescription({ type: 'answer', sdp: answer } as any);
      if (!live()) {
        pc.close();
        return;
      }

      pcRef.current = pc;
      dcRef.current = dc;
      micRef.current = mic;
      lastDcEventAtRef.current = Date.now();
      setStatus('connected');

      // guardian
      if (guardianTimerRef.current) clearInterval(guardianTimerRef.current);
      guardianTimerRef.current = setInterval(() => {
        if (!dcRef.current || dcRef.current.readyState !== 'open') return;
        if (Date.now() < cooldownUntilRef.current) return;
        if (!responseActiveRef.current && (pendingResponseRef.current || pendingItemsRef.current.length > 0)) {
          pendingResponseRef.current = false;
          scheduleResponse();
          return;
        }
        if (responseActiveRef.current && Date.now() - lastDcEventAtRef.current > 20_000) {
          responseActiveRef.current = false;
          scheduleResponse();
        }
      }, 4000);
    } catch (e) {
      if (!live()) return;
      setError(e instanceof Error ? e.message : '接続に失敗しました');
      setStatus('error');
    }
  }, [api, chatTitle, dcSend, disconnect, executeTool, injectItem, injectSystemAndRespond, pushActivity, roomId, saveTranscript, scheduleResponse, token]);

  // ---- 音量ポーリング（getStats の audioLevel）→ オーブ駆動 ----
  useEffect(() => {
    if (status !== 'connected') return;
    const timer = setInterval(async () => {
      const pc = pcRef.current;
      if (!pc) return;
      try {
        const stats = await pc.getStats();
        let user = 0;
        let ai = 0;
        stats.forEach((s: any) => {
          if (s.type === 'media-source' && s.kind === 'audio' && typeof s.audioLevel === 'number') user = s.audioLevel;
          if (s.type === 'inbound-rtp' && (s.kind === 'audio' || s.mediaType === 'audio') && typeof s.audioLevel === 'number')
            ai = s.audioLevel;
        });
        userLevelRef.current = Math.min(1, Math.sqrt(user) * 1.8);
        aiLevelRef.current = ai < 0.01 ? 0 : Math.min(1, Math.sqrt(ai) * 1.8);
      } catch {}
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
    if (visible) void connect();
    else disconnect();
    return () => disconnect();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible]);

  const spin = cloudSpin.interpolate({ inputRange: [0, 1], outputRange: ['0deg', '360deg'] });
  const spinRev = cloudSpin.interpolate({ inputRange: [0, 1], outputRange: ['360deg', '0deg'] });

  return (
    <Modal visible={visible} animationType="fade" onRequestClose={onClose} statusBarTranslucent>
      <View style={vstyles.backdrop}>
        <View style={vstyles.panel}>
          <View style={vstyles.header}>
            <Text style={vstyles.headerText}>
              音声モード{sessionCost > 0 ? ` ・ $${sessionCost.toFixed(2)}` : ''}
            </Text>
            <Pressable onPress={onClose} hitSlop={12}>
              <Ionicons name="close" size={26} color="#d9d2c8" />
            </Pressable>
          </View>

          <View style={vstyles.centerArea}>
          <View style={vstyles.orbArea}>
            <Animated.View style={[vstyles.orb, { transform: [{ scale: orbScale }] }]}>
              <Animated.View style={[vstyles.cloud, vstyles.cloud1, { opacity: cloudOpacity, transform: [{ rotate: spin }] }]} />
              <Animated.View style={[vstyles.cloud, vstyles.cloud2, { opacity: cloudOpacity, transform: [{ rotate: spinRev }] }]} />
              <Animated.View style={[vstyles.cloud, vstyles.cloud3, { opacity: cloudOpacity, transform: [{ rotate: spin }] }]} />
              <View style={vstyles.gloss} />
            </Animated.View>
          </View>

          <Text style={vstyles.statusText}>
            {status === 'connecting' && '接続中…'}
            {status === 'error' && (error || '接続エラー')}
            {status === 'connected' && (currentActivity ? `（${currentActivity}）` : '')}
          </Text>

          {activity.length > 0 && (
            <View style={vstyles.activityBox}>
              {activity.map((line, i) => (
                <Text key={i} style={vstyles.activityLine} numberOfLines={1}>
                  {line}
                </Text>
              ))}
            </View>
          )}

          {status === 'error' && (
            <Pressable style={vstyles.retryButton} onPress={() => void connect()}>
              <Text style={vstyles.retryText}>再接続</Text>
            </Pressable>
          )}
          </View>
        </View>
      </View>
    </Modal>
  );
}

const vstyles = StyleSheet.create({
  // 全画面表示（後ろのチャットは見せない）
  backdrop: { flex: 1, backgroundColor: '#0d0c10' },
  panel: { flex: 1, width: '100%', backgroundColor: '#0d0c10', paddingHorizontal: 24, paddingTop: 54, paddingBottom: 32 },
  header: { width: '100%', flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  headerText: { color: '#a49d92', fontSize: 13 },
  centerArea: { flex: 1, justifyContent: 'center', alignItems: 'center' },
  orbArea: { paddingVertical: 30 },
  orb: {
    width: 210,
    height: 210,
    borderRadius: 105,
    backgroundColor: '#bcd7fa',
    overflow: 'hidden',
    justifyContent: 'center',
    alignItems: 'center',
  },
  cloud: { position: 'absolute', borderRadius: 999 },
  cloud1: { width: 154, height: 154, backgroundColor: '#e6f0ff', top: -25, left: -17 },
  cloud2: { width: 134, height: 134, backgroundColor: '#9fc2f5', bottom: -20, right: -14 },
  cloud3: { width: 112, height: 112, backgroundColor: '#cfe2ff', bottom: 25, left: 11 },
  gloss: { position: 'absolute', width: 98, height: 98, borderRadius: 999, backgroundColor: 'rgba(255,255,255,0.45)', top: 17, left: 28 },
  statusText: { color: '#a49d92', fontSize: 13, minHeight: 20, textAlign: 'center' },
  activityBox: { width: '100%', borderTopWidth: StyleSheet.hairlineWidth, borderTopColor: '#33313a', marginTop: 14, paddingTop: 10, gap: 4 },
  activityLine: { color: '#8f8a81', fontSize: 13, textAlign: 'center' },
  retryButton: { marginTop: 14, borderWidth: 1, borderColor: '#4a4650', borderRadius: 8, paddingHorizontal: 18, paddingVertical: 8 },
  retryText: { color: '#d9d2c8', fontSize: 14 },
});
