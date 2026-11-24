import { EDGES, NODES } from './architecture';
import type { CircuitStep } from './circuit-audio';

export type Segment = { key: string; inferred: boolean; reverse: boolean };
export type Trace = ReturnType<typeof architectureTrace> & {
  reply?: string; activity?: string; inspect?: (node: string, index: number) => void;
};
const nodeIds = new Set(NODES.map(n => n.id));
// These error labels identify the emitting component in conversation_circuit.py.
const errorSources: Record<string, string> = {
  '振り分け失敗': 'router', '作業を開始できず': 'router',
  '音声接続でエラー': 'voice', 'エラー': 'parallel',
};
const edgeIds = new Set(EDGES.map(e => e.from + '/' + e.to));

// Infrastructure between these endpoints belongs to the architecture. Its individual
// hops have no timestamps in the event stream, so display those lines dashed.
const entryPaths: Record<string, string[]> = {
  chat: ['owner', 'devices', 'next', 'gateway', 'core', 'chat'],
  voice: ['owner', 'audio', 'voice'],
  router: ['owner', 'audio', 'voice', 'router'],
  editor: ['owner', 'editor-ui', 'devices', 'next', 'gateway', 'core', 'editor'],
};

export function stepNode(step?: CircuitStep) {
  if (!step) return '';
  if (['ダンの返事','ダンが話した言葉'].includes(step.label)) return 'reply';
  if (step.node === 'error') return errorSources[step.label] || '';
  return nodeIds.has(step.node) ? step.node : '';
}

export function transition(from: string, to: string): Segment[] {
  if (from === to) return [];
  if (edgeIds.has(from + '/' + to)) return [{key: from + '/' + to, inferred: false, reverse: false}];
  if (edgeIds.has(to + '/' + from)) return [{key: to + '/' + from, inferred: false, reverse: true}];
  const path = from === 'owner' ? entryPaths[to] : to === 'owner' ? entryPaths[from] : undefined;
  if (!path) return [];
  const segments = path.slice(1).map((node, i) => ({key: path[i] + '/' + node, inferred: true, reverse: to === 'owner'}));
  return to === 'owner' ? segments.reverse() : segments;
}

export function architectureTrace(steps: CircuitStep[], index: number) {
  const visits = new Map<string, number>();
  const lines = new Map<string, Segment>();
  let current = '';
  for (let i = 0; i <= index && i < steps.length; i++) {
    const next = stepNode(steps[i]);
    for (const segment of transition(current, next)) lines.set(segment.key, segment);
    current = next;
    if (current) visits.set(current, i);
  }
  return {current, visits, lines, failed: steps[index]?.node === 'error' || steps[index]?.label === '失敗'};
}
