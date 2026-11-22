import { EDGES, NODES } from './architecture';
import type { CircuitStep } from './circuit-audio';

export type Trace = ReturnType<typeof architectureTrace>;
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
  chat: ['owner', 'next', 'gateway', 'core', 'chat'],
  editor: ['owner', 'next', 'gateway', 'sandbox', 'editor'],
};

export function architectureTrace(steps: CircuitStep[], index: number) {
  const visits = new Map<string, number>();
  const lines = new Map<string, { inferred: boolean; reverse: boolean }>();
  let current = '';
  let previous = '';
  for (let i = 0; i <= index && i < steps.length; i++) {
    const step = steps[i];
    current = step.node === 'error' ? errorSources[step.label] || '' : nodeIds.has(step.node) ? step.node : '';
    // A tool name alone doesn't identify which server ran it. Keep the event in
    // the step inspector without lighting an unrelated box.
    if (current) visits.set(current, i);
    const forward = previous + '/' + current;
    const back = current + '/' + previous;
    if (edgeIds.has(forward)) lines.set(forward, { inferred: false, reverse: false });
    else if (edgeIds.has(back)) lines.set(back, { inferred: false, reverse: true });
    else if (previous === 'owner' && entryPaths[current]) {
      const path = entryPaths[current];
      path.slice(1).forEach((to, n) => lines.set(path[n] + '/' + to, { inferred: true, reverse: false }));
    }
    previous = current;
  }
  return { current, visits, lines, failed: steps[index]?.node === 'error' || steps[index]?.label === '失敗' };
}
