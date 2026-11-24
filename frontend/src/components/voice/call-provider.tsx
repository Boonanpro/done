'use client';

/**
 * 通話は画面全体で1つ（2026-11-24 本人「音声モードのまま自由に画面を移動したい。1回の通話の中でまとめて修正指示を出したい」）。
 *
 * 前は通話がその部屋の会話欄（ProjectChatPanel）の中にあり、エディターで別のタイムライン・一覧へ移る、会話欄を畳む、
 * チャットで別の部屋を開く、のどれでも会話欄ごと消えて電話が切れた。今は通話をここ（全ページの外側の Providers）で持ち、
 * 会話欄は電話マークで「かける・切る」を頼むだけ。会話欄は自分の部屋を「本人が今見ている部屋」として知らせ、通話は
 * それをサーバーへ送る（作業の頼みはその部屋＝そのタイムラインへ行く。app/services/voice_sideband.Dialogue.set_focus）。
 *
 * PC ではエディターが別の窓で開く。同じダンの窓どうしは BroadcastChannel で話す: 通話の無い窓の電話マークは通話のある窓の
 * 通話を映し、その窓で見ている部屋も通話へ知らせる（押すと切れる）。
 */
import { createContext, useCallback, useContext, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react';

import { VoiceSession } from './voice-session';

type CallOptions = { stageWidthClass?: string; chatTitle?: string };
type Msg =
  | { type: 'status'; room: string | null; from: string }
  | { type: 'ask-status'; from: string }
  | { type: 'focus'; room: string; from: string }
  | { type: 'end'; from: string };

interface CallApi {
  /** 通話中の部屋（この窓か、別の窓の通話）。無ければ null */
  room: string | null;
  start: (roomId: string, opts?: CallOptions) => void;
  end: () => void;
  /** 本人が今見ている部屋（見えている会話欄が知らせる） */
  setFocus: (roomId: string) => void;
}

const CallContext = createContext<CallApi | null>(null);
const CHANNEL = 'dan-call';

export function CallProvider({ children }: { children: ReactNode }) {
  const [call, setCall] = useState<({ room: string } & CallOptions) | null>(null);
  const [remoteRoom, setRemoteRoom] = useState<string | null>(null);
  const [focusRoom, setFocusRoom] = useState('');
  const me = useRef('');
  const channelRef = useRef<BroadcastChannel | null>(null);
  const callRef = useRef(call);
  const focusRef = useRef(focusRoom);
  useLayoutEffect(() => {
    callRef.current = call;
    focusRef.current = focusRoom;
  }, [call, focusRoom]);

  const post = useCallback((msg: Msg) => {
    try { channelRef.current?.postMessage(msg); } catch { /* 古いブラウザ: 窓をまたがないだけ */ }
  }, []);

  useEffect(() => {
    if (!me.current) me.current = Math.random().toString(36).slice(2);
    if (typeof BroadcastChannel === 'undefined') return;
    const ch = new BroadcastChannel(CHANNEL);
    channelRef.current = ch;
    ch.onmessage = (event: MessageEvent<Msg>) => {
      const msg = event.data;
      if (!msg || msg.from === me.current) return;
      if (msg.type === 'status') setRemoteRoom(msg.room);
      else if (msg.type === 'ask-status') { if (callRef.current) post({ type: 'status', room: callRef.current.room, from: me.current }); }
      else if (msg.type === 'focus') { if (callRef.current) setFocusRoom(msg.room); }
      else if (msg.type === 'end') { if (callRef.current) setCall(null); }
    };
    post({ type: 'ask-status', from: me.current });
    return () => { ch.close(); channelRef.current = null; };
  }, [post]);

  // この窓の通話の有無を他の窓へ
  useEffect(() => {
    post({ type: 'status', room: call?.room ?? null, from: me.current });
  }, [call?.room, post]);
  useEffect(() => {
    const bye = () => { if (callRef.current) post({ type: 'status', room: null, from: me.current }); };
    window.addEventListener('pagehide', bye);
    return () => window.removeEventListener('pagehide', bye);
  }, [post]);

  // 別の窓へ移った時、その窓で見ている部屋を通話へ知らせ直す
  useEffect(() => {
    const onFocus = () => { if (!callRef.current && focusRef.current) post({ type: 'focus', room: focusRef.current, from: me.current }); };
    window.addEventListener('focus', onFocus);
    return () => window.removeEventListener('focus', onFocus);
  }, [post]);

  const start = useCallback((roomId: string, opts?: CallOptions) => {
    if (remoteRoom) return;   // 別の窓で通話中: 2本目はかけない
    setFocusRoom(roomId);
    setCall({ room: roomId, ...opts });
  }, [remoteRoom]);

  const end = useCallback(() => {
    if (callRef.current) setCall(null);
    else post({ type: 'end', from: me.current });
  }, [post]);

  const setFocus = useCallback((roomId: string) => {
    if (!roomId) return;
    setFocusRoom(roomId);
    if (!callRef.current && (typeof document === 'undefined' || document.hasFocus())) post({ type: 'focus', room: roomId, from: me.current });
  }, [post]);

  const api = useMemo<CallApi>(() => ({ room: call?.room ?? remoteRoom, start, end, setFocus }), [call?.room, remoteRoom, start, end, setFocus]);

  return (
    <CallContext.Provider value={api}>
      {children}
      {call && (
        <VoiceSession
          key={call.room}
          roomId={call.room}
          focusRoomId={focusRoom}
          chatTitle={call.chatTitle}
          stageWidthClass={call.stageWidthClass}
          onClose={() => setCall(null)}
        />
      )}
    </CallContext.Provider>
  );
}

export function useCall(): CallApi {
  const api = useContext(CallContext);
  if (api) return api;
  return NO_CALL;   // Providers の外（試験・単体の画面）: 何もしない
}

const NO_CALL: CallApi = { room: null, start: () => {}, end: () => {}, setFocus: () => {} };
