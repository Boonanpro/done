// チャットの「指示文の地図の直す所」（部品 MapPlan）と、指示文の画面の大きな地図（components/prompts/arch-board.tsx）をつなぐ。
// 2026-11-27 本人「どこをどう変えようと思っているのかを左にある指示文のマップと紐づけてない」。
// - 同じ画面（/prompts、開発室の「指示文」）: window のイベントで渡す。
// - 開発室の成果物タブ: 会話は外の画面、地図は中の枠（iframe）なので postMessage で渡し、中から受け取りの返事（ack）をもらう。
// - どちらにも地図が無ければ、/prompts?place=<箱> を新しいタブで開く。
// 渡すのは箱の id と番号だけ（押して地図を動かすだけの無害な知らせなので、送り元は問わない）。

export type PlanMark = { node: string; n: number; title: string };

const FOCUS = 'dan-map-focus';
const PLAN = 'dan-map-plan';
const ACK = 'dan-map-ack';
const HELLO = 'dan-map-hello';   // 後から開いた中の枠の地図が、外の会話に今の番号を聞く
const ID_RE = /^[A-Za-z0-9-]{1,40}$/;

type Here = { focus: (node: string) => void; plan: (marks: PlanMark[]) => void };
let here: Here | null = null;
let lastPlan: PlanMark[] = [];

function cleanMarks(v: unknown): PlanMark[] {
  if (!Array.isArray(v)) return [];
  return v.flatMap((m) => (m && typeof m === 'object' && typeof (m as PlanMark).node === 'string' && ID_RE.test((m as PlanMark).node)
    ? [{ node: (m as PlanMark).node, n: Number((m as PlanMark).n) || 0, title: String((m as PlanMark).title || '').slice(0, 80) }] : []));
}

function frames(): Window[] {
  if (typeof document === 'undefined') return [];
  return Array.from(document.querySelectorAll('iframe')).flatMap((f) => (f.contentWindow ? [f.contentWindow] : []));
}

/** チャットの部品が、直す所の番号を地図に出す（新しい返事ほど後に呼ばれ、最後の物が残る） */
let answering = false;
export function announcePlan(marks: PlanMark[]) {
  lastPlan = marks;
  if (!answering && typeof window !== 'undefined') {
    answering = true;
    window.addEventListener('message', (e) => {
      if (e.data?.type === HELLO && lastPlan.length) (e.source as Window | null)?.postMessage({ type: PLAN, marks: lastPlan }, '*');
    });
  }
  if (here) here.plan(marks);
  for (const w of frames()) w.postMessage({ type: PLAN, marks }, '*');
}

/** 地図のその箱を開く。地図がどこにも無ければ指示文の画面を新しいタブで開く */
export function focusMapBox(node: string) {
  if (!ID_RE.test(node)) return;
  if (here) { here.focus(node); return; }
  const targets = frames();
  let acked = false;
  const onAck = (e: MessageEvent) => { if (e.data?.type === ACK && e.data.node === node) acked = true; };
  window.addEventListener('message', onAck);
  for (const w of targets) w.postMessage({ type: FOCUS, node }, '*');
  window.setTimeout(() => {
    window.removeEventListener('message', onAck);
    if (!acked) window.open(`/prompts?place=${encodeURIComponent(node)}`, '_blank', 'noopener');
  }, targets.length ? 450 : 0);
}

/** 地図を持つ画面が呼ぶ。外して戻す関数を返す */
export function hostMap(h: Here): () => void {
  here = h;
  if (lastPlan.length) h.plan(lastPlan);
  const onMessage = (e: MessageEvent) => {
    const d = e.data;
    if (!d || typeof d !== 'object') return;
    if (d.type === FOCUS && typeof d.node === 'string' && ID_RE.test(d.node)) {
      h.focus(d.node);
      (e.source as Window | null)?.postMessage({ type: ACK, node: d.node }, '*');
    } else if (d.type === PLAN) {
      h.plan(cleanMarks(d.marks));
    }
  };
  window.addEventListener('message', onMessage);
  if (window.parent !== window) window.parent.postMessage({ type: HELLO }, '*');
  return () => { window.removeEventListener('message', onMessage); if (here === h) here = null; };
}
