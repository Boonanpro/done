// チャットの「指示文の地図の直す所」（部品 MapPlan）と、指示文の画面の大きな地図（components/prompts/arch-board.tsx）をつなぐ。
// 2026-11-27 本人「どこをどう変えようと思っているのかを左にある指示文のマップと紐づけてない」。
// - 同じ画面（/prompts、開発室の「指示文」）: window のイベントで渡す。
// - 開発室の成果物タブ: 会話は外の画面、地図は中の枠（iframe）なので postMessage で渡し、中から受け取りの返事（ack）をもらう。
// - どちらにも地図が無ければ、/prompts?place=<箱> を新しいタブで開く。
// 渡すのは箱の id・番号と、案の中身の短い文だけ（押して地図を動かし、中身を見せるだけの無害な知らせなので、送り元は問わない）。
// 2026-11-28 本人「番号を押しても該当するパネルが開くだけで、何で開いたのか意味分からん」→ 押した番号も渡し、指示文の画面は
// 箱の中身の一番上にその案（今→直した後・見込み・直す文の前後）を出す。

export type PlanMark = {
  node: string; n: number; title: string;
  now?: string; after?: string; effect?: string; prompt?: string; quote?: string; rewrite?: string;
};

const FOCUS = 'dan-map-focus';
const PLAN = 'dan-map-plan';
const ACK = 'dan-map-ack';
const HELLO = 'dan-map-hello';   // 後から開いた中の枠の地図が、外の会話に今の番号を聞く
const ID_RE = /^[A-Za-z0-9-]{1,40}$/;
const PROMPT_RE = /^[A-Za-z0-9][A-Za-z0-9/_.-]{0,80}$/;

type Here = { focus: (node: string, n?: number) => void; plan: (marks: PlanMark[]) => void };
let here: Here | null = null;
let lastPlan: PlanMark[] = [];

function cleanMarks(v: unknown): PlanMark[] {
  if (!Array.isArray(v)) return [];
  const s = (x: unknown, max: number) => (typeof x === 'string' && x.trim() ? x.slice(0, max) : undefined);
  return v.flatMap((raw) => {
    const m = raw as PlanMark;
    if (!m || typeof m !== 'object' || typeof m.node !== 'string' || !ID_RE.test(m.node)) return [];
    const prompt = s(m.prompt, 81);
    return [{
      node: m.node, n: Number(m.n) || 0, title: String(m.title || '').slice(0, 80),
      now: s(m.now, 160), after: s(m.after, 160), effect: s(m.effect, 120),
      prompt: prompt && PROMPT_RE.test(prompt) ? prompt : undefined, quote: s(m.quote, 300), rewrite: s(m.rewrite, 400),
    }];
  });
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

/** 地図のその箱を開き、n 番の案をその中身の一番上に出す。地図がどこにも無ければ指示文の画面を新しいタブで開く */
export function focusMapBox(node: string, n?: number) {
  if (!ID_RE.test(node)) return;
  if (here) { here.focus(node, n); return; }
  const targets = frames();
  let acked = false;
  const onAck = (e: MessageEvent) => { if (e.data?.type === ACK && e.data.node === node) acked = true; };
  window.addEventListener('message', onAck);
  for (const w of targets) w.postMessage({ type: FOCUS, node, n }, '*');
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
      h.focus(d.node, Number(d.n) || undefined);
      (e.source as Window | null)?.postMessage({ type: ACK, node: d.node }, '*');
    } else if (d.type === PLAN) {
      h.plan(cleanMarks(d.marks));
    }
  };
  window.addEventListener('message', onMessage);
  if (window.parent !== window) window.parent.postMessage({ type: HELLO }, '*');
  return () => { window.removeEventListener('message', onMessage); if (here === h) here = null; };
}
