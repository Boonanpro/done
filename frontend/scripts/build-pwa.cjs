// Generate after Next completes: independent of its webpack/Turbopack bundler.
const { generateSW } = require('workbox-build');
const runtimeCaching = require('next-pwa/cache');
const { readFileSync, mkdirSync, copyFileSync, existsSync } = require('node:fs');
const { createHash } = require('node:crypto');
const path = require('node:path');

async function build() {
  const dist = process.env.NEXT_DIST_DIR || '.next';
  const dest = process.env.DAN_PWA_DEST || 'public';
  if (!existsSync(path.join(dist, 'BUILD_ID'))) throw new Error('Next build is incomplete');
  mkdirSync(dest, { recursive: true });
  const source = readFileSync('worker/index.js');
  const name = `worker-${createHash('sha256').update(source).digest('hex').slice(0, 16)}.js`;
  copyFileSync('worker/index.js', path.join(dest, name));
  const result = await generateSW({
    swDest: path.join(dest, 'sw.js'),
    globDirectory: dist,
    globPatterns: ['static/**/*.{js,css,woff,woff2}'],
    modifyURLPrefix: { 'static/': '/_next/static/' },
    manifestTransforms: [async entries => ({
      manifest: entries.map(entry => ({ ...entry, url: encodeURI(entry.url) })),
      warnings: [],
    })],
    importScripts: [`/${name}`],
    skipWaiting: true,
    clientsClaim: true,
    cleanupOutdatedCaches: true,
    runtimeCaching: [
      { urlPattern: /^https?:\/\/[^/]+\/api\/v1\/collab\/(?!files\/)/,
        handler: 'NetworkOnly', method: 'GET' },
      ...runtimeCaching,
    ],
  });
  if (!result.count) throw new Error('No assets were included in the service worker');
  result.warnings.forEach(warning => console.warn(warning));
  console.log(`PWA generated: ${result.count} assets`);
}
build().catch(error => { console.error(error); process.exitCode = 1; });
