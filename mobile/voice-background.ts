import { AppRegistry, DeviceEventEmitter, NativeModules, Platform } from 'react-native';

// An active Headless task keeps React Native timers running after Activity pause.
// The native service owns the notification and CPU wake lock, only during calls.
let finishTask: (() => void) | undefined;
AppRegistry.registerHeadlessTask('DanVoiceCall', () => () => new Promise<void>(resolve => {
  finishTask = resolve;
}));
DeviceEventEmitter.addListener('DanVoiceStopped', () => { finishTask?.(); finishTask = undefined; });

export async function startVoiceBackground() {
  if (Platform.OS === 'android') return await NativeModules.DanVoiceCall.start() as string;
  return 'non-android';
}
export function stopVoiceBackground(lease: string) {
  if (Platform.OS === 'android') NativeModules.DanVoiceCall.stop(lease);
}
export function onVoiceEnd(listener: () => void) {
  return DeviceEventEmitter.addListener('DanVoiceEnd', listener);
}
export function onVoiceTick(listener: () => void) {
  return DeviceEventEmitter.addListener('DanVoiceTick', listener);
}
export function markVoiceConnected() {
  if (Platform.OS === 'android') NativeModules.DanVoiceCall.connected();
}
export async function playVoiceCue(kind: 'ready' | 'standby') {
  if (Platform.OS === 'android') await NativeModules.DanVoiceCall.cue(kind);
}
/** Ready/standby cue on the pin during a pin call; falls back to the phone when the pin cannot play it. */
export async function playPinVoiceCue(kind: 'ready' | 'standby', pcId: number | undefined) {
  if (Platform.OS === 'android' && pcId != null && await NativeModules.DanVoiceCall?.pinCue?.(pcId, kind).catch(() => false)) return;
  await playVoiceCue(kind);
}
export function setWorkWaiting(active: boolean) {
  if (Platform.OS === 'android') NativeModules.DanVoiceCall?.waiting?.(active);
}

export async function bindRemoteAudio(pcId: number, trackId: string) {
  if (Platform.OS !== 'android' || !NativeModules.DanVoiceCall?.bindRemoteAudio) return false;
  return NativeModules.DanVoiceCall.bindRemoteAudio(pcId, trackId);
}
/** True when the call will capture from Bluetooth earbuds; such calls skip noise suppression so whispers survive. */
export async function quietSpeechInput(): Promise<boolean> {
  if (Platform.OS !== 'android' || !NativeModules.DanVoiceCall?.quietSpeechInput) return false;
  return NativeModules.DanVoiceCall.quietSpeechInput();
}
export function unbindRemoteAudio(pcId: number) {
  if (Platform.OS === 'android') NativeModules.DanVoiceCall?.unbindRemoteAudio?.(pcId);
}
export async function audioEndpointStats(pcId: number) {
  if (Platform.OS !== 'android' || !NativeModules.DanVoiceCall?.audioEndpointStats) return null;
  return NativeModules.DanVoiceCall.audioEndpointStats(pcId);
}
export function muteExternalAudio(pcId: number, value: boolean) {
  if (Platform.OS === 'android') NativeModules.DanVoiceCall?.muteExternalAudio?.(pcId, value);
}
/** Attach the Dan pin (BLE) microphone to this phone-owned call. Dan keeps answering from the phone. */
export async function connectPinAudio(pcId: number) {
  if (Platform.OS !== 'android' || !NativeModules.DanVoiceCall?.connectPinAudio) throw new Error('アプリの更新が必要です');
  return NativeModules.DanVoiceCall.connectPinAudio(pcId);
}
