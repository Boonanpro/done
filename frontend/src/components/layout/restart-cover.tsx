'use client';

import { useEffect, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';

import { askAlive, useRestartStore } from '@/stores/restart-store';

const USUAL_MS = 20_000; // 止めてから両方が応答するまでの、いつもの長さの目安
const NEVER_STOPPED_MS = 20_000; // 知らせは来たが本体が止まらなかった（再起動が取りやめになった）と見なすまで

/**
 * 本体の再起動中、画面全体にかぶせる表示。インジケーターは時間の見込みで進み、本体が応答したら
 * 7割まで、部屋の一覧を返すサーバーも応答したら満ちて、かぶせが消える。ページの読み直しは要らない。
 */
export function RestartCover() {
  const cover = useRestartStore((s) => s.cover);
  const end = useRestartStore((s) => s.end);
  const queryClient = useQueryClient();
  const [filled, setFilled] = useState(0);

  useEffect(() => {
    if (!cover) return;
    setFilled(0);
    let stopped = false;
    let sawDown = !cover.announced;
    let floor = 0;
    let timer: number | null = null;

    const back = () => {
      stopped = true;
      setFilled(1);
      window.setTimeout(() => {
        end();
        void queryClient.invalidateQueries();
      }, 450);
    };

    const tick = async () => {
      const alive = await askAlive();
      if (stopped) return;
      const waited = Date.now() - cover.since;
      if (alive?.state === 'down') sawDown = true;
      const isNew = sawDown || (alive?.started !== undefined && alive.started !== cover.started);
      if (alive && alive.state !== 'down' && isNew) {
        if (alive.state === 'up') return back();
        floor = 0.7;
      } else if (alive && alive.state !== 'down' && waited > NEVER_STOPPED_MS) {
        return back();
      }
      setFilled(Math.max(floor, 0.9 * (1 - Math.exp(-waited / USUAL_MS))));
      timer = window.setTimeout(tick, 1000);
    };
    void tick();

    return () => {
      stopped = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [cover, end, queryClient]);

  if (!cover) return null;

  return (
    <div
      role="status"
      className="fixed inset-0 z-[10000] flex flex-col items-center justify-center gap-5 bg-background/90 backdrop-blur-sm"
    >
      <p className="text-base font-medium text-foreground">
        {cover.announced ? 'ダンを再起動中です' : 'ダンの本体につながりません'}
      </p>
      <div className="h-1.5 w-[min(320px,70vw)] overflow-hidden rounded-full bg-muted">
        <div
          className={`h-full rounded-full bg-primary transition-[width] ease-linear ${filled === 1 ? 'duration-300' : 'duration-1000'}`}
          style={{ width: `${filled * 100}%` }}
        />
      </div>
    </div>
  );
}
