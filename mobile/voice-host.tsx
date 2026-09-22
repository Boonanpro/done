import React, {createContext, useContext, useState, type ReactNode} from 'react';
import {View,Alert,NativeModules} from 'react-native';
import {VoiceOverlay} from './voice';

type Call = {roomId: string; chatTitle: string; apiBase: string; token: string; audioEndpoint?: 'phone' | 'atom'};
const VoiceContext = createContext<{start: (call: Call) => void; stop: () => void; roomId: string | null; minimized: boolean}>({start() {},stop() {},roomId:null,minimized:false});
export const useVoice = () => useContext(VoiceContext);

/** A call belongs to its starting room, not whichever screen is currently open. */
export function VoiceHost({children}: {children: ReactNode}) {
  const [call, setCall] = useState<Call | null>(null);
  const [expanded, setExpanded] = useState(true);
  return <VoiceContext.Provider value={{
    start: next => {void (async()=>{
      const relay=await NativeModules.DanVoiceCall?.atomRelayStatus?.();
      if(relay?.enabled) {Alert.alert('デバイスで接続中','Atomか接続したイヤホンで話せます。スマホだけで新しく通話する場合は、デバイス接続を停止してください。');return}
      setCall(current => current || next); setExpanded(true);
    })().catch(()=>{});},
    stop: () => setCall(null), roomId: call?.roomId || null, minimized: !!call && !expanded,
  }}>
    <View style={{flex:1,backgroundColor:'#12110f'}}>
      {call && <VoiceOverlay {...call} visible expanded={expanded}
        onMinimize={() => setExpanded(false)} onExpand={() => setExpanded(true)} onClose={() => setCall(null)} />}
      <View style={{flex:1}}>{children}</View>
    </View>
  </VoiceContext.Provider>;
}
