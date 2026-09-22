/** Optional local Atom transport. Only the paired room can activate it. */
export interface AtomWifiTransport {
  stream: MediaStream;
  play: (stream: MediaStream) => void;
  close: () => void;
  interrupt: () => void;
  resume: () => void;
  standby: () => Promise<void>;
  cueOutput: AudioNode;
}

export async function connectAtomWifi(roomId: string, context: AudioContext): Promise<AtomWifiTransport | null> {
  const raw = localStorage.getItem('dan-atom-wifi');
  if (!raw) return null;
  const config = JSON.parse(raw) as { roomId?: string; key?: string; enabled?: boolean };
  if (!config.enabled) return null;
  if (config.roomId !== roomId) throw new Error('この音声デバイスは設定した部屋でのみ使えます');
  if (!config.key || !/^[a-f0-9]{32}$/.test(config.key)) throw new Error('音声デバイスの接続設定が不正です');
  if (context.sampleRate !== 48000) throw new Error('音声デバイスには48kHzの音声出力が必要です');
  await context.audioWorklet.addModule('/atom-wifi-worklet.js');
  const mic = new AudioWorkletNode(context, 'atom-wifi-mic', { numberOfInputs: 0, outputChannelCount: [1] });
  const destination = context.createMediaStreamDestination();
  mic.connect(destination);
  const speaker = new AudioWorkletNode(context, 'atom-wifi-speaker', { outputChannelCount: [1] });
  // Silent graph output keeps the worklet running; actual sound goes over Wi-Fi.
  speaker.connect(context.destination);
  const highpass = context.createBiquadFilter();
  highpass.type = 'highpass'; highpass.frequency.value = 180; highpass.Q.value = 0.7071;
  highpass.connect(speaker);
  const socket = new WebSocket('ws://127.0.0.1:48801/audio');
  socket.binaryType = 'arraybuffer';
  let source: MediaStreamAudioSourceNode | null = null;
  const close = () => {
    socket.close(); mic.disconnect(); source?.disconnect(); highpass.disconnect(); speaker.disconnect();
    destination.stream.getTracks().forEach(track => track.stop());
  };
  try {
    await new Promise<void>((resolve, reject) => {
      const timeout = setTimeout(() => reject(new Error('音声デバイスの中継に接続できません')), 8000);
      socket.onopen = () => socket.send(JSON.stringify({ key: config.key, roomId }));
      socket.onerror = () => { clearTimeout(timeout); reject(new Error('PCの音声デバイス中継が起動していません')); };
      socket.onclose = () => { clearTimeout(timeout); reject(new Error('音声デバイスの中継接続が閉じました')); };
      socket.onmessage = event => {
        if (typeof event.data === 'string') {
          const message = JSON.parse(event.data);
          if (message.type === 'ready') {
            clearTimeout(timeout);
            if (message.deviceConnected) resolve();
            else reject(new Error('Wi-Fi上の音声デバイスが見つかりません。電源を確認してください'));
          }
        } else mic.port.postMessage(event.data, [event.data]);
      };
    });
    speaker.port.onmessage = event => {
      if (socket.readyState === WebSocket.OPEN && socket.bufferedAmount < 19200) socket.send(event.data);
    };
    await context.resume();
    return {
      stream: destination.stream,
      cueOutput: highpass,
      play: stream => { source?.disconnect(); source = context.createMediaStreamSource(stream); source.connect(highpass); },
      interrupt: () => {
        speaker.port.postMessage('interrupt');
        if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: 'flush' }));
      },
      resume: () => speaker.port.postMessage('resume'),
      standby: async () => {
        const response = await fetch('http://127.0.0.1:48802/command', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ key: config.key, action: 'stop' }),
          signal: AbortSignal.timeout(3000),
        });
        if (!response.ok) throw new Error('待機への切り替えに失敗しました');
        speaker.port.postMessage('interrupt');
        destination.stream.getAudioTracks().forEach(track => { track.enabled = false; });
      },
      close,
    };
  } catch (error) { close(); throw error; }
}
