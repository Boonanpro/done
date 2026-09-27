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
