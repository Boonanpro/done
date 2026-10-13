/**
 * 開いたままにする線（新着を受け取る /chat/feed）を、必ず1本だけにする。
 *
 * 2026-10-13 まで: 線が切れた時の後始末が「いま変数に入っている線」を閉じていて、切れた線そのものを閉じて
 * いなかった。切れている間にタブへ戻ると、つなぎ直しと再試行のタイマーの両方が線を作り、片方が閉じられずに
 * 残った。残った線はブラウザが自分でつなぎ直し続け、次に切れるたびに全部の線がそれぞれ新しい線を作るので、
 * 本体の再起動のたびに倍々に増えた（1タブで 1→2→4→7→14 本）。ブラウザが同じ相手に同時に開ける通信の数は
 * 全タブで共有なので、線で埋まると送信もページの読み込みも出ていかなくなった。
 *
 * ここでは、つなぐ時に必ず「待っている再試行を取り消し、いまの線を閉じてから」1本作る。切れた線は自分自身を
 * 閉じ、もう自分が今の線でなければ何もしない。なので線は多くて1本、再試行のタイマーも多くて1つ。
 * mobile/one-line.ts は同じ中身（アプリは別のパッケージなので取り込めない）。
 */
export type Line = { close: () => void };

export function oneLine(
  open: (on: { up: () => void; dropped: () => void }) => Line,
  onDropped?: () => void,
) {
  let line: Line | null = null;
  let timer: ReturnType<typeof setTimeout> | null = null;
  let retry = 1000;
  let stopped = false;

  const close = () => {
    if (timer) clearTimeout(timer);
    timer = null;
    line?.close();
    line = null;
  };
  const connect = () => {
    if (stopped) return;
    close();
    const mine: Line = open({
      up: () => {
        if (line === mine) retry = 1000;
      },
      dropped: () => {
        mine.close();
        if (line !== mine || stopped) return;
        line = null;
        onDropped?.();
        timer = setTimeout(connect, retry);
        retry = Math.min(retry * 2, 30_000);
      },
    });
    line = mine;
  };

  return {
    /** いまの線を閉じて、すぐつなぎ直す。 */
    connect,
    /** 線が無い時だけつなぐ（タブに戻った・回線が戻った）。待っている再試行はこれに置き換わる。 */
    connectIfClosed: () => {
      if (!line) connect();
    },
    /** 閉じて、再試行もしない（アプリが背面に回った）。connect でまた開ける。 */
    close,
    /** 終わり。以後は何もつながない。 */
    stop: () => {
      stopped = true;
      close();
    },
  };
}
