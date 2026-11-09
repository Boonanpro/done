import { applyOwnStep } from './undo-history.ts';
import assert from 'node:assert/strict';
const clip = (id: string, s: number, e: number, extra = {}) => ({ id, source_start: 0, source_end: e - s, timeline_start: s, timeline_end: e, ...extra });
const seq = (v: any[], o: any[] = []) => ({ version: 1, tracks: [{ id: 'V1', type: 'video', clips: v }, { id: 'O1', type: 'overlay', clips: o }] });
const snap = (sequence: any, annotations: any[] = []) => ({ sequence, annotations });

// 1. owner moves A, Dan then changes B and adds C, owner undo -> A back, B and C stay
const s0 = seq([clip('A', 0, 5), clip('B', 5, 10)]);
const s1 = seq([clip('A', 2, 7), clip('B', 5, 10)]);              // owner moved A
const step1 = { before: snap(s0), after: snap(s1) };
const dan = seq([clip('A', 2, 7), clip('B', 5, 12, { label: 'dan' })], [clip('C', 1, 3)]);
const u = applyOwnStep(snap(dan), step1, 'undo');
const V = (x: any) => x.sequence.tracks[0].clips, O = (x: any) => x.sequence.tracks[1].clips;
assert.equal(V(u)[0].timeline_start, 0); assert.equal(V(u)[1].timeline_end, 12); assert.equal(V(u)[1].label, 'dan'); assert.equal(O(u)[0].id, 'C');
const r = applyOwnStep(u, step1, 'redo');
assert.equal(V(r)[0].timeline_start, 2); assert.equal(V(r)[1].label, 'dan'); assert.equal(O(r).length, 1);

// 2. owner deletes B; Dan adds C; undo re-adds B at its place; redo deletes again
const d1 = seq([clip('A', 0, 5)]);
const step2 = { before: snap(s0), after: snap(d1) };
const dan2 = seq([clip('A', 0, 5)], [clip('C', 1, 3)]);
const u2 = applyOwnStep(snap(dan2), step2, 'undo');
assert.deepEqual(V(u2).map((c: any) => c.id), ['A', 'B']); assert.equal(O(u2)[0].id, 'C');
assert.deepEqual(V(applyOwnStep(u2, step2, 'redo')).map((c: any) => c.id), ['A']);

// 3. same clip: owner trims end, Dan changes label -> undo restores end only, keeps Dan's label
const t1 = seq([clip('A', 0, 4), clip('B', 5, 10)]);
const step3 = { before: snap(s0), after: snap(t1) };
const dan3 = seq([{ ...clip('A', 0, 4), label: 'dan' }, clip('B', 5, 10)]);
const u3 = applyOwnStep(snap(dan3), step3, 'undo');
assert.equal(V(u3)[0].timeline_end, 5); assert.equal(V(u3)[0].label, 'dan');

// 4. Dan removed the clip the owner moved: undo leaves it removed, no crash
const u4 = applyOwnStep(snap(seq([clip('B', 5, 10)])), step1, 'undo');
assert.deepEqual(V(u4).map((c: any) => c.id), ['B']);

// 5. annotations: owner adds note n1, Dan adds n2; undo removes n1 only
const a1 = [{ id: 'n1', kind: 'note', intent: 'comment', start: 1, data: {} }];
const step5 = { before: snap(s0, []), after: snap(s0, a1) };
const u5 = applyOwnStep(snap(s0, [...a1, { id: 'n2', kind: 'note', intent: 'comment', start: 2, data: {} }]), step5, 'undo');
assert.deepEqual(u5.annotations.map((a: any) => a.id), ['n2']);

// 6. split: owner splits A into A + A2 (new id) ; undo removes A2 and restores A's end
const sp = seq([clip('A', 0, 2), clip('A2', 2, 5), clip('B', 5, 10)]);
const step6 = { before: snap(s0), after: snap(sp) };
const u6 = applyOwnStep(snap(sp), step6, 'undo');
assert.deepEqual(u6.sequence, s0);
console.log('all ok');
