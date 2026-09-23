/** Live appends. The server answers delegations; clients only append small context/speech events. */
type Item = Record<string, unknown>;

let appendSequence = 0;
const appendEventId = () => `voice-${Date.now()}-${++appendSequence}`;

/** Appends have a 500-token ceiling; large records stay in the backend. */
export function appendLive(send: (event: Item) => void, kind: 'commentary' | 'thinking', text: string, delegationId: string | null = null) {
  // Tool records are context, not 10 separate invitations to start speaking.
  // Preserve the full record silently, then finish this delegation once.
  let record: Item | undefined;
  try { const value=JSON.parse(text); if(value && typeof value==='object' && !Array.isArray(value))record=value; } catch {}
  if(kind==='commentary' && record && !record.evidence_type) {
    appendLive(send,'thinking',text,delegationId);
    send({type:'session.commentary.append',event_id:appendEventId(),delegation_id:delegationId,
      content:'確認結果を受信しました。直前の結果に基づいて、今の質問に答えてください。'});
    return;
  }
  // Evidence is context, not a sequence of sentences to announce. Sending
  // every JSON fragment as commentary can make Live answer and then restart.
  let evidence = false;
  try { evidence = JSON.parse(text).evidence_type === 'search_excerpts'; } catch {}
  if (evidence && kind === 'commentary') {
    const result = JSON.parse(text);
    if (Array.isArray(result.evidence_context)) {
      for (const content of result.evidence_context) if (typeof content === 'string')
        send({type:'session.thinking.append',event_id:appendEventId(),delegation_id:delegationId,content});
    }
    // The server selects a complete source passage and caps it at 450 tokens.
    // Never start speaking from an incomplete JSON/source fragment.
    if (typeof result.spoken_evidence === 'string') {
      send({type:'session.commentary.append',event_id:appendEventId(),delegation_id:delegationId,content:result.spoken_evidence});
    } else {
      appendLive(send, 'thinking', text, delegationId);
    }
    return;
  }
  let part = '', bytes = 0;
  const flush = () => { if (part) send({ type: `session.${kind}.append`, event_id: appendEventId(), delegation_id: delegationId, content: part }); part = ''; bytes = 0; };
  for (const char of text) {
    const cp = char.codePointAt(0)!;
    const size = cp < 0x80 ? 1 : cp < 0x800 ? 2 : cp < 0x10000 ? 3 : 4;
    if (bytes + size > 480) flush();
    part += char; bytes += size;
  }
  flush();
}
