export interface PlaybackState {
  active: boolean;
  generating: boolean;
  playing: boolean;
  epoch: number;
}

/** Finish already-started speech before closing; a new utterance cancels standby. */
export async function waitForStandbyDrain(
  state: () => PlaybackState,
  options: {
    now?: () => number;
    sleep?: (ms: number) => Promise<void>;
    timeoutMs?: number;
    tailMs?: number;
  } = {},
): Promise<'drained' | 'superseded' | 'timeout'> {
  const now = options.now ?? (() => performance.now());
  const sleep = options.sleep ?? ((ms: number) => new Promise<void>(resolve => setTimeout(resolve, ms)));
  const epoch = state().epoch;
  const deadline = now() + (options.timeoutMs ?? 30000);
  let quietSince: number | null = null;
  while (true) {
    const snapshot = state();
    if (!snapshot.active || snapshot.epoch !== epoch) return 'superseded';
    if (snapshot.generating || snapshot.playing) quietSince = null;
    else {
      quietSince ??= now();
      // Cover the worklet/bridge/device tail after WebRTC playback ends.
      if (now() - quietSince >= (options.tailMs ?? 300)) return 'drained';
    }
    if (now() >= deadline) return 'timeout';
    await sleep(40);
  }
}
