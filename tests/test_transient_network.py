"""A send whose reply stream is cut mid-way is an interruption, not an error (2026-10-14).

Chrome reports a stream cut by a restart of the screen's server or of Dan's core as "network error". The list of
transient wordings had only Firefox's "NetworkError", so the screen showed "network error" in the bottom right and
turned the working display off while Dan kept working."""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

SCENARIO = r"""
const fs = require('fs'), vm = require('vm'), assert = require('assert/strict');
const ts = require(process.argv[2]);
const box = { exports: {} };
vm.runInNewContext(ts.transpileModule(fs.readFileSync(process.argv[3], 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText, { exports: box.exports });
const transient = box.exports.isTransientNetworkError;
for (const cut of ['network error', 'TypeError: network error', 'Failed to fetch', 'NetworkError when attempting to fetch resource.',
                   'Load failed', 'The network connection was lost.']) assert.equal(transient(cut), true, cut);
for (const real of ['HTTP 500', '追い連絡の注入に失敗しました', 'Unauthorized', '', undefined]) assert.equal(transient(real), false, String(real));
console.log('ok');
"""


def test_a_cut_stream_is_an_interruption_on_every_browser(tmp_path):
    typescript = ROOT / 'frontend' / 'node_modules' / 'typescript'
    if not shutil.which('node') or not typescript.exists():
        pytest.skip('node and the frontend packages are needed to run the screen code')
    script = tmp_path / 'scenario.cjs'
    script.write_text(SCENARIO, encoding='utf-8')
    done = subprocess.run(['node', str(script), str(typescript), str(ROOT / 'frontend/src/lib/transient-network.ts')],
                          capture_output=True, text=True, encoding='utf-8')
    assert done.returncode == 0 and done.stdout.strip() == 'ok', done.stderr[-2000:]


def test_the_send_stream_asks_the_shared_list():
    source = (ROOT / 'frontend/src/lib/api-client.ts').read_text(encoding='utf-8')
    assert "from './transient-network'" in source and 'function isTransientNetworkError' not in source
    assert 'isTransientNetworkError(errorMsg)' in source
