// スマホのアプリ用の写し: frontend/src/lib/chat-shapes/job-report.ts と同じ中身（同じフォルダの読み込みの名前だけ違う）。
// frontend/scripts/sync-mobile-chat-shapes.mjs が作る。手で直さず、元を直して写し直す
// （tests/chat_shapes_program.test.mjs が同じ中身かを見る）。
/**
 * 並行作業（部屋から枝分かれした別のダンの作業）の報告を、会話の本文に流さず1行の札にするための読み手（2026-10-23）。
 * 本人「書かれてることが膨大過ぎて何から答えていいか何の話か見失う。返事しようにもできない」。報告の全文は部屋の記録に
 * 残り（部屋のダンが読む）、画面は「作業の名前・終わった／止まった」の札だけを出し、押すと全文が開く。本人への返事は、
 * 報告を読んだ部屋のダンが短く1通だけ書く（app/services/parallel_job_runner.py wake_room）。
 *
 * 印はサーバーが付ける ai_context.job_report（parallel_job_runner.report_card）。印の無い古い報告も、本文の頭
 * 「**【並行作業：名前】**」で読む（止まった知らせは本文が「作業を停止しました」で始まる）。
 * PC・スマホ・開発室のチャットが同じ物を使う（スマホの写しは frontend/scripts/sync-mobile-chat-shapes.mjs が作る）。依存なし。
 */

export type JobReport = {
  /** 作業の名前 */
  title: string;
  state: 'done' | 'stopped';
  /** 報告の本文（頭の「【並行作業：…】」を除いた全文。札を押すと開く） */
  body: string;
};

export const JOB_STATE_TEXT: Record<JobReport['state'], string> = { done: '終わった', stopped: '止まった' };

const HEAD = /^\s*\*\*【並行作業：([\s\S]*?)】\*\*[ \t]*\r?\n?/;

/** ダンの発言が並行作業の報告なら、その札の中身。違えば null */
export function readJobReport(aiContext: unknown, content: string | null | undefined): JobReport | null {
  const text = content || '';
  const head = HEAD.exec(text);
  const card = aiContext && typeof aiContext === 'object' ? (aiContext as { job_report?: unknown }).job_report : null;
  if (!head && !(card && typeof card === 'object')) return null;
  const body = (head ? text.slice(head[0].length) : text).trim();
  const c = (card && typeof card === 'object' ? card : {}) as { title?: unknown; state?: unknown };
  const title = (typeof c.title === 'string' && c.title.trim() ? c.title.trim() : head ? head[1].trim() : '') || '作業';
  const state: JobReport['state'] = c.state === 'stopped' || c.state === 'done'
    ? c.state
    : /^作業を停止しました/.test(body) ? 'stopped' : 'done';
  return { title: title.length > 40 ? `${title.slice(0, 39)}…` : title, state, body };
}
