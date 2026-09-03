/**
 * 実使用の体感時間を記録する（部屋切替など）。
 *
 * 手元の headless 計測と本人の体感がずれたため、本人の操作そのものを
 * 「タップ→内容が見える」まで測ってバックエンドに残す。
 * 送信は fire-and-forget、失敗しても何もしない。
 */
export type PerfEvent = {
  surface: 'web' | 'mobile';
  event: string;
  ms: number;
  room_id?: string | null;
  extra?: Record<string, unknown>;
};

export function perfLog(ev: PerfEvent): void {
  if (typeof window === 'undefined') return;
  const payload = { ...ev, at: new Date().toISOString(), ua: navigator.userAgent.slice(0, 80) };
  // eslint-disable-next-line no-console
  console.log(`[perf] ${ev.event} ${Math.round(ev.ms)}ms`, ev.extra ?? '');
  try {
    fetch('/api/v1/chat/perf', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      keepalive: true,
    }).catch(() => undefined);
  } catch {
    /* ignore */
  }
}

/** サイドバーで部屋を押した瞬間。パネルの mount より前のコストも含めて測るための起点。 */
export function markRoomClick(projectId: string): void {
  if (typeof window === 'undefined') return;
  (window as unknown as { __danRoomClick?: { id: string; at: number } }).__danRoomClick = {
    id: projectId,
    at: performance.now(),
  };
}

export function roomClickStart(projectId: string): number | null {
  if (typeof window === 'undefined') return null;
  const m = (window as unknown as { __danRoomClick?: { id: string; at: number } }).__danRoomClick;
  return m && m.id === projectId ? m.at : null;
}
