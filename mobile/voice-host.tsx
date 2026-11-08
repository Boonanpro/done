import {useUiLanguage} from './ui-language';
import React, {createContext, useContext, useState, type ReactNode} from 'react';
import {View} from 'react-native';
import {VoiceOverlay} from './voice';

type Call = {roomId: string; chatTitle: string; apiBase: string; token: string; audioEndpoint?: 'phone' | 'pin'};
type StartOptions = {preserveScreen?: boolean};
const VoiceContext = createContext<{start: (call: Call, options?: StartOptions) => void; stop: () => void; roomId: string | null; minimized: boolean}>({start() {},stop() {},roomId:null,minimized:false});
export const useVoice = () => useContext(VoiceContext);

/** A call belongs to its starting room, not whichever screen is currently open. */
export function VoiceHost({children}: {children: ReactNode}) {
  useUiLanguage();
  const [call, setCall] = useState<Call | null>(null);
  const [expanded, setExpanded] = useState(true);
  return <VoiceContext.Provider value={{
    start: (next, options) => {
      setCall(current => current || next);
      setExpanded(current => options?.preserveScreen ? (call ? current : false) : true);
    },
    stop: () => setCall(null), roomId: call?.roomId || null, minimized: !!call && !expanded,
  }}>
    <View style={{flex:1,backgroundColor:'#12110f'}}>
      {call && <VoiceOverlay {...call} visible expanded={expanded}
        onMinimize={() => setExpanded(false)} onExpand={() => setExpanded(true)} onClose={() => setCall(null)} />}
      <View style={{flex:1}}>{children}</View>
    </View>
  </VoiceContext.Provider>;
}
