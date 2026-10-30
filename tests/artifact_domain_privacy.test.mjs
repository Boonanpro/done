import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { artifactRoutingDomains } from '../frontend/scripts/artifact-routing-config.ts';

const generated = { paina: ['paina.info'], kittoku: ['kittoku.vercel.app'] };
const configured = {
  NEXT_PUBLIC_ARTIFACT_CUSTOM_DOMAINS: 'other=other.example,paina=paina.info|www.paina.info',
  NEXT_PUBLIC_ARTIFACT_HOST_MAP: 'yoshikawa-tokuso.vercel.app:kittoku,extra.example:other',
};

test('dedicated sites receive no other customer identities, including environment overrides', () => {
  assert.deepEqual(artifactRoutingDomains(generated, { ...configured, ARTIFACT_ONLY_SLUG: 'paina' }), { paina: ['paina.info', 'www.paina.info'] });
  assert.deepEqual(artifactRoutingDomains(generated, { ...configured, ARTIFACT_ONLY_SLUG: 'new-attack' }), {});
});

test('legacy aliases and configured domains keep working in shared and own builds', () => {
  for (const ARTIFACT_ONLY_SLUG of [undefined, 'kittoku']) {
    const domains = artifactRoutingDomains(generated, { ...configured, ARTIFACT_ONLY_SLUG });
    assert.ok(domains.kittoku.includes('kittoku.vercel.app'));
    assert.ok(domains.kittoku.includes('yoshikawa-tokuso.vercel.app'));
  }
  assert.deepEqual(artifactRoutingDomains(generated, configured).other, ['other.example', 'extra.example']);
});

// Execute the actual blocking script with a browser stub. A dedicated root and
// a legacy alias must look up overrides for the same artifact as React does.
const layout = fs.readFileSync(new URL('../frontend/src/app/artifacts/layout.tsx', import.meta.url), 'utf8');
const functionSource = layout.slice(layout.indexOf('function prePaintScript('), layout.indexOf('function liveGuardScript('))
  .replace('(fallbackSlug: string | null): string', '(fallbackSlug)');
function prePaint(slug) {
  const context = { KNOWN_CUSTOM_DOMAINS: artifactRoutingDomains(generated, configured) };
  vm.createContext(context);
  vm.runInContext(functionSource, context);
  return context.prePaintScript(slug);
}
test('dedicated HTML omits the global map and still selects its own root overrides', () => {
  const script = prePaint('new-attack');
  assert.doesNotMatch(script, /kittoku|yoshikawa|paina\.info/);
  let storageKey;
  const self = {};
  vm.runInNewContext(script, {
    window: { self, top: {} }, location: { pathname: '/', host: 'demo.example', search: '' },
    URLSearchParams, localStorage: { getItem(key) { storageKey = key; return null; } },
  });
  assert.equal(storageKey, 'dan-inspector-overrides-new-attack');
});
test('shared iframe and both legacy aliases retain override selection', () => {
  for (const host of ['kittoku.vercel.app', 'yoshikawa-tokuso.vercel.app']) {
    let storageKey;
    vm.runInNewContext(prePaint(null), {
      window: { self: {}, top: {} }, location: { pathname: '/', host, search: '' },
      URLSearchParams, localStorage: { getItem(key) { storageKey = key; return null; } },
    });
    assert.equal(storageKey, 'dan-inspector-overrides-kittoku');
  }
});
