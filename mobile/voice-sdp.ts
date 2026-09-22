/** Negotiate audio retransmission as well as Opus FEC. A remote peer that does
 * not support NACK can omit it from its answer; never fabricate the answer.
 * Only touch Opus payloads in audio sections, leaving ICE/DTLS/data untouched.
 */
export function withAudioRecovery(sdp: string): string {
  const eol = sdp.includes('\r\n') ? '\r\n' : '\n';
  const lines = sdp.split(eol);
  let start = 0;
  while (start < lines.length) {
    if (!lines[start].startsWith('m=audio ')) { start++; continue; }
    let end = start + 1;
    while (end < lines.length && !lines[end].startsWith('m=')) end++;
    const payloads = lines.slice(start, end).flatMap(line => {
      const match = /^a=rtpmap:(\d+) opus\/48000\/2$/i.exec(line);
      return match ? [match[1]] : [];
    });
    for (const pt of payloads) {
      const feedback = `a=rtcp-fb:${pt} nack`;
      if (!lines.slice(start, end).includes(feedback)) {
        let insertion = end;
        while (insertion > start && lines[insertion - 1] === '') insertion--;
        lines.splice(insertion, 0, feedback);
        end++;
      }
    }
    start = end;
  }
  return lines.join(eol);
}
