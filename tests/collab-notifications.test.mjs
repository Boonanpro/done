import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFileSync } from 'node:fs';

const source = readFileSync(new URL('../frontend/worker/index.js', import.meta.url), 'utf8');
function worker(windows = []) {
  const handlers = {}, notifications = [], opened = [];
  const self = {
    location: { origin: 'https://chat.example' },
    addEventListener: (name, fn) => { handlers[name] = fn; },
    registration: { showNotification: async (title, options) => { notifications.push({ title, ...options }); } },
    clients: { matchAll: async () => windows, openWindow: async (url) => { opened.push(url); } },
  };
  vm.runInNewContext(source, { self, URL });
  async function dispatch(name, data) {
    let work;
    handlers[name]({ ...data, waitUntil: (promise) => { work = promise; } });
    await work;
  }
  return { dispatch, notifications, opened };
}

test('a guest push retains its personal room destination when tapped', async () => {
  const w = worker();
  await w.dispatch('push', { data: { json: () => ({ title: '田中', body: '画像を送りました', url: '/collab/join/guest-a' }) } });
  assert.equal(w.notifications[0].body, '画像を送りました');
  await w.dispatch('notificationclick', { notification: { ...w.notifications[0], close() {} } });
  assert.deepEqual(w.opened, ['https://chat.example/collab/join/guest-a']);
});
test('a click focuses the matching room and does not open an unrelated conversation', async () => {
  const focused = [];
  const w = worker([
    { url: 'https://chat.example/collab/join/other', focus: () => focused.push('other') },
    { url: 'https://chat.example/collab/join/mine', postMessage: (msg) => assert.equal(msg.type, 'collab-notification-open'), focus: () => focused.push('mine') },
  ]);
  await w.dispatch('notificationclick', { notification: { data: { url: 'https://chat.example/collab/join/mine' }, close() {} } });
  assert.deepEqual(focused, ['mine']); assert.deepEqual(w.opened, []);
});
test('a malformed or external destination cannot navigate a notification outside this app', async () => {
  const w = worker();
  await w.dispatch('push', { data: { json: () => ({ url: 'https://evil.example' }) } });
  assert.equal(w.notifications[0].data.url, 'https://chat.example/collab');
});
