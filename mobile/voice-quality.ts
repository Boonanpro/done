/** Transport observations, not a claim about intelligibility or acoustic latency.
 * Missing WebRTC counters stay null so an unsupported metric cannot pass as zero.
 */
export function voiceQuality(stats: {forEach(fn: (row: any) => void): void}) {
  let inputLevel = 0, outputLevel = 0, inputAvailable = false;
  const inbound: Record<string, number | null>[] = [];
  stats.forEach(row => {
    if (row.kind !== 'audio' && row.mediaType !== 'audio') return;
    if (row.type === 'media-source' && typeof row.audioLevel === 'number' && Number.isFinite(row.audioLevel)) {
      inputAvailable = true;
      inputLevel = Math.max(inputLevel, row.audioLevel);
    }
    if (row.type !== 'inbound-rtp') return;
    if (typeof row.audioLevel === 'number') outputLevel = Math.max(outputLevel, row.audioLevel);
    const item: Record<string, number | null> = {};
    for (const field of ['packetsReceived','packetsLost','packetsDiscarded','nackCount','fecPacketsReceived','jitter','concealedSamples','silentConcealedSamples','concealmentEvents','totalSamplesReceived','jitterBufferDelay','jitterBufferTargetDelay','jitterBufferMinimumDelay','jitterBufferEmittedCount']) {
      item[field] = typeof row[field] === 'number' && Number.isFinite(row[field]) ? row[field] : null;
    }
    inbound.push(item);
  });
  return {inputLevel, inputAvailable, outputLevel, inbound};
}

/** Allowlisted transport data. Never persist candidate addresses or identifiers. */
export function voiceTransport(stats: {forEach(fn: (row: any) => void): void}) {
  const rows: any[] = [];
  stats.forEach(row => rows.push(row));
  const selectedId = rows.find(row => row.type === 'transport' && row.selectedCandidatePairId)?.selectedCandidatePairId;
  const pair = rows.find(row => row.type === 'candidate-pair' && row.id === selectedId)
    ?? rows.find(row => row.type === 'candidate-pair' && row.selected === true);
  const number = (row: any, key: string) => typeof row?.[key] === 'number' && Number.isFinite(row[key]) ? row[key] : null;
  const candidate = (id: string | undefined) => {
    const row = rows.find(row => id && row.id === id);
    return row ? {type: row.candidateType ?? null, protocol: row.protocol ?? null,
      relayProtocol: row.relayProtocol ?? null, networkType: row.networkType ?? null} : null;
  };
  return {
    pair: pair ? {state:pair.state, rtt:number(pair,'currentRoundTripTime'),
      availableOutgoingBitrate:number(pair,'availableOutgoingBitrate'),
      bytesSent:number(pair,'bytesSent'), bytesReceived:number(pair,'bytesReceived'),
      local:candidate(pair.localCandidateId), remote:candidate(pair.remoteCandidateId)} : null,
    upstream: rows.filter(row => row.type === 'remote-inbound-rtp' && (row.kind === 'audio' || row.mediaType === 'audio'))
      .map(row => ({packetsLost:number(row,'packetsLost'),fractionLost:number(row,'fractionLost'),
        jitter:number(row,'jitter'),rtt:number(row,'roundTripTime')})),
    ...voiceQuality(stats),
  };
}
