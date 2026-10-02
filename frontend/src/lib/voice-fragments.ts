// 音声会話の断片を1つの吹き出しにまとめる（表示だけ。保存行はそのまま）。
//
// 音声認識は1回の発言を息継ぎごとに区切って保存するので、「、あなたのスマホから」
// 「、スマホでポルノを…」のような断片が別々の吹き出しになり、間にダンの一言が
// 挟まって会話が読めなくなっていた（2026-09-27）。同じ話し手の 🎙 行が続いている
// 間（間隔 GAP_MS 以内・間に別の行が無い）を1つにまとめる。
// mobile/chatTimeline.ts に同じ関数がある（両方を同じに保つ）。

const GAP_MS = 45_000;
const VOICE = '🎙';
// ダンの相づちだけの行（「はい。」「ん。」）。新しい通話では保存されないが、それ以前の行は表示で落とす。
const BACKCHANNEL = /^(?:(?:はい|ええ|うん|ん|え|ああ|あー|あ|うんうん|はいはい|なるほど|そうですね|ほう)[。、．,.!！?？…ー〜\s]*)+$/;

type VoiceLike = { id: string; sender_type: string; content?: string | null; created_at: string };

function body(content: string): string {
  return content.slice(VOICE.length).trim().replace(/^[、。，．,.?？!！\s]+/, '');
}

/** messages are chronological (oldest first). Returns the same order with runs of one speaker's 🎙 lines merged into
 * the first line of the run (its id and time), the text joined. */
export function mergeVoiceFragments<M extends VoiceLike>(messages: M[]): M[] {
  const out: M[] = [];
  let lastTime = 0;
  for (const msg of messages) {
    const content = msg.content || '';
    const time = new Date(msg.created_at).getTime() || 0;
    if (content.startsWith(VOICE) && msg.sender_type !== 'human' && BACKCHANNEL.test(body(content))) continue;
    const prev = out[out.length - 1];
    if (
      content.startsWith(VOICE) &&
      prev &&
      (prev.content || '').startsWith(VOICE) &&
      prev.sender_type === msg.sender_type &&
      time - lastTime <= GAP_MS
    ) {
      const joined = body(prev.content || '') + body(content);
      out[out.length - 1] = { ...prev, content: `${VOICE} ${joined}` };
      lastTime = time;
      continue;
    }
    out.push(content.startsWith(VOICE) ? { ...msg, content: `${VOICE} ${body(content)}` } : msg);
    lastTime = time;
  }
  return out;
}

// 作業の依頼の写し（【あなたの依頼・Done経由】）と、作業の報告の見出し・「作業の部屋」リンクを、
// 読める形にする（表示だけ）。2026-09-27 以前の行には、作業担当への内部の指示と直前の会話の JSON が
// そのまま入っていて、同じ部屋の音声から頼んだ作業にも見出しとこの部屋へのリンクが付いていた。
const REQUEST_HEAD = '【あなたの依頼・Done経由】';

export function tidyRelayMessage<M extends VoiceLike>(msg: M, projectId?: string): M {
  const content = msg.content || '';
  if (content.startsWith(REQUEST_HEAD)) {
    const asked = content
      .slice(REQUEST_HEAD.length)
      .split('\n参考の直前会話（')[0]
      .split('\n音声通話からの依頼です。')[0]
      .replace(/^\s*今回のユーザー発言（原文）:\s*/, '')
      .trim();
    return { ...msg, content: `${REQUEST_HEAD}\n${asked}` };
  }
  if (projectId && content.startsWith('【') && content.includes(`[作業の部屋](/chat/${projectId})`)) {
    const text = content
      .replace(`[作業の部屋](/chat/${projectId})`, '')
      .replace(/^【[^】\n]*からの報告】\n?/, '')
      .trim();
    return { ...msg, content: text };
  }
  return msg;
}

// 通話の中身は画面に出さず、通話ごとに「📞 ダンと通話 …」の1行にする（表示だけ。発話の 🎙 行は保存したままで、
// ダンは読める）。本人の方針（2026-09-30）: 電話の履歴のように「いつ・何分話したか」だけが残ればよい。
// 2026-09-30 以降の通話はサーバーがその1行を書く（開始時刻と長さ入り）。それより前の通話は 🎙 行の連なりから1行を作る。
// 作業の報告や通話中に「出して」で出した物は通話の中身ではないので、そのまま残る。
// mobile/chatTimeline.ts と frontend/src/lib/voice-fragments.ts に同じ関数がある（両方を同じに保つ）。
const CALL = '📞';
const CALL_GAP_MS = 5 * 60_000;

/** 本人とダンの通話の記録の行なら、かけた側（本人＝右、ダン＝左。電話の発着信の履歴と同じ置き方）。それ以外は null。
 * 「📞 ダンからの通話」はダンがかけた通話、「📞 ダンと通話」は本人がかけた通話（それより前の記録はすべて本人から）。 */
export function callSide(m: VoiceLike): 'owner' | 'dan' | null {
  const content = m.content || '';
  if (m.sender_type !== 'system' || !content.startsWith(`${CALL} ダン`)) return null;
  return content.startsWith(`${CALL} ダンから`) ? 'dan' : 'owner';
}

/** 通話の記録の長さを LINE と同じ「分:秒」で（例 3:05）。長さが書かれていない昔の行は開始〜終了の時刻から分だけ出す。 */
export function callDuration(content: string): string {
  const m = content.match(/（(?:(\d+)分)?(\d+)秒）/);
  if (m) return `${Number(m[1] || 0)}:${String(Number(m[2])).padStart(2, '0')}`;
  const r = content.match(/(\d{1,2}):(\d{2})〜(\d{1,2}):(\d{2})/);
  if (!r) return '';
  const minutes = (Number(r[3]) * 60 + Number(r[4]) - Number(r[1]) * 60 - Number(r[2]) + 1440) % 1440;
  return `${minutes}:00`;
}

function callLengthMs(content: string): number {
  const m = content.match(/（(?:(\d+)分)?(\d+)秒）/);
  return m ? (Number(m[1] || 0) * 60 + Number(m[2])) * 1000 : 0;
}

function clock(ms: number): string {
  const d = new Date(ms);
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

/** messages are chronological (oldest first). 🎙 lines are left out; each earlier call without the server's 📞 line
 * becomes one system row at the call's first line. */
export function collapseCalls<M extends VoiceLike>(messages: M[]): M[] {
  const logged: Array<[number, number]> = [];
  for (const m of messages) {
    const content = m.content || '';
    if (m.sender_type === 'system' && content.startsWith(CALL)) {
      const t = new Date(m.created_at).getTime() || 0;
      logged.push([t - 60_000, t + callLengthMs(content) + 60_000]);
    }
  }
  const out: M[] = [];
  let run: { row: M; index: number; first: number; last: number } | null = null;
  const close = (open: { row: M; index: number; first: number; last: number } | null) => {
    if (open) out[open.index] = { ...open.row, sender_type: 'system', content: `${CALL} ダンと通話 ${clock(open.first)}〜${clock(open.last)}` };
  };
  for (const m of messages) {
    const content = m.content || '';
    if (!content.startsWith(VOICE)) {
      out.push(m);
      continue;
    }
    const t = new Date(m.created_at).getTime() || 0;
    if (logged.some(([from, to]) => t >= from && t <= to)) continue;
    if (run && t - run.last <= CALL_GAP_MS) {
      run.last = t;
      continue;
    }
    close(run);
    out.push(m);
    run = { row: m, index: out.length - 1, first: t, last: t };
  }
  close(run);
  return out;
}
