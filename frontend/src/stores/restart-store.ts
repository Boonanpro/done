'use client';

import { create } from 'zustand';

/**
 * ダンの本体（チャットを動かすサーバー）が再起動している間、画面にかぶせる表示の状態。
 *
 * 始まり方は2つ:
 * - announced: 再起動の係が止める直前に、新着の線（/chat/feed）で知らせてきた。
 * - それ以外: 知らせが無いまま線が切れ、確かめたら本体が応答しなかった。
 */
export type Alive = { state: 'up' | 'starting' | 'down'; started?: number };

type RestartState = {
  cover: { announced: boolean; started?: number; since: number } | null;
  /** 戻った回数。新着の線はこれが変わったら待たずにつなぎ直す。 */
  backs: number;
  begin: (cover: { announced: boolean; started?: number }) => void;
  end: () => void;
};

export const useRestartStore = create<RestartState>((set, get) => ({
  cover: null,
  backs: 0,
  begin: (cover) => {
    if (!get().cover) set({ cover: { ...cover, since: Date.now() } });
  },
  end: () => set((s) => ({ cover: null, backs: s.backs + 1 })),
}));

/**
 * 本体が応答するか。up=部屋の一覧を返すサーバーも応答する / starting=本体だけ応答する /
 * down=画面のサーバーは応答するが本体が待ち受けていない（中継が 500 を返す）。
 * この端末から届かない・返事が来ない・途中の経路が落ちている（502 など）時は null（本体の様子は分からない）。
 */
export async function askAlive(): Promise<Alive | null> {
  try {
    const res = await fetch('/api/v1/chat/alive', { cache: 'no-store', signal: AbortSignal.timeout(4000) });
    if (res.status === 500) return { state: 'down' };
    if (res.status > 500) return null;
    if (!res.ok) return { state: 'up' }; // /alive を持たない前の版の本体
    const d = (await res.json()) as { sandbox?: boolean; started?: number };
    return { state: d.sandbox ? 'up' : 'starting', started: d.started };
  } catch {
    return null;
  }
}

/** 新着の線が切れた時に呼ぶ。本体が待ち受けていないと2回続けて分かったら、かぶせを出す。 */
export async function coverIfDown(): Promise<void> {
  if (useRestartStore.getState().cover) return;
  if ((await askAlive())?.state !== 'down') return;
  await new Promise((r) => setTimeout(r, 1000));
  if ((await askAlive())?.state === 'down') useRestartStore.getState().begin({ announced: false });
}
