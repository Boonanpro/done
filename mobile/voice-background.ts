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
export async function playAtomVoiceCue(kind: 'ready' | 'standby', pcId: number | undefined) {
  if (Platform.OS === 'android' && pcId != null && await NativeModules.DanVoiceCall?.atomCueOnPhone?.(pcId)) {
    await playVoiceCue(kind);
  }
}
export function setWorkWaiting(active: boolean) {
  if (Platform.OS === 'android') NativeModules.DanVoiceCall?.waiting?.(active);
}

export async function bindRemoteAudio(pcId: number, trackId: string) {
  if (Platform.OS !== 'android' || !NativeModules.DanVoiceCall?.bindRemoteAudio) return false;
  return NativeModules.DanVoiceCall.bindRemoteAudio(pcId, trackId);
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
export async function connectAtomAudio(pcId: number, host: string, key: string) {
  if (Platform.OS !== 'android' || !NativeModules.DanVoiceCall?.connectAtomAudio) throw new Error('アプリの更新が必要です');
  return NativeModules.DanVoiceCall.connectAtomAudio(pcId, host, key);
}
