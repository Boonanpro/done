import React,{useEffect,useRef,useState} from 'react';
import {AppState,Modal,NativeModules,PermissionsAndroid,Platform,Pressable,Text,View} from 'react-native';
import {Ionicons} from '@expo/vector-icons';
import {useSafeAreaInsets} from 'react-native-safe-area-context';
import {VoiceOrb} from './voice-orb';
import {voiceCallStyles as s} from './voice-call-styles';

export function AtomRelayControl({apiBase,token,callActive,onStartDirect}:{apiBase:string;token:string;callActive:boolean;onStartDirect?:()=>void}) {
  const [status,setStatus]=useState({enabled:false,state:'off',route:'atom',headset:false,connected:false,paused:false,phoneCall:false,ending:false,muted:false,startedAt:0});
  const insets=useSafeAreaInsets();
  const [showCall,setShowCall]=useState(false);
  const active=useRef(false);
  const [busy,setBusy]=useState(false),[error,setError]=useState('');
  useEffect(()=>{
    let alive=true;
    const poll=()=>NativeModules.DanVoiceCall?.atomRelayStatus?.().then((s:any)=>{if(alive){setStatus(s);if(s.enabled&&s.connected&&!active.current)setShowCall(true);active.current=s.enabled&&s.connected;if(!s.enabled||!s.connected)setShowCall(false)}}).catch(()=>{});
    const subscription=AppState.addEventListener('change',s=>{if(s==='active'&&active.current)setShowCall(true)});
    poll();const timer=setInterval(poll,1000);return()=>{alive=false;clearInterval(timer);subscription.remove()};
  },[]);
  async function toggle() {
    setBusy(true);setError('');
    try {
      if(status.enabled) {NativeModules.DanVoiceCall.stopAtomRelay();setStatus({...status,enabled:false,state:'off'});return}
      if (onStartDirect) { onStartDirect(); return; }
      if(Platform.OS!=='android' || !NativeModules.DanVoiceCall?.startAtomRelay) throw Error('アプリの更新が必要です');
      const permissions=[PermissionsAndroid.PERMISSIONS.RECORD_AUDIO,PermissionsAndroid.PERMISSIONS.BLUETOOTH_CONNECT];
      const allowed=await PermissionsAndroid.requestMultiple(permissions);
      if(permissions.some(p=>allowed[p]!==PermissionsAndroid.RESULTS.GRANTED))throw Error('マイクとBluetoothへの許可が必要です');
      const response=await fetch(apiBase+'/api/v1/voicelog/atom-relay',{headers:{Authorization:`Bearer ${token}`}});
      if(!response.ok)throw Error('デバイスの接続設定を取得できませんでした');
      const config=await response.json();
      await NativeModules.DanVoiceCall.startAtomRelay(apiBase,token,config.host,config.key);
      setStatus({...status,enabled:true,state:'connecting'});
    } catch(e) {setError(e instanceof Error?e.message:'接続できませんでした')}
    finally {setBusy(false)}
  }
  const description=status.enabled ? (status.paused?'ほかのアプリが音声を使用中です。Danのマイクと再生は一時停止しています。':status.state==='connecting'?'接続しています…':status.route==='headset'?'イヤホンで話せます':status.connected?'Atomで話せます。':'「ヘイダン」の呼びかけを待っています。'):
    status.state!=='off'?'接続が切れました。Atomと同じWi-Fiにいるか確認してください。':onStartDirect?'Atomと同じWi-Fiで、Atomのマイクとスピーカーを使います。':'Atomと同じWi-Fiで、イヤホンへの自動切り替えを使えます。';
  const seconds=status.startedAt?Math.max(0,Math.floor((Date.now()-status.startedAt)/1000)):0;
  const duration=`${Math.floor(seconds/60)}:${String(seconds%60).padStart(2,'0')}`;
  const end=()=>{NativeModules.DanVoiceCall.endAtomCall();setStatus({...status,ending:true})};
  return <View style={{marginTop:18,gap:8}}>
    <Modal visible={showCall} animationType="fade" onRequestClose={()=>setShowCall(false)} statusBarTranslucent>
      <View style={s.backdrop}><View style={[s.panel,{paddingTop:insets.top+12,paddingBottom:insets.bottom+24}]}>
        <View style={s.header}>
          <Pressable accessibilityRole="button" accessibilityLabel="通話を続けたまま小さくする" onPress={()=>setShowCall(false)} style={s.headerButton}><Ionicons name="chevron-down" size={26} color="#d9d2c8"/></Pressable>
          <Text style={s.headerText}>{status.ending?'通話を終了しています':status.paused?'音声は一時停止中':'通話中'}</Text>
          <Text style={s.timer}>{duration}</Text>
        </View>
        <View style={s.centerArea}>
          <Text style={s.callTitle}>Dan</Text><Text style={s.roomTitle}>全体の相談・確認</Text>
          <VoiceOrb muted={status.muted||status.paused}/>
          <Text accessibilityLiveRegion="polite" style={s.statusText}>{status.state==='end_failed'?'終了を確認できませんでした。もう一度終了を押してください。':status.muted?'マイクをミュートしています':description}</Text>
          {status.paused&&<Pressable accessibilityRole="button" disabled={status.phoneCall} onPress={()=>NativeModules.DanVoiceCall.resumeAtomAudio()} style={s.retryButton}><Text style={s.retryText}>{status.phoneCall?'電話の終了を待っています':'Danとの会話に戻る'}</Text></Pressable>}
        </View>
        <View style={s.controls}>
          <View style={s.controlItem}><Pressable accessibilityRole="button" accessibilityLabel={status.muted?'ミュート解除':'マイクをミュート'} accessibilityState={{selected:status.muted}} onPress={()=>NativeModules.DanVoiceCall.muteAtomMicrophone(!status.muted)} style={[s.controlButton,status.muted&&{backgroundColor:'#e4e9e5'}]}><Ionicons name={status.muted?'mic-off':'mic'} size={26} color={status.muted?'#15251f':'#e4e9e5'}/></Pressable><Text style={s.controlLabel}>{status.muted?'ミュート解除':'ミュート'}</Text></View>
          <View style={s.controlItem}><Pressable accessibilityRole="button" accessibilityLabel="通話を終了" disabled={status.ending} onPress={end} style={[s.controlButton,{backgroundColor:'#b74d4d'}]}><Ionicons name="call" size={27} color="#fff" style={{transform:[{rotate:'135deg'}]}}/></Pressable><Text style={s.controlLabel}>終了</Text></View>
        </View>
        <Text style={s.backgroundHint}>画面を消しても、ほかのアプリを開いても話せます</Text>
      </View></View>
    </Modal>
    {status.connected&&<Pressable accessibilityRole="button" onPress={()=>setShowCall(true)} style={{paddingVertical:14}}><Text style={{color:'#edf5ef',fontSize:17}}>{status.paused?'一時停止中の会話を開く':'通話画面を開く'}</Text></Pressable>}
    <Pressable accessibilityRole="button" accessibilityLabel={status.enabled?'デバイス接続を停止':onStartDirect?'Atomで話す':'Atomとイヤホンを接続'} disabled={busy||callActive} onPress={()=>void toggle()}
      style={{minHeight:48,justifyContent:'center',paddingHorizontal:16,borderRadius:14,borderWidth:1,borderColor:'#81978a',opacity:(busy||callActive) ? .5 : 1}}>
      <Text style={{color:'#edf5ef',fontSize:15}}>{busy?'接続を変更中…':status.enabled?'デバイス接続を停止':onStartDirect?'Atomで話す':'Atomとイヤホンを接続'}</Text>
    </Pressable>
    <Text accessibilityLiveRegion="polite" style={{color:error?'#ffb4ab':'#c2d0c6',fontSize:13,lineHeight:19}}>{error|| (callActive?'スマホの通話を終了すると接続できます。':description)}</Text>
  </View>;
}
