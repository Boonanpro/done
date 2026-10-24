// 成果物を Tailwind のスキャン対象に載せる（本体は ../scripts/wire_artifact_tailwind_sources.py）。
//
// 成果物ごとの公開サイトは frontend だけを Vercel に上げてビルドするので、そこには ../scripts が無い。
// prebuild で python を直に呼ぶと「No such file」で npm run build が落ち、10/18 から公開版の作り直しが
// 全部失敗していた（2026-10-24 発見。開発室のスマホ版が古いままだった）。無い所では何もしない。
// 上げる frontend には、手元で書き出した artifact-sources.css がそのまま入っている。
import { existsSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const script = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../scripts/wire_artifact_tailwind_sources.py');
if (!existsSync(script)) {
  console.log('[wire-artifact-tailwind] skip: scripts folder is not here (dedicated site build)');
  process.exit(0);
}
const python = process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
let run = spawnSync(python, [script], { stdio: 'inherit' });
if (run.error && python === 'python3') run = spawnSync('python', [script], { stdio: 'inherit' });
process.exit(run.status ?? 1);
