// Microphone path that keeps whispers. An in-ear mic hears a whisper about 20 dB below normal speech; the browser's
// noise suppression removes it and Live does not treat it as speech. Capture without noise suppression or browser
// gain control, then lift quiet speech in quiet-speech-worklet.js before it goes to Live.

export const QUIET_SPEECH_MIC: MediaTrackConstraints = { echoCancellation: true, noiseSuppression: false, autoGainControl: false };

export async function liftQuietSpeech(context: AudioContext, mic: MediaStream): Promise<MediaStream> {
  await context.audioWorklet.addModule('/quiet-speech-worklet.js');
  const lift = new AudioWorkletNode(context, 'quiet-speech-lift', { channelCount: 1, channelCountMode: 'explicit', outputChannelCount: [1] });
  const destination = context.createMediaStreamDestination();
  context.createMediaStreamSource(mic).connect(lift).connect(destination);
  return destination.stream;
}
